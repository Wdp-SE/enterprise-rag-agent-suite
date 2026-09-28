"""Frozen V3 retrieval evaluation for the expanded public DolphinScheduler corpus.

The holdout is a one-shot measurement. Do not inspect it while choosing a policy.
This runner measures retrieval only; it does not grade generated answer accuracy.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import statistics
import sys
import time
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parent
REPO = ROOT.parents[2]
SERVICE = REPO / "versioned-rag-service"
CORPUS = SERVICE / "public_corpus"
sys.path.insert(0, str(SERVICE))

from src.public_knowledge import PublicKnowledgeIndex, SUPPORTED_POLICIES  # noqa: E402


LOCKED_INPUTS = {
    "cases.jsonl": ROOT / "cases.jsonl",
    "frozen_split.json": ROOT / "frozen_split.json",
    "run_quality_v3.py": ROOT / "run_quality_v3.py",
    "corpus_manifest.json": CORPUS / "corpus_manifest.json",
    "chunks.json": CORPUS / "chunks.json",
    "dense_vectors.npy": CORPUS / "dense_vectors.npy",
    "retrieval_policy.json": CORPUS / "retrieval_policy.json",
}
CODE_PATH = SERVICE / "src" / "public_knowledge.py"
SEED = "quality-v3-expanded-corpus-2026-09-28"
TOP_K = 5


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read_cases(path: Path = ROOT / "cases.jsonl") -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def source_id(row: dict) -> str:
    return f"{row['version']}|{row['language']}|{row['document_key']}"


def candidate_fingerprint() -> dict[str, str]:
    return {
        "public_knowledge.py": sha256(CODE_PATH),
        "retrieval_policy.json": sha256(CORPUS / "retrieval_policy.json"),
    }


def split_cases(cases: list[dict]) -> dict[str, list[str]]:
    """Assign whole scenario families, four cases per category per split."""
    categories: dict[str, dict[str, list[str]]] = defaultdict(lambda: defaultdict(list))
    for case in cases:
        categories[case["category"]][case["family"]].append(case["query_id"])
    split = {"dev": [], "holdout": []}
    for category, families in sorted(categories.items()):
        if len(families) != 4 or sorted(map(len, families.values())) != [2, 2, 2, 2]:
            raise ValueError(f"{category}: expected four two-query scenario families")
        ordered = sorted(
            families, key=lambda family: hashlib.sha256(
                f"{SEED}|{category}|{family}".encode("utf-8")
            ).digest(),
        )
        for family in ordered[:2]:
            split["dev"].extend(families[family])
        for family in ordered[2:]:
            split["holdout"].extend(families[family])
    return {name: sorted(ids) for name, ids in split.items()}


def validate_cases(cases: list[dict], index: PublicKnowledgeIndex) -> None:
    missing_markers: list[str] = []
    ids = [case["query_id"] for case in cases]
    if len(cases) != 72 or len(ids) != len(set(ids)):
        raise ValueError("V3 requires exactly 72 unique questions")
    if len({case["query"].strip().casefold() for case in cases}) != len(cases):
        raise ValueError("duplicate question text")
    manifest_by_id = {source_id(row): row for row in index.manifest["sources"]}
    chunks_by_id: dict[str, list[dict]] = defaultdict(list)
    for chunk in index.chunks:
        chunks_by_id[source_id(chunk)].append(chunk)
    categories = Counter(case["category"] for case in cases)
    if len(categories) != 9 or set(categories.values()) != {8}:
        raise ValueError("V3 requires nine balanced eight-query categories")
    for case in cases:
        case_id = case["query_id"]
        if not case["query"].strip() or len(case["query"]) > 4000:
            raise ValueError(f"{case_id}: invalid query")
        if case["language"] not in ("zh", "en", "all"):
            raise ValueError(f"{case_id}: invalid language")
        if case["version_scope"] not in ("3.4.2", "3.4.3", "all"):
            raise ValueError(f"{case_id}: invalid version")
        evidence = case["expected_markers"]
        if bool(case["answerable"]) != bool(evidence):
            raise ValueError(f"{case_id}: answerability and evidence disagree")
        if case["category"] == "no_answer" and case["answerable"]:
            raise ValueError(f"{case_id}: no-answer category cannot be answerable")
        if case["category"] == "cross_document" and len(evidence) < 2:
            raise ValueError(f"{case_id}: cross-document case needs two sources")
        if case["category"] == "version_compare" and {s.split("|", 1)[0] for s in evidence} != {"3.4.2", "3.4.3"}:
            raise ValueError(f"{case_id}: version comparison needs both versions")
        for sid, markers in evidence.items():
            if sid not in manifest_by_id or sid not in chunks_by_id:
                raise ValueError(f"{case_id}: missing pinned source {sid}")
            version, language, _ = sid.split("|", 2)
            if case["version_scope"] != "all" and version != case["version_scope"]:
                raise ValueError(f"{case_id}: source outside requested version")
            if case["language"] != "all" and language != case["language"]:
                raise ValueError(f"{case_id}: source outside requested language")
            if not isinstance(markers, list) or not markers:
                raise ValueError(f"{case_id}: source has no evidence marker")
            raw = (CORPUS / manifest_by_id[sid]["local_path"]).read_text(encoding="utf-8").casefold()
            chunk_texts = [
                " ".join([chunk["document_title"], chunk["heading"], *chunk["heading_path"], chunk["content"]]).casefold()
                for chunk in chunks_by_id[sid]
            ]
            for marker in markers:
                if not isinstance(marker, str) or not marker.strip() or "[图片" in marker or ".png" in marker:
                    raise ValueError(f"{case_id}: invalid evidence marker")
                if marker.casefold() not in raw:
                    missing_markers.append(f"{case_id}: marker absent from source {sid}: {marker}")
                if not any(marker.casefold() in text for text in chunk_texts):
                    missing_markers.append(f"{case_id}: marker absent from indexed chunks {sid}: {marker}")
    if missing_markers:
        raise ValueError("\n".join(missing_markers))


def freeze() -> dict:
    if (ROOT / "selection_lock.json").exists() or (ROOT / "frozen_split.json").exists():
        raise FileExistsError("V3 inputs already frozen")
    index = PublicKnowledgeIndex()
    cases = read_cases()
    validate_cases(cases, index)
    split = split_cases(cases)
    if sorted(len(ids) for ids in split.values()) != [36, 36]:
        raise ValueError("DEV and HOLDOUT must each contain 36 questions")
    split_path = ROOT / "frozen_split.json"
    split_path.write_text(json.dumps(split, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")
    lock = {
        "format_version": 1,
        "split_seed": SEED,
        "source_id_format": "version|language|document_key",
        "top_k": TOP_K,
        "case_count": len(cases),
        "source_count": len(index.manifest["sources"]),
        "chunk_count": len(index.chunks),
        "sha256": {name: sha256(path) for name, path in LOCKED_INPUTS.items()},
    }
    (ROOT / "selection_lock.json").write_text(
        json.dumps(lock, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n"
    )
    return lock


def load_locked() -> tuple[list[dict], dict[str, list[str]], dict, PublicKnowledgeIndex]:
    lock = json.loads((ROOT / "selection_lock.json").read_text(encoding="utf-8"))
    actual = {name: sha256(path) for name, path in LOCKED_INPUTS.items()}
    if actual != lock.get("sha256"):
        changed = [name for name in actual if actual[name] != lock.get("sha256", {}).get(name)]
        raise ValueError("V3 locked input hash mismatch: " + ", ".join(changed))
    cases = read_cases()
    index = PublicKnowledgeIndex()
    validate_cases(cases, index)
    split = json.loads((ROOT / "frozen_split.json").read_text(encoding="utf-8"))
    if split != split_cases(cases):
        raise ValueError("V3 split changed")
    return cases, split, lock, index


def _percentile(values: list[float], quantile: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    return ordered[max(0, math.ceil(quantile * len(ordered)) - 1)]


def _case_result(case: dict, hits: list[dict], elapsed_ms: float) -> dict:
    required = set(case["expected_markers"])
    retrieved = [source_id(hit) for hit in hits]
    unique = list(dict.fromkeys(retrieved))
    found = required.intersection(unique)
    first_rank = next((i for i, sid in enumerate(unique, 1) if sid in required), None)
    marker_total = sum(len(markers) for markers in case["expected_markers"].values())
    marker_found = 0
    for sid, markers in case["expected_markers"].items():
        texts = [
            " ".join([hit["document_title"], hit["heading"], *hit["heading_path"], hit["content"]]).casefold()
            for hit in hits if source_id(hit) == sid
        ]
        marker_found += sum(any(marker.casefold() in text for text in texts) for marker in markers)
    return {
        "query_id": case["query_id"],
        "category": case["category"],
        "family": case["family"],
        "answerable": case["answerable"],
        "version_scope": case["version_scope"],
        "language": case["language"],
        "required_source_ids": sorted(required),
        "top5_source_ids": unique,
        "top5_chunk_ids": [hit["chunk_id"] for hit in hits],
        "source_hit_at_5": bool(found) if required else None,
        "source_recall_at_5": len(found) / len(required) if required else None,
        "complete_source_at_5": required.issubset(unique) if required else None,
        "reciprocal_rank": 1 / first_rank if first_rank else 0.0,
        "evidence_marker_count": marker_total,
        "evidence_marker_found": marker_found,
        "evidence_marker_recall_at_5": marker_found / marker_total if marker_total else None,
        "top1_score": hits[0]["retrieval_score"] if hits else None,
        "latency_ms": elapsed_ms,
    }


def summarize(cases: list[dict]) -> dict:
    answerable = [case for case in cases if case["answerable"]]
    no_answer = [case for case in cases if not case["answerable"]]
    multi = [case for case in answerable if len(case["required_source_ids"]) > 1]
    marker_total = sum(case["evidence_marker_count"] for case in answerable)
    scores = [case["top1_score"] for case in no_answer if case["top1_score"] is not None]
    return {
        "question_count": len(cases),
        "answerable_count": len(answerable),
        "no_answer_count": len(no_answer),
        "source_hit_at_5": statistics.mean(case["source_hit_at_5"] for case in answerable) if answerable else None,
        "source_recall_at_5_macro": statistics.mean(case["source_recall_at_5"] for case in answerable) if answerable else None,
        "source_recall_at_5_micro": (
            sum(case["source_recall_at_5"] * len(case["required_source_ids"]) for case in answerable)
            / sum(len(case["required_source_ids"]) for case in answerable)
            if answerable else None
        ),
        "complete_source_at_5": statistics.mean(case["complete_source_at_5"] for case in answerable) if answerable else None,
        "multi_source_question_count": len(multi),
        "complete_multi_source_at_5": statistics.mean(case["complete_source_at_5"] for case in multi) if multi else None,
        "mrr": statistics.mean(case["reciprocal_rank"] for case in answerable) if answerable else None,
        "evidence_marker_recall_at_5_micro": (
            sum(case["evidence_marker_found"] for case in answerable) / marker_total if marker_total else None
        ),
        "warm_search_p50_ms": statistics.median(case["latency_ms"] for case in cases) if cases else None,
        "warm_search_p95_ms": _percentile([case["latency_ms"] for case in cases], 0.95),
        "no_answer_top1_score": {
            "count": len(scores),
            "median": statistics.median(scores) if scores else None,
            "p95": _percentile(scores, 0.95),
        },
    }


def run(split_name: str, policy: str) -> Path:
    cases, split, lock, index = load_locked()
    if policy not in SUPPORTED_POLICIES:
        raise ValueError(f"unsupported policy: {policy}")
    if split_name not in ("dev", "holdout"):
        raise ValueError(f"unsupported split: {split_name}")
    fingerprint = candidate_fingerprint()
    selected = [case for case in cases if case["query_id"] in set(split[split_name])]
    result_dir = ROOT / "results"
    result_dir.mkdir(exist_ok=True)
    output = result_dir / f"{split_name}__{policy}.json"
    if split_name == "holdout":
        selection_path = ROOT / "candidate_selection.json"
        if not selection_path.exists():
            raise ValueError("select a DEV-tested candidate before opening HOLDOUT")
        selection = json.loads(selection_path.read_text(encoding="utf-8"))
        dev_path = result_dir / f"dev__{policy}.json"
        if (
            selection.get("policy") != policy
            or selection.get("candidate_fingerprint") != fingerprint
            or selection.get("input_sha256") != lock["sha256"]
            or not dev_path.exists()
            or selection.get("dev_result_sha256") != sha256(dev_path)
        ):
            raise ValueError("HOLDOUT candidate differs from the locked DEV selection")
        if output.exists() or (ROOT / "holdout_execution.json").exists():
            raise FileExistsError("V3 HOLDOUT has already been opened; create a new eval version instead")
        (ROOT / "holdout_execution.json").write_text(json.dumps({
            "policy": policy,
            "candidate_fingerprint": fingerprint,
            "opened_at_utc": datetime.now(timezone.utc).isoformat(),
            "input_sha256": lock["sha256"],
        }, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")
    # Warm the same index and request shape before measuring only retrieval latency.
    for case in selected:
        index.search(case["query"], top_k=TOP_K, version=case["version_scope"],
                     language=case["language"], policy=policy)
    results = []
    for case in selected:
        started = time.perf_counter()
        hits = index.search(case["query"], top_k=TOP_K, version=case["version_scope"],
                            language=case["language"], policy=policy)
        results.append(_case_result(case, hits, (time.perf_counter() - started) * 1000))
    groups: dict[str, list[dict]] = defaultdict(list)
    for result in results:
        groups[result["category"]].append(result)
    payload = {
        "split": split_name,
        "policy": policy,
        "candidate_fingerprint": fingerprint,
        "input_sha256": lock["sha256"],
        "top_k": TOP_K,
        "overall": summarize(results),
        "by_category": {category: summarize(rows) for category, rows in sorted(groups.items())},
        "cases": results,
        "interpretation": "Retrieval-only; no-answer scores are diagnostics, not refusal accuracy; no answer faithfulness measured.",
    }
    output.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
                      encoding="utf-8", newline="\n")
    return output


def select_candidate(policy: str) -> Path:
    _, _, lock, _ = load_locked()
    fingerprint = candidate_fingerprint()
    dev_path = ROOT / "results" / f"dev__{policy}.json"
    if not dev_path.exists():
        raise FileNotFoundError("candidate must have a DEV result first")
    dev = json.loads(dev_path.read_text(encoding="utf-8"))
    if dev.get("candidate_fingerprint") != fingerprint or dev.get("input_sha256") != lock["sha256"]:
        raise ValueError("candidate code or frozen inputs changed since DEV")
    selection_path = ROOT / "candidate_selection.json"
    if selection_path.exists():
        raise FileExistsError("candidate already selected for the one-shot HOLDOUT")
    selection_path.write_text(json.dumps({
        "policy": policy, "candidate_fingerprint": fingerprint,
        "dev_result_sha256": sha256(dev_path), "input_sha256": lock["sha256"],
        "selected_at_utc": datetime.now(timezone.utc).isoformat(),
    }, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")
    return selection_path


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--freeze", action="store_true")
    group.add_argument("--split", choices=("dev", "holdout"))
    group.add_argument("--select-candidate", metavar="POLICY")
    parser.add_argument("--policy", default="bm25")
    args = parser.parse_args()
    if args.freeze:
        print(json.dumps(freeze(), ensure_ascii=False, indent=2))
    elif args.select_candidate:
        print(select_candidate(args.select_candidate))
    else:
        print(run(args.split, args.policy))


if __name__ == "__main__":
    main()
