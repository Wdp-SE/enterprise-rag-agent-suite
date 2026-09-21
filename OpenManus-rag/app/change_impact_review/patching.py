"""Fail-closed paragraph patching with conflict, freshness and idempotency checks."""

from __future__ import annotations

import re
from pathlib import Path

from docx import Document

from app.document_workflow.evidence_models import Evidence, sha256_text
from app.document_workflow.freshness import EvidenceFreshness, EvidenceFreshnessValidator

from .models import PatchApplyResult, PatchApplyStatus, PatchCandidate, PatchReviewStatus


class ParagraphPatchApplier:
    def apply(
        self,
        patch: PatchCandidate,
        *,
        source: str | Path,
        output: str | Path,
        current_version_id: str,
        applied_keys: set[str],
    ) -> PatchApplyResult:
        key = patch.idempotency_key
        if key in applied_keys:
            patch.apply_status = PatchApplyStatus.SKIPPED_ALREADY_APPLIED
            return PatchApplyResult(
                patch_id=patch.patch_id,
                status=patch.apply_status,
                output_path=str(Path(output).resolve()) if Path(output).exists() else None,
                idempotency_key=key,
            )
        if patch.review_status is not PatchReviewStatus.APPROVED:
            patch.apply_status = PatchApplyStatus.BLOCKED_REVIEW
            return self._result(patch, key, "PATCH_NOT_APPROVED")
        if current_version_id != patch.base_version_id:
            patch.apply_status = PatchApplyStatus.CONFLICT
            return self._result(patch, key, "BASE_VERSION_CHANGED")
        match = re.fullmatch(r"paragraph:(\d+)", patch.target_anchor)
        if match is None:
            patch.apply_status = PatchApplyStatus.CONFLICT
            return self._result(patch, key, "TARGET_ANCHOR_INVALID")
        source_path = Path(source).resolve()
        output_path = Path(output).resolve()
        if source_path == output_path:
            raise ValueError("candidate output must not overwrite its source")
        if not source_path.is_file() or source_path.suffix.lower() != ".docx":
            raise ValueError("patch source must be an existing DOCX")
        document = Document(source_path)
        index = int(match.group(1))
        if index >= len(document.paragraphs):
            patch.apply_status = PatchApplyStatus.CONFLICT
            return self._result(patch, key, "TARGET_ANCHOR_MISSING")
        paragraph = document.paragraphs[index]
        if paragraph.text != patch.original_content or sha256_text(paragraph.text) != patch.original_content_hash:
            patch.apply_status = PatchApplyStatus.CONFLICT
            return self._result(patch, key, "ORIGINAL_CONTENT_CHANGED")
        if output_path.exists():
            patch.apply_status = PatchApplyStatus.CONFLICT
            return self._result(patch, key, "CANDIDATE_OUTPUT_EXISTS")
        if paragraph.runs:
            paragraph.runs[0].text = patch.proposed_content
            for run in paragraph.runs[1:]:
                run.text = ""
        else:
            paragraph.add_run(patch.proposed_content)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        document.save(output_path)
        applied_keys.add(key)
        patch.apply_status = PatchApplyStatus.APPLIED
        return PatchApplyResult(
            patch_id=patch.patch_id,
            status=patch.apply_status,
            output_path=str(output_path),
            idempotency_key=key,
        )

    @staticmethod
    def _result(patch: PatchCandidate, key: str, reason: str) -> PatchApplyResult:
        return PatchApplyResult(
            patch_id=patch.patch_id,
            status=patch.apply_status,
            failure_reason=reason,
            idempotency_key=key,
        )


class PatchExecutionService:
    def __init__(self, active_version_for_document):
        self.freshness = EvidenceFreshnessValidator(active_version_for_document)
        self.applier = ParagraphPatchApplier()

    def apply(
        self,
        patch: PatchCandidate,
        *,
        evidence_by_id: dict[str, Evidence],
        expected_scope_fingerprint: str,
        source: str | Path,
        output: str | Path,
        current_version_id: str,
        applied_keys: set[str],
    ) -> PatchApplyResult:
        if patch.scope_fingerprint != expected_scope_fingerprint:
            patch.apply_status = PatchApplyStatus.BLOCKED_SCOPE
            return ParagraphPatchApplier._result(patch, patch.idempotency_key, "SCOPE_FINGERPRINT_CHANGED")
        for evidence_id in patch.evidence_ids:
            item = evidence_by_id.get(evidence_id)
            if item is None or item.content_hash != patch.evidence_content_hashes.get(evidence_id):
                patch.apply_status = PatchApplyStatus.BLOCKED_STALE_EVIDENCE
                return ParagraphPatchApplier._result(patch, patch.idempotency_key, "EVIDENCE_CONTENT_CHANGED")
            decision = self.freshness.evaluate(item)
            if decision.freshness is not EvidenceFreshness.FRESH:
                patch.apply_status = PatchApplyStatus.BLOCKED_STALE_EVIDENCE
                return ParagraphPatchApplier._result(patch, patch.idempotency_key, "EVIDENCE_STALE")
        return self.applier.apply(
            patch,
            source=source,
            output=output,
            current_version_id=current_version_id,
            applied_keys=applied_keys,
        )

