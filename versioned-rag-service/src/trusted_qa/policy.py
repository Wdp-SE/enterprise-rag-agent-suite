"""Deterministic, versioned Trusted QA evidence policies."""

from __future__ import annotations

from enum import Enum

from src.trusted_qa.models import (
    DecisionState,
    EvidenceSufficiencyDecision,
    PreconditionResult,
    ReasonCode,
    RetrievalSignalSnapshot,
    TrustedQAMode,
    VersionResolutionStatus,
)


class ShadowPolicyProfile(str, Enum):
    HARD_ONLY = "HARD_ONLY"
    HARD_PLUS_SOFT = "HARD_PLUS_SOFT"
    HARD_SOFT_AGREEMENT = "HARD_SOFT_AGREEMENT"


POLICY_VERSIONS = {
    ShadowPolicyProfile.HARD_ONLY: "trusted_qa_shadow_v0_1_hard",
    ShadowPolicyProfile.HARD_PLUS_SOFT: "trusted_qa_shadow_v0_1",
    ShadowPolicyProfile.HARD_SOFT_AGREEMENT: "trusted_qa_shadow_v0_1_agreement",
}

# Calibration-only positive evidence hints. They never produce a hard reject.
# 0.75 is close to the answerable median (0.756) and remains above the observed
# unanswerable maximum (0.6862) in domain_eval_v0_1. These are deliberately not
# exposed as production thresholds.
CALIBRATION_STRONG_TOP1 = 0.75
CALIBRATION_STRONG_TOP3_MEAN = 0.70
CALIBRATION_EXTREMELY_WEAK_TOP1 = 0.50
CALIBRATION_MIN_DOCUMENT_CONCENTRATION = 0.60


def evaluate_preconditions(
    snapshot: RetrievalSignalSnapshot,
) -> list[PreconditionResult]:
    version_enabled = snapshot.version_governance_enabled
    return [
        PreconditionResult(
            reason_code=ReasonCode.NO_RETRIEVAL_RESULT,
            triggered=snapshot.retrieved_count == 0,
            proposed_decision=(
                DecisionState.REJECT if snapshot.retrieved_count == 0 else None
            ),
            detail="The retriever returned no candidate evidence.",
        ),
        PreconditionResult(
            reason_code=ReasonCode.INVALID_RETRIEVAL_STATE,
            triggered=not snapshot.retrieval_state_valid,
            proposed_decision=(
                DecisionState.REJECT if not snapshot.retrieval_state_valid else None
            ),
            detail=(
                "; ".join(snapshot.retrieval_state_issues)
                if snapshot.retrieval_state_issues
                else "Retrieval state is structurally valid."
            ),
        ),
        PreconditionResult(
            reason_code=ReasonCode.NO_ELIGIBLE_DOCUMENT,
            triggered=(
                version_enabled and snapshot.eligible_document_count == 0
            ),
            proposed_decision=(
                DecisionState.REJECT
                if version_enabled and snapshot.eligible_document_count == 0
                else None
            ),
            detail="Version resolution produced no eligible indexed document.",
        ),
        PreconditionResult(
            reason_code=ReasonCode.VERSION_RESOLUTION_FAILED,
            triggered=(
                version_enabled
                and snapshot.version_resolution_status
                == VersionResolutionStatus.FAILED
            ),
            proposed_decision=(
                DecisionState.REJECT
                if version_enabled
                and snapshot.version_resolution_status
                == VersionResolutionStatus.FAILED
                else None
            ),
            detail="Version resolution failed for the current query.",
        ),
        PreconditionResult(
            reason_code=ReasonCode.VERSION_AMBIGUITY,
            triggered=(
                version_enabled
                and (
                    snapshot.version_ambiguity
                    or snapshot.version_resolution_status
                    == VersionResolutionStatus.AMBIGUOUS
                )
            ),
            proposed_decision=(
                DecisionState.UNCERTAIN
                if version_enabled
                and (
                    snapshot.version_ambiguity
                    or snapshot.version_resolution_status
                    == VersionResolutionStatus.AMBIGUOUS
                )
                else None
            ),
            detail="Version governance reports an unresolved ambiguity.",
        ),
    ]


def decide_evidence_sufficiency(
    snapshot: RetrievalSignalSnapshot,
    *,
    mode: TrustedQAMode = TrustedQAMode.SHADOW,
    profile: ShadowPolicyProfile = ShadowPolicyProfile.HARD_PLUS_SOFT,
) -> EvidenceSufficiencyDecision | None:
    """Return a counterfactual decision; never mutates the answer pipeline."""

    mode = TrustedQAMode(mode)
    profile = ShadowPolicyProfile(profile)
    if mode == TrustedQAMode.OFF:
        return None
    # ENFORCE is intentionally post-answer-only.  Pre-generation evidence
    # sufficiency remains the same counterfactual Shadow observation.

    preconditions = evaluate_preconditions(snapshot)
    hard_reasons = [
        item.reason_code
        for item in preconditions
        if item.triggered and item.proposed_decision == DecisionState.REJECT
    ]
    if hard_reasons:
        return EvidenceSufficiencyDecision(
            decision=DecisionState.REJECT,
            reason_codes=hard_reasons,
            signals_used=["deterministic_preconditions"],
            preconditions=preconditions,
            policy_version=POLICY_VERSIONS[profile],
            shadow_mode=True,
        )

    uncertain_reasons = [
        item.reason_code
        for item in preconditions
        if item.triggered and item.proposed_decision == DecisionState.UNCERTAIN
    ]
    if uncertain_reasons:
        return EvidenceSufficiencyDecision(
            decision=DecisionState.UNCERTAIN,
            reason_codes=uncertain_reasons,
            signals_used=["deterministic_preconditions"],
            preconditions=preconditions,
            policy_version=POLICY_VERSIONS[profile],
            shadow_mode=True,
        )

    if profile == ShadowPolicyProfile.HARD_ONLY:
        return EvidenceSufficiencyDecision(
            decision=DecisionState.ANSWER,
            reason_codes=[],
            signals_used=["deterministic_preconditions"],
            preconditions=preconditions,
            policy_version=POLICY_VERSIONS[profile],
            shadow_mode=True,
        )

    strong_scores = (
        snapshot.top1_score is not None
        and snapshot.top3_mean is not None
        and snapshot.top1_score >= CALIBRATION_STRONG_TOP1
        and snapshot.top3_mean >= CALIBRATION_STRONG_TOP3_MEAN
    )
    signals_used = ["top1_score", "top3_mean"]
    if profile == ShadowPolicyProfile.HARD_SOFT_AGREEMENT:
        retrieval_agreement = (
            snapshot.dominant_document_ratio is not None
            and snapshot.dominant_document_ratio
            >= CALIBRATION_MIN_DOCUMENT_CONCENTRATION
        ) or snapshot.adjacent_page_pair_count > 0
        strong_scores = strong_scores and retrieval_agreement
        signals_used.extend(
            ["dominant_document_ratio", "adjacent_page_pair_count"]
        )

    if strong_scores:
        return EvidenceSufficiencyDecision(
            decision=DecisionState.ANSWER,
            reason_codes=[],
            signals_used=signals_used,
            preconditions=preconditions,
            policy_version=POLICY_VERSIONS[profile],
            shadow_mode=True,
        )

    if (
        snapshot.top1_score is not None
        and snapshot.top1_score < CALIBRATION_EXTREMELY_WEAK_TOP1
    ):
        reason = ReasonCode.WEAK_RETRIEVAL_SIGNAL
    else:
        reason = ReasonCode.AMBIGUOUS_RETRIEVAL_SIGNAL
    return EvidenceSufficiencyDecision(
        decision=DecisionState.UNCERTAIN,
        reason_codes=[reason],
        signals_used=signals_used,
        preconditions=preconditions,
        policy_version=POLICY_VERSIONS[profile],
        shadow_mode=True,
    )
