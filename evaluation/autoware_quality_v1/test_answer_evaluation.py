from __future__ import annotations

from evaluation.autoware_quality_v1.evaluate_saved_answers import answer_sha256, evaluate_saved_answers


def test_hash_mismatch_disables_semantic_judgment_for_that_answer():
    cases = [{
        "case_id": "c1", "answerable": True,
        "required_answer_points": ["The node reads parameters from a file."],
    }]
    answers = [{
        "case_id": "c1", "answer": "A stale answer.", "citations": ["chunk-1"],
        "retrieved_chunk_ids": ["chunk-1"], "abstained": False,
    }]
    reviews = [{
        "case_id": "c1", "answer_sha256": "0" * 64,
        "claims": [{"claim_text": "The value comes from an environment variable.", "supported": True, "supporting_chunk_ids": ["chunk-1"]}],
        "covered_required_points": [], "abstained": False,
    }]

    result = evaluate_saved_answers(cases, answers, reviews)

    assert result["answer_sha256_mismatch_count"] == 1
    assert result["semantic_reviewed_answer_count"] == 0
    assert result["supported_claim_ratio"] is None
    assert result["required_point_completeness"] is None


def test_supported_claims_and_required_point_coverage_are_reported_separately():
    answer = "Parameters are loaded from a file at startup, but defaults are not covered here."
    cases = [{
        "case_id": "c1", "answerable": True,
        "required_answer_points": ["Parameter values come from a file.", "All required parameters must be present."],
    }]
    answers = [{
        "case_id": "c1", "answer": answer, "citations": ["chunk-supported", "chunk-extra"],
        "retrieved_chunk_ids": ["chunk-supported", "chunk-extra"], "abstained": False,
    }]
    reviews = [{
        "case_id": "c1", "answer_sha256": answer_sha256(answer),
        "claims": [
            {"claim_text": "Parameters are loaded from a file at startup.", "supported": True, "supporting_chunk_ids": ["chunk-supported"]},
            {"claim_text": "Defaults are set to 10.", "supported": False, "supporting_chunk_ids": []},
        ],
        "covered_required_points": ["Parameter values come from a file."], "abstained": False,
    }]

    result = evaluate_saved_answers(cases, answers, reviews)

    assert result["citation_membership_rate"] == 1.0
    assert result["citation_support_precision"] == 0.5
    assert result["supported_claim_ratio"] == 0.5
    assert result["required_point_completeness"] == 0.5


def test_human_reviewed_abstention_scores_no_answer_behavior():
    answers = [
        {"case_id": "answerable", "answer": "A supported answer", "citations": ["a"], "retrieved_chunk_ids": ["a"], "abstained": False},
        {"case_id": "unanswerable", "answer": "", "citations": [], "retrieved_chunk_ids": ["noise"], "abstained": True},
    ]
    cases = [
        {"case_id": "answerable", "answerable": True, "required_answer_points": []},
        {"case_id": "unanswerable", "answerable": False, "required_answer_points": []},
    ]
    reviews = [
        {"case_id": row["case_id"], "answer_sha256": answer_sha256(row["answer"]), "claims": [], "covered_required_points": [], "abstained": row["abstained"]}
        for row in answers
    ]

    result = evaluate_saved_answers(cases, answers, reviews)

    assert result["abstention_precision"] == 1.0
    assert result["abstention_recall"] == 1.0
    assert result["abstention_confusion"] == {"true_abstain": 1, "false_abstain": 0, "missed_abstain": 0}
