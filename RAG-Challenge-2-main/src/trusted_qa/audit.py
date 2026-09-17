"""Post-generation observation for Trusted QA shadow mode."""

from __future__ import annotations

from typing import Optional, Sequence

from src.trusted_qa.models import (
    AnswerEvidenceAudit,
    DecisionState,
    PostValidationStatus,
    ReasonCode,
)


def not_available_answer_audit() -> AnswerEvidenceAudit:
    return AnswerEvidenceAudit(
        generation_performed=False,
        post_validation_status=PostValidationStatus.NOT_AVAILABLE,
    )


def build_answer_evidence_audit(
    *,
    generation_performed: bool,
    structured_output_valid: Optional[bool],
    final_answer: object = None,
    claimed_citations: Optional[Sequence[object]] = None,
    validated_citations: Optional[Sequence[object]] = None,
    citation_membership_checked: bool,
    generation_error_type: Optional[str] = None,
) -> AnswerEvidenceAudit:
    if not generation_performed:
        return not_available_answer_audit()

    claimed_count = len(claimed_citations or [])
    valid_count = len(validated_citations or [])
    if structured_output_valid is not True:
        return AnswerEvidenceAudit(
            generation_performed=True,
            structured_output_valid=False,
            answer_is_na=None,
            claimed_citation_count=None,
            citation_count=None,
            citation_membership_valid=None,
            semantic_support_verified=None,
            post_validation_status=PostValidationStatus.STRUCTURED_OUTPUT_INVALID,
            post_answer_shadow_decision=DecisionState.REJECT,
            reason_codes=[ReasonCode.STRUCTURED_OUTPUT_INVALID],
            generation_error_type=generation_error_type,
        )

    answer_is_na = final_answer == "N/A"
    if answer_is_na:
        return AnswerEvidenceAudit(
            generation_performed=True,
            structured_output_valid=True,
            answer_is_na=True,
            claimed_citation_count=claimed_count,
            citation_count=valid_count,
            citation_membership_valid=(
                claimed_count == valid_count if citation_membership_checked else None
            ),
            semantic_support_verified=None,
            post_validation_status=PostValidationStatus.ANSWER_IS_NA,
            post_answer_shadow_decision=DecisionState.REJECT,
            reason_codes=[ReasonCode.ANSWER_IS_NA],
        )

    if citation_membership_checked and valid_count == 0:
        return AnswerEvidenceAudit(
            generation_performed=True,
            structured_output_valid=True,
            answer_is_na=False,
            claimed_citation_count=claimed_count,
            citation_count=0,
            citation_membership_valid=False,
            semantic_support_verified=None,
            post_validation_status=PostValidationStatus.EMPTY_VALID_CITATIONS,
            post_answer_shadow_decision=DecisionState.REJECT,
            reason_codes=[ReasonCode.ANSWER_WITHOUT_VALID_CITATION],
        )

    if citation_membership_checked and valid_count < claimed_count:
        return AnswerEvidenceAudit(
            generation_performed=True,
            structured_output_valid=True,
            answer_is_na=False,
            claimed_citation_count=claimed_count,
            citation_count=valid_count,
            citation_membership_valid=False,
            semantic_support_verified=None,
            post_validation_status=PostValidationStatus.INVALID_CITATIONS_FILTERED,
            post_answer_shadow_decision=DecisionState.UNCERTAIN,
            reason_codes=[ReasonCode.CITATION_MEMBERSHIP_FAILED],
        )

    return AnswerEvidenceAudit(
        generation_performed=True,
        structured_output_valid=True,
        answer_is_na=False,
        claimed_citation_count=claimed_count,
        citation_count=valid_count,
        citation_membership_valid=(True if citation_membership_checked else None),
        semantic_support_verified=None,
        post_validation_status=PostValidationStatus.VALID,
        post_answer_shadow_decision=DecisionState.ANSWER,
        reason_codes=[],
    )

