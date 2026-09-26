"""Deterministic post-answer fail-closed policy.

The policy deliberately evaluates only structured-output and citation-membership
invariants already observed by the existing pipeline.  It performs no retrieval,
model call, score thresholding, or semantic-entailment inference.
"""

from __future__ import annotations

from copy import deepcopy
from typing import Mapping, Sequence

from src.trusted_qa.models import (
    AnswerEvidenceAudit,
    CitationState,
    OriginalAnswerState,
    PostAnswerEnforcementAction,
    PostAnswerEnforcementDecision,
    PostAnswerEnforcementReason,
    StructuredOutputState,
    TrustedQAMode,
)


POST_ANSWER_POLICY_VERSION = "trusted_qa_post_answer_v1"


def _observed_states(
    audit: AnswerEvidenceAudit,
) -> tuple[OriginalAnswerState, CitationState, StructuredOutputState]:
    if not audit.generation_performed:
        answer_state = OriginalAnswerState.NOT_AVAILABLE
        structured_state = StructuredOutputState.NOT_AVAILABLE
    elif audit.structured_output_valid is not True:
        answer_state = OriginalAnswerState.UNKNOWN
        structured_state = StructuredOutputState.INVALID
    else:
        answer_state = (
            OriginalAnswerState.EXPLICIT_NA
            if audit.answer_is_na
            else OriginalAnswerState.SUBSTANTIVE_ANSWER
        )
        structured_state = StructuredOutputState.VALID

    if not audit.generation_performed:
        citation_state = CitationState.NOT_AVAILABLE
    elif audit.citation_membership_valid is None:
        citation_state = CitationState.NOT_CHECKED
    elif audit.citation_membership_valid is False:
        citation_state = CitationState.INVALID
    elif (audit.claimed_citation_count or 0) == 0:
        citation_state = CitationState.EMPTY
    else:
        citation_state = CitationState.VALID
    return answer_state, citation_state, structured_state


def decide_post_answer_enforcement(
    audit: AnswerEvidenceAudit | Mapping[str, object],
    *,
    mode: TrustedQAMode | str = TrustedQAMode.SHADOW,
) -> PostAnswerEnforcementDecision:
    """Evaluate high-certainty answer invariants after citation validation."""

    if not isinstance(audit, AnswerEvidenceAudit):
        audit = AnswerEvidenceAudit.model_validate(audit)
    mode = TrustedQAMode(mode)
    answer_state, citation_state, structured_state = _observed_states(audit)

    action = PostAnswerEnforcementAction.PASS
    reasons: list[PostAnswerEnforcementReason] = []
    if audit.generation_performed and audit.structured_output_valid is not True:
        action = PostAnswerEnforcementAction.FAIL_CLOSED
        reasons = [PostAnswerEnforcementReason.STRUCTURED_OUTPUT_INVALID]
    elif audit.answer_is_na:
        if (
            (audit.claimed_citation_count or 0) == 0
            and (audit.citation_count or 0) == 0
        ):
            action = PostAnswerEnforcementAction.VALID_ABSTENTION
            reasons = [PostAnswerEnforcementReason.VALID_MODEL_ABSTENTION]
        else:
            action = PostAnswerEnforcementAction.FAIL_CLOSED
            reasons = [
                PostAnswerEnforcementReason.ANSWER_CITATION_STATE_CONFLICT
            ]
    elif audit.generation_performed and audit.structured_output_valid is True:
        # A formal answer always supplies a checked True/False citation state.
        # NOT_CHECKED is retained only for a caller that performs no generation.
        if audit.citation_membership_valid is False:
            if (audit.claimed_citation_count or 0) == 0:
                reasons = [
                    PostAnswerEnforcementReason.SUBSTANTIVE_ANSWER_WITHOUT_CITATION
                ]
            else:
                reasons = [
                    PostAnswerEnforcementReason.CITATION_MEMBERSHIP_INVALID
                ]
            action = PostAnswerEnforcementAction.FAIL_CLOSED

    post_answer_enabled = mode == TrustedQAMode.ENFORCE
    enforced = (
        post_answer_enabled
        and action == PostAnswerEnforcementAction.FAIL_CLOSED
    )
    return PostAnswerEnforcementDecision(
        action=action,
        reason_codes=reasons,
        policy_version=POST_ANSWER_POLICY_VERSION,
        original_answer_state=answer_state,
        citation_state=citation_state,
        structured_output_state=structured_state,
        enforced=enforced,
        post_answer_enforcement=post_answer_enabled,
    )


def apply_post_answer_enforcement(
    result: Mapping[str, object],
    decision: PostAnswerEnforcementDecision,
    *,
    citation_fields: Sequence[str],
) -> dict:
    """Return a schema-compatible result; mutate only an enforced invalid state."""

    final_result = deepcopy(dict(result))
    if not decision.enforced:
        return final_result
    final_result["final_answer"] = "N/A"
    for field in citation_fields:
        if field in final_result:
            final_result[field] = []
    return final_result
