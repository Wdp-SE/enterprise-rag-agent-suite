"""Strict, RAG-independent contracts for the live research workflow."""

from __future__ import annotations

import json
from datetime import datetime
from enum import Enum
from typing import Any

from pydantic import Field, field_validator, model_validator

from app.research.models import (
    SHA256_PATTERN,
    SourceLevel,
    StrictModel,
    canonicalize_source_url,
    normalize_text,
    sha256_text,
    validate_workspace_relative_path,
)


class ResearchPhase(str, Enum):
    DISCOVER = "DISCOVER"
    SELECT = "SELECT"
    ACQUIRE = "ACQUIRE"
    EXTRACT = "EXTRACT"
    BUILD_RESULT = "BUILD_RESULT"
    OUTPUT = "OUTPUT"
    COMPLETE = "COMPLETE"


class ResearchStatus(str, Enum):
    COMPLETED = "COMPLETED"
    PARTIAL = "PARTIAL"
    INSUFFICIENT_EVIDENCE = "INSUFFICIENT_EVIDENCE"
    FAILED = "FAILED"


class ResearchErrorCode(str, Enum):
    SEARCH_FAILED = "SEARCH_FAILED"
    DOWNLOAD_FAILED = "DOWNLOAD_FAILED"
    UNSUPPORTED_SCAN_PDF = "UNSUPPORTED_SCAN_PDF"
    EMPTY_CONTENT = "EMPTY_CONTENT"
    EVIDENCE_EXTRACTION_FAILED = "EVIDENCE_EXTRACTION_FAILED"
    INSUFFICIENT_EVIDENCE = "INSUFFICIENT_EVIDENCE"


class AcquisitionMethod(str, Enum):
    HTTP = "HTTP"
    BROWSER = "BROWSER"


def _require_timezone(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("datetime must include a timezone")
    return value


class ResearchSearchResult(StrictModel):
    search_result_id: str | None = Field(default=None, pattern=r"^sr_[0-9a-f]{20}$")
    query: str = Field(min_length=1)
    title: str = Field(min_length=1)
    url: str
    snippet: str = ""
    engine: str = Field(min_length=1)
    position: int = Field(ge=1)

    @field_validator("query", "title", "snippet", "engine")
    @classmethod
    def normalize_text_fields(cls, value: str) -> str:
        return normalize_text(value)

    @field_validator("url")
    @classmethod
    def normalize_url(cls, value: str) -> str:
        return canonicalize_source_url(value)

    @model_validator(mode="after")
    def set_stable_id(self) -> "ResearchSearchResult":
        payload = json.dumps(
            {"engine": self.engine.casefold(), "url": self.url},
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        expected = f"sr_{sha256_text(payload)[:20]}"
        if self.search_result_id is not None and self.search_result_id != expected:
            raise ValueError("search_result_id does not match its stable identity")
        self.search_result_id = expected
        return self


class SelectedSource(StrictModel):
    search_result_id: str = Field(pattern=r"^sr_[0-9a-f]{20}$")
    title: str = Field(min_length=1)
    url: str
    organization: str = Field(min_length=1)
    organization_type: str | None = None
    source_type: str = Field(min_length=1)
    source_level: SourceLevel
    selection_reason: str = Field(min_length=1)
    search_engine: str = Field(min_length=1)
    search_position: int = Field(ge=1)

    @field_validator("url")
    @classmethod
    def normalize_url(cls, value: str) -> str:
        return canonicalize_source_url(value)

    @field_validator(
        "title",
        "organization",
        "organization_type",
        "source_type",
        "selection_reason",
        "search_engine",
    )
    @classmethod
    def normalize_optional_text(cls, value: str | None) -> str | None:
        return normalize_text(value) if value is not None else None


class AcquiredSource(StrictModel):
    artifact_id: str | None = Field(default=None, pattern=r"^art_[0-9a-f]{20}$")
    search_result_id: str = Field(pattern=r"^sr_[0-9a-f]{20}$")
    title: str = Field(min_length=1)
    organization: str = Field(min_length=1)
    source_url: str
    final_url: str
    source_type: str = Field(min_length=1)
    source_level: SourceLevel
    media_type: str = Field(pattern=r"^(application/pdf|text/html)$")
    acquisition_method: AcquisitionMethod
    retrieved_at: datetime
    local_file: str
    raw_file_hash: str
    reused: bool = False

    @field_validator("source_url", "final_url")
    @classmethod
    def normalize_url(cls, value: str) -> str:
        return canonicalize_source_url(value)

    @field_validator("retrieved_at")
    @classmethod
    def validate_retrieved_at(cls, value: datetime) -> datetime:
        return _require_timezone(value)

    @field_validator("local_file")
    @classmethod
    def normalize_local_file(cls, value: str) -> str:
        return validate_workspace_relative_path(value)

    @field_validator("raw_file_hash")
    @classmethod
    def validate_raw_hash(cls, value: str) -> str:
        if not SHA256_PATTERN.fullmatch(value):
            raise ValueError("raw_file_hash must be a lowercase SHA256 digest")
        return value

    @model_validator(mode="after")
    def set_stable_artifact_id(self) -> "AcquiredSource":
        expected = f"art_{sha256_text(f'{self.final_url}|{self.raw_file_hash}')[:20]}"
        if self.artifact_id is not None and self.artifact_id != expected:
            raise ValueError("artifact_id does not match its stable identity")
        self.artifact_id = expected
        return self


class ResearchFailure(StrictModel):
    code: ResearchErrorCode
    message: str = Field(min_length=1)
    phase: ResearchPhase
    source_url: str | None = None

    @field_validator("source_url")
    @classmethod
    def normalize_source_url(cls, value: str | None) -> str | None:
        return canonicalize_source_url(value) if value is not None else None


class ResearchFinding(StrictModel):
    finding_id: str | None = Field(default=None, pattern=r"^finding_[0-9a-f]{16}$")
    statement: str = Field(min_length=1)
    evidence_ids: list[str] = Field(min_length=1)

    @field_validator("statement")
    @classmethod
    def normalize_statement(cls, value: str) -> str:
        return normalize_text(value)

    @field_validator("evidence_ids")
    @classmethod
    def validate_evidence_ids(cls, values: list[str]) -> list[str]:
        normalized = sorted(set(values))
        if len(normalized) != len(values):
            raise ValueError("finding evidence_ids must be unique")
        if any(not value.startswith("ev_") for value in normalized):
            raise ValueError("finding contains an invalid evidence_id")
        return normalized

    @model_validator(mode="after")
    def set_stable_id(self) -> "ResearchFinding":
        payload = json.dumps(
            {"evidence_ids": self.evidence_ids, "statement": self.statement},
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        expected = f"finding_{sha256_text(payload)[:16]}"
        if self.finding_id is not None and self.finding_id != expected:
            raise ValueError("finding_id does not match its stable identity")
        self.finding_id = expected
        return self


class ResearchSource(StrictModel):
    source_id: str = Field(pattern=r"^S[0-9]{2}$")
    title: str = Field(min_length=1)
    organization: str = Field(min_length=1)
    url: str
    source_type: str = Field(min_length=1)
    source_level: SourceLevel
    local_file: str
    raw_file_hash: str
    retrieved_at: datetime
    evidence_ids: list[str] = Field(default_factory=list)

    @field_validator("url")
    @classmethod
    def normalize_url(cls, value: str) -> str:
        return canonicalize_source_url(value)

    @field_validator("local_file")
    @classmethod
    def normalize_local_file(cls, value: str) -> str:
        return validate_workspace_relative_path(value)

    @field_validator("raw_file_hash")
    @classmethod
    def validate_raw_hash(cls, value: str) -> str:
        if not SHA256_PATTERN.fullmatch(value):
            raise ValueError("raw_file_hash must be a lowercase SHA256 digest")
        return value

    @field_validator("retrieved_at")
    @classmethod
    def validate_retrieved_at(cls, value: datetime) -> datetime:
        return _require_timezone(value)

    @field_validator("evidence_ids")
    @classmethod
    def stable_evidence_ids(cls, values: list[str]) -> list[str]:
        if len(values) != len(set(values)):
            raise ValueError("source evidence_ids must be unique")
        return sorted(values)


class TokenUsage(StrictModel):
    model: str = "none"
    prompt_tokens: int = Field(default=0, ge=0)
    completion_tokens: int = Field(default=0, ge=0)
    total_tokens: int = Field(default=0, ge=0)
    latency_seconds: float = Field(default=0.0, ge=0)

    @model_validator(mode="after")
    def validate_total(self) -> "TokenUsage":
        if self.total_tokens != self.prompt_tokens + self.completion_tokens:
            raise ValueError("total_tokens must equal prompt_tokens + completion_tokens")
        return self


class ResearchSynthesis(StrictModel):
    summary: str = ""
    key_findings: list[ResearchFinding] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)
    unresolved_questions: list[str] = Field(default_factory=list)
    token_usage: TokenUsage = Field(default_factory=TokenUsage)


class ResearchResult(StrictModel):
    run_id: str = Field(pattern=r"^kr_[0-9]{8}T[0-9]{12}Z_[0-9a-f]{8}$")
    profile_id: str
    research_topic: str = Field(min_length=1)
    status: ResearchStatus
    summary: str = ""
    key_findings: list[ResearchFinding] = Field(default_factory=list)
    evidence_ids: list[str] = Field(default_factory=list)
    sources: list[ResearchSource] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)
    unresolved_questions: list[str] = Field(default_factory=list)
    generated_at: datetime

    @field_validator("generated_at")
    @classmethod
    def validate_generated_at(cls, value: datetime) -> datetime:
        return _require_timezone(value)

    @field_validator("summary")
    @classmethod
    def normalize_summary(cls, value: str) -> str:
        return normalize_text(value) if value else ""

    @field_validator("evidence_ids")
    @classmethod
    def stable_evidence_ids(cls, values: list[str]) -> list[str]:
        if len(values) != len(set(values)):
            raise ValueError("ResearchResult evidence_ids must be unique")
        return sorted(values)

    @field_validator("limitations", "unresolved_questions")
    @classmethod
    def normalize_text_lists(cls, values: list[str]) -> list[str]:
        normalized = [normalize_text(value) for value in values]
        if any(not value for value in normalized):
            raise ValueError("text list values cannot be blank")
        return normalized

    @model_validator(mode="after")
    def enforce_grounded_findings(self) -> "ResearchResult":
        known_ids = set(self.evidence_ids)
        source_evidence_ids = {
            evidence_id for source in self.sources for evidence_id in source.evidence_ids
        }
        if not source_evidence_ids.issubset(known_ids):
            raise ValueError("ResearchSource references unknown Evidence")
        for finding in self.key_findings:
            if not set(finding.evidence_ids).issubset(known_ids):
                raise ValueError("ResearchFinding references unknown Evidence")
        if not known_ids and self.key_findings:
            raise ValueError("ResearchResult without Evidence cannot contain findings")
        if self.status is ResearchStatus.INSUFFICIENT_EVIDENCE and self.key_findings:
            raise ValueError("insufficient Evidence result cannot contain findings")
        return self


class ResearchRunMetrics(StrictModel):
    search_count: int = Field(default=0, ge=0)
    selected_source_count: int = Field(default=0, ge=0)
    download_success: int = Field(default=0, ge=0)
    download_failure: int = Field(default=0, ge=0)
    evidence_count: int = Field(default=0, ge=0)
    source_level_distribution: dict[str, int] = Field(default_factory=dict)
    duration_seconds: float = Field(default=0.0, ge=0)
    llm: TokenUsage = Field(default_factory=TokenUsage)


class OutputArtifact(StrictModel):
    adapter: str
    status: str
    path: str | None = None
    details: dict[str, Any] = Field(default_factory=dict)

    @field_validator("path")
    @classmethod
    def normalize_path(cls, value: str | None) -> str | None:
        return validate_workspace_relative_path(value) if value is not None else None


class ResearchRunOutcome(StrictModel):
    result: ResearchResult
    metrics: ResearchRunMetrics
    failures: list[ResearchFailure] = Field(default_factory=list)
    outputs: list[OutputArtifact] = Field(default_factory=list)
    phases: list[ResearchPhase] = Field(default_factory=list)


class RagImportIssue(StrictModel):
    code: str
    message: str


class RagImportResult(StrictModel):
    accepted: bool
    candidate_id: str | None = None
    document_id: str | None = None
    issues: list[RagImportIssue] = Field(default_factory=list)
    ingestion_performed: bool = False
