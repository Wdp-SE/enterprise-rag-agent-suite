from scripts.run_rd_v2_embedding_enrichment import (
    classify_delta,
    dense_deficiency_conclusion,
    semantic_regression,
)


def _type_metric(*, hit5: float, hit20: float, hit50: float, mrr50: float) -> dict:
    return {
        "hit_at_k": {"5": hit5, "20": hit20, "50": hit50},
        "mrr_at_50": mrr50,
    }


def test_rank_delta_classification_uses_material_regression_boundary():
    assert classify_delta(None, 30) == "RECOVERED"
    assert classify_delta(18, 8) == "IMPROVED"
    assert classify_delta(1, 2) == "REGRESSED"
    assert classify_delta(8, 10) == "UNCHANGED"
    assert classify_delta(8, None) == "REGRESSED"


def test_single_shallow_semantic_movement_is_minor_when_deep_recall_improves():
    baseline = _type_metric(hit5=4 / 9, hit20=6 / 9, hit50=6 / 9, mrr50=0.226)
    candidate = _type_metric(hit5=3 / 9, hit20=6 / 9, hit50=7 / 9, mrr50=0.212)

    assert semantic_regression({"semantic": candidate}, {"semantic": baseline}) == "MINOR"


def test_deep_semantic_recall_loss_is_full_regression():
    baseline = _type_metric(hit5=0.5, hit20=0.7, hit50=0.8, mrr50=0.3)
    candidate = _type_metric(hit5=0.5, hit20=0.5, hit50=0.6, mrr50=0.2)

    assert semantic_regression({"semantic": candidate}, {"semantic": baseline}) == "YES"


def test_partial_representation_evidence_requires_no_overclaim():
    baseline = {"hit_at_k": {"20": 0.425, "50": 0.5}}
    candidate = {"hit_at_k": {"20": 0.475, "50": 0.525}}

    assert (
        dense_deficiency_conclusion(
            candidate,
            baseline,
            {"field": False, "exact_term": False, "dependency": True},
            "NO",
        )
        == "PARTIAL"
    )
