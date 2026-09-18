"""Strict data contracts shared by the offline knowledge-research core."""

from __future__ import annotations

import re
import hashlib
import json
import unicodedata
from datetime import date, datetime
from enum import Enum
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


NON_EMPTY_TEXT = re.compile(r"\S")
SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")


def normalize_text(value: str) -> str:
    """Normalize text before identity or content hashing."""

    normalized = unicodedata.normalize("NFKC", value)
    return re.sub(r"\s+", " ", normalized).strip()


def sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def canonicalize_source_url(value: str) -> str:
    """Return a stable HTTP(S) source identity without fragments."""

    parsed = urlsplit(value.strip())
    if parsed.scheme.lower() not in {"http", "https"} or not parsed.hostname:
        raise ValueError("source_url must be an absolute HTTP(S) URL")
    scheme = parsed.scheme.lower()
    hostname = parsed.hostname.lower()
    port = parsed.port
    if port and not ((scheme == "http" and port == 80) or (scheme == "https" and port == 443)):
        hostname = f"{hostname}:{port}"
    path = parsed.path or "/"
    if path != "/":
        path = path.rstrip("/")
    query = urlencode(sorted(parse_qsl(parsed.query, keep_blank_values=True)))
    return urlunsplit((scheme, hostname, path, query, ""))


def validate_workspace_relative_path(value: str) -> str:
    normalized = value.replace("\\", "/").strip()
    candidate = Path(normalized)
    if not normalized or normalized.startswith("/") or candidate.is_absolute() or candidate.drive:
        raise ValueError("local_file must be a workspace-relative path")
    if ".." in candidate.parts:
        raise ValueError("local_file cannot contain parent traversal")
    return candidate.as_posix()


class StrictModel(BaseModel):
    """Base model that rejects undeclared contract fields."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class OutputRequirements(StrictModel):
    """Candidate output constraints supplied by a research profile."""

    document_type: str = Field(min_length=1)
    tags: list[str] = Field(default_factory=list)
    minimum_evidence_count: int = Field(default=1, ge=1)
    required_sections: list[str] = Field(min_length=1)

    @field_validator("tags", "required_sections")
    @classmethod
    def validate_non_empty_items(cls, values: list[str]) -> list[str]:
        if any(not NON_EMPTY_TEXT.search(value) for value in values):
            raise ValueError("list items must contain non-whitespace text")
        if len(values) != len(set(values)):
            raise ValueError("list items must be unique")
        return values


class ResearchProfile(StrictModel):
    """Configuration-only description of a domain research task."""

    profile_id: str = Field(pattern=r"^[a-z0-9][a-z0-9_-]{2,63}$")
    domain: str = Field(pattern=r"^[a-z0-9][a-z0-9_-]{2,63}$")
    research_topic: str = Field(min_length=1)
    research_questions: list[str] = Field(min_length=1)
    preferred_source_types: list[str] = Field(min_length=1)
    knowledge_category: str = Field(min_length=1)
    max_sources: int = Field(default=3, ge=1, le=20)
    output_requirements: OutputRequirements

    @field_validator("research_questions", "preferred_source_types")
    @classmethod
    def validate_non_empty_unique_items(cls, values: list[str]) -> list[str]:
        if any(not NON_EMPTY_TEXT.search(value) for value in values):
            raise ValueError("list items must contain non-whitespace text")
        if len(values) != len(set(values)):
            raise ValueError("list items must be unique")
        return values

    @model_validator(mode="after")
    def validate_evidence_limits(self) -> "ResearchProfile":
        if self.output_requirements.minimum_evidence_count > self.max_sources:
            raise ValueError("minimum_evidence_count cannot exceed max_sources")
        return self


class SourceLevel(str, Enum):
    TIER1 = "TIER1"
    TIER2 = "TIER2"
    TIER3 = "TIER3"


class Evidence(StrictModel):
    """A traceable fact unit and the only factual input accepted by drafting."""

    evidence_id: str | None = None
    title: str = Field(min_length=1)
    content: str = Field(min_length=1)
    organization: str = Field(min_length=1)
    source_url: str | None = None
    source_type: str = Field(min_length=1)
    document_number: str | None = None
    document_id: str | None = None
    version_id: str | None = None
    version_status: str | None = None
    freshness: str | None = None
    chunk_id: str | None = None
    query: str | None = None
    section_path: list[str] | None = None
    publish_date: date | None = None
    effective_date: date | None = None
    retrieved_at: datetime
    local_file: str | None = None
    page_number: int | None = Field(default=None, ge=1)
    section: str | None = None
    source_level: SourceLevel
    content_hash: str | None = None

    @field_validator("title", "content", "organization", "source_type", "document_number", "document_id", "version_id", "version_status", "freshness", "chunk_id", "query", "section")
    @classmethod
    def normalize_text_fields(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = normalize_text(value)
        if not normalized:
            raise ValueError("text fields cannot be blank")
        return normalized

    @field_validator("source_url")
    @classmethod
    def normalize_source_url(cls, value: str | None) -> str | None:
        return canonicalize_source_url(value) if value is not None else None

    @field_validator("retrieved_at")
    @classmethod
    def require_timezone(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("retrieved_at must include a timezone")
        return value

    @field_validator("local_file")
    @classmethod
    def normalize_local_file(cls, value: str | None) -> str | None:
        return validate_workspace_relative_path(value) if value is not None else None

    def canonical_source_identity(self) -> str:
        if self.source_url:
            return self.source_url
        fallback = "|".join(
            normalize_text(value).casefold()
            for value in (self.organization, self.document_number or "", self.title)
        )
        return f"metadata:{fallback}"

    def expected_content_hash(self) -> str:
        return sha256_text(normalize_text(self.content))

    def expected_evidence_id(self, content_hash: str | None = None) -> str:
        payload = {
            "content_hash": content_hash or self.expected_content_hash(),
            "page_number": self.page_number,
            "section": normalize_text(self.section or ""),
            "source_identity": self.canonical_source_identity(),
        }
        if self.chunk_id is not None:
            payload["chunk_id"] = self.chunk_id
        if self.version_id is not None:
            payload["version_id"] = self.version_id
        canonical = json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        return f"ev_{sha256_text(canonical)[:20]}"

    @model_validator(mode="after")
    def validate_stable_hashes_and_id(self) -> "Evidence":
        expected_hash = self.expected_content_hash()
        if self.content_hash is not None:
            if not SHA256_PATTERN.fullmatch(self.content_hash):
                raise ValueError("content_hash must be a lowercase SHA256 digest")
            if self.content_hash != expected_hash:
                raise ValueError("content_hash does not match normalized Evidence content")
        self.content_hash = expected_hash

        expected_id = self.expected_evidence_id(expected_hash)
        if self.evidence_id is not None and self.evidence_id != expected_id:
            raise ValueError("evidence_id does not match the stable Evidence identity")
        self.evidence_id = expected_id
        return self
