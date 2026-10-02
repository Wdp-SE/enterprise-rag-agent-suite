from __future__ import annotations

import importlib.util
from pathlib import Path


SCRIPT = Path(__file__).with_name("run_evaluation.py")
spec = importlib.util.spec_from_file_location("edge_ai_retrieval_v2", SCRIPT)
evaluation = importlib.util.module_from_spec(spec)
assert spec.loader
spec.loader.exec_module(evaluation)


def test_source_families_are_not_split_between_dev_and_holdout():
    cases = evaluation.read_cases()
    families = {}
    for case in cases:
        previous = families.setdefault(case["family_id"], case["split"])
        assert previous == case["split"]
    assert {case["split"] for case in cases} == {"dev", "holdout"}
    assert sum(case["split"] == "dev" for case in cases) > 0
    assert sum(case["split"] == "holdout" for case in cases) > 0


def test_frozen_lock_detects_case_mutation():
    lock = evaluation.lock_payload()
    lock["input_fingerprints"]["cases_sha256"] = "0" * 64

    try:
        evaluation.verify_lock(lock)
    except ValueError as exc:
        assert "input_fingerprints" in str(exc)
    else:
        raise AssertionError("mutated cases were accepted by the frozen lock")


def test_metrics_keep_answerable_recall_separate_from_no_answer_candidates():
    metrics = evaluation._metrics([
        {
            "answerable": True, "source_recall": 1.0, "complete_source_set": True,
            "wrong_scope_result_count": 0, "wrong_language_result_count": 0,
            "wrong_snapshot_result_count": 0, "latency_ms": 4.0,
            "candidate_count": 2, "category": "fact",
        },
        {
            "answerable": False, "source_recall": None, "complete_source_set": False,
            "wrong_scope_result_count": 0, "wrong_language_result_count": 0,
            "wrong_snapshot_result_count": 0, "latency_ms": 8.0,
            "candidate_count": 1, "category": "out_of_corpus",
        },
    ])

    assert metrics["mean_required_source_recall"] == 1.0
    assert metrics["complete_required_source_set_rate"] == 1.0
    assert metrics["unanswerable_query_count"] == 1
    assert metrics["unanswerable_candidate_query_count"] == 1
    assert metrics["unanswerable_candidate_rate"] == 1.0
    assert metrics["latency_ms"]["p50"] == 4.0


def test_actual_index_eval_runs_both_strategies_without_model_calls():
    cases = [row for row in evaluation.read_cases() if row["split"] == "dev"][:2]
    result = evaluation.evaluate(cases)

    assert set(result["splits"]["dev"]) == {"bm25", "bm25_faceted_rrf"}
    for strategy in result["splits"]["dev"].values():
        assert strategy["query_count"] == 2
        assert strategy["answerable_query_count"] == 2
        assert strategy["latency_ms"]["p95"] is not None
