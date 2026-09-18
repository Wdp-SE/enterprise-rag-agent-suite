"""Deterministic evidence-sufficiency decisions for one field."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from .evidence_models import Evidence, normalize_text
from .models import FieldTask


class EvidenceSufficiency(str, Enum):
    SUFFICIENT = "SUFFICIENT"
    INSUFFICIENT = "INSUFFICIENT"
    MISSING = "MISSING"


@dataclass(frozen=True)
class SufficiencyDecision:
    status: EvidenceSufficiency
    evidence_ids: tuple[str, ...]
    reason: str


class EvidenceSufficiencyService:
    def evaluate(self, field: FieldTask, evidence: list[Evidence]) -> SufficiencyDecision:
        usable = [item for item in evidence if normalize_text(item.content)]
        ids = tuple(item.evidence_id for item in usable if item.evidence_id)
        if not usable:
            return SufficiencyDecision(EvidenceSufficiency.MISSING, (), "NO_EVIDENCE")
        substantive = [item for item in usable if len(normalize_text(item.content)) >= 12]
        if not substantive:
            return SufficiencyDecision(EvidenceSufficiency.INSUFFICIENT, ids, "EVIDENCE_TOO_SHORT")
        return SufficiencyDecision(EvidenceSufficiency.SUFFICIENT, ids, "CONTENT_AVAILABLE")
