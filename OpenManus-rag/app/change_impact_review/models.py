"""Agent-owned models for evidence-driven patch review and application."""

from __future__ import annotations

import hashlib
import json
from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.document_workflow.evidence_models import sha256_text


class ImpactDiscoverySource(str, Enum):
    EXPLICIT_TRACE = "EXPLICIT_TRACE"
    RETRIEVAL_SUGGESTION = "RETRIEVAL_SUGGESTION"


class ImpactReviewStatus(str, Enum):
    CONFIRMED = "CONFIRMED"
    SUGGESTED = "SUGGESTED"
    REJECTED = "REJECTED"


class ImpactCandidate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    changed_item_id: str
    impacted_item_id: str
    discovery_source: ImpactDiscoverySource
    evidence_ids: list[str] = Field(default_factory=list)
    trace_link_id: str | None = None
    review_status: ImpactReviewStatus

    @model_validator(mode="after")
    def preserve_confirmed_and_suggested_boundary(self) -> "ImpactCandidate":
        if (
            self.discovery_source is ImpactDiscoverySource.RETRIEVAL_SUGGESTION
            and self.review_status is ImpactReviewStatus.CONFIRMED
        ):
            raise ValueError("retrieval suggestion cannot enter Agent as a confirmed fact")
        if (
            self.discovery_source is ImpactDiscoverySource.EXPLICIT_TRACE
            and self.review_status is ImpactReviewStatus.SUGGESTED
        ):
            raise ValueError("explicit confirmed trace cannot be represented as a suggestion")
        return self


class PatchOperation(str, Enum):
    REPLACE_PARAGRAPH = "REPLACE_PARAGRAPH"


class PatchReviewStatus(str, Enum):
    PENDING = "PENDING"
    EDITED_RECONFIRM_REQUIRED = "EDITED_RECONFIRM_REQUIRED"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"


class PatchReviewAction(str, Enum):
    APPROVE = "APPROVE"
    EDIT = "EDIT"
    REJECT = "REJECT"


class PatchApplyStatus(str, Enum):
    PENDING = "PENDING"
    APPLIED = "APPLIED"
    SKIPPED_ALREADY_APPLIED = "SKIPPED_ALREADY_APPLIED"
    BLOCKED_REVIEW = "BLOCKED_REVIEW"
    BLOCKED_STALE_EVIDENCE = "BLOCKED_STALE_EVIDENCE"
    BLOCKED_SCOPE = "BLOCKED_SCOPE"
    CONFLICT = "CONFLICT"


class ChangeTaskStatus(str, Enum):
    PENDING = "PENDING"
    IMPACT_READY = "IMPACT_READY"
    REVIEW_REQUIRED = "REVIEW_REQUIRED"
    APPLY_READY = "APPLY_READY"
    CANDIDATE_READY = "CANDIDATE_READY"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"


class PatchCandidate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    patch_id: str
    target_document_id: str
    base_version_id: str
    target_section_id: str
    target_anchor: str
    operation: PatchOperation
    original_content: str
    original_content_hash: str
    proposed_content: str
    reason: str
    evidence_ids: list[str] = Field(min_length=1)
    evidence_content_hashes: dict[str, str]
    scope_fingerprint: str
    review_status: PatchReviewStatus = PatchReviewStatus.PENDING
    apply_status: PatchApplyStatus = PatchApplyStatus.PENDING

    @model_validator(mode="after")
    def validate_integrity(self) -> "PatchCandidate":
        if self.original_content_hash != sha256_text(self.original_content):
            raise ValueError("original_content_hash mismatch")
        if set(self.evidence_ids) != set(self.evidence_content_hashes):
            raise ValueError("Evidence ids and content hashes must match")
        if not self.proposed_content.strip() or self.proposed_content == self.original_content:
            raise ValueError("proposed_content must be a non-empty change")
        return self

    @classmethod
    def create(cls, **values: Any) -> "PatchCandidate":
        original = str(values["original_content"])
        identity = {
            "target_document_id": values["target_document_id"],
            "base_version_id": values["base_version_id"],
            "target_anchor": values["target_anchor"],
            "original_content_hash": sha256_text(original),
            "proposed_content": values["proposed_content"],
        }
        canonical = json.dumps(identity, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        return cls(
            patch_id=f"patch_{hashlib.sha256(canonical.encode('utf-8')).hexdigest()[:20]}",
            original_content_hash=sha256_text(original),
            **values,
        )

    @property
    def idempotency_key(self) -> str:
        canonical = "|".join((
            self.patch_id,
            self.base_version_id,
            self.target_anchor,
            self.original_content_hash,
        ))
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


class PatchReviewRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")

    review_id: str
    patch_id: str
    action: PatchReviewAction
    status: PatchReviewStatus
    reviewer: str
    reviewed_at: str
    comment: str = ""
    previous_content_hash: str
    approved_content_hash: str | None = None


class PatchApplyResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    patch_id: str
    status: PatchApplyStatus
    output_path: str | None = None
    failure_reason: str | None = None
    idempotency_key: str


class ChangeImpactTaskState(BaseModel):
    model_config = ConfigDict(extra="forbid")

    task_id: str
    organization_id: str
    project_id: str
    scope: dict[str, Any]
    scope_fingerprint: str
    base_document_id: str
    base_version_id: str
    source_path: str
    candidate_path: str
    status: ChangeTaskStatus = ChangeTaskStatus.PENDING
    patches: list[PatchCandidate] = Field(default_factory=list)
    reviews: list[PatchReviewRecord] = Field(default_factory=list)
    applied_keys: set[str] = Field(default_factory=set)
    impacts: list[ImpactCandidate] = Field(default_factory=list)
    evidence_snapshot: dict[str, dict[str, Any]] = Field(default_factory=dict)
    trace: list[dict[str, Any]] = Field(default_factory=list)
    failure_reason: str | None = None
    candidate_version_record: dict[str, Any] | None = None

