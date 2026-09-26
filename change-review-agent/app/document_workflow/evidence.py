"""Task- and field-scoped Evidence cache with freshness-aware membership."""

from __future__ import annotations

from collections import defaultdict
from pathlib import Path

from .evidence_models import Evidence
from .evidence_store import EvidenceAddStatus, EvidenceStore, EvidenceStoreError
from .freshness import EvidenceFreshness, EvidenceFreshnessValidator, FreshnessDecision


class EvidenceCache:
    def __init__(self, workspace_root: Path, output_path: Path):
        self.store = EvidenceStore(workspace_root, output_path)
        self.by_task: dict[str, set[str]] = defaultdict(set)
        self.by_field: dict[tuple[str, str], set[str]] = defaultdict(set)
        self.by_query: dict[tuple[str, str, str], set[str]] = defaultdict(set)
        self.query_attempted: set[tuple[str, str, str]] = set()

    def add(self, task_id: str, field_id: str, query: str, evidence: Evidence) -> bool:
        assert evidence.evidence_id is not None
        added = self.store.add(evidence) is EvidenceAddStatus.ADDED
        self.by_task[task_id].add(evidence.evidence_id)
        self.by_field[(task_id, field_id)].add(evidence.evidence_id)
        self.by_query[(task_id, field_id, query)].add(evidence.evidence_id)
        return added

    @staticmethod
    def _usable(evidence: Evidence) -> bool:
        return not (
            evidence.version_id is not None
            and evidence.freshness in {EvidenceFreshness.STALE.value, EvidenceFreshness.UNKNOWN.value}
        )

    def _resolve(self, ids: set[str]) -> list[Evidence]:
        return [
            item for evidence_id in sorted(ids)
            if (item := self.store.get(evidence_id)) is not None and self._usable(item)
        ]

    def for_task(self, task_id: str) -> list[Evidence]:
        return self._resolve(self.by_task[task_id])

    def for_field(self, task_id: str, field_id: str) -> list[Evidence]:
        return self._resolve(self.by_field[(task_id, field_id)])

    def membership(self, task_id: str, evidence_ids: list[str]) -> bool:
        return set(evidence_ids).issubset(self.by_task[task_id]) and all(
            (item := self.store.get(evidence_id)) is not None and self._usable(item)
            for evidence_id in evidence_ids
        )

    def apply_freshness(
        self,
        validator: EvidenceFreshnessValidator,
        *,
        historical_version_ids: set[str] | None = None,
    ) -> tuple[list[FreshnessDecision], set[str]]:
        decisions = [
            validator.evaluate(item, historical_version_ids=historical_version_ids or set())
            for item in self.store.list()
        ]
        affected_tasks: set[str] = set()
        for decision in decisions:
            item = self.store.get(decision.evidence_id)
            assert item is not None
            item.freshness = decision.freshness.value
            if decision.freshness in {EvidenceFreshness.STALE, EvidenceFreshness.UNKNOWN}:
                affected_tasks.update(task for task, ids in self.by_task.items() if decision.evidence_id in ids)
        return decisions, affected_tasks

    def invalidate_task(self, task_id: str) -> None:
        """Remove active task indexes while retaining Evidence for audit history."""
        self.by_task.pop(task_id, None)
        self.by_field = defaultdict(
            set, {key: ids for key, ids in self.by_field.items() if key[0] != task_id}
        )
        self.by_query = defaultdict(
            set, {key: ids for key, ids in self.by_query.items() if key[0] != task_id}
        )
        self.query_attempted = {item for item in self.query_attempted if item[0] != task_id}

    def save(self) -> None:
        self.store.save()

    def snapshot(self) -> dict:
        return {
            "format_version": 2,
            "evidence": [item.model_dump(mode="json") for item in self.store.list()],
            "by_task": {key: sorted(ids) for key, ids in self.by_task.items()},
            "by_field": [
                {"task_id": task, "field_id": field, "ids": sorted(ids)}
                for (task, field), ids in sorted(self.by_field.items())
            ],
            "by_query": [
                {"task_id": task, "field_id": field, "query": query, "ids": sorted(ids)}
                for (task, field, query), ids in sorted(self.by_query.items())
            ],
            "query_attempted": [list(item) for item in sorted(self.query_attempted)],
        }

    def restore(self, snapshot: dict) -> None:
        try:
            if snapshot.get("format_version") != 2:
                raise EvidenceStoreError("unsupported EvidenceCache snapshot")
            for record in snapshot["evidence"]:
                if self.store.add(Evidence.model_validate(record)) is EvidenceAddStatus.DUPLICATE:
                    raise EvidenceStoreError("duplicate checkpoint evidence")
            for task, ids in snapshot["by_task"].items():
                if not isinstance(ids, list) or any(self.store.get(item) is None for item in ids):
                    raise EvidenceStoreError("invalid checkpoint task evidence reference")
                self.by_task[task].update(ids)
            for entry in snapshot["by_field"]:
                key = (entry["task_id"], entry["field_id"])
                if key[0] not in self.by_task or not set(entry["ids"]).issubset(self.by_task[key[0]]):
                    raise EvidenceStoreError("invalid checkpoint field evidence reference")
                self.by_field[key].update(entry["ids"])
            for entry in snapshot["by_query"]:
                key = (entry["task_id"], entry["field_id"], entry["query"])
                if not set(entry["ids"]).issubset(self.by_field[(key[0], key[1])]):
                    raise EvidenceStoreError("invalid checkpoint query evidence reference")
                self.by_query[key].update(entry["ids"])
            self.query_attempted.update(tuple(item) for item in snapshot["query_attempted"])
        except (KeyError, TypeError, ValueError) as exc:
            raise EvidenceStoreError("invalid checkpoint EvidenceCache") from exc
