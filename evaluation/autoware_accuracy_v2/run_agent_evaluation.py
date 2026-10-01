"""Evaluate saved Agent review traces against human-authored impact expectations."""

from __future__ import annotations

import argparse
import json
import math
import statistics
from collections import Counter, defaultdict
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
CORPUS = ROOT / "versioned-rag-service" / "public_corpus_autoware"
HERE = Path(__file__).resolve().parent
CHANGE_TYPES = frozenset({
    "parameter_config", "interface_compatibility", "workflow_behavior", "planning_behavior",
    "data_storage", "security_permission", "general",
})
SEVERITIES = frozenset({"low", "medium", "high"})
RELATION_STATES = frozenset({"verified", "candidate", "unknown", "none"})


def _source_id(row: dict) -> str:
    return str(row.get("source_id") or f"{row['version']}:{row['language']}:{row['document_key']}")


def _source_family(source_id: str) -> str:
    parts = source_id.split(":", 2)
    if len(parts) != 3:
        raise ValueError(f"invalid source ID: {source_id}")
    component = "universe" if parts[2].startswith("planning/") else "documentation"
    return f"{component}:{parts[2]}"


def _normalized_query(value: str) -> str:
    import unicodedata
    import re
    normalized = unicodedata.normalize("NFKC", value).casefold()
    return "".join(character for character in normalized if character.isalnum())


def _index_unique(rows: list[dict], label: str) -> dict[str, dict]:
    result = {}
    for row in rows:
        if not isinstance(row, dict) or not isinstance(row.get("case_id"), str) or not row["case_id"]:
            raise ValueError(f"{label} row requires a non-empty case_id")
        if row["case_id"] in result:
            raise ValueError(f"duplicate {label} case id: {row['case_id']}")
        result[row["case_id"]] = row
    return result


def load_jsonl(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def validate_agent_cases(
    cases: list[dict], manifest: dict, *, forbidden_families: set[str],
    forbidden_source_families: set[str] | None = None, forbidden_summaries: set[str] | None = None,
) -> None:
    required_fields = {
        "case_id", "family_id", "split", "language", "target_version", "change_type", "severity",
        "change_summary", "required_impact_sources", "required_checklist_items",
        "expected_relation_states", "expected_gaps", "critical_source_ids", "expected_abstain",
    }
    sources = manifest.get("sources", []) if isinstance(manifest, dict) else []
    source_ids = {
        _source_id(row) for row in sources
        if isinstance(row, dict) and row.get("version") and row.get("language") and row.get("document_key")
    }
    source_ids.update(
        row["source_id"] for row in sources
        if isinstance(row, dict) and isinstance(row.get("source_id"), str)
    )
    ids: set[str] = set()
    normalized_families: dict[str, set[str]] = defaultdict(set)
    source_family_splits: dict[str, set[str]] = defaultdict(set)
    seen_summaries: set[str] = set()
    for case in cases:
        if not isinstance(case, dict) or not required_fields.issubset(case):
            raise ValueError("Agent case is missing required fields")
        case_id, family_id = case["case_id"], case["family_id"]
        if not isinstance(case_id, str) or not case_id.strip() or case_id in ids:
            raise ValueError("Agent case IDs must be unique non-empty strings")
        if not isinstance(family_id, str) or not family_id.strip():
            raise ValueError(f"invalid family_id for {case_id}")
        ids.add(case_id)
        split = case["split"]
        if split not in {"dev", "holdout"}:
            raise ValueError(f"invalid split for {case_id}")
        if split == "holdout" and family_id in forbidden_families:
            raise ValueError(f"Agent case family is present in the forbidden V1 HOLDOUT set: {family_id}")
        normalized_families[family_id].add(split)
        if len(normalized_families[family_id]) > 1:
            raise ValueError(f"Agent family split leakage: {family_id}")
        if case["language"] not in {"zh", "en", "bilingual"}:
            raise ValueError(f"invalid language for {case_id}")
        if case["change_type"] not in CHANGE_TYPES:
            raise ValueError(f"invalid change_type for {case_id}")
        if case["severity"] not in SEVERITIES:
            raise ValueError(f"invalid severity for {case_id}")
        if not isinstance(case["target_version"], str) or not case["target_version"].strip():
            raise ValueError(f"invalid target_version for {case_id}")
        if not isinstance(case["change_summary"], str) or not case["change_summary"].strip():
            raise ValueError(f"empty change_summary for {case_id}")
        normalized_summary = _normalized_query(case["change_summary"])
        if normalized_summary in seen_summaries or normalized_summary in (forbidden_summaries or set()):
            raise ValueError(f"duplicate or V1-overlapping change summary for {case_id}")
        seen_summaries.add(normalized_summary)
        for field in ("required_impact_sources", "required_checklist_items", "expected_gaps", "critical_source_ids"):
            values = case[field]
            if not isinstance(values, list) or any(not isinstance(value, str) or not value.strip() for value in values):
                raise ValueError(f"invalid {field} for {case_id}")
            if len(values) != len(set(values)):
                raise ValueError(f"duplicate {field} for {case_id}")
        unknown = set(case["required_impact_sources"]) - source_ids
        unknown |= set(case["critical_source_ids"]) - source_ids
        if unknown:
            raise ValueError(f"unknown required/critical source IDs for {case_id}: {sorted(unknown)}")
        split_source_ids = set(case["required_impact_sources"]) | set(case["critical_source_ids"]) | set(case["expected_relation_states"])
        for source_id in split_source_ids:
            source_family = _source_family(source_id)
            source_family_splits[source_family].add(split)
            if len(source_family_splits[source_family]) > 1:
                raise ValueError(f"Agent source family split leakage: {source_family}")
            if split == "holdout" and source_family in (forbidden_source_families or set()):
                raise ValueError(f"Agent source family is present in the forbidden V1 HOLDOUT set: {source_family}")
        if not set(case["critical_source_ids"]).issubset(case["required_impact_sources"]):
            raise ValueError(f"critical sources must be required impact sources for {case_id}")
        states = case["expected_relation_states"]
        if not isinstance(states, dict) or not set(states).issubset(source_ids):
            raise ValueError(f"invalid expected relation source IDs for {case_id}")
        if any(state not in RELATION_STATES for state in states.values()):
            raise ValueError(f"invalid expected relation state for {case_id}")
        if not isinstance(case["expected_abstain"], bool):
            raise ValueError(f"expected_abstain must be boolean for {case_id}")


def _percentile(values: list[float], fraction: float) -> float | None:
    finite = sorted(value for value in values if isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value) and value >= 0)
    return finite[max(0, math.ceil(len(finite) * fraction) - 1)] if finite else None


def _evaluate_subset(cases: list[dict], results: dict[str, dict], *, include_groups: bool) -> dict:
    evidence_required_total = evidence_retrieved_required = evidence_complete_count = 0
    impact_required_total = impact_retrieved_required = impact_complete_count = 0
    critical_total = critical_misses = false_no_impact = false_impact_count = 0
    checklist_total = checklist_covered = relation_total = relation_correct = 0
    model_evaluated_cases = 0
    expected_gap_total = gap_found = 0
    abstain_tp = abstain_fp = abstain_fn = 0
    abstention_evaluated_cases = 0
    retrieval_checks_required = retrieval_checks_covered = 0
    retrieval_languages_attempted = retrieval_languages_covered = 0
    retrieval_coverage_cases = retrieval_complete_cases = 0
    latencies: list[float] = []
    call_counts: list[int] = []
    selected_evidence_counts: list[int] = []
    rows = []
    for case in cases:
        result = results.get(case["case_id"], {})
        impacts = result.get("impact_candidates", [])
        if not isinstance(impacts, list):
            raise ValueError(f"impact_candidates must be a list for {case['case_id']}")
        impact_ids = set(impacts)
        if any(not isinstance(value, str) or not value for value in impact_ids):
            raise ValueError(f"invalid impact candidate IDs for {case['case_id']}")
        retrieved_rows = result.get("retrieved_source_ids", [])
        if not isinstance(retrieved_rows, list) or any(not isinstance(value, str) or not value for value in retrieved_rows):
            raise ValueError(f"retrieved_source_ids must be non-empty strings for {case['case_id']}")
        retrieved_ids = set(retrieved_rows)
        required = set(case["required_impact_sources"])
        critical = set(case["critical_source_ids"])
        checklist_actual = set(result.get("covered_checklist_items", []))
        if any(not isinstance(value, str) for value in checklist_actual):
            raise ValueError(f"invalid covered_checklist_items for {case['case_id']}")
        expected_relations = case["expected_relation_states"]
        actual_relations = result.get("relation_states", {})
        if not isinstance(actual_relations, dict):
            raise ValueError(f"relation_states must be an object for {case['case_id']}")
        expected_gaps = set(case["expected_gaps"])
        actual_gaps = set(result.get("gap_types", []))
        if any(not isinstance(value, str) for value in actual_gaps):
            raise ValueError(f"gap_types must contain strings for {case['case_id']}")
        if not isinstance(result.get("complete", False), bool):
            raise ValueError(f"complete must be boolean for {case['case_id']}")
        coverage = result.get("coverage")
        if coverage is not None:
            if not isinstance(coverage, dict):
                raise ValueError(f"coverage must be an object for {case['case_id']}")
            required_checks = coverage.get("required_check_count")
            covered_checks = coverage.get("covered_check_count")
            attempted_languages = coverage.get("attempted_languages", [])
            covered_languages = coverage.get("covered_languages", [])
            coverage_complete = coverage.get("complete")
            if (
                not isinstance(required_checks, int) or isinstance(required_checks, bool) or required_checks < 0
                or not isinstance(covered_checks, int) or isinstance(covered_checks, bool)
                or not 0 <= covered_checks <= required_checks
                or not isinstance(attempted_languages, list) or not isinstance(covered_languages, list)
                or any(not isinstance(language, str) for language in attempted_languages + covered_languages)
                or not set(covered_languages).issubset(attempted_languages)
                or not isinstance(coverage_complete, bool)
            ):
                raise ValueError(f"invalid coverage fields for {case['case_id']}")
            retrieval_checks_required += required_checks
            retrieval_checks_covered += covered_checks
            retrieval_languages_attempted += len(attempted_languages)
            retrieval_languages_covered += len(covered_languages)
            retrieval_coverage_cases += 1
            retrieval_complete_cases += int(coverage_complete)
        abstained = bool(result.get("abstained", result.get("status") in {"ABSTAINED", "NO_EVIDENCE"}))
        evidence_required_total += len(required)
        evidence_retrieved_required += len(required & retrieved_ids)
        evidence_complete_count += int(bool(required) and required.issubset(retrieved_ids))
        model_evaluated = result.get("model_status") == "OK"
        if model_evaluated:
            model_evaluated_cases += 1
            impact_required_total += len(required)
            impact_retrieved_required += len(required & impact_ids)
            impact_complete_count += int(bool(required) and required.issubset(impact_ids))
            critical_total += len(critical)
            critical_misses += len(critical - impact_ids)
            declared_no_impact = bool(result.get("declared_no_impact", False))
            false_no_impact += int(declared_no_impact and bool(required))
            false_impact_count += len(impact_ids - required)
        required_checks = set(case["required_checklist_items"])
        if model_evaluated:
            checklist_total += len(required_checks)
            checklist_covered += len(required_checks & checklist_actual)
        relation_total += len(expected_relations)
        relation_correct += sum(actual_relations.get(source_id) == state for source_id, state in expected_relations.items())
        expected_gap_total += len(expected_gaps)
        gap_found += len(expected_gaps & actual_gaps)
        expected_abstain = case["expected_abstain"]
        abstention_evaluated = result.get("abstention_evaluated", model_evaluated)
        if not isinstance(abstention_evaluated, bool):
            raise ValueError(f"abstention_evaluated must be boolean for {case['case_id']}")
        if abstention_evaluated:
            abstention_evaluated_cases += 1
            abstain_tp += int(expected_abstain and abstained)
            abstain_fp += int(not expected_abstain and abstained)
            abstain_fn += int(expected_abstain and not abstained)
        latency = result.get("latency_ms")
        if isinstance(latency, (int, float)) and not isinstance(latency, bool) and math.isfinite(latency) and latency >= 0:
            latencies.append(float(latency))
        calls = result.get("search_calls")
        if isinstance(calls, int) and not isinstance(calls, bool) and calls >= 0:
            call_counts.append(calls)
        evidence_count = result.get("selected_evidence_count")
        if isinstance(evidence_count, int) and not isinstance(evidence_count, bool) and evidence_count >= 0:
            selected_evidence_counts.append(evidence_count)
        rows.append({
            "case_id": case["case_id"], "severity": case["severity"],
            "required_impact_sources": sorted(required), "impact_candidates": sorted(impact_ids),
            "retrieved_source_ids": sorted(retrieved_ids),
            "coverage": coverage,
            "critical_misses": sorted(critical - impact_ids) if model_evaluated else None,
            "missing_checklist_items": sorted(required_checks - checklist_actual) if model_evaluated else None,
            "relation_mismatches": {
                source_id: {"expected": state, "actual": actual_relations.get(source_id)}
                for source_id, state in expected_relations.items()
                if actual_relations.get(source_id) != state
            },
        })
    count = len(cases)
    metrics = {
        "evidence_source_recall": evidence_retrieved_required / evidence_required_total if evidence_required_total else None,
        "complete_evidence_source_rate": evidence_complete_count / sum(bool(case["required_impact_sources"]) for case in cases) if any(case["required_impact_sources"] for case in cases) else None,
        "model_evaluated_case_count": model_evaluated_cases,
        "impact_source_recall": impact_retrieved_required / impact_required_total if impact_required_total else None,
        "complete_impact_source_rate": impact_complete_count / sum(
            bool(case["required_impact_sources"]) for case in cases
            if results.get(case["case_id"], {}).get("model_status") == "OK"
        ) if model_evaluated_cases else None,
        "critical_impact_miss_count": critical_misses if model_evaluated_cases else None,
        "critical_impact_miss_rate": critical_misses / critical_total if critical_total else None,
        "false_no_impact_count": false_no_impact if model_evaluated_cases else None,
        "false_impact_candidate_count": false_impact_count if model_evaluated_cases else None,
        "checklist_item_coverage": checklist_covered / checklist_total if checklist_total else None,
        "relation_state_accuracy": relation_correct / relation_total if relation_total else None,
        "expected_gap_recall": gap_found / expected_gap_total if expected_gap_total else None,
        "abstention_evaluated_case_count": abstention_evaluated_cases,
        "retrieval_check_coverage_rate": retrieval_checks_covered / retrieval_checks_required if retrieval_checks_required else None,
        "retrieval_language_coverage_rate": retrieval_languages_covered / retrieval_languages_attempted if retrieval_languages_attempted else None,
        "complete_retrieval_case_rate": retrieval_complete_cases / retrieval_coverage_cases if retrieval_coverage_cases else None,
        "abstention_precision": abstain_tp / (abstain_tp + abstain_fp) if abstain_tp + abstain_fp else None,
        "abstention_recall": abstain_tp / (abstain_tp + abstain_fn) if abstain_tp + abstain_fn else None,
        "search_calls_mean": statistics.mean(call_counts) if call_counts else None,
        "selected_evidence_mean": statistics.mean(selected_evidence_counts) if selected_evidence_counts else None,
        "latency_p50_ms": _percentile(latencies, 0.50),
        "latency_p95_ms": _percentile(latencies, 0.95),
    }
    result = {"case_count": count, "metrics": metrics, "cases": rows}
    if include_groups:
        for key, values in (
            ("by_severity", sorted({case["severity"] for case in cases})),
            ("by_change_type", sorted({case["change_type"] for case in cases})),
            ("by_language", sorted({case["language"] for case in cases})),
        ):
            result[key] = {
                value: _evaluate_subset(
                    [case for case in cases if case[key.removeprefix("by_")] == value],
                    results, include_groups=False,
                )
                for value in values
            }
    return result


def evaluate_agent_results(cases: list[dict], results_by_case: dict[str, dict]) -> dict:
    report = _evaluate_subset(cases, results_by_case, include_groups=True)
    report["metric_scope"] = "change-review candidate and workflow coverage; an impact candidate is not a confirmed impact or final approval"
    report["label_scope_counts"] = dict(sorted(Counter(
        str(case.get("label_scope", "unspecified")) for case in cases
    ).items()))
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--split", choices=("dev", "holdout"), default="dev")
    parser.add_argument("--cases", type=Path, default=HERE / "agent_cases.jsonl")
    parser.add_argument("--results", type=Path, default=HERE / "results" / "agent-baseline.jsonl")
    parser.add_argument("--output", type=Path, default=HERE / "results" / "agent-evaluation.json")
    args = parser.parse_args()
    manifest = json.loads((CORPUS / "corpus_manifest.json").read_text(encoding="utf-8"))
    cases = load_jsonl(args.cases)
    v1_path = ROOT / "evaluation" / "autoware_quality_v1" / "cases.jsonl"
    v1_cases = load_jsonl(v1_path)
    forbidden_families = {
        str(row["family_id"]) for row in v1_cases
        if row.get("split") == "holdout" and row.get("family_id")
    }
    forbidden_source_families = set()
    for old_case in v1_cases:
        if old_case.get("split") != "holdout":
            continue
        for source_id in old_case.get("required_sources", []):
            forbidden_source_families.add(_source_family(str(source_id)))
    forbidden_summaries = {
        _normalized_query(str(row.get("query") or "")) for row in v1_cases if row.get("query")
    }
    validate_agent_cases(
        cases, manifest, forbidden_families=forbidden_families,
        forbidden_source_families=forbidden_source_families,
        forbidden_summaries=forbidden_summaries,
    )
    results = _index_unique(load_jsonl(args.results), "result")
    selected = [case for case in cases if case["split"] == args.split]
    report = {
        "schema_version": 1, "evaluation": "autoware_accuracy_v2_agent",
        "split": args.split,
        "missing_result_count": sum(case["case_id"] not in results for case in selected),
        "results": evaluate_agent_results(selected, results),
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")
    print(json.dumps(report["results"]["metrics"], ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
