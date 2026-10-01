"""Classify frozen retrieval misses without translating scores into confidence."""

from __future__ import annotations

import argparse
import json
from collections import defaultdict
from pathlib import Path

try:
    from .run_benchmark import HERE, _load_cases
except ImportError:  # Direct script invocation from the repository root.
    from run_benchmark import HERE, _load_cases


DIMENSIONS = {
    "by_category": "category",
    "by_query_language": "query_language",
    "by_relation_state": "expected_relation_state",
}


def _version_key(case: dict) -> str:
    versions = case.get("expected_component_versions", {})
    return ",".join(f"{name}={versions[name]}" for name in sorted(versions)) or "unspecified"


def analyze_failures(report: dict, cases: list[dict], policy: str = "bm25") -> dict:
    """Group missing sources/images and wrong-version hits by business dimension."""
    case_by_id = {case["case_id"]: case for case in cases}
    if len(case_by_id) != len(cases):
        raise ValueError("duplicate case IDs in failure-analysis input")
    failures = []
    no_answer_candidates = {}
    grouped = {key: defaultdict(lambda: {"case_ids": set(), "missing_source_ids": set(), "missing_image_ids": set(), "wrong_version_count": 0})
               for key in (*DIMENSIONS, "by_selected_component_version", "by_expected_modality")}
    splits = report.get("splits")
    if not isinstance(splits, dict):
        raise ValueError("benchmark report is missing splits")
    for split in ("dev", "holdout"):
        policy_report = splits.get(split, {}).get(policy)
        if not isinstance(policy_report, dict) or not isinstance(policy_report.get("cases"), list):
            raise ValueError(f"benchmark report is missing {split}/{policy} case details")
        rows = {row.get("case_id"): row for row in policy_report["cases"] if isinstance(row, dict)}
        expected_split_ids = {case_id for case_id, case in case_by_id.items() if case.get("split") == split}
        if set(rows) != expected_split_ids:
            raise ValueError(f"benchmark case rows do not match frozen {split} cases")
        no_answer_candidates[split] = policy_report.get("no_answer_nonempty_candidates", "unknown")
        for case_id in sorted(expected_split_ids):
            case = case_by_id[case_id]
            row = rows[case_id]
            required = set(case.get("required_sources", []))
            found_sources = set(row.get("found_sources_at_5", []))
            missing_sources = sorted(required - found_sources)
            expected_images = set(case.get("expected_image_ids", []))
            found_images = set(row.get("found_image_ids_at_5", []))
            missing_images = sorted(expected_images - found_images)
            version_mismatches = row.get("version_mismatches_at_5", [])
            if not (missing_sources or missing_images or version_mismatches):
                continue
            modality = "image" if expected_images else "text"
            failure = {
                "case_id": case_id,
                "split": split,
                "category": case.get("category", "unknown"),
                "query_language": case.get("query_language", "unknown"),
                "selected_component_versions": _version_key(case),
                "relation_state": case.get("expected_relation_state", "unknown"),
                "expected_modality": modality,
                "missing_required_sources": missing_sources,
                "missing_image_ids": missing_images,
                "hit_document_ids_at_5": row.get("hit_document_ids_at_5", []),
                "version_mismatches_at_5": version_mismatches,
            }
            failures.append(failure)
            dimensions = {
                "by_category": failure["category"],
                "by_query_language": failure["query_language"],
                "by_relation_state": failure["relation_state"],
                "by_selected_component_version": failure["selected_component_versions"],
                "by_expected_modality": modality,
            }
            for dimension, value in dimensions.items():
                bucket = grouped[dimension][value]
                bucket["case_ids"].add(case_id)
                bucket["missing_source_ids"].update(missing_sources)
                bucket["missing_image_ids"].update(missing_images)
                bucket["wrong_version_count"] += len(version_mismatches)

    return {
        "schema_version": 1,
        "benchmark": report.get("name"),
        "policy": policy,
        "failure_count": len(failures),
        "case_count": len(cases),
        "no_answer_nonempty_candidates": no_answer_candidates,
        "metric_scope": "retrieval misses and wrong-version diagnostics only; not answer accuracy or confidence",
        "failures": failures,
        **{
            key: {
                value: {
                    "case_ids": sorted(bucket["case_ids"]),
                    "missing_source_ids": sorted(bucket["missing_source_ids"]),
                    "missing_image_ids": sorted(bucket["missing_image_ids"]),
                    "wrong_version_count": bucket["wrong_version_count"],
                }
                for value, bucket in sorted(groups.items())
            }
            for key, groups in grouped.items()
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report", type=Path, default=HERE / "results" / "benchmark.json")
    parser.add_argument("--policy", default="bm25")
    parser.add_argument("--output", type=Path, default=HERE / "results" / "failure_analysis_bm25.json")
    args = parser.parse_args()
    report = json.loads(args.report.read_text(encoding="utf-8"))
    cases, _ = _load_cases()
    result = analyze_failures(report, cases, args.policy)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")
    print(json.dumps({
        "policy": result["policy"], "failure_count": result["failure_count"],
        "no_answer_nonempty_candidates": result["no_answer_nonempty_candidates"],
        "by_category": result["by_category"],
        "by_query_language": result["by_query_language"],
        "by_relation_state": result["by_relation_state"],
        "by_expected_modality": result["by_expected_modality"],
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
