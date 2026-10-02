"""Evaluate the edge-AI change planner and evidence retrieval without generation."""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import sys
import time
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
SERVICE = ROOT / "versioned-rag-service"
RETRIEVAL_EVAL = ROOT / "evaluation" / "edge_ai_retrieval_v2"
EVAL = Path(__file__).resolve().parent
CASES = EVAL / "cases.jsonl"
LOCK = EVAL / "split_lock.json"
PROFILE_PATH = ROOT / "change-review-agent" / "config" / "edge_ai_device_change_profile.json"
AGENT_ROOT = ROOT / "change-review-agent"
AGENT_CODE = (
    Path(__file__).resolve(),
    AGENT_ROOT / "app" / "change_request.py",
    AGENT_ROOT / "app" / "domain_profile.py",
    PROFILE_PATH,
    RETRIEVAL_EVAL / "run_evaluation.py",
    SERVICE / "src" / "public_knowledge.py",
    SERVICE / "src" / "public_retrieval_runtime.py",
    SERVICE / "src" / "retrieval_fusion.py",
)

sys.path.insert(0, str(AGENT_ROOT))
sys.path.insert(0, str(SERVICE))
_retrieval_spec = importlib.util.spec_from_file_location(
    "edge_ai_retrieval_evaluation", RETRIEVAL_EVAL / "run_evaluation.py",
)
if _retrieval_spec is None or _retrieval_spec.loader is None:
    raise RuntimeError("retrieval evaluation runner is unavailable")
retrieval_eval = importlib.util.module_from_spec(_retrieval_spec)
sys.modules[_retrieval_spec.name] = retrieval_eval
_retrieval_spec.loader.exec_module(retrieval_eval)

from app.change_request import build_request_plan  # noqa: E402
from app.domain_profile import load_change_profile  # noqa: E402


def read_cases(path: Path = CASES) -> list[dict[str, Any]]:
    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    if not rows or len({row.get("case_id") for row in rows}) != len(rows):
        raise ValueError("change-review cases must be non-empty and have unique case_id values")
    if any(row.get("split") not in {"dev", "holdout"} for row in rows):
        raise ValueError("change-review cases must use dev or holdout split")
    families: dict[str, set[str]] = defaultdict(set)
    for row in rows:
        families[str(row.get("family_id"))].add(row["split"])
    if any(len(splits) > 1 for splits in families.values()):
        raise ValueError("a change-review source family may not be split between DEV and HOLDOUT")
    if {row["split"] for row in rows} != {"dev", "holdout"}:
        raise ValueError("change-review cases must include DEV and HOLDOUT")
    return rows


def input_fingerprints(*, cases_path: Path = CASES) -> dict[str, str]:
    values = retrieval_eval.input_fingerprints(
        cases_path=RETRIEVAL_EVAL / "cases.jsonl",
        code_inputs=retrieval_eval.CODE_INPUTS,
    )
    values["agent_cases_sha256"] = retrieval_eval.sha256_file(cases_path)
    values.update({
        f"code:{path.relative_to(ROOT).as_posix()}": retrieval_eval.sha256_file(path)
        for path in AGENT_CODE
    })
    return values


def lock_payload(*, cases_path: Path = CASES) -> dict[str, Any]:
    cases = read_cases(cases_path)
    return {
        "schema_version": 1,
        "dataset_id": "edge_ai_change_review_v2",
        "case_count": len(cases),
        "split_counts": dict(sorted(Counter(row["split"] for row in cases).items())),
        "case_ids": sorted(row["case_id"] for row in cases),
        "family_splits": dict(sorted({row["family_id"]: row["split"] for row in cases}.items())),
        "input_fingerprints": input_fingerprints(cases_path=cases_path),
        "split_note": "Change-review cases and their source families are fixed before scoring; HOLDOUT is not used to tune the planner.",
    }


def verify_lock(lock: dict[str, Any] | None = None, *, cases_path: Path = CASES) -> dict[str, Any]:
    lock = lock or json.loads(LOCK.read_text(encoding="utf-8"))
    expected = lock_payload(cases_path=cases_path)
    for field in ("dataset_id", "case_count", "split_counts", "case_ids", "family_splits", "input_fingerprints"):
        if lock.get(field) != expected[field]:
            raise ValueError(f"change-review evaluation lock mismatch: {field}")
    return expected


def _is_missing_scope(plan: dict[str, Any]) -> bool:
    return bool(plan.get("scope_warnings"))


def evaluate(cases: list[dict[str, Any]], *, runtime=None, profile: dict | None = None) -> dict[str, Any]:
    runtime = runtime or retrieval_eval.create_runtime()
    profile = profile or load_change_profile(PROFILE_PATH)
    report: dict[str, Any] = {
        "schema_version": 1, "dataset_id": "edge_ai_change_review_v2", "splits": {},
    }
    for split in ("dev", "holdout"):
        split_cases = [case for case in cases if case["split"] == split]
        if not split_cases:
            continue
        case_reports = []
        for case in split_cases:
            scope = dict(case.get("device_scope") or {})
            planning_started = time.perf_counter()
            plan = build_request_plan(
                case["summary"], change_type="auto", impact_scope=case.get("impact_scope"),
                profile=profile,
                device_model=scope.get("device_model"), module_sku=scope.get("module_sku"),
                carrier_board=scope.get("carrier_board"), software_baseline=scope.get("software_baseline"),
                target_snapshot=case.get("target_snapshot", "current"),
            )
            planning_ms = (time.perf_counter() - planning_started) * 1000
            retrieved_ids: set[str] = set()
            query_traces = []
            search_ms = []
            for query in plan["queries"]:
                started = time.perf_counter()
                rows = runtime.search(
                    query["search_query"], top_k=int(case.get("top_k", 5)),
                    version=case.get("target_snapshot", "current"), language="zh",
                    **{key: value for key, value in scope.items() if value is not None},
                )
                elapsed = (time.perf_counter() - started) * 1000
                search_ms.append(elapsed)
                ids = [str(row.get("source_id") or "") for row in rows]
                retrieved_ids.update(ids)
                query_traces.append({"query": query["query"], "search_query": query["search_query"], "source_ids": ids})
            required = set(case.get("required_source_ids", []))
            source_recall = len(required & retrieved_ids) / len(required) if required else None
            missing_scope = _is_missing_scope(plan)
            case_reports.append({
                "case_id": case["case_id"], "family_id": case["family_id"],
                "category": case["category"],
                "expected_change_type": case["expected_change_type"],
                "planned_change_type": plan["change_type"],
                "change_type_match": plan["change_type"] == case["expected_change_type"],
                "planned_query_count": len(plan["queries"]),
                "query_limit": plan["query_limit"],
                "required_source_ids": sorted(required),
                "retrieved_source_ids": sorted(retrieved_ids),
                "required_source_recall": round(source_recall, 4) if source_recall is not None else None,
                "complete_required_source_set": bool(required) and required.issubset(retrieved_ids),
                "expected_scope_gap": bool(case["expected_scope_gap"]),
                "scope_gap_detected": missing_scope,
                "scope_gap_match": missing_scope == bool(case["expected_scope_gap"]),
                "manual_review_required": bool(plan.get("manual_review_required")),
                "manual_review_expected": bool(case["expected_manual_review"]),
                "manual_review_match": bool(plan.get("manual_review_required")) == bool(case["expected_manual_review"]),
                "planning_latency_ms": round(planning_ms, 3),
                "retrieval_latency_ms": round(sum(search_ms), 3),
                "queries": query_traces,
            })
        answerable = [row for row in case_reports if row["required_source_ids"]]
        recall_values = [row["required_source_recall"] for row in answerable]
        report["splits"][split] = {
            "case_count": len(case_reports),
            "expected_change_type_accuracy": round(sum(row["change_type_match"] for row in case_reports) / len(case_reports), 4),
            "required_source_recall_across_planned_queries": round(sum(recall_values) / len(recall_values), 4) if recall_values else None,
            "complete_required_source_set_count": sum(row["complete_required_source_set"] for row in answerable),
            "answerable_case_count": len(answerable),
            "scope_gap_detection_accuracy": round(sum(row["scope_gap_match"] for row in case_reports) / len(case_reports), 4),
            "manual_review_boundary_accuracy": round(sum(row["manual_review_match"] for row in case_reports) / len(case_reports), 4),
            "manual_review_required_count": sum(row["manual_review_required"] for row in case_reports),
            "human_quality_scoring": {
                "status": "not_scored",
                "note": "Planner coverage and retrieval evidence are automated; impact-candidate precision and recommendation correctness require blinded human review.",
                "cases_requiring_review": len(case_reports),
            },
            "planning_latency_ms": {
                "p50": retrieval_eval._percentile([row["planning_latency_ms"] for row in case_reports], .50),
                "p95": retrieval_eval._percentile([row["planning_latency_ms"] for row in case_reports], .95),
            },
            "retrieval_latency_ms": {
                "p50": retrieval_eval._percentile([row["retrieval_latency_ms"] for row in case_reports], .50),
                "p95": retrieval_eval._percentile([row["retrieval_latency_ms"] for row in case_reports], .95),
            },
            "cases": case_reports,
        }
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--split", choices=("dev", "holdout", "all"), default="all")
    parser.add_argument("--output", type=Path)
    parser.add_argument("--freeze-lock", action="store_true")
    args = parser.parse_args()
    try:
        if args.freeze_lock:
            if LOCK.exists():
                raise ValueError("split lock already exists; refusing to overwrite the frozen lock")
            payload = lock_payload()
            LOCK.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")
            print(json.dumps({"status": "LOCKED", "case_count": payload["case_count"]}, ensure_ascii=False))
            return 0
        lock = json.loads(LOCK.read_text(encoding="utf-8"))
        verify_lock(lock)
        cases = read_cases()
        if args.split != "all":
            cases = [row for row in cases if row["split"] == args.split]
        report = {
            "status": "MEASURED",
            "generated_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "input_fingerprints": lock["input_fingerprints"],
            "split_lock_sha256": retrieval_eval.sha256_file(LOCK),
            **evaluate(cases),
        }
        serialized = json.dumps(report, ensure_ascii=False, indent=2) + "\n"
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
