"""Draft and official-output integrity guards."""

from __future__ import annotations

import hashlib
from pathlib import Path

from .models import FieldDraftStatus, SectionDraft
from .review import ReviewService, section_content_hash


class OutputIntegrityError(ValueError):
    pass


class OutputIntegrityValidator:
    def validate_draft(self, *, source: Path, original_hash: str, schema, tasks, drafts, cache) -> None:
        if hashlib.sha256(source.read_bytes()).hexdigest() != original_hash or schema.template_id != f"tpl_{original_hash[:16]}":
            raise OutputIntegrityError("TEMPLATE_ID_OR_HASH_INVALID")
        if {item.section_id for item in tasks} != {item.section_id for item in drafts}:
            raise OutputIntegrityError("REQUIRED_SECTION_INVALID")
        task_by_section = {item.section_id: item for item in tasks}
        for draft in drafts:
            task = task_by_section[draft.section_id]
            if {item.field_id for item in draft.fields} != {item.field_id for item in task.required_fields}:
                raise OutputIntegrityError("SECTION_DRAFT_INVALID")
            for field in draft.fields:
                if field.status is FieldDraftStatus.DRAFTED and not field.evidence_ids:
                    raise OutputIntegrityError("DRAFT_WITHOUT_EVIDENCE")
                if not cache.membership(task.task_id, field.evidence_ids):
                    raise OutputIntegrityError("EVIDENCE_MEMBERSHIP_INVALID")
                for evidence_id in field.evidence_ids:
                    evidence = cache.store.get(evidence_id)
                    if evidence is None or (evidence.version_id is not None and evidence.freshness != "FRESH"):
                        raise OutputIntegrityError("EVIDENCE_FRESHNESS_INVALID")

    def validate_final(self, *, state, schema, tasks, drafts, cache) -> None:
        self.validate_draft(
            source=Path(state.template_path), original_hash=state.template_hash,
            schema=schema, tasks=tasks, drafts=drafts, cache=cache,
        )
        if not ReviewService.all_approved(state):
            raise OutputIntegrityError("ALL_REQUIRED_SECTIONS_MUST_BE_APPROVED")
        for draft in drafts:
            if any(item.status in {FieldDraftStatus.MISSING, FieldDraftStatus.INSUFFICIENT_EVIDENCE, FieldDraftStatus.INVALID} for item in draft.fields):
                raise OutputIntegrityError("UNRESOLVED_FIELD_BLOCKS_FINALIZATION")
            review = state.section_reviews[draft.section_id]
            if review.get("approved_content_hash") != section_content_hash(draft):
                raise OutputIntegrityError("APPROVED_CONTENT_HASH_INVALID")
