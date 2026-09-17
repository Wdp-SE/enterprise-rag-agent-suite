"""Atomic, versioned recovery state. Sensitive evidence belongs here, not in trace."""

from __future__ import annotations

import json
import os
import tempfile
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path


SCHEMA_VERSION = "document-workflow-checkpoint-v1"


class CheckpointInvalid(ValueError):
    code = "CHECKPOINT_INVALID"


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class WorkflowState:
    workflow_id: str
    template_id: str
    template_hash: str
    template_path: str
    output_path: str
    config_fingerprint: str
    workflow_status: str = "PENDING"
    current_section_id: str | None = None
    section_states: dict[str, dict] = field(default_factory=dict)
    section_drafts: dict[str, dict] = field(default_factory=dict)
    evidence_snapshot: dict = field(default_factory=dict)
    step_count: int = 0
    rag_call_count: int = 0
    created_at: str = field(default_factory=now)
    updated_at: str = field(default_factory=now)
    requires_human_review: bool = True

    def payload(self) -> dict:
        from dataclasses import asdict
        value = asdict(self)
        value["checkpoint_schema_version"] = SCHEMA_VERSION
        value["completed_section_ids"] = sorted(k for k, v in self.section_states.items() if v.get("status") == "COMPLETE")
        value["pending_section_ids"] = sorted(k for k, v in self.section_states.items() if v.get("status") == "PENDING")
        value["failed_section_ids"] = sorted(k for k, v in self.section_states.items() if v.get("status") in {"FAILED", "PARTIAL", "NO_PROGRESS"})
        value["missing_fields"] = {k: v.get("missing_fields", []) for k, v in self.section_states.items() if v.get("missing_fields")}
        return value


class CheckpointStore:
    def __init__(self, root: Path):
        self.root = root.resolve()
        self.root.mkdir(parents=True, exist_ok=True)

    def path(self, workflow_id: str) -> Path:
        if not workflow_id.startswith("dw_") or not all(c.isalnum() or c == "_" for c in workflow_id):
            raise CheckpointInvalid("invalid workflow_id")
        return self.root / f"{workflow_id}.json"

    def save(self, state: WorkflowState) -> Path:
        state.updated_at = now()
        target = self.path(state.workflow_id)
        temporary = None
        try:
            with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=self.root,
                                             prefix=".checkpoint.", suffix=".tmp", delete=False) as handle:
                temporary = Path(handle.name)
                json.dump(state.payload(), handle, ensure_ascii=False, sort_keys=True)
                handle.write("\n")
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, target)
        finally:
            if temporary is not None and temporary.exists():
                temporary.unlink()
        return target

    def load(self, workflow_id: str) -> WorkflowState:
        try:
            payload = json.loads(self.path(workflow_id).read_text(encoding="utf-8"))
            if not isinstance(payload, dict) or payload.get("checkpoint_schema_version") != SCHEMA_VERSION:
                raise CheckpointInvalid("checkpoint schema version mismatch")
            if payload.get("workflow_id") != workflow_id or payload.get("requires_human_review") is not True:
                raise CheckpointInvalid("checkpoint identity or human-review contract invalid")
            keys = WorkflowState.__dataclass_fields__.keys()
            state = WorkflowState(**{key: payload[key] for key in keys})
            if not isinstance(state.section_states, dict) or not isinstance(state.section_drafts, dict) or not isinstance(state.evidence_snapshot, dict):
                raise CheckpointInvalid("checkpoint state schema invalid")
            return state
        except (OSError, KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
            if isinstance(exc, CheckpointInvalid):
                raise
            raise CheckpointInvalid("checkpoint missing or malformed") from exc
