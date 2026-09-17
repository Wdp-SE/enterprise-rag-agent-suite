"""Strict JSON models written into a Candidate Package."""

from __future__ import annotations

from datetime import date, datetime
from typing import Literal

from pydantic import Field, field_validator

from app.research.models import SourceLevel, StrictModel


class CandidateReviewMetadata(StrictModel):
    status: Literal["CANDIDATE"] = "CANDIDATE"
    generated_by: Literal["openmanus-agent"] = "openmanus-agent"
    requires_review: Literal[True] = True
    created_at: datetime

    @field_validator("created_at")
    @classmethod
    def require_timezone(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("candidate.created_at must include a timezone")
        return value


class CandidateDocumentMetadata(StrictModel):
    document_id: str = Field(pattern=r"^doc_[a-z0-9-]+_[0-9a-f]{16}$")
    title: str = Field(min_length=1)
    document_type: str = Field(min_length=1)
    source: str = Field(min_length=1)
    source_url: str = Field(min_length=1)
    category: str = Field(min_length=1)
    tags: list[str] = Field(default_factory=list)
    legacy_company_name: None = None
    candidate: CandidateReviewMetadata


class CandidateSource(StrictModel):
    source_id: str = Field(pattern=r"^S[0-9]{2}$")
    evidence_id: str = Field(pattern=r"^ev_[0-9a-f]{20}$")
    title: str = Field(min_length=1)
    organization: str = Field(min_length=1)
    url: str = Field(min_length=1)
    source_type: str = Field(min_length=1)
    document_number: str | None = None
    publish_date: date | None = None
    effective_date: date | None = None
    source_level: SourceLevel
    retrieved_at: datetime
    local_file: str = Field(pattern=r"^raw_sources/[0-9a-f]{64}\.(pdf|html|txt)$")
    content_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    raw_file_hash: str = Field(pattern=r"^[0-9a-f]{64}$")

    @field_validator("retrieved_at")
    @classmethod
    def require_timezone(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("retrieved_at must include a timezone")
        return value
