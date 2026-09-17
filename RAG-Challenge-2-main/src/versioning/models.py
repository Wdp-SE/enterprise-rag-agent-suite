"""Models shared by version intent detection, resolution, and retrieval."""

from __future__ import annotations

from datetime import date
from enum import Enum
from typing import List, Optional

from pydantic import BaseModel, ConfigDict, Field, model_validator

from src.evaluation.corpus import CorpusStatus


class VersionIntent(str, Enum):
    CURRENT = "CURRENT"
    HISTORICAL = "HISTORICAL"
    EXPLICIT_VERSION = "EXPLICIT_VERSION"
    TEMPORAL_DATE = "TEMPORAL_DATE"
    UNSPECIFIED = "UNSPECIFIED"


class DatePrecision(str, Enum):
    DAY = "DAY"
    MONTH = "MONTH"
    YEAR = "YEAR"


class VersionAction(str, Enum):
    ALLOW = "ALLOW"
    DEMOTE = "DEMOTE"
    EXCLUDE = "EXCLUDE"
    PREFER = "PREFER"


class VersionMetadata(BaseModel):
    """Normalized version data. ``is_current`` is deliberately computed."""

    model_config = ConfigDict(extra="forbid")

    document_id: str
    title: Optional[str] = None
    document_number: Optional[str] = None
    version_family: Optional[str] = None
    version: Optional[str] = None
    status: Optional[CorpusStatus] = None
    publish_date: Optional[date] = None
    effective_from: Optional[date] = None
    effective_to: Optional[date] = None
    effective_to_source: Optional[str] = None
    supersedes: List[str] = Field(default_factory=list)
    superseded_by: List[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_effective_interval(self):
        if (
            self.effective_from is not None
            and self.effective_to is not None
            and self.effective_to <= self.effective_from
        ):
            raise ValueError("effective_to must be later than effective_from")
        return self

    def is_current(self, as_of_date: date) -> Optional[bool]:
        if self.status is None or self.effective_from is None:
            return None
        if self.status != "ACTIVE" or as_of_date < self.effective_from:
            return False
        return self.effective_to is None or as_of_date < self.effective_to


class VersionContext(BaseModel):
    model_config = ConfigDict(extra="forbid")

    intent: VersionIntent
    explicit_versions: List[str] = Field(default_factory=list)
    matched_document_ids: List[str] = Field(default_factory=list)
    matched_version_families: List[str] = Field(default_factory=list)
    query_date: Optional[date] = None
    query_period_start: Optional[date] = None
    query_period_end: Optional[date] = None
    date_precision: Optional[DatePrecision] = None
    signals: List[str] = Field(default_factory=list)
    temporal_ambiguity: bool = False


class VersionDecision(BaseModel):
    model_config = ConfigDict(extra="forbid")

    document_id: str
    document_status: Optional[CorpusStatus] = None
    version_family: Optional[str] = None
    version: Optional[str] = None
    action: VersionAction
    adjustment: float = 0.0
    reason: str
    index_available: bool = False


class VersionResolutionPlan(BaseModel):
    model_config = ConfigDict(extra="forbid")

    context: VersionContext
    as_of_date: date
    eligible_document_ids: List[str] = Field(default_factory=list)
    decisions: List[VersionDecision] = Field(default_factory=list)
    issues: List[str] = Field(default_factory=list)

    def decision_for(self, document_id: str) -> Optional[VersionDecision]:
        return next(
            (item for item in self.decisions if item.document_id == document_id),
            None,
        )

    def trace(self, *, question_id: Optional[str] = None) -> dict:
        return {
            "question_id": question_id,
            "version_intent": self.context.intent.value,
            "query_date": (
                self.context.query_date.isoformat()
                if self.context.query_date is not None
                else None
            ),
            "query_period_start": (
                self.context.query_period_start.isoformat()
                if self.context.query_period_start is not None
                else None
            ),
            "query_period_end": (
                self.context.query_period_end.isoformat()
                if self.context.query_period_end is not None
                else None
            ),
            "date_precision": (
                self.context.date_precision.value
                if self.context.date_precision is not None
                else None
            ),
            "explicit_versions": self.context.explicit_versions,
            "matched_document_ids": self.context.matched_document_ids,
            "temporal_ambiguity": self.context.temporal_ambiguity,
            "signals": self.context.signals,
            "issues": self.issues,
            "candidate_documents": [
                {
                    "candidate_document_id": item.document_id,
                    "document_status": item.document_status,
                    "version_family": item.version_family,
                    "version_action": item.action.value,
                    "version_adjustment": item.adjustment,
                    "reason": item.reason,
                    "index_available": item.index_available,
                }
                for item in self.decisions
            ],
        }
