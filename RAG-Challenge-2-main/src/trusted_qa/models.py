"""Typed observation and decision models for Trusted QA shadow mode."""

from __future__ import annotations

from enum import Enum
from typing import Any, List, Optional

from pydantic import BaseModel, ConfigDict, Field


class TrustedQAMode(str, Enum):
    OFF = "OFF"
    SHADOW = "SHADOW"
    ENFORCE = "ENFORCE"


class EnforcementScope(str, Enum):
    """Supported enforcement boundary for the autumn-recruitment baseline."""

    POST_ANSWER_ONLY = "POST_ANSWER_ONLY"


class DecisionState(str, Enum):
    ANSWER = "ANSWER"
    REJECT = "REJECT"
    UNCERTAIN = "UNCERTAIN"


class ReasonCode(str, Enum):
    NO_RETRIEVAL_RESULT = "NO_RETRIEVAL_RESULT"
    NO_ELIGIBLE_DOCUMENT = "NO_ELIGIBLE_DOCUMENT"
    VERSION_AMBIGUITY = "VERSION_AMBIGUITY"
    VERSION_RESOLUTION_FAILED = "VERSION_RESOLUTION_FAILED"
    INVALID_RETRIEVAL_STATE = "INVALID_RETRIEVAL_STATE"
    WEAK_RETRIEVAL_SIGNAL = "WEAK_RETRIEVAL_SIGNAL"
    AMBIGUOUS_RETRIEVAL_SIGNAL = "AMBIGUOUS_RETRIEVAL_SIGNAL"
    STRUCTURED_OUTPUT_INVALID = "STRUCTURED_OUTPUT_INVALID"
    ANSWER_IS_NA = "ANSWER_IS_NA"
    ANSWER_WITHOUT_VALID_CITATION = "ANSWER_WITHOUT_VALID_CITATION"
    CITATION_MEMBERSHIP_FAILED = "CITATION_MEMBERSHIP_FAILED"


class VersionResolutionStatus(str, Enum):
    DISABLED = "DISABLED"
    RESOLVED = "RESOLVED"
    RESOLVED_WITH_ISSUES = "RESOLVED_WITH_ISSUES"
    AMBIGUOUS = "AMBIGUOUS"
    FAILED = "FAILED"


class PostValidationStatus(str, Enum):
    NOT_AVAILABLE = "NOT_AVAILABLE"
    VALID = "VALID"
    ANSWER_IS_NA = "ANSWER_IS_NA"
    STRUCTURED_OUTPUT_INVALID = "STRUCTURED_OUTPUT_INVALID"
    EMPTY_VALID_CITATIONS = "EMPTY_VALID_CITATIONS"
    INVALID_CITATIONS_FILTERED = "INVALID_CITATIONS_FILTERED"


class PostAnswerEnforcementAction(str, Enum):
    PASS = "PASS"
    VALID_ABSTENTION = "VALID_ABSTENTION"
    FAIL_CLOSED = "FAIL_CLOSED"


class PostAnswerEnforcementReason(str, Enum):
    STRUCTURED_OUTPUT_INVALID = "STRUCTURED_OUTPUT_INVALID"
    SUBSTANTIVE_ANSWER_WITHOUT_CITATION = (
        "SUBSTANTIVE_ANSWER_WITHOUT_CITATION"
    )
    CITATION_MEMBERSHIP_INVALID = "CITATION_MEMBERSHIP_INVALID"
    ANSWER_CITATION_STATE_CONFLICT = "ANSWER_CITATION_STATE_CONFLICT"
    VALID_MODEL_ABSTENTION = "VALID_MODEL_ABSTENTION"


class OriginalAnswerState(str, Enum):
    SUBSTANTIVE_ANSWER = "SUBSTANTIVE_ANSWER"
    EXPLICIT_NA = "EXPLICIT_NA"
    NOT_AVAILABLE = "NOT_AVAILABLE"
    UNKNOWN = "UNKNOWN"


class CitationState(str, Enum):
    VALID = "VALID"
    EMPTY = "EMPTY"
    INVALID = "INVALID"
    NOT_CHECKED = "NOT_CHECKED"
    NOT_AVAILABLE = "NOT_AVAILABLE"


class StructuredOutputState(str, Enum):
    VALID = "VALID"
    INVALID = "INVALID"
    NOT_AVAILABLE = "NOT_AVAILABLE"


class PageIdentity(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    document_id: str
    page_number: int = Field(ge=1)


class PreconditionResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reason_code: ReasonCode
    triggered: bool
    proposed_decision: Optional[DecisionState] = None
    detail: str


class RetrievalSignalSnapshot(BaseModel):
    """Observed retrieval facts. This model intentionally contains no verdict."""

    model_config = ConfigDict(extra="forbid")

    question_id: str
    retrieved_count: int = Field(ge=0)
    top1_score: Optional[float] = None
    top2_score: Optional[float] = None
    top3_score: Optional[float] = None
    top5_scores: List[float] = Field(default_factory=list)
    top1_top2_margin: Optional[float] = None
    top3_mean: Optional[float] = None
    top5_mean: Optional[float] = None
    retrieved_document_count: int = Field(ge=0)
    retrieved_page_count: int = Field(ge=0)
    document_ids: List[str] = Field(default_factory=list)
    page_ids: List[PageIdentity] = Field(default_factory=list)
    dominant_document_ratio: Optional[float] = None
    top3_document_concentration: Optional[float] = None
    adjacent_page_pair_count: int = Field(default=0, ge=0)
    version_governance_enabled: bool
    version_intent: Optional[str] = None
    version_resolution_status: VersionResolutionStatus
    version_ambiguity: bool
    eligible_document_count: Optional[int] = Field(default=None, ge=0)
    version_resolution_issues: List[str] = Field(default_factory=list)
    citation_candidates_available: bool
    citation_candidate_count: int = Field(ge=0)
    rerank_available: bool
    rerank_score: Optional[float] = None
    rerank_scores: List[float] = Field(default_factory=list)
    rerank_margin: Optional[float] = None
    retrieval_state_valid: bool
    retrieval_state_issues: List[str] = Field(default_factory=list)


class EvidenceSufficiencyDecision(BaseModel):
    model_config = ConfigDict(extra="forbid")

    decision: DecisionState
    reason_codes: List[ReasonCode] = Field(default_factory=list)
    signals_used: List[str] = Field(default_factory=list)
    preconditions: List[PreconditionResult] = Field(default_factory=list)
    policy_version: str
    shadow_mode: bool


class AnswerEvidenceAudit(BaseModel):
    model_config = ConfigDict(extra="forbid")

    generation_performed: bool
    structured_output_valid: Optional[bool] = None
    answer_is_na: Optional[bool] = None
    claimed_citation_count: Optional[int] = Field(default=None, ge=0)
    citation_count: Optional[int] = Field(default=None, ge=0)
    citation_membership_valid: Optional[bool] = None
    semantic_support_verified: Optional[bool] = None
    post_validation_status: PostValidationStatus
    post_answer_shadow_decision: Optional[DecisionState] = None
    reason_codes: List[ReasonCode] = Field(default_factory=list)
    generation_error_type: Optional[str] = None


class PostAnswerEnforcementDecision(BaseModel):
    """Deterministic post-generation decision with no model-derived confidence."""

    model_config = ConfigDict(extra="forbid")

    action: PostAnswerEnforcementAction
    reason_codes: List[PostAnswerEnforcementReason] = Field(default_factory=list)
    policy_version: str = "trusted_qa_post_answer_v1"
    original_answer_state: OriginalAnswerState
    citation_state: CitationState
    structured_output_state: StructuredOutputState
    enforced: bool
    enforcement_scope: EnforcementScope = EnforcementScope.POST_ANSWER_ONLY
    pre_generation_enforcement: bool = False
    post_answer_enforcement: bool
    extra_llm_calls: int = Field(default=0, ge=0, le=0)
    semantic_entailment_verified: bool = False


class TrustedQATrace(BaseModel):
    model_config = ConfigDict(extra="forbid")

    question_id: str
    signal_snapshot: RetrievalSignalSnapshot
    shadow_decision: EvidenceSufficiencyDecision
    post_answer_audit: AnswerEvidenceAudit
    actual_pipeline_result: Optional[dict[str, Any]] = None
    post_answer_enforcement: Optional[PostAnswerEnforcementDecision] = None
    original_pipeline_result: Optional[dict[str, Any]] = None
    final_pipeline_result: Optional[dict[str, Any]] = None
