"""Change-impact checkpoint adapter over the existing atomic CheckpointStore."""

from __future__ import annotations

from app.document_workflow.state import CheckpointStore

from .models import ChangeImpactTaskState


SCHEMA_VERSION = "change-impact-checkpoint-v1"


class ChangeImpactCheckpointStore:
    def __init__(self, store: CheckpointStore):
        self.store = store

    def save(self, state: ChangeImpactTaskState):
        return self.store.save_payload(
            state.task_id,
            state.model_dump(mode="json"),
            schema_version=SCHEMA_VERSION,
            requires_human_review=True,
        )

    def load(self, task_id: str) -> ChangeImpactTaskState:
        return ChangeImpactTaskState.model_validate(
            self.store.load_payload(task_id, schema_version=SCHEMA_VERSION)
        )

