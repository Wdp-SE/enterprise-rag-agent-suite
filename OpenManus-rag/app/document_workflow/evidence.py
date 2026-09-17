"""Reuse validated research Evidence and EvidenceStore with task/query indexes."""

from __future__ import annotations

from collections import defaultdict
from pathlib import Path

from app.research.evidence_store import EvidenceAddStatus, EvidenceStore
from app.research.models import Evidence
from app.research.evidence_store import EvidenceStoreError


class EvidenceCache:
    def __init__(self, workspace_root: Path, output_path: Path):
        self.store = EvidenceStore(workspace_root, output_path)
        self.by_task: dict[str, set[str]] = defaultdict(set)
        self.by_query: dict[tuple[str, str], set[str]] = defaultdict(set)
        self.query_attempted: set[tuple[str, str]] = set()

    def add(self, task_id: str, query: str, evidence: Evidence) -> bool:
        assert evidence.evidence_id is not None
        added = self.store.add(evidence) is EvidenceAddStatus.ADDED
        self.by_task[task_id].add(evidence.evidence_id)
        self.by_query[(task_id, query)].add(evidence.evidence_id)
        return added

    def for_task(self, task_id: str) -> list[Evidence]:
        return [self.store.get(eid) for eid in sorted(self.by_task[task_id]) if self.store.get(eid)]

    def covers(self, task_id: str, field_name: str) -> bool:
        return any(field_name in item.content for item in self.for_task(task_id))

    def membership(self, task_id: str, evidence_ids: list[str]) -> bool:
        return set(evidence_ids).issubset(self.by_task[task_id]) and all(
            self.store.get(eid) is not None for eid in evidence_ids
        )

    def save(self) -> None:
        self.store.save()

    def snapshot(self) -> dict:
        return {
            "evidence": [item.model_dump(mode="json") for item in self.store.list()],
            "by_task": {key: sorted(ids) for key, ids in self.by_task.items()},
            "by_query": [{"task_id": task, "query": query, "ids": sorted(ids)}
                         for (task, query), ids in self.by_query.items()],
            "query_attempted": [[task, query] for task, query in sorted(self.query_attempted)],
        }

    def restore(self, snapshot: dict) -> None:
        try:
            for record in snapshot["evidence"]:
                item = Evidence.model_validate(record)
                if self.store.add(item) is EvidenceAddStatus.DUPLICATE:
                    raise EvidenceStoreError("duplicate checkpoint evidence")
            for task, ids in snapshot["by_task"].items():
                if not isinstance(ids, list) or any(self.store.get(eid) is None for eid in ids):
                    raise EvidenceStoreError("invalid checkpoint task evidence reference")
                self.by_task[task].update(ids)
            for entry in snapshot["by_query"]:
                task, query, ids = entry["task_id"], entry["query"], entry["ids"]
                if task not in self.by_task or not set(ids).issubset(self.by_task[task]):
                    raise EvidenceStoreError("invalid checkpoint query evidence reference")
                self.by_query[(task, query)].update(ids)
            self.query_attempted.update((task, query) for task, query in snapshot["query_attempted"])
        except (KeyError, TypeError, ValueError) as exc:
            raise EvidenceStoreError("invalid checkpoint EvidenceCache") from exc
