"""Single-reviewer section review and approval domain."""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from enum import Enum

from .models import FieldDraftStatus, SectionDraft, TaskStatus, WorkflowStatus
from .state import WorkflowState, now


class SectionReviewStatus(str, Enum):
    PENDING = "PENDING"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"


@dataclass
class SectionReview:
    section_id: str
    status: SectionReviewStatus
    reviewer: str
    reviewed_at: str
    comment: str
    draft_hash: str
    approved_content_hash: str | None
    edited_fields: dict[str, str]

    def to_dict(self) -> dict:
        value = asdict(self)
        value["status"] = self.status.value
        return value


def section_content_hash(draft: SectionDraft) -> str:
    canonical = json.dumps(draft.to_dict(), ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


class ReviewService:
    def review_section(
        self,
        state: WorkflowState,
        *,
        section_id: str,
        status: SectionReviewStatus,
        reviewer: str,
        comment: str = "",
        edited_fields: dict[str, str] | None = None,
    ) -> SectionReview:
        reviewer = reviewer.strip()
        if not reviewer:
            raise ValueError("reviewer is required")
        if section_id not in state.section_drafts:
            raise ValueError("unknown section_id")
        draft = SectionDraft.from_dict(state.section_drafts[section_id])
        original_hash = section_content_hash(draft)
        edits = {key: value.strip() for key, value in (edited_fields or {}).items()}
        known = {item.field_id for item in draft.fields}
        if set(edits) - known or any(not value for value in edits.values()):
            raise ValueError("review edits must target known fields with non-empty content")
        for field in draft.fields:
            if field.field_id in edits:
                field.content = edits[field.field_id]
                field.status = FieldDraftStatus.MANUAL
                field.missing_reason = None
        if status is SectionReviewStatus.APPROVED and any(
            field.status in {FieldDraftStatus.MISSING, FieldDraftStatus.INSUFFICIENT_EVIDENCE, FieldDraftStatus.INVALID}
            for field in draft.fields
        ):
            raise ValueError("missing or invalid fields must be edited before approval")
        draft.status = TaskStatus.COMPLETE if not draft.missing_fields else TaskStatus.PARTIAL
        state.section_drafts[section_id] = draft.to_dict()
        task = state.section_states[section_id]
        task["status"] = draft.status.value
        task["missing_fields"] = list(draft.missing_fields)
        approved_hash = section_content_hash(draft) if status is SectionReviewStatus.APPROVED else None
        record = SectionReview(section_id, status, reviewer, now(), comment.strip(), original_hash, approved_hash, edits)
        state.section_reviews[section_id] = record.to_dict()
        state.workflow_status = (
            WorkflowStatus.REJECTED.value
            if any(item.get("status") == SectionReviewStatus.REJECTED.value for item in state.section_reviews.values())
            else WorkflowStatus.REVIEW_REQUIRED.value
        )
        return record

    @staticmethod
    def all_approved(state: WorkflowState) -> bool:
        return bool(state.section_drafts) and set(state.section_reviews) == set(state.section_drafts) and all(
            item.get("status") == SectionReviewStatus.APPROVED.value for item in state.section_reviews.values()
        )
