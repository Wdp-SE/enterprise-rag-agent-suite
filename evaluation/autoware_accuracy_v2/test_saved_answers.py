from __future__ import annotations

from evaluate_saved_answers import evaluate_saved_answers


def test_only_human_reviews_matching_answer_hash_count_as_answer_quality():
    cases = [
        {
            "case_id": "answerable",
            "answerable": True,
            "required_sources": ["doc-1"],
            "required_answer_points": ["The config sets a timeout."],
        },
        {
            "case_id": "no-answer",
            "answerable": False,
            "required_sources": [],
            "required_answer_points": [],
        },
    ]
    answers = [
        {
            "case_id": "answerable",
            "answer_sha256": "hash-a",
            "abstained": False,
            "claims": [{"claim_id": "claim-1", "evidence_ids": ["chunk-1"]}],
            "retrieved_evidence_ids": ["chunk-1", "chunk-2"],
        },
        {
            "case_id": "no-answer",
            "answer_sha256": "hash-b",
            "abstained": False,
            "claims": [{"claim_id": "claim-2", "evidence_ids": []}],
            "retrieved_evidence_ids": [],
        },
    ]
    reviews = [
        {
            "case_id": "answerable",
            "answer_sha256": "hash-a",
            "claims": [{"claim_id": "claim-1", "supported": True, "supporting_chunk_ids": ["chunk-1"]}],
            "covered_required_points": ["The config sets a timeout."],
            "should_abstain": False,
        },
        {
            "case_id": "no-answer",
            "answer_sha256": "stale-hash",
            "claims": [{"claim_id": "claim-2", "supported": False, "supporting_chunk_ids": []}],
            "covered_required_points": [],
            "should_abstain": True,
        },
    ]

    report = evaluate_saved_answers(cases, answers, reviews)

    assert report["evaluated_count"] == 1
    assert report["excluded_count"] == 1
    assert report["claim_support_rate"] == 1.0
    assert report["required_point_coverage"] == 1.0
    assert report["abstention_recall"] is None


def test_foreign_citations_are_not_counted_as_supported_sources():
    case = {
        "case_id": "case-1",
        "answerable": True,
        "required_sources": ["doc-1"],
        "required_answer_points": [],
    }
    answer = {
        "case_id": "case-1", "answer_sha256": "hash", "abstained": False,
        "claims": [{"claim_id": "claim-1", "evidence_ids": ["foreign"]}],
        "retrieved_evidence_ids": ["chunk-1"],
    }
    review = {
        "case_id": "case-1",
        "answer_sha256": "hash",
        "claims": [{"claim_id": "claim-1", "supported": True, "supporting_chunk_ids": ["chunk-1"]}],
        "covered_required_points": [],
        "should_abstain": False,
    }

    report = evaluate_saved_answers([case], [answer], [review])

    assert report["citation_precision"] == 0.0
    assert report["citation_recall"] == 0.0
