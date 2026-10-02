"""Reproduce retrieval metrics against the pinned Chinese edge-AI corpus."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import sys
import time
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from statistics import median
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
SERVICE = ROOT / "versioned-rag-service"
CORPUS = SERVICE / "public_corpus_edge_ai"
EVAL = Path(__file__).resolve().parent
CASES = EVAL / "cases.jsonl"
LOCK = EVAL / "split_lock.json"
RUNTIME_CONFIG = CORPUS / "public_retrieval_runtime.json"
CODE_INPUTS = (
    Path(__file__).resolve(),
    SERVICE / "src" / "public_knowledge.py",
    SERVICE / "src" / "public_retrieval_runtime.py",
    SERVICE / "src" / "retrieval_fusion.py",
)
STRATEGIES = ("bm25", "bm25_faceted_rrf")

sys.path.insert(0, str(SERVICE))


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value.replace(b"\r\n", b"\n")).hexdigest()


def sha256_file(path: Path) -> str:
    return sha256_bytes(path.read_bytes())


def read_cases(path: Path = CASES) -> list[dict[str, Any]]:
    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    if not rows or len({row.get("case_id") for row in rows}) != len(rows):
        raise ValueError("evaluation cases must be non-empty and have unique case_id values")
    if any(row.get("split") not in {"dev", "holdout"} for row in rows):
        raise ValueError("evaluation cases must use dev or holdout split")
    family_splits: dict[str, set[str]] = defaultdict(set)
    source_splits: dict[str, set[str]] = defaultdict(set)
    source_ids = {
        str(source.get("source_id")) for source in
        json.loads((CORPUS / "corpus_manifest.json").read_text(encoding="utf-8")).get("sources", [])
    }
    for row in rows:
        family_splits[str(row.get("family_id"))].add(row["split"])
        for source_id in row.get("required_source_ids", []):
            if source_id not in source_ids:
                raise ValueError(f"unknown required source id: {source_id}")
            source_splits[source_id].add(row["split"])
    if any(len(splits) > 1 for splits in (*family_splits.values(), *source_splits.values())):
        raise ValueError("a source family may not be split between DEV and HOLDOUT")
    if {row["split"] for row in rows} != {"dev", "holdout"}:
        raise ValueError("evaluation cases must include DEV and HOLDOUT")
    return rows


def input_fingerprints(*, cases_path: Path = CASES, code_inputs: tuple[Path, ...] = CODE_INPUTS) -> dict[str, str]:
    values = {
        "corpus_manifest_sha256": sha256_file(CORPUS / "corpus_manifest.json"),
        "chunks_sha256": sha256_file(CORPUS / "chunks.json"),
        "dense_vectors_sha256": sha256_file(CORPUS / "dense_vectors.npy"),
        "retrieval_policy_sha256": sha256_file(CORPUS / "retrieval_policy.json"),
        "runtime_config_sha256": sha256_file(RUNTIME_CONFIG),
        "cases_sha256": sha256_file(cases_path),
    }
    values.update({f"code:{path.relative_to(ROOT).as_posix()}": sha256_file(path) for path in code_inputs})
    return values


def lock_payload(*, cases_path: Path = CASES, code_inputs: tuple[Path, ...] = CODE_INPUTS) -> dict[str, Any]:
    cases = read_cases(cases_path)
    return {
        "schema_version": 1,
        "dataset_id": "edge_ai_retrieval_v2",
        "case_count": len(cases),
        "split_counts": dict(sorted(Counter(row["split"] for row in cases).items())),
        "case_ids": sorted(row["case_id"] for row in cases),
        "family_splits": dict(sorted({row["family_id"]: row["split"] for row in cases}.items())),
        "strategy_allowlist": list(STRATEGIES),
        "input_fingerprints": input_fingerprints(cases_path=cases_path, code_inputs=code_inputs),
        "split_note": "Source-document families are held wholly in DEV or HOLDOUT; HOLDOUT is not used to tune query cases or policies.",
    }


def verify_lock(lock: dict[str, Any] | None = None, *, cases_path: Path = CASES,
                code_inputs: tuple[Path, ...] = CODE_INPUTS) -> dict[str, Any]:
    lock = lock or json.loads(LOCK.read_text(encoding="utf-8"))
    expected = lock_payload(cases_path=cases_path, code_inputs=code_inputs)
    for field in ("dataset_id", "case_count", "split_counts", "case_ids", "family_splits", "strategy_allowlist", "input_fingerprints"):
        if lock.get(field) != expected[field]:
            raise ValueError(f"evaluation lock mismatch: {field}")
    return expected


def create_runtime():
    from src.public_knowledge import PublicKnowledgeIndex
    from src.public_retrieval_runtime import PublicRetrievalRuntime

    index = PublicKnowledgeIndex(CORPUS)
    manifest_hash = sha256_file(CORPUS / "corpus_manifest.json")
    empty = {"schema_version": 1, "corpus_manifest_sha256": manifest_hash}
    # This corpus contains no approved OCR rows. Supplying empty, hash-matched
    # in-memory figure indexes exercises the deployed document retrieval strategy
    # without writing temporary artifacts into the immutable corpus.
    return PublicRetrievalRuntime(
        index, config_path=RUNTIME_CONFIG,
        sidecar_data={**empty, "chunks": []},
        inventory_data={**empty, "figures": []},
    )


def _matches_scope(row: dict[str, Any], scope: dict[str, Any]) -> bool:
    for request_key, expected in scope.items():
        if expected is None:
            continue
        row_key = "software_baselines" if request_key == "software_baseline" else request_key
        observed = row.get(row_key)
        if isinstance(observed, list):
            if "*" not in observed and expected not in observed:
                return False
        elif observed != "*" and observed != expected:
            return False
    return True


def _percentile(values: list[float], q: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    return round(ordered[max(0, math.ceil(q * len(ordered)) - 1)], 3)


def _metrics(rows: list[dict[str, Any]]) -> dict[str, Any]:
    answerable = [row for row in rows if row["answerable"]]
    unanswerable = [row for row in rows if not row["answerable"]]
    source_recalls = [row["source_recall"] for row in answerable if row["source_recall"] is not None]
    complete = [row for row in answerable if row["complete_source_set"]]
    wrong_scope = sum(row["wrong_scope_result_count"] for row in rows)
    category_rows: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        category_rows[row["category"]].append(row)
    return {
        "query_count": len(rows),
        "answerable_query_count": len(answerable),
        "unanswerable_query_count": len(unanswerable),
        "mean_required_source_recall": round(sum(source_recalls) / len(source_recalls), 4) if source_recalls else None,
        "complete_required_source_set_rate": round(len(complete) / len(answerable), 4) if answerable else None,
        "wrong_scope_result_count": wrong_scope,
        "wrong_scope_query_count": sum(row["wrong_scope_result_count"] > 0 for row in rows),
        "wrong_language_result_count": sum(row["wrong_language_result_count"] for row in rows),
        "wrong_snapshot_result_count": sum(row["wrong_snapshot_result_count"] for row in rows),
        "unanswerable_candidate_query_count": sum(row["candidate_count"] > 0 for row in unanswerable),
        "unanswerable_candidate_rate": (
            round(sum(row["candidate_count"] > 0 for row in unanswerable) / len(unanswerable), 4)
            if unanswerable else None
        ),
        "latency_ms": {
            "p50": _percentile([row["latency_ms"] for row in rows], .50),
            "p95": _percentile([row["latency_ms"] for row in rows], .95),
        },
        "by_category": {
            category: {
                "query_count": len(group),
                "mean_required_source_recall": round(
                    sum(row["source_recall"] for row in group if row["source_recall"] is not None)
                    / max(1, sum(row["source_recall"] is not None for row in group)), 4,
                ) if any(row["source_recall"] is not None for row in group) else None,
                "complete_required_source_set_count": sum(row["complete_source_set"] for row in group),
                "wrong_scope_result_count": sum(row["wrong_scope_result_count"] for row in group),
            }
            for category, group in sorted(category_rows.items())
        },
        "cases": rows,
    }


def evaluate(cases: list[dict[str, Any]], *, runtime=None, policies: tuple[str, ...] = STRATEGIES) -> dict[str, Any]:
    runtime = runtime or create_runtime()
    report: dict[str, Any] = {"schema_version": 1, "dataset_id": "edge_ai_retrieval_v2", "splits": {}}
    for split in ("dev", "holdout"):
        split_rows = [row for row in cases if row["split"] == split]
        if not split_rows:
            continue
        report["splits"][split] = {}
        for policy in policies:
            case_reports = []
            for case in split_rows:
                started = time.perf_counter()
                results = runtime.search(
                    case["query"], top_k=int(case["top_k"]), version=case["version"],
                    language=case["language"], policy=policy, **case.get("scope", {}),
                )
                latency = (time.perf_counter() - started) * 1000
                required = set(case.get("required_source_ids", []))
                retrieved = [str(row.get("source_id") or "") for row in results]
                retrieved_set = set(retrieved)
                recall = len(required & retrieved_set) / len(required) if required else None
                allowed_versions = runtime.base_index._version_members(case["version"])
                wrong_scope = sum(not _matches_scope(row, case.get("scope", {})) for row in results)
                wrong_language = sum(row.get("language") != "zh" for row in results)
                wrong_snapshot = sum(
                    allowed_versions is not None and row.get("version") not in allowed_versions
                    for row in results
                )
                case_reports.append({
                    "case_id": case["case_id"], "family_id": case["family_id"],
                    "category": case["category"], "answerable": bool(case["answerable"]),
                    "required_source_ids": sorted(required), "retrieved_source_ids": retrieved,
                    "source_recall": round(recall, 4) if recall is not None else None,
                    "complete_source_set": bool(required) and required.issubset(retrieved_set),
                    "candidate_count": len(results), "wrong_scope_result_count": wrong_scope,
                    "wrong_language_result_count": wrong_language,
                    "wrong_snapshot_result_count": wrong_snapshot,
                    "latency_ms": round(latency, 3),
                })
            report["splits"][split][policy] = _metrics(case_reports)
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--split", choices=("dev", "holdout", "all"), default="all")
    parser.add_argument("--strategies", nargs="+", choices=STRATEGIES, default=list(STRATEGIES))
    parser.add_argument("--output", type=Path)
    parser.add_argument("--freeze-lock", action="store_true", help="create the split lock once before the first evaluation")
    args = parser.parse_args()
    try:
        if args.freeze_lock:
            if LOCK.exists():
                raise ValueError("split lock already exists; refusing to overwrite the frozen lock")
            LOCK.write_text(json.dumps(lock_payload(), ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")
            print(json.dumps({"status": "LOCKED", "path": str(LOCK), "fingerprints": lock_payload()["input_fingerprints"]}, ensure_ascii=False, indent=2))
            return 0
        lock = json.loads(LOCK.read_text(encoding="utf-8"))
        verify_lock(lock)
        cases = read_cases()
        if args.split != "all":
            cases = [row for row in cases if row["split"] == args.split]
        report = evaluate(cases, policies=tuple(args.strategies))
        result = {
            "status": "MEASURED",
            "generated_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "input_fingerprints": lock["input_fingerprints"],
            "split_lock_sha256": sha256_file(LOCK),
            **report,
        }
        serialized = json.dumps(result, ensure_ascii=False, indent=2) + "\n"
        if args.output:
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(serialized, encoding="utf-8", newline="\n")
        print(serialized, end="")
        return 0
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(json.dumps({"status": "INVALID", "reason": str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
