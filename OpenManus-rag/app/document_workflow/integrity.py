"""Finalization contract for a human-reviewed DOCX draft."""

from __future__ import annotations

import hashlib
import re
from pathlib import Path

from .models import TaskStatus


class OutputIntegrityError(ValueError):
    pass


class OutputIntegrityValidator:
    def validate(self, *, source: Path, target: Path, original_hash: str,
                 schema, tasks, drafts, cache, workflow_status: str) -> None:
        if source.resolve() == target.resolve():
            raise OutputIntegrityError("ORIGINAL_TEMPLATE_OVERWRITE_BLOCKED")
        if hashlib.sha256(source.read_bytes()).hexdigest() != original_hash or schema.template_id != f"tpl_{original_hash[:16]}":
            raise OutputIntegrityError("TEMPLATE_ID_OR_HASH_INVALID")
        task_ids = {task.section_id for task in tasks}
        draft_by_id = {draft.section_id: draft for draft in drafts}
        if task_ids != set(draft_by_id) or any(task.status in {TaskStatus.PENDING, TaskStatus.RUNNING, TaskStatus.FAILED} for task in tasks):
            raise OutputIntegrityError("REQUIRED_SECTION_INVALID")
        if any(draft.requires_human_review is not True for draft in drafts):
            raise OutputIntegrityError("HUMAN_REVIEW_REQUIRED")
        for task in tasks:
            draft = draft_by_id[task.section_id]
            if draft.status != task.status or set(draft.field_values) != {field.field_id for field in task.required_fields}:
                raise OutputIntegrityError("SECTION_DRAFT_INVALID")
            if task.status == TaskStatus.COMPLETE and (draft.missing_fields or task.missing_fields):
                raise OutputIntegrityError("COMPLETE_SECTION_HAS_MISSING")
            if task.status in {TaskStatus.PARTIAL, TaskStatus.NO_PROGRESS} and not (draft.missing_fields or task.stop_reason):
                raise OutputIntegrityError("PARTIAL_SECTION_REASON_MISSING")
            if not cache.membership(task.task_id, draft.evidence_ids):
                raise OutputIntegrityError("EVIDENCE_MEMBERSHIP_INVALID")
            cited = set(re.findall(r"\[Evidence: ([^\]]+)\]", draft.content))
            if cited != set(draft.evidence_ids) or not cache.membership(task.task_id, list(cited)):
                raise OutputIntegrityError("EVIDENCE_MEMBERSHIP_INVALID")
            for field in task.required_fields:
                is_missing = draft.field_values[field.field_id].startswith("[MISSING:")
                if is_missing != (field.field_name in draft.missing_fields):
                    raise OutputIntegrityError("MISSING_FIELD_STATUS_INVALID")
        expected = "COMPLETE" if all(task.status == TaskStatus.COMPLETE for task in tasks) else "PARTIAL"
        if workflow_status != expected:
            raise OutputIntegrityError("WORKFLOW_STATUS_INCONSISTENT")
