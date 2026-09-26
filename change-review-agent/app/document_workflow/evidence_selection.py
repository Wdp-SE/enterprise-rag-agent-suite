"""Thin, deterministic Evidence selection for bounded Agent context."""

from __future__ import annotations

from dataclasses import dataclass

from pydantic import BaseModel, ConfigDict, Field

from .evidence_models import Evidence
from .freshness import EvidenceFreshness
from .scope import WorkflowScope


class EvidenceSelectionError(ValueError):
    """Fail-closed selection error that never widens Scope or Freshness."""


@dataclass(frozen=True)
class EvidenceSelectionPolicy:
    max_evidence_count: int = 5

    def __post_init__(self) -> None:
        if self.max_evidence_count <= 0:
            raise ValueError("max_evidence_count must be positive")


class EvidenceSelectionStats(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    retrieved_evidence_count: int = Field(ge=0)
    valid_evidence_count: int = Field(ge=0)
    deduplicated_evidence_count: int = Field(ge=0)
    selected_evidence_count: int = Field(ge=0)


@dataclass(frozen=True)
class EvidenceSelectionResult:
    selected: tuple[Evidence, ...]
    stats: EvidenceSelectionStats


def evidence_in_scope(evidence: Evidence, scope: WorkflowScope) -> bool:
    """Return whether Evidence satisfies the immutable business retrieval scope."""
    if scope.project_ids and evidence.project_id not in scope.project_ids:
        return False
    if scope.document_ids and evidence.document_id not in scope.document_ids:
        return False
    if scope.document_types and evidence.document_type not in scope.document_types:
        return False
    if scope.version_ids and evidence.version_id not in scope.version_ids:
        return False
    if scope.active_only and evidence.version_id is not None:
        return evidence.version_status == "ACTIVE"
    return True


class EvidenceSelector:
    """Apply existing Scope/Freshness rules, stable deduplication and a count budget."""

    def __init__(self, policy: EvidenceSelectionPolicy | None = None):
        self.policy = policy or EvidenceSelectionPolicy()

    def select(
        self,
        candidates: list[Evidence] | tuple[Evidence, ...],
        scope: WorkflowScope,
        *,
        required_evidence_ids: tuple[str, ...] | list[str] = (),
    ) -> EvidenceSelectionResult:
        rows = list(candidates)
        valid = [item for item in rows if evidence_in_scope(item, scope) and self._fresh(item)]

        unique: list[Evidence] = []
        seen: set[tuple[str, str, str]] = set()
        for item in valid:
            key = (
                item.canonical_source_identity(),
                item.chunk_id or "",
                item.content_hash or item.expected_content_hash(),
            )
            if key not in seen:
                seen.add(key)
                unique.append(item)

        required = tuple(dict.fromkeys(item for item in required_evidence_ids if item))
        by_id = {item.evidence_id: item for item in unique}
        unavailable = [item for item in required if item not in by_id]
        if unavailable:
            raise EvidenceSelectionError(
                "required Evidence is unavailable after scope/freshness validation"
            )
        if len(required) > self.policy.max_evidence_count:
            raise EvidenceSelectionError(
                "required Evidence exceeds max_evidence_count; refusing to drop critical Evidence"
            )

        required_set = set(required)
        ordered = [by_id[item] for item in required]
        ordered.extend(item for item in unique if item.evidence_id not in required_set)
        selected = tuple(ordered[: self.policy.max_evidence_count])
        return EvidenceSelectionResult(
            selected=selected,
            stats=EvidenceSelectionStats(
                retrieved_evidence_count=len(rows),
                valid_evidence_count=len(valid),
                deduplicated_evidence_count=len(unique),
                selected_evidence_count=len(selected),
            ),
        )

    @staticmethod
    def _fresh(evidence: Evidence) -> bool:
        if evidence.version_id is None:
            return True
        return evidence.freshness not in {
            EvidenceFreshness.STALE.value,
            EvidenceFreshness.UNKNOWN.value,
        }
