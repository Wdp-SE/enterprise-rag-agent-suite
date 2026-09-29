"""Independent V4 evaluation for multi-source and reviewed-image retrieval.

This runner evaluates retrieval evidence only. It does not score generated
answer accuracy, model abstention, or hallucination rates.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import statistics
import sys
import time
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable


ROOT = Path(__file__).resolve().parent
REPO = ROOT.parents[2]
SERVICE = REPO / "versioned-rag-service"
CORPUS = SERVICE / "public_corpus"
SIDECAR = CORPUS / "figure_evidence_reviewed.json"
sys.path.insert(0, str(SERVICE))

TOP_K = 20
TARGET_CASE_COUNT = 104
POLICIES = (
    "bm25",
    "bm25_faceted_rrf",
    "bm25_figure_ocr",
    "bm25_faceted_figure_ocr",
    "hybrid",
)


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read_cases(path: Path = ROOT / "cases.jsonl") -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def source_id(row: dict) -> str:
    return f"{row['version']}|{row['language']}|{row['document_key']}"


def split_cases(cases: list[dict], seed: str) -> dict[str, list[str]]:
    """Hash-assign connected family/figure groups so related cases never leak."""
    parents: dict[str, str] = {}

    def find(value: str) -> str:
        parents.setdefault(value, value)
        if parents[value] != value:
            parents[value] = find(parents[value])
        return parents[value]

    def union(left: str, right: str) -> None:
        a, b = find(left), find(right)
        if a != b:
            parents[max(a, b)] = min(a, b)

    keys_by_case: dict[str, list[str]] = {}
    for case in cases:
        family_key = f"family:{case['family_id']}"
        keys = [family_key]
        for figure_id in case.get("expected_image_markers", {}):
            keys.append(f"figure:{figure_id}")
        for key in keys[1:]:
            union(keys[0], key)
        keys_by_case[case["query_id"]] = keys

    groups: dict[str, list[str]] = defaultdict(list)
    for query_id, keys in keys_by_case.items():
        groups[find(keys[0])].append(query_id)
    ordered = sorted(
        groups.items(),
        key=lambda item: hashlib.sha256(f"{seed}|{item[0]}".encode("utf-8")).digest(),
    )
    split = {"dev": [], "holdout": []}
    for _, ids in ordered:
        if len(split["dev"]) <= len(split["holdout"]):
            target = "dev"
        else:
            target = "holdout"
        split[target].extend(ids)
    return {name: sorted(ids) for name, ids in split.items()}


def _chunk_text(chunk: dict) -> str:
    return " ".join([
        chunk.get("document_title", ""),
        chunk.get("heading", ""),
        *chunk.get("heading_path", []),
        chunk.get("content", ""),
    ]).casefold()


def validate_cases(cases: list[dict], index, sidecar: dict) -> None:
    ids = [case.get("query_id") for case in cases]
    if not cases or any(not isinstance(value, str) or not value.strip() for value in ids) or len(ids) != len(set(ids)):
        raise ValueError("V4 requires unique non-empty query IDs")
    if len({case.get("query", "").strip().casefold() for case in cases}) != len(cases):
        raise ValueError("V4 contains duplicate query text")
    manifest_sources = {source_id(source): source for source in index.manifest["sources"]}
    chunks_by_source: dict[str, list[dict]] = defaultdict(list)
    for chunk in index.chunks:
        chunks_by_source[source_id(chunk)].append(chunk)
    reviewed_chunks = {
        (chunk.get("figure_id"), chunk.get("version"), chunk.get("language")): chunk
        for chunk in sidecar.get("chunks", [])
        if chunk.get("modality") == "image_ocr" and chunk.get("review_status") == "approved"
    }
    for case in cases:
        qid = case.get("query_id", "<missing>")
        query = case.get("query", "")
        version = case.get("version_scope")
        language = case.get("language")
        markers = case.get("expected_markers", {})
        image_markers = case.get("expected_image_markers", {})
        answerable = bool(case.get("answerable"))
        if not query.strip() or len(query) > 4000:
            raise ValueError(f"{qid}: invalid query")
        if version not in ("3.4.2", "3.4.3", "all") or language not in ("zh", "en", "all"):
            raise ValueError(f"{qid}: invalid version or language scope")
        if answerable != bool(markers or image_markers):
            raise ValueError(f"{qid}: answerability and evidence disagree")
        category = case.get("category")
        if category not in {"single_source", "cross_document", "cross_version", "image_only", "text_plus_image", "no_answer"}:
            raise ValueError(f"{qid}: unsupported V4 category")
        if category == "single_source" and (not answerable or len(markers) != 1 or image_markers):
            raise ValueError(f"{qid}: single-source case requires exactly one text source")
        if category == "no_answer" and answerable:
            raise ValueError(f"{qid}: no-answer case must be unanswerable")
        if category == "no_answer" and (markers or image_markers):
            raise ValueError(f"{qid}: no-answer case cannot declare evidence")
        if category == "cross_document" and len(markers) < 2:
            raise ValueError(f"{qid}: cross-document case requires at least two text sources")
        if category == "cross_version":
            versions = {sid.split("|", 1)[0] for sid in markers}
            if version != "all" or versions != {"3.4.2", "3.4.3"}:
                raise ValueError(f"{qid}: cross-version case must require both fixed versions")
        if category == "image_only" and (markers or not image_markers):
            raise ValueError(f"{qid}: image-only case must require approved image evidence only")
        if category == "text_plus_image" and (not markers or not image_markers):
            raise ValueError(f"{qid}: text-plus-image case requires both modalities")
        if set(case.get("image_refs", {})) != set(image_markers):
            raise ValueError(f"{qid}: image hash and region references must match required figures")
        for sid, required_markers in markers.items():
            if sid not in manifest_sources or sid not in chunks_by_source:
                raise ValueError(f"{qid}: missing pinned source {sid}")
            source = manifest_sources[sid]
            src_version, src_language, _ = sid.split("|", 2)
            if version != "all" and src_version != version:
                raise ValueError(f"{qid}: expected source outside requested version")
            if language != "all" and src_language != language:
                raise ValueError(f"{qid}: expected source outside requested language")
            raw = (index.root / source["local_path"]).read_text(encoding="utf-8").casefold()
            texts = [_chunk_text(chunk) for chunk in chunks_by_source[sid]]
            if not required_markers:
                raise ValueError(f"{qid}: source has no evidence markers")
            for marker in required_markers:
                if not isinstance(marker, str) or not marker.strip() or marker.casefold() not in raw:
                    raise ValueError(f"{qid}: marker absent from pinned source {sid}: {marker}")
                if not any(marker.casefold() in text for text in texts):
                    raise ValueError(f"{qid}: marker absent from index chunks {sid}: {marker}")
        for figure_id, required_markers in image_markers.items():
            languages = ("zh", "en") if language == "all" else (language,)
            versions = ("3.4.2", "3.4.3") if version == "all" else (version,)
            matches = [
                reviewed_chunks[(figure_id, ver, lang)]
                for ver in versions for lang in languages
                if (figure_id, ver, lang) in reviewed_chunks
            ]
            if not matches:
                raise ValueError(f"{qid}: figure is missing from approved image sidecar: {figure_id}")
            image_ref = case.get("image_refs", {}).get(figure_id)
            if not isinstance(image_ref, dict) or not image_ref.get("sha256") or not image_ref.get("page_or_region", "").strip():
                raise ValueError(f"{qid}: image hash and region are required for {figure_id}")
            if not any(chunk.get("sha256") == image_ref["sha256"] for chunk in matches):
                raise ValueError(f"{qid}: image provenance mismatch for {figure_id}")
            if not required_markers or not any(
                marker.casefold() in chunk.get("content", "").casefold()
                for chunk in matches for marker in required_markers
            ):
                raise ValueError(f"{qid}: image marker absent from approved figure {figure_id}")


def _percentile(values: list[float], quantile: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    return ordered[max(0, math.ceil(quantile * len(ordered)) - 1)]


def _source(hit: dict) -> str:
    return f"{hit['version']}|{hit['language']}|{hit['document_key']}"


def _metrics_for_rows(rows: list[dict]) -> dict:
    answerable = [row for row in rows if row["answerable"]]
    no_answer = [row for row in rows if not row["answerable"]]
    source_recalls = [row["source_recall_at_20"] for row in answerable if row["required_source_count"]]
    anchor_total = sum(row["evidence_marker_count"] for row in answerable)
    image_rows = [row for row in answerable if row["required_figure_count"]]
    cross_document = [row for row in answerable if row["category"] == "cross_document"]
    cross_version = [row for row in answerable if row["category"] == "cross_version"]
    elapsed = [row["latency_ms"] for row in rows if row["latency_ms"] is not None]
    return {
        "question_count": len(rows),
        "answerable_count": len(answerable),
        "no_answer_count": len(no_answer),
        "source_recall_at_20": statistics.mean(source_recalls) if source_recalls else None,
        "source_hit_at_5": statistics.mean(row["source_hit_at_5"] for row in answerable) if answerable else None,
        "complete_source_at_5": statistics.mean(row["complete_source_at_5"] for row in answerable) if answerable else None,
        "anchor_recall_at_5": anchor_total and sum(row["evidence_marker_found_at_5"] for row in answerable) / anchor_total or 0.0,
        "cross_document_complete_at_5": statistics.mean(row["complete_source_at_5"] for row in cross_document) if cross_document else None,
        "cross_version_complete_at_5": statistics.mean(row["complete_source_at_5"] for row in cross_version) if cross_version else None,
        "image_hit_at_5": statistics.mean(row["complete_image_at_5"] for row in image_rows) if image_rows else None,
        "image_recall_at_5": (
            sum(row["image_found_at_5"] for row in image_rows)
            / sum(row["required_figure_count"] for row in image_rows)
            if image_rows else None
        ),
        "version_mismatch_count": sum(row["version_mismatch_count"] for row in rows),
        "mrr": statistics.mean(row["reciprocal_rank"] for row in answerable) if answerable else None,
        "ndcg_at_5": statistics.mean(row["ndcg_at_5"] for row in answerable) if answerable else None,
        "no_answer_nonempty_candidate_rate": statistics.mean(row["candidate_nonempty"] for row in no_answer) if no_answer else None,
        "answerable_zero_result_rate": statistics.mean(not row["candidate_nonempty"] for row in answerable) if answerable else None,
        "retrieval_call_count": sum(row["retrieval_call_count"] for row in rows),
        "warm_p50_ms": statistics.median(elapsed) if elapsed else None,
        "warm_p95_ms": _percentile(elapsed, 0.95),
    }


def compute_metrics(
    cases: list[dict],
    ranked_hits: dict[str, list[dict]],
    *,
    elapsed_ms: dict[str, float] | None = None,
    retrieval_calls: dict[str, int] | None = None,
    top_k: int = 5,
) -> dict:
    """Score required evidence retrieval; never infer answer correctness."""
    elapsed_ms = elapsed_ms or {}
    retrieval_calls = retrieval_calls or {}
    rows = []
    for case in cases:
        hits = ranked_hits.get(case["query_id"], [])
        required_sources = set(case.get("expected_markers", {}))
        required_figures = set(case.get("expected_image_markers", {}))
        top = hits[:top_k]
        top_sources = [_source(hit) for hit in top]
        top_20_sources = {_source(hit) for hit in hits[:20]}
        found_sources = required_sources.intersection(top_sources)
        source_rank = next((rank for rank, hit in enumerate(top, 1) if _source(hit) in required_sources), None)
        found_figures = {hit.get("figure_id") for hit in top if hit.get("modality") == "image_ocr"}
        image_found = len(required_figures.intersection(found_figures))
        markers = case.get("expected_markers", {})
        marker_count = sum(len(items) for items in markers.values())
        marker_found = 0
        for sid, items in markers.items():
            texts = [_chunk_text(hit) for hit in top if _source(hit) == sid]
            marker_found += sum(any(item.casefold() in text for text in texts) for item in items)
        mismatch = 0
        scope = case["version_scope"]
        if scope != "all":
            mismatch = sum(hit.get("version") != scope for hit in hits)
        relevance = [1 if _source(hit) in required_sources or hit.get("figure_id") in required_figures else 0 for hit in top]
        dcg = sum(rel / math.log2(rank + 1) for rank, rel in enumerate(relevance, 1))
        ideal_count = min(len(required_sources) + len(required_figures), top_k)
        idcg = sum(1 / math.log2(rank + 1) for rank in range(1, ideal_count + 1))
        rows.append({
            "query_id": case["query_id"],
            "category": case["category"],
            "family_id": case["family_id"],
            "answerable": case["answerable"],
            "required_sources": sorted(required_sources),
            "required_source_count": len(required_sources),
            "required_figure_ids": sorted(required_figures),
            "required_figure_count": len(required_figures),
            "top5_source_ids": list(dict.fromkeys(top_sources)),
            "top5_figure_ids": [hit.get("figure_id") for hit in top if hit.get("modality") == "image_ocr"],
            "source_recall_at_20": len(required_sources.intersection(top_20_sources)) / len(required_sources) if required_sources else 1.0,
            "source_hit_at_5": bool(found_sources or required_figures.intersection(found_figures)) if case["answerable"] else None,
            "complete_source_at_5": required_sources.issubset(set(top_sources)) if required_sources else True,
            "evidence_marker_count": marker_count,
            "evidence_marker_found_at_5": marker_found,
            "image_found_at_5": image_found,
            "complete_image_at_5": required_figures.issubset(found_figures) if required_figures else True,
            "version_mismatch_count": mismatch,
            "reciprocal_rank": 1 / source_rank if source_rank else (1.0 if required_figures.intersection(found_figures) else 0.0),
            "ndcg_at_5": dcg / idcg if idcg else None,
            "candidate_nonempty": bool(hits),
            "retrieval_call_count": retrieval_calls.get(case["query_id"], 1),
            "latency_ms": elapsed_ms.get(case["query_id"]),
        })
    groups: dict[str, list[dict]] = defaultdict(list)
    for row in rows:
        groups[row["category"]].append(row)
    return {
        "overall": _metrics_for_rows(rows),
        "by_category": {key: _metrics_for_rows(value) for key, value in sorted(groups.items())},
        "cases": rows,
        "interpretation": "Retrieval-only candidate metrics. They do not measure generated-answer accuracy, model abstention, or hallucination rate.",
    }


def assert_holdout_allowed(selection_lock: dict | None, input_hashes: dict, execution_path: Path) -> bool:
    if not selection_lock:
        raise ValueError("HOLDOUT requires a selection lock")
    if selection_lock.get("input_sha256") != input_hashes:
        raise ValueError("HOLDOUT selection input hash mismatch")
    if not selection_lock.get("policy") or not selection_lock.get("candidate_fingerprint"):
        raise ValueError("HOLDOUT selection lock is incomplete")
    if execution_path.exists():
        raise FileExistsError("HOLDOUT has already executed")
    return True


def _lock_paths() -> dict[str, Path]:
    return {
        "cases.jsonl": ROOT / "cases.jsonl",
        "frozen_split.json": ROOT / "frozen_split.json",
        "run_quality_v4.py": ROOT / "run_quality_v4.py",
        "corpus_manifest.json": CORPUS / "corpus_manifest.json",
        "chunks.json": CORPUS / "chunks.json",
        "dense_vectors.npy": CORPUS / "dense_vectors.npy",
        "figure_evidence_reviewed.json": SIDECAR,
        "retrieval_fusion.py": SERVICE / "src" / "retrieval_fusion.py",
        "public_retrieval_runtime.py": SERVICE / "src" / "public_retrieval_runtime.py",
        "public_retrieval_runtime.json": SERVICE / "config" / "public_retrieval_runtime.json",
    }


def runtime_config_fingerprint(config: dict) -> str:
    """Hash retrieval parameters while excluding only the serving default pointer.

    V4 always passes a candidate policy explicitly. This lets a one-time HOLDOUT
    promote that already-scored policy by changing only default_policy, without
    changing any candidate behavior or invalidating its execution fingerprint.
    """
    parameters = dict(config)
    parameters.pop("default_policy", None)
    payload = json.dumps(parameters, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _input_hashes() -> dict[str, str]:
    hashes = {}
    for name, path in _lock_paths().items():
        if name == "public_retrieval_runtime.json":
            hashes[name] = runtime_config_fingerprint(json.loads(path.read_text(encoding="utf-8")))
        else:
            hashes[name] = sha256(path)
    return hashes


def freeze() -> dict:
    lock_path = ROOT / "input_lock.json"
    split_path = ROOT / "frozen_split.json"
    if lock_path.exists() or split_path.exists():
        raise FileExistsError("V4 evaluation inputs are already frozen")
    from src.public_knowledge import PublicKnowledgeIndex
    index = PublicKnowledgeIndex()
    cases = read_cases()
    sidecar = json.loads(SIDECAR.read_text(encoding="utf-8"))
    validate_cases(cases, index, sidecar)
    split = split_cases(cases, seed="quality-v4-family-figure-2026-09-29")
    if set(split["dev"]) | set(split["holdout"]) != {case["query_id"] for case in cases}:
        raise ValueError("V4 split omitted cases")
    split_path.write_text(json.dumps(split, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    hashes = _input_hashes()
    lock = {
        "schema_version": 1,
        "split_seed": "quality-v4-family-figure-2026-09-29",
        "case_count": len(cases),
        "target_case_count": TARGET_CASE_COUNT,
        "pilot": len(cases) < TARGET_CASE_COUNT,
        "source_count": len(index.manifest["sources"]),
        "chunk_count": len(index.chunks),
        "approved_image_chunk_count": len(sidecar.get("chunks", [])),
        "split_counts": {key: len(value) for key, value in split.items()},
        "sha256": hashes,
    }
    lock_path.write_text(json.dumps(lock, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return lock


def load_frozen():
    lock_path = ROOT / "input_lock.json"
    if not lock_path.exists():
        raise FileNotFoundError("freeze V4 inputs before running strategies")
    lock = json.loads(lock_path.read_text(encoding="utf-8"))
    actual = _input_hashes()
    if actual != lock.get("sha256"):
        changed = [key for key in actual if lock.get("sha256", {}).get(key) != actual[key]]
        raise ValueError("V4 locked input hash mismatch: " + ", ".join(changed))
    cases = read_cases()
    split = json.loads((ROOT / "frozen_split.json").read_text(encoding="utf-8"))
    from src.public_knowledge import PublicKnowledgeIndex
    index = PublicKnowledgeIndex()
    sidecar = json.loads(SIDECAR.read_text(encoding="utf-8"))
    validate_cases(cases, index, sidecar)
    if split != split_cases(cases, seed=lock["split_seed"]):
        raise ValueError("V4 frozen split mismatch")
    return cases, split, lock, sidecar, index


def candidate_fingerprint() -> dict[str, str]:
    paths = {
        "retrieval_fusion.py": SERVICE / "src" / "retrieval_fusion.py",
        "public_retrieval_runtime.py": SERVICE / "src" / "public_retrieval_runtime.py",
        "public_retrieval_runtime.json": SERVICE / "config" / "public_retrieval_runtime.json",
    }
    fingerprints = {name: sha256(path) for name, path in paths.items() if name != "public_retrieval_runtime.json"}
    fingerprints["public_retrieval_runtime.json"] = runtime_config_fingerprint(
        json.loads(paths["public_retrieval_runtime.json"].read_text(encoding="utf-8"))
    )
    return fingerprints


def run(split_name: str, policy: str) -> Path:
    cases, split, lock, sidecar, index = load_frozen()
    if split_name not in ("dev", "holdout"):
        raise ValueError("unsupported split")
    if policy not in POLICIES:
        raise ValueError(f"unsupported policy: {policy}")
    selection_path = ROOT / "selection_lock.json"
    execution_path = ROOT / "holdout_execution.json"
    if split_name == "holdout":
        selection = json.loads(selection_path.read_text(encoding="utf-8")) if selection_path.exists() else None
        assert_holdout_allowed(selection, lock["sha256"], execution_path)
        if selection.get("policy") != policy or selection.get("candidate_fingerprint") != candidate_fingerprint():
            raise ValueError("HOLDOUT does not match selected DEV candidate")
        execution_path.write_text(json.dumps({
            "policy": policy,
            "candidate_fingerprint": candidate_fingerprint(),
            "opened_at_utc": datetime.now(timezone.utc).isoformat(),
            "input_sha256": lock["sha256"],
            "status": "running",
        }, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    from src.public_retrieval_runtime import PublicRetrievalRuntime
    runtime = PublicRetrievalRuntime(index, sidecar_path=SIDECAR)
    selected = [case for case in cases if case["query_id"] in set(split[split_name])]
    for case in selected:
        runtime.search(case["query"], top_k=TOP_K, version=case["version_scope"], language=case["language"], policy=policy)
    ranked, elapsed, calls = {}, {}, {}
    for case in selected:
        started = time.perf_counter()
        ranked[case["query_id"]] = runtime.search(
            case["query"], top_k=TOP_K,
            version=case["version_scope"], language=case["language"], policy=policy,
        )
        elapsed[case["query_id"]] = (time.perf_counter() - started) * 1000
        calls[case["query_id"]] = runtime.last_retrieval_call_count
    payload = compute_metrics(selected, ranked, elapsed_ms=elapsed, retrieval_calls=calls)
    payload.update({
        "split": split_name,
        "policy": policy,
        "candidate_fingerprint": candidate_fingerprint(),
        "input_sha256": lock["sha256"],
        "target_case_count": TARGET_CASE_COUNT,
        "pilot": len(cases) < TARGET_CASE_COUNT,
    })
    result_dir = ROOT / "results"
    result_dir.mkdir(exist_ok=True)
    output = result_dir / f"{split_name}__{policy}.json"
    if output.exists():
        raise FileExistsError(f"V4 {split_name} result already exists: {output.name}")
    output.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    if split_name == "holdout":
        marker = json.loads(execution_path.read_text(encoding="utf-8"))
        marker.update({"status": "completed", "result_sha256": sha256(output)})
        execution_path.write_text(json.dumps(marker, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return output


def lock_selection(policy: str) -> Path:
    cases, _, lock, _, _ = load_frozen()
    if policy not in POLICIES:
        raise ValueError(f"unsupported policy: {policy}")
    dev_path = ROOT / "results" / f"dev__{policy}.json"
    if not dev_path.exists():
        raise FileNotFoundError("run this policy on DEV before locking it")
    dev = json.loads(dev_path.read_text(encoding="utf-8"))
    if dev.get("candidate_fingerprint") != candidate_fingerprint() or dev.get("input_sha256") != lock["sha256"]:
        raise ValueError("candidate or frozen input changed after DEV")
    selection_path = ROOT / "selection_lock.json"
    if selection_path.exists():
        raise FileExistsError("V4 candidate has already been selected")
    selection = {
        "schema_version": 1,
        "policy": policy,
        "candidate_fingerprint": candidate_fingerprint(),
        "input_sha256": lock["sha256"],
        "dev_result_sha256": sha256(dev_path),
        "selected_case_count": len(cases),
        "locked_at_utc": datetime.now(timezone.utc).isoformat(),
        "promotion_gate": "pending_review",
    }
    selection_path.write_text(json.dumps(selection, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return selection_path


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--freeze", action="store_true")
    group.add_argument("--split", choices=("dev", "holdout"))
    group.add_argument("--lock-selection", action="store_true")
    parser.add_argument("--policy", default="bm25")
    args = parser.parse_args()
    if args.freeze:
        result = freeze()
    elif args.lock_selection:
        result = lock_selection(args.policy)
    else:
        result = run(args.split, args.policy)
    print(json.dumps(result, ensure_ascii=False, indent=2) if isinstance(result, dict) else str(result))


if __name__ == "__main__":
    main()
