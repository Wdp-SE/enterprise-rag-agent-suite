import pytest

from evaluation.real_world_retrieval.quality_v4.run_quality_v4_baseline import (
    compare_results,
    validate_baseline_run,
)


def test_paired_comparison_applies_documented_promotion_gates():
    candidate = {
        "overall": {
            "complete_source_at_5": 0.90,
            "anchor_recall_at_5": 0.80,
            "image_hit_at_5": 1.0,
            "version_mismatch_count": 0,
            "no_answer_nonempty_candidate_rate": 0.5,
            "warm_p95_ms": 10.0,
        },
        "by_category": {
            "cross_document": {"complete_source_at_5": 0.75},
            "cross_version": {"complete_source_at_5": 0.75},
        },
    }
    baseline = {
        "overall": {
            "complete_source_at_5": 0.90,
            "anchor_recall_at_5": 0.80,
            "image_hit_at_5": 0.0,
            "version_mismatch_count": 0,
            "no_answer_nonempty_candidate_rate": 0.5,
            "warm_p95_ms": 12.0,
        },
        "by_category": {
            "cross_document": {"complete_source_at_5": 0.625},
            "cross_version": {"complete_source_at_5": 0.75},
        },
    }

    result = compare_results(candidate, baseline)

    assert result["passed"] is True
    assert result["checks"]["image_hit_at_5"] is True
    assert result["checks"]["cross_document_noninferiority"] is True
    assert result["checks"]["cross_version_noninferiority"] is True


def test_paired_comparison_rejects_material_text_regression_and_wrong_version():
    candidate = {
        "overall": {
            "complete_source_at_5": 0.80,
            "anchor_recall_at_5": 0.70,
            "image_hit_at_5": 1.0,
            "version_mismatch_count": 1,
            "no_answer_nonempty_candidate_rate": 1.0,
            "warm_p95_ms": 251.0,
        },
        "by_category": {
            "cross_document": {"complete_source_at_5": 0.50},
            "cross_version": {"complete_source_at_5": 0.50},
        },
    }
    baseline = {
        "overall": {
            "complete_source_at_5": 0.90,
            "anchor_recall_at_5": 0.80,
            "image_hit_at_5": 0.0,
            "version_mismatch_count": 0,
            "no_answer_nonempty_candidate_rate": 0.5,
            "warm_p95_ms": 10.0,
        },
        "by_category": {
            "cross_document": {"complete_source_at_5": 0.75},
            "cross_version": {"complete_source_at_5": 0.75},
        },
    }

    result = compare_results(candidate, baseline)

    assert result["passed"] is False
    assert result["checks"]["complete_source_noninferiority"] is False
    assert result["checks"]["version_mismatch_zero"] is False
    assert result["checks"]["latency_budget"] is False


def test_baseline_runner_requires_completed_locked_candidate_and_is_one_shot():
    validate_baseline_run(
        selection={"policy": "bm25_figure_ocr", "input_sha256": {"cases": "a"}, "candidate_fingerprint": {"code": "b"}},
        execution={"status": "completed", "policy": "bm25_figure_ocr", "input_sha256": {"cases": "a"}, "candidate_fingerprint": {"code": "b"}, "result_sha256": "c"},
        already_executed=False,
        input_sha256={"cases": "a"},
        candidate_fingerprint={"code": "b"},
    )

    with pytest.raises(ValueError, match="already"):
        validate_baseline_run(
            selection={"policy": "bm25_figure_ocr", "input_sha256": {"cases": "a"}, "candidate_fingerprint": {"code": "b"}},
            execution={"status": "completed", "policy": "bm25_figure_ocr", "input_sha256": {"cases": "a"}, "candidate_fingerprint": {"code": "b"}, "result_sha256": "c"},
            already_executed=True,
            input_sha256={"cases": "a"},
            candidate_fingerprint={"code": "b"},
        )

    with pytest.raises(ValueError, match="fingerprint"):
        validate_baseline_run(
            selection={"policy": "bm25_figure_ocr", "input_sha256": {"cases": "a"}, "candidate_fingerprint": {"code": "b"}},
            execution={"status": "completed", "policy": "bm25_figure_ocr", "input_sha256": {"cases": "a"}, "candidate_fingerprint": {"code": "b"}, "result_sha256": "c"},
            already_executed=False,
            input_sha256={"cases": "a"},
            candidate_fingerprint={"code": "changed"},
        )
