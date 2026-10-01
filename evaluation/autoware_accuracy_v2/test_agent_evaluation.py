from __future__ import annotations

import pytest

from run_agent_evaluation import evaluate_agent_results, validate_agent_cases


def agent_case(case_id="case-1", *, split="dev", severity="high"):
    return {
        "case_id": case_id,
        "family_id": f"family-{case_id}",
        "split": split,
        "language": "bilingual",
        "target_version": "latest",
        "change_type": "planning_behavior",
        "severity": severity,
        "change_summary": "调整轨迹校验行为并检查验证资料。",
        "required_impact_sources": ["universe:en:planning/validator", "docs-main:zh:guide/validation"],
        "required_checklist_items": ["design", "configuration", "test"],
        "expected_relation_states": {"universe:en:planning/validator": "none"},
        "expected_gaps": [],
        "critical_source_ids": ["universe:en:planning/validator"],
        "expected_abstain": False,
    }


def test_agent_validator_rejects_unknown_source_family_leakage_and_bad_severity():
    manifest = {
        "sources": [
            {"source_id": "universe:en:planning/validator", "version": "0.52.0"},
            {"source_id": "docs-main:zh:guide/validation", "version": "docs-main"},
        ]
    }
    cases = [agent_case("a"), agent_case("b", split="holdout")]
    cases[1]["family_id"] = cases[0]["family_id"]
    with pytest.raises(ValueError, match="family"):
        validate_agent_cases(cases, manifest, forbidden_families=set())

    old_dev_family = agent_case("old-dev-family")
    validate_agent_cases(
        [old_dev_family], manifest, forbidden_families={old_dev_family["family_id"]},
    )
    old_holdout_family = agent_case("old-holdout-family", split="holdout")
    with pytest.raises(ValueError, match="forbidden"):
        validate_agent_cases(
            [old_holdout_family], manifest, forbidden_families={old_holdout_family["family_id"]},
        )

    invalid = agent_case("bad-source")
    invalid["required_impact_sources"] = ["missing-source"]
    with pytest.raises(ValueError, match="source"):
        validate_agent_cases([invalid], manifest, forbidden_families=set())

    invalid_severity = agent_case("bad-severity")
    invalid_severity["severity"] = "urgent"
    with pytest.raises(ValueError, match="severity"):
        validate_agent_cases([invalid_severity], manifest, forbidden_families=set())


def test_agent_metrics_expose_critical_misses_and_false_no_impact():
    case = agent_case()
    result = {
        "case_id": case["case_id"],
        "model_status": "OK",
        "impact_candidates": ["docs-main:zh:guide/validation"],
        "covered_checklist_items": ["design", "configuration"],
        "relation_states": {"universe:en:planning/validator": "candidate"},
        "summary": "无影响。",
        "declared_no_impact": True,
        "complete": False,
        "search_calls": 4,
        "selected_evidence_count": 2,
        "latency_ms": 12.0,
    }
    report = evaluate_agent_results([case], {case["case_id"]: result})

    assert report["metrics"]["critical_impact_miss_count"] == 1
    assert report["metrics"]["false_no_impact_count"] == 1
    assert report["metrics"]["checklist_item_coverage"] == pytest.approx(2 / 3)
    assert report["metrics"]["relation_state_accuracy"] == 0.0
    assert report["by_severity"]["high"]["case_count"] == 1


def test_agent_metrics_track_false_positive_impact_candidates():
    case = agent_case()
    result = {
        "case_id": case["case_id"],
        "model_status": "OK",
        "impact_candidates": [*case["required_impact_sources"], "unrelated-source"],
        "covered_checklist_items": case["required_checklist_items"],
        "relation_states": case["expected_relation_states"],
        "complete": True,
        "search_calls": 2,
        "selected_evidence_count": 4,
        "latency_ms": 30.0,
    }
    report = evaluate_agent_results([case], {case["case_id"]: result})
    assert report["metrics"]["false_impact_candidate_count"] == 1
    assert report["metrics"]["critical_impact_miss_count"] == 0


def test_retrieval_only_baseline_does_not_masquerade_as_agent_impact_quality():
    case = agent_case()
    result = {
        "case_id": case["case_id"],
        "model_status": "NOT_CALLED",
        "retrieved_source_ids": [case["required_impact_sources"][0]],
        "impact_candidates": [],
        "search_calls": 4,
        "selected_evidence_count": 3,
        "latency_ms": 22.0,
    }
    report = evaluate_agent_results([case], {case["case_id"]: result})

    assert report["metrics"]["evidence_source_recall"] == 0.5
    assert report["metrics"]["complete_evidence_source_rate"] == 0.0
    assert report["metrics"]["impact_source_recall"] is None
    assert report["metrics"]["model_evaluated_case_count"] == 0


def test_retrieval_only_candidates_do_not_count_as_agent_abstention_failures():
    case = agent_case()
    case["expected_abstain"] = True
    result = {
        "case_id": case["case_id"], "model_status": "NOT_CALLED",
        "retrieved_source_ids": [case["required_impact_sources"][0]],
        "impact_candidates": [], "abstained": False, "abstention_evaluated": False,
    }

    report = evaluate_agent_results([case], {case["case_id"]: result})

    assert report["metrics"]["abstention_precision"] is None
    assert report["metrics"]["abstention_recall"] is None


def test_retrieval_only_agent_report_measures_check_and_language_coverage():
    case = agent_case()
    result = {
        "case_id": case["case_id"], "model_status": "NOT_CALLED",
        "coverage": {
            "required_check_count": 2, "covered_check_count": 1,
            "attempted_languages": ["zh", "en"], "covered_languages": ["zh"],
            "complete": False,
        },
    }

    report = evaluate_agent_results([case], {case["case_id"]: result})

    assert report["metrics"]["retrieval_check_coverage_rate"] == 0.5
    assert report["metrics"]["retrieval_language_coverage_rate"] == 0.5
    assert report["metrics"]["complete_retrieval_case_rate"] == 0.0
