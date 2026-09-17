"""Shared result contracts for offline Candidate Package construction."""

from __future__ import annotations

from enum import Enum

from pydantic import Field

from app.research.models import StrictModel


class CandidateBuildStatus(str, Enum):
    CREATED = "CREATED"
    REUSED = "REUSED"
    INSUFFICIENT_EVIDENCE = "INSUFFICIENT_EVIDENCE"


class CandidateBuildResult(StrictModel):
    status: CandidateBuildStatus
    candidate_id: str | None = None
    document_id: str | None = None
    package_path: str | None = None
    reason: str | None = None


class ValidationIssue(StrictModel):
    code: str
    message: str


class CandidateValidationResult(StrictModel):
    accepted: bool
    issues: list[ValidationIssue] = Field(default_factory=list)
