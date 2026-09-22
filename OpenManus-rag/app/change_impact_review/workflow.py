"""Checkpointed workflow for Patch review and candidate DOCX construction."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import time
import uuid
from pathlib import Path
from typing import Callable, Sequence

from app.document_workflow.evidence_models import Evidence
from app.document_workflow.state import CheckpointStore

from .checkpoint import ChangeImpactCheckpointStore
from .models import (
    ChangeImpactTaskState,
    ChangeTaskStatus,
    ImpactCandidate,
    PatchApplyResult,
    PatchApplyStatus,
    PatchCandidate,
    PatchReviewAction,
    PatchReviewStatus,
    QualityGateReason,
    QualityGateResult,
)
from .patching import PatchExecutionService
from .review import PatchReviewService


def scope_fingerprint(scope: dict) -> str:
    canonical = json.dumps(scope, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


class ChangeImpactWorkflow:
    def __init__(
        self,
        runtime_root: str | Path,
        *,
        active_version_for_document: Callable[[str], str | None],
        version_client=None,
    ):
        self.runtime_root = Path(runtime_root).resolve()
        self.tasks_root = self.runtime_root / "change_impact_tasks"
        self.tasks_root.mkdir(parents=True, exist_ok=True)
        self.checkpoints = ChangeImpactCheckpointStore(CheckpointStore(self.tasks_root / "checkpoints"))
        self.active_version_for_document = active_version_for_document
        self.version_client = version_client

    def create_task(
        self,
        *,
        organization_id: str,
        project_id: str,
        scope: dict,
        base_document_id: str,
        base_version_id: str,
        source: str | Path,
        impacts: Sequence[dict],
        patches: Sequence[PatchCandidate],
        evidence: Sequence[Evidence],
        rag_calls: int = 0,
    ) -> ChangeImpactTaskState:
        source_path = Path(source).resolve()
        if source_path.suffix.lower() != ".docx" or not source_path.is_file():
            raise ValueError("change task source must be an existing DOCX")
        task_id = f"cir_{uuid.uuid4().hex}"
        task_root = self.tasks_root / task_id
        task_root.mkdir()
        immutable_source = task_root / "source.docx"
        shutil.copy2(source_path, immutable_source)
        fingerprint = scope_fingerprint(scope)
        normalized_patches = [patch.model_copy(deep=True) for patch in patches]
        if any(patch.scope_fingerprint != fingerprint for patch in normalized_patches):
            raise ValueError("Patch scope fingerprint does not match task scope")
        evidence_snapshot = {
            str(item.evidence_id): item.model_dump(mode="json")
            for item in evidence if item.evidence_id is not None
        }
        state = ChangeImpactTaskState(
            task_id=task_id,
            organization_id=organization_id,
            project_id=project_id,
            scope=dict(scope),
            scope_fingerprint=fingerprint,
            base_document_id=base_document_id,
            base_version_id=base_version_id,
            source_path=str(immutable_source),
            candidate_path=str(task_root / "candidate.docx"),
            status=ChangeTaskStatus.REVIEW_REQUIRED,
            patches=normalized_patches,
            impacts=[ImpactCandidate.model_validate(item) for item in impacts],
            evidence_snapshot=evidence_snapshot,
            rag_calls=rag_calls,
        )
        state.trace.append(self._trace(state, "CREATE_TASK", "COMPLETE", 0.0))
        self.checkpoints.save(state)
        return state

    def get(self, task_id: str) -> ChangeImpactTaskState:
        return self.checkpoints.load(task_id)

    def review_patch(
        self,
        task_id: str,
        patch_id: str,
        *,
        action: PatchReviewAction,
        reviewer: str,
        comment: str = "",
        edited_content: str | None = None,
    ) -> ChangeImpactTaskState:
        state = self.get(task_id)
        patch = next((item for item in state.patches if item.patch_id == patch_id), None)
        if patch is None:
            raise ValueError("unknown patch_id")
        record = PatchReviewService().review(
            patch,
            action=action,
            reviewer=reviewer,
            comment=comment,
            edited_content=edited_content,
        )
        state.reviews.append(record)
        pending = {
            PatchReviewStatus.PENDING,
            PatchReviewStatus.EDITED_RECONFIRM_REQUIRED,
        }
        if any(item.review_status in pending for item in state.patches):
            state.status = ChangeTaskStatus.REVIEW_REQUIRED
        elif any(item.review_status is PatchReviewStatus.APPROVED for item in state.patches):
            state.status = ChangeTaskStatus.APPLY_READY
        else:
            state.status = ChangeTaskStatus.FAILED
            state.failure_reason = "ALL_PATCHES_REJECTED"
        state.trace.append(self._trace(state, "HUMAN_REVIEW", record.status.value, 0.0))
        self.checkpoints.save(state)
        return state

    def apply_reviewed_patches(
        self, task_id: str, *, current_version_id: str
    ) -> tuple[ChangeImpactTaskState, list[PatchApplyResult]]:
        state = self.get(task_id)
        started = time.perf_counter()
        evidence_by_id = {
            evidence_id: Evidence.model_validate(value)
            for evidence_id, value in state.evidence_snapshot.items()
        }
        service = PatchExecutionService(self.active_version_for_document)
        approved = [item for item in state.patches if item.review_status is PatchReviewStatus.APPROVED]
        state.rag_calls += 1 + sum(len(item.evidence_ids) for item in approved)
        if not approved:
            raise ValueError("no approved PatchCandidate is available")
        results: list[PatchApplyResult] = []
        candidate = Path(state.candidate_path)
        current_source = Path(state.source_path)
        for index, patch in enumerate(approved):
            if patch.idempotency_key in state.applied_keys:
                output = candidate
            elif index == 0 and not candidate.exists():
                output = candidate
            else:
                output = candidate.with_name(f"candidate-step-{index + 1}.docx")
                if output.exists():
                    output.unlink()
                if candidate.exists():
                    current_source = candidate
            result = service.apply(
                patch,
                evidence_by_id=evidence_by_id,
                expected_scope_fingerprint=state.scope_fingerprint,
                source=current_source,
                output=output,
                current_version_id=current_version_id,
                applied_keys=state.applied_keys,
                expected_scope=state.scope,
            )
            results.append(result)
            state.quality_gate = result.quality_gate
            if result.status is PatchApplyStatus.APPLIED and output != candidate:
                os.replace(output, candidate)
                current_source = candidate
            if result.status in {
                PatchApplyStatus.CONFLICT,
                PatchApplyStatus.BLOCKED_SCOPE,
                PatchApplyStatus.BLOCKED_STALE_EVIDENCE,
                PatchApplyStatus.BLOCKED_REVIEW,
            }:
                state.status = ChangeTaskStatus.REVIEW_REQUIRED
                state.failure_reason = result.failure_reason
                state.trace.append(self._trace(
                    state, "APPLY_PATCH", result.status.value,
                    time.perf_counter() - started,
                    failure_reason=result.failure_reason,
                ))
                self.checkpoints.save(state)
                return state, results
        state.status = ChangeTaskStatus.CANDIDATE_READY
        state.failure_reason = None
        state.trace.append(self._trace(
            state, "APPLY_PATCH", "COMPLETE", time.perf_counter() - started
        ))
        self.checkpoints.save(state)
        return state, results

    def finalize_candidate_version(
        self,
        task_id: str,
        *,
        version_id: str,
        version_label: str,
        document_type: str,
        title: str,
        profile: dict,
    ) -> ChangeImpactTaskState:
        state = self.get(task_id)
        if state.status is not ChangeTaskStatus.CANDIDATE_READY:
            raise ValueError("task candidate DOCX is not ready")
        if self.version_client is None:
            raise ValueError("RAG candidate version client is required")
        candidate_path = Path(state.candidate_path)
        if not candidate_path.is_file():
            raise ValueError("candidate DOCX is missing")
        approved_content = [
            patch.proposed_content
            for patch in state.patches
            if patch.review_status is PatchReviewStatus.APPROVED
        ]
        started = time.perf_counter()
        state.rag_calls += 1
        built = self.version_client.build_candidate_version(
            document_id=state.base_document_id,
            project_id=state.project_id,
            document_type=document_type,
            title=title,
            version_id=version_id,
            version_label=version_label,
            source_bytes=candidate_path.read_bytes(),
            source_name=candidate_path.name,
            profile=profile,
            expected_contents=approved_content,
        )
        state.candidate_version_record = dict(built)
        if built.get("status") != "VALIDATED":
            state.status = ChangeTaskStatus.FAILED
            state.failure_reason = str(built.get("failure_reason") or "CANDIDATE_BUILD_FAILED")
            state.quality_gate = QualityGateResult.blocked(
                QualityGateReason.CANDIDATE_VALIDATION_FAILED,
                PatchApplyStatus.PENDING,
                failure_reason=state.failure_reason,
            )
            state.trace.append(self._trace(
                state, "CANDIDATE_BUILD", "FAILED", time.perf_counter() - started,
                failure_reason=state.failure_reason,
            ))
            self.checkpoints.save(state)
            return state
        state.rag_calls += 1
        activated = self.version_client.activate_candidate_version(str(built["candidate_id"]))
        state.candidate_version_record = dict(activated)
        if activated.get("status") != "ACTIVE":
            state.status = ChangeTaskStatus.FAILED
            state.failure_reason = str(activated.get("failure_reason") or "CANDIDATE_ACTIVATION_FAILED")
            state.quality_gate = QualityGateResult.blocked(
                QualityGateReason.CANDIDATE_VALIDATION_FAILED,
                PatchApplyStatus.PENDING,
                failure_reason=state.failure_reason,
            )
        else:
            state.status = ChangeTaskStatus.COMPLETED
            state.failure_reason = None
            state.quality_gate = QualityGateResult.passed(PatchApplyStatus.APPLIED)
        state.trace.append(self._trace(
            state,
            "SAFE_ACTIVATION",
            state.status.value,
            time.perf_counter() - started,
            failure_reason=state.failure_reason,
        ))
        self.checkpoints.save(state)
        return state

    @staticmethod
    def _trace(
        state: ChangeImpactTaskState,
        step: str,
        status: str,
        latency: float,
        *,
        failure_reason: str | None = None,
    ) -> dict:
        return {
            "workflow_id": state.task_id,
            "step": step,
            "status": status,
            "latency": round(latency, 6),
            "rag_calls": state.rag_calls,
            "llm_calls": 0,
            "evidence_count": len(state.evidence_snapshot),
            "organization_id": state.organization_id,
            "project_id": state.project_id,
            "document_version": state.base_version_id,
            "prompt_version": None,
            "failure_reason": failure_reason,
            "quality_gate": (
                state.quality_gate.model_dump(mode="json")
                if state.quality_gate is not None
                else None
            ),
        }

