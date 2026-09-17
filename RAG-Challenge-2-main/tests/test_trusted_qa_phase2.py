import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from src.evaluation import load_evaluation_dataset
from src.trusted_qa import (
    AnswerEvidenceAudit,
    PostAnswerCandidateAction,
    PostValidationStatus,
    TrustedQAHoldoutItem,
    assert_exact_independence,
    decide_post_answer_candidate,
    evaluate_holdout_shadow,
    evaluate_post_answer_candidates,
    load_frozen_holdout,
    load_holdout_dataset,
)


PROJECT_ROOT = Path(__file__).resolve().parents[1]
HOLDOUT = PROJECT_ROOT / "data/evaluation/trusted_qa_holdout_v0_1.jsonl"
FREEZE = PROJECT_ROOT / "data/evaluation/trusted_qa_holdout_v0_1.freeze.json"


def _base_item(**updates):
    payload = {
        "question_id": "holdout-test",
        "question": "What does the evidence say?",
        "question_type": "single_document",
        "answerable": True,
        "expected_document_ids": ["doc-a"],
        "expected_pages": [{"document_id": "doc-a", "page_number": 1}],
        "reference_answer": "Supported answer.",
        "key_points": ["Supported"],
        "unanswerable_reason": None,
        "difficulty": "MEDIUM",
        "negative_class": None,
        "notes": "Manual review.",
        "review_status": "VERIFIED",
        "schema": "text",
    }
    payload.update(updates)
    return payload


def _audit(**updates):
    payload = {
        "generation_performed": True,
        "structured_output_valid": True,
        "answer_is_na": False,
        "claimed_citation_count": 1,
        "citation_count": 1,
        "citation_membership_valid": True,
        "semantic_support_verified": None,
        "post_validation_status": "VALID",
        "post_answer_shadow_decision": "ANSWER",
        "reason_codes": [],
        "generation_error_type": None,
    }
    payload.update(updates)
    return AnswerEvidenceAudit.model_validate(payload)


def test_repository_holdout_is_frozen_and_balanced():
    items, freeze = load_frozen_holdout(HOLDOUT, FREEZE)

    assert freeze.status == "FROZEN"
    assert freeze.holdout_contaminated is False
    assert freeze.evaluated_before_freeze is False
    assert len(items) == 20
    assert sum(item.answerable for item in items) == 10
    assert sum(not item.answerable for item in items) == 10
    assert sum(
        getattr(item.negative_class, "value", None) == "HARD_NEGATIVE"
        for item in items
    ) == 7


def test_repository_holdout_has_no_exact_calibration_overlap():
    items = load_holdout_dataset(HOLDOUT)
    assert_exact_independence(
        items,
        [
            load_evaluation_dataset(
                PROJECT_ROOT / "data/evaluation/domain_eval_v0_1.jsonl"
            ),
            load_evaluation_dataset(
                PROJECT_ROOT / "data/evaluation/version_eval_v0_1.jsonl"
            ),
        ],
        excluded_question_ids={
            "single-001",
            "cross-006",
            "version-002",
            "unanswerable-001",
            "unanswerable-004",
            "unanswerable-007",
        },
    )


def test_frozen_holdout_detects_byte_changes(tmp_path):
    dataset = tmp_path / "holdout.jsonl"
    dataset.write_bytes(HOLDOUT.read_bytes() + b"\n")
    with pytest.raises(ValueError, match="hash mismatch"):
        load_frozen_holdout(dataset, FREEZE)


def test_holdout_schema_rejects_unknown_fields():
    with pytest.raises(ValidationError, match="extra_forbidden"):
        TrustedQAHoldoutItem.model_validate(
            _base_item(accidental_schema_drift=True)
        )


def test_unanswerable_requires_negative_class_and_reason():
    payload = _base_item(
        question_type="unanswerable",
        answerable=False,
        expected_document_ids=[],
        expected_pages=[],
        reference_answer=None,
        negative_class=None,
        unanswerable_reason=None,
    )
    with pytest.raises(ValidationError, match="negative_class"):
        TrustedQAHoldoutItem.model_validate(payload)


def test_hard_negative_requires_hard_difficulty():
    payload = _base_item(
        question_type="unanswerable",
        answerable=False,
        expected_document_ids=[],
        expected_pages=[],
        reference_answer=None,
        negative_class="HARD_NEGATIVE",
        unanswerable_reason="The requested number is absent.",
        difficulty="MEDIUM",
    )
    with pytest.raises(ValidationError, match="difficulty=HARD"):
        TrustedQAHoldoutItem.model_validate(payload)


def test_holdout_metrics_report_answerable_easy_and_hard_separately():
    rows = [
        {
            "ground_truth_answerable": True,
            "negative_class": None,
            "shadow_decision": "ANSWER",
        },
        {
            "ground_truth_answerable": False,
            "negative_class": "EASY_NEGATIVE",
            "shadow_decision": "UNCERTAIN",
        },
        {
            "ground_truth_answerable": False,
            "negative_class": "HARD_NEGATIVE",
            "shadow_decision": "REJECT",
        },
    ]
    metrics = evaluate_holdout_shadow(rows)

    groups = metrics["by_ground_truth_group"]
    assert groups["ANSWERABLE"]["answerable_decisions"]["ANSWER"] == 1
    assert groups["EASY_NEGATIVE"]["unanswerable_decisions"]["UNCERTAIN"] == 1
    assert groups["HARD_NEGATIVE"]["unanswerable_decisions"]["REJECT"] == 1


def test_post_answer_candidate_allows_valid_cited_answer():
    decision = decide_post_answer_candidate(_audit())
    assert decision.action == PostAnswerCandidateAction.ALLOW_ANSWER
    assert decision.shadow_only is True
    assert decision.response_modified is False
    assert decision.semantic_entailment_verified is None


def test_post_answer_candidate_treats_empty_na_as_valid_abstention():
    decision = decide_post_answer_candidate(
        _audit(
            answer_is_na=True,
            claimed_citation_count=0,
            citation_count=0,
            citation_membership_valid=True,
            post_validation_status="ANSWER_IS_NA",
            post_answer_shadow_decision="REJECT",
            reason_codes=["ANSWER_IS_NA"],
        )
    )
    assert decision.action == PostAnswerCandidateAction.VALID_ABSTENTION
    assert decision.reason_codes[0].value == "EXPLICIT_NA"


def test_post_answer_candidate_fails_closed_on_invalid_structure():
    decision = decide_post_answer_candidate(
        _audit(
            structured_output_valid=False,
            answer_is_na=None,
            claimed_citation_count=None,
            citation_count=None,
            citation_membership_valid=None,
            post_validation_status="STRUCTURED_OUTPUT_INVALID",
            post_answer_shadow_decision="REJECT",
            reason_codes=["STRUCTURED_OUTPUT_INVALID"],
        )
    )
    assert decision.action == PostAnswerCandidateAction.FAIL_CLOSED


def test_post_answer_candidate_fails_closed_without_valid_citation():
    decision = decide_post_answer_candidate(
        _audit(
            citation_count=0,
            citation_membership_valid=False,
            post_validation_status="EMPTY_VALID_CITATIONS",
            post_answer_shadow_decision="REJECT",
            reason_codes=["ANSWER_WITHOUT_VALID_CITATION"],
        )
    )
    assert decision.action == PostAnswerCandidateAction.FAIL_CLOSED
    assert decision.reason_codes[0].value == "ANSWER_WITHOUT_VALID_CITATION"


def test_post_answer_candidate_fails_closed_on_partially_filtered_citations():
    decision = decide_post_answer_candidate(
        _audit(
            claimed_citation_count=2,
            citation_count=1,
            citation_membership_valid=False,
            post_validation_status="INVALID_CITATIONS_FILTERED",
            post_answer_shadow_decision="UNCERTAIN",
            reason_codes=["CITATION_MEMBERSHIP_FAILED"],
        )
    )
    assert decision.action == PostAnswerCandidateAction.FAIL_CLOSED
    assert decision.reason_codes[0].value == "CITATION_MEMBERSHIP_FAILED"


def test_na_with_citation_is_an_explicit_contradiction():
    decision = decide_post_answer_candidate(
        _audit(
            answer_is_na=True,
            post_validation_status="ANSWER_IS_NA",
            post_answer_shadow_decision="REJECT",
            reason_codes=["ANSWER_IS_NA"],
        )
    )
    assert decision.action == PostAnswerCandidateAction.FAIL_CLOSED
    assert decision.reason_codes[0].value == "NA_WITH_CITATION_CONTRADICTION"


def test_post_answer_metrics_do_not_claim_entailment_or_production_enforcement():
    rows = [
        {
            "ground_truth_answerable": True,
            "post_answer_candidate": decide_post_answer_candidate(
                _audit()
            ).model_dump(mode="json"),
        },
        {
            "ground_truth_answerable": False,
            "post_answer_candidate": decide_post_answer_candidate(
                _audit(
                    answer_is_na=True,
                    claimed_citation_count=0,
                    citation_count=0,
                    citation_membership_valid=True,
                    post_validation_status=PostValidationStatus.ANSWER_IS_NA,
                    post_answer_shadow_decision="REJECT",
                    reason_codes=["ANSWER_IS_NA"],
                )
            ).model_dump(mode="json"),
        },
    ]
    metrics = evaluate_post_answer_candidates(rows)

    assert metrics["correct_abstention_rate"] == 1.0
    assert metrics["answerable_valid_answer_rate"] == 1.0
    assert metrics["answerable_false_abstention_rate"] == 0.0
    assert metrics["unsupported_answer_rate"] == 0.0
    assert metrics["citation_membership_is_semantic_entailment"] is False
    assert metrics["response_enforcement_performed"] is False
