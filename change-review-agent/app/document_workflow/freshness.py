"""Version freshness checks for checkpointed workflow Evidence."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Callable, Iterable

from .evidence_models import Evidence


class EvidenceFreshness(str, Enum):
    FRESH = "FRESH"
    STALE = "STALE"
    UNKNOWN = "UNKNOWN"


@dataclass(frozen=True)
class FreshnessDecision:
    evidence_id: str
    document_id: str | None
    version_id: str | None
    active_version_id: str | None
    freshness: EvidenceFreshness


class EvidenceFreshnessValidator:
    def __init__(self, active_version_for_document: Callable[[str], str | None]):
        self.active_version_for_document = active_version_for_document

    def evaluate(self, evidence: Evidence, *, historical_version_ids: Iterable[str] = ()) -> FreshnessDecision:
        historical = set(historical_version_ids)
        active = self.active_version_for_document(evidence.document_id) if evidence.document_id else None
        if evidence.version_id in historical:
            status = EvidenceFreshness.FRESH
        elif evidence.document_id is None or evidence.version_id is None or active is None:
            status = EvidenceFreshness.UNKNOWN
        elif evidence.version_id == active:
            status = EvidenceFreshness.FRESH
        else:
            status = EvidenceFreshness.STALE
        assert evidence.evidence_id is not None
        return FreshnessDecision(evidence.evidence_id, evidence.document_id, evidence.version_id, active, status)
