"""Filesystem persistence boundary for workflow history and resume."""

from __future__ import annotations

from pathlib import Path

from .state import CheckpointInvalid, CheckpointStore, WorkflowState


class WorkflowRepository:
    def __init__(self, runtime_root: str | Path):
        self.runtime_root = Path(runtime_root).resolve()
        self.outputs_root = self.runtime_root / "outputs"
        self.outputs_root.mkdir(parents=True, exist_ok=True)

    def _checkpoint_path(self, workflow_id: str) -> Path:
        matches = list(self.outputs_root.glob(f"*/checkpoints/{workflow_id}.json"))
        if len(matches) != 1:
            raise CheckpointInvalid("workflow checkpoint not found or ambiguous")
        return matches[0]

    def get(self, workflow_id: str) -> WorkflowState:
        path = self._checkpoint_path(workflow_id)
        return CheckpointStore(path.parent).load(workflow_id)

    def save(self, state: WorkflowState) -> Path:
        return CheckpointStore(Path(state.output_path) / "checkpoints").save(state)

    def list_workflows(self) -> list[dict]:
        result: list[dict] = []
        for path in self.outputs_root.glob("*/checkpoints/dw_*.json"):
            try:
                state = CheckpointStore(path.parent).load(path.stem)
            except CheckpointInvalid:
                continue
            evidence = state.evidence_snapshot.get("evidence", []) if isinstance(state.evidence_snapshot, dict) else []
            result.append({
                "workflow_id": state.workflow_id,
                "template_name": Path(state.template_path).name,
                "scope": state.scope,
                "workflow_status": state.workflow_status,
                "completed_sections": sum(item.get("status") == "COMPLETE" for item in state.section_states.values()),
                "failed_sections": sum(item.get("status") in {"FAILED", "PARTIAL", "NO_PROGRESS"} for item in state.section_states.values()),
                "stale_evidence_count": sum(item.get("freshness") in {"STALE", "UNKNOWN"} for item in evidence),
                "last_stop_reason": state.last_stop_reason,
                "updated_at": state.updated_at,
            })
        return sorted(result, key=lambda item: item["updated_at"], reverse=True)
