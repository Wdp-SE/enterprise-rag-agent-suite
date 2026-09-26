"""Evidence contracts owned by the document workflow domain."""

from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from datetime import datetime
from enum import Enum
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")


def normalize_text(value: str) -> str:
    return re.sub(r"\s+", " ", unicodedata.normalize("NFKC", value)).strip()


def sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _canonicalize_url(value: str) -> str:
    parsed = urlsplit(value.strip())
    if parsed.scheme.lower() not in {"http", "https"} or not parsed.hostname:
        raise ValueError("source_url must be an absolute HTTP(S) URL")
    scheme = parsed.scheme.lower()
    hostname = parsed.hostname.lower()
    if parsed.port and not ((scheme == "http" and parsed.port == 80) or (scheme == "https" and parsed.port == 443)):
        hostname = f"{hostname}:{parsed.port}"
    path = parsed.path or "/"
    if path != "/":
        path = path.rstrip("/")
    query = urlencode(sorted(parse_qsl(parsed.query, keep_blank_values=True)))
    return urlunsplit((scheme, hostname, path, query, ""))


def _workspace_path(value: str) -> str:
    normalized = value.replace("\\", "/").strip()
    candidate = Path(normalized)
    if not normalized or normalized.startswith("/") or candidate.is_absolute() or candidate.drive or ".." in candidate.parts:
        raise ValueError("local_file must be a workspace-relative path")
    return candidate.as_posix()


class SourceLevel(str, Enum):
    TIER1 = "TIER1"
    TIER2 = "TIER2"
    TIER3 = "TIER3"


class Evidence(BaseModel):
    """Version-aware evidence accepted by drafting and finalization."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    evidence_id: str | None = None
    title: str = Field(min_length=1)
    content: str = Field(min_length=1)
    organization: str = Field(min_length=1)
    source_url: str | None = None
    source_type: str = Field(min_length=1)
    document_number: str | None = None
    document_id: str | None = None
    project_id: str | None = None
    document_type: str | None = None
    version_id: str | None = None
    version_label: str | None = None
    version_status: str | None = None
    freshness: str | None = None
    chunk_id: str | None = None
    query: str | None = None
    section_path: list[str] | None = None
    retrieved_at: datetime
    local_file: str | None = None
    page_number: int | None = Field(default=None, ge=1)
    section: str | None = None
    source_level: SourceLevel = SourceLevel.TIER3
    content_hash: str | None = None
    similarity: float | None = None

    @field_validator(
        "title", "content", "organization", "source_type", "document_number",
        "document_id", "project_id", "document_type", "version_id", "version_label",
        "version_status", "freshness", "chunk_id", "query", "section",
    )
    @classmethod
    def normalize_fields(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = normalize_text(value)
        if not normalized:
            raise ValueError("text fields cannot be blank")
        return normalized

    @field_validator("source_url")
    @classmethod
    def normalize_url(cls, value: str | None) -> str | None:
        return _canonicalize_url(value) if value is not None else None

    @field_validator("retrieved_at")
    @classmethod
    def timezone_required(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("retrieved_at must include a timezone")
        return value

    @field_validator("local_file")
    @classmethod
    def normalize_local_file(cls, value: str | None) -> str | None:
        return _workspace_path(value) if value is not None else None

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
        payload: dict[str, object] = {
            "content_hash": content_hash or self.expected_content_hash(),
            "page_number": self.page_number,
            "section": normalize_text(self.section or ""),
            "source_identity": self.canonical_source_identity(),
        }
        if self.chunk_id is not None:
            payload["chunk_id"] = self.chunk_id
        if self.version_id is not None:
            payload["version_id"] = self.version_id
        canonical = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        return f"ev_{sha256_text(canonical)[:20]}"

    @model_validator(mode="after")
    def stable_identity(self) -> "Evidence":
        expected_hash = self.expected_content_hash()
        if self.content_hash is not None:
            if not SHA256_PATTERN.fullmatch(self.content_hash) or self.content_hash != expected_hash:
                raise ValueError("content_hash does not match normalized Evidence content")
        self.content_hash = expected_hash
        expected_id = self.expected_evidence_id(expected_hash)
        if self.evidence_id is not None and self.evidence_id != expected_id:
            raise ValueError("evidence_id does not match the stable Evidence identity")
        self.evidence_id = expected_id
        return self
