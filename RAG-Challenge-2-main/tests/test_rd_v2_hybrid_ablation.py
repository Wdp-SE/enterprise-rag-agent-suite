from scripts.run_rd_v2_hybrid_ablation import (
    choose_candidate,
    complementarity,
    hybrid_value,
    rank_delta,
)


def _record(question_id: str, query_type: str, ranks: set[int]) -> dict:
    return {
        "question_id": question_id,
        "question_type": query_type,
        "expected_document_id": "doc",
        "expected_pages": [1],
        "expected_section_ids": ["section"],
        "hit_at_k": {
            str(k): int(any(rank <= k for rank in ranks))
            for k in (1, 3, 5, 10, 20, 50)
        },
        "first_evidence_rank": min(ranks) if ranks else None,
        "first_evidence": None,
    }


def test_complementarity_counts_dense_miss_sparse_recovery_by_type():
    dense = [_record("q1", "field", set()), _record("q2", "exact_term", {3})]
    sparse = [_record("q1", "field", {40}), _record("q2", "exact_term", set())]

    result = complementarity(dense, sparse)

    assert result["overall"]["DENSE_MISS_BM25_RECOVERED"] == 1
    assert result["overall"]["DENSE_HIT_BM25_MISS"] == 1
    assert result["by_question_type"]["field"]["DENSE_MISS_BM25_RECOVERED"] == 1


def test_rank_delta_uses_requested_cutoff_transitions():
    dense = [_record("q1", "interface", {8}), _record("q2", "semantic", {1})]
    hybrid = [_record("q1", "interface", {4}), _record("q2", "semantic", {7})]

    result = rank_delta(dense, hybrid)

    assert result["counts"]["RECOVERED_TOP5"] == 1
    assert result["counts"]["REGRESSED_FROM_TOP1"] == 1
    assert result["counts"]["REGRESSION_QUESTION_COUNT"] == 1


def test_near_tie_candidate_selection_prefers_semantic_guardrail():
    empty_delta = {
        "counts": {"REGRESSED_FROM_TOP1": 0, "REGRESSION_QUESTION_COUNT": 1}
    }
    candidates = {
        "A": {
            "score": 6.00,
            "semantic_regression": "YES",
            "delta": empty_delta,
        },
        "B": {
            "score": 5.97,
            "semantic_regression": "NO",
            "delta": empty_delta,
        },
    }

    assert choose_candidate(candidates) == "B"


def test_exact_outcome_tie_prefers_lower_lexical_weight():
    delta = {
        "counts": {"REGRESSED_FROM_TOP1": 0, "REGRESSION_QUESTION_COUNT": 1}
    }
    candidates = {
        "C": {
            "score": 6.0,
            "semantic_regression": "MINOR",
            "delta": delta,
            "tie_preference": -0.5,
        },
        "D": {
            "score": 6.0,
            "semantic_regression": "MINOR",
            "delta": delta,
            "tie_preference": -0.25,
        },
    }

    assert choose_candidate(candidates) == "D"


def test_hybrid_partial_value_does_not_claim_full_success_with_tradeoffs():
    dense = {"hit_at_k": {"5": 0.35, "20": 0.475, "50": 0.55}}
    hybrid = {"hit_at_k": {"5": 0.325, "20": 0.525, "50": 0.525}}
    delta = {"counts": {"RECOVERED_TOP5": 0}}

    assert (
        hybrid_value(
            hybrid,
            dense,
            {
                "field": False,
                "exact_term": False,
                "interface": True,
                "dependency": False,
            },
            "YES",
            delta,
        )
        == "PARTIAL"
    )
