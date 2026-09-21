"""Atomic checkpoint state and repository-compatible summaries."""

from __future__ import annotations

import json
import os
import tempfile
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path


SCHEMA_VERSION = "document-workflow-checkpoint-v2"


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
    scope: dict
    scope_fingerprint: str
    workflow_status: str = "PENDING"
    current_section_id: str | None = None
    section_states: dict[str, dict] = field(default_factory=dict)
    section_drafts: dict[str, dict] = field(default_factory=dict)
    section_reviews: dict[str, dict] = field(default_factory=dict)
    evidence_snapshot: dict = field(default_factory=dict)
    step_count: int = 0
    rag_call_count: int = 0
    created_at: str = field(default_factory=now)
    updated_at: str = field(default_factory=now)
    draft_path: str | None = None
    approved_path: str | None = None
    last_stop_reason: str | None = None
    requires_human_review: bool = True

    def payload(self) -> dict:
        value = asdict(self)
        value["checkpoint_schema_version"] = SCHEMA_VERSION
        value["completed_section_ids"] = sorted(key for key, item in self.section_states.items() if item.get("status") == "COMPLETE")
        value["failed_section_ids"] = sorted(key for key, item in self.section_states.items() if item.get("status") in {"FAILED", "PARTIAL", "NO_PROGRESS"})
        return value


class CheckpointStore:
    def __init__(self, root: Path):
        self.root = root.resolve()
        self.root.mkdir(parents=True, exist_ok=True)

    def path(self, workflow_id: str) -> Path:
        if not workflow_id.startswith(("dw_", "cir_")) or not all(char.isalnum() or char == "_" for char in workflow_id):
            raise CheckpointInvalid("invalid workflow_id")
        return self.root / f"{workflow_id}.json"

    def save(self, state: WorkflowState) -> Path:
        state.updated_at = now()
        target = self.path(state.workflow_id)
        temporary: Path | None = None
        try:
            with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=self.root, prefix=".checkpoint.", suffix=".tmp", delete=False) as handle:
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

    def save_payload(
        self,
        record_id: str,
        payload: dict,
        *,
        schema_version: str,
        requires_human_review: bool,
    ) -> Path:
        value = dict(payload)
        value["checkpoint_schema_version"] = schema_version
        value["checkpoint_record_id"] = record_id
        value["requires_human_review"] = requires_human_review
        target = self.path(record_id)
        temporary: Path | None = None
        try:
            with tempfile.NamedTemporaryFile(
                "w", encoding="utf-8", dir=self.root,
                prefix=".checkpoint.", suffix=".tmp", delete=False,
            ) as handle:
                temporary = Path(handle.name)
                json.dump(value, handle, ensure_ascii=False, sort_keys=True)
                handle.write("\n")
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, target)
        finally:
            if temporary is not None and temporary.exists():
                temporary.unlink()
        return target

    def load_payload(self, record_id: str, *, schema_version: str) -> dict:
        try:
            payload = json.loads(self.path(record_id).read_text(encoding="utf-8"))
            if (
                not isinstance(payload, dict)
                or payload.get("checkpoint_schema_version") != schema_version
                or payload.get("checkpoint_record_id") != record_id
                or payload.get("requires_human_review") is not True
            ):
                raise CheckpointInvalid("checkpoint payload schema or identity invalid")
            payload.pop("checkpoint_schema_version", None)
            payload.pop("checkpoint_record_id", None)
            payload.pop("requires_human_review", None)
            return payload
        except (OSError, TypeError, ValueError, json.JSONDecodeError) as exc:
            if isinstance(exc, CheckpointInvalid):
                raise
            raise CheckpointInvalid("checkpoint payload missing or malformed") from exc

    def load(self, workflow_id: str) -> WorkflowState:
        try:
            payload = json.loads(self.path(workflow_id).read_text(encoding="utf-8"))
            if not isinstance(payload, dict) or payload.get("checkpoint_schema_version") != SCHEMA_VERSION:
                raise CheckpointInvalid("checkpoint schema version mismatch")
            if payload.get("workflow_id") != workflow_id or payload.get("requires_human_review") is not True:
                raise CheckpointInvalid("checkpoint identity or human-review contract invalid")
            keys = WorkflowState.__dataclass_fields__.keys()
            state = WorkflowState(**{key: payload[key] for key in keys})
            if not all(isinstance(item, dict) for item in (state.section_states, state.section_drafts, state.section_reviews, state.evidence_snapshot, state.scope)):
                raise CheckpointInvalid("checkpoint state schema invalid")
            return state
        except (OSError, KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
            if isinstance(exc, CheckpointInvalid):
                raise
            raise CheckpointInvalid("checkpoint missing or malformed") from exc
