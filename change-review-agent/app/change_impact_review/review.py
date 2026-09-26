"""Single-reviewer PatchCandidate review rules."""

from __future__ import annotations

import hashlib

from app.document_workflow.evidence_models import sha256_text
from app.document_workflow.state import now

from .models import (
    PatchCandidate,
    PatchReviewAction,
    PatchReviewRecord,
    PatchReviewStatus,
)


class PatchReviewService:
    def review(
        self,
        patch: PatchCandidate,
        *,
        action: PatchReviewAction,
        reviewer: str,
        comment: str = "",
        edited_content: str | None = None,
    ) -> PatchReviewRecord:
        reviewer = reviewer.strip()
        if not reviewer:
            raise ValueError("reviewer is required")
        previous_hash = sha256_text(patch.proposed_content)
        if action is PatchReviewAction.EDIT:
            edited = (edited_content or "").strip()
            if not edited or edited == patch.proposed_content:
                raise ValueError("EDIT requires changed non-empty content")
            patch.proposed_content = edited
            patch.review_status = PatchReviewStatus.EDITED_RECONFIRM_REQUIRED
        elif action is PatchReviewAction.APPROVE:
            patch.review_status = PatchReviewStatus.APPROVED
        elif action is PatchReviewAction.REJECT:
            patch.review_status = PatchReviewStatus.REJECTED
        reviewed_at = now()
        identity = f"{patch.patch_id}|{reviewer}|{reviewed_at}|{action.value}"
        return PatchReviewRecord(
            review_id=f"review_{hashlib.sha256(identity.encode()).hexdigest()[:20]}",
            patch_id=patch.patch_id,
            action=action,
            status=patch.review_status,
            reviewer=reviewer,
            reviewed_at=reviewed_at,
            comment=comment.strip(),
            previous_content_hash=previous_hash,
            approved_content_hash=(
                sha256_text(patch.proposed_content)
                if patch.review_status is PatchReviewStatus.APPROVED else None
            ),
        )

