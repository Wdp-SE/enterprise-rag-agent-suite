"""Stable cross-organization domain models for engineering change analysis."""

from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


def normalize_text(value: str) -> str:
    return re.sub(r"\s+", " ", unicodedata.normalize("NFKC", value)).strip()


def content_hash(value: str) -> str:
    return hashlib.sha256(normalize_text(value).encode("utf-8")).hexdigest()


class EngineeringItemType(str, Enum):
    REQUIREMENT = "REQUIREMENT"
    DESIGN = "DESIGN"
    API = "API"
    TEST_CASE = "TEST_CASE"
    RUNBOOK = "RUNBOOK"


class OrganizationProfile(BaseModel):
    """The only V4 boundary allowed to describe organization-specific syntax."""

    model_config = ConfigDict(extra="forbid")

    organization_id: str = Field(min_length=1)
    identifier_patterns: dict[EngineeringItemType, list[str]]
    document_type_mapping: dict[str, EngineeringItemType]
    section_aliases: dict[str, str] = Field(default_factory=dict)
    version_status_mapping: dict[str, str]

    @field_validator("organization_id")
    @classmethod
    def normalize_organization(cls, value: str) -> str:
        normalized = normalize_text(value)
        if not normalized:
            raise ValueError("organization_id cannot be blank")
        return normalized

    @model_validator(mode="after")
    def validate_configuration(self) -> "OrganizationProfile":
        if not self.identifier_patterns:
            raise ValueError("identifier_patterns cannot be empty")
        for patterns in self.identifier_patterns.values():
            if not patterns:
                raise ValueError("identifier pattern list cannot be empty")
            for pattern in patterns:
                try:
                    re.compile(pattern)
                except re.error as exc:
                    raise ValueError(f"invalid identifier pattern: {pattern}") from exc
        allowed = {"ACTIVE", "SUPERSEDED"}
        if not self.version_status_mapping or set(self.version_status_mapping.values()) - allowed:
            raise ValueError("version status mapping must use ACTIVE or SUPERSEDED")
        return self

    def document_type(self, source_name: str) -> EngineeringItemType:
        try:
            return self.document_type_mapping[normalize_text(source_name)]
        except KeyError as exc:
            raise ValueError(f"unmapped document type: {source_name}") from exc

    def canonical_section(self, source_name: str) -> str:
        normalized = normalize_text(source_name)
        return self.section_aliases.get(normalized, normalized)

    def version_status(self, source_name: str) -> str:
        try:
            return self.version_status_mapping[normalize_text(source_name)]
        except KeyError as exc:
            raise ValueError(f"unmapped version status: {source_name}") from exc


class ParsedEngineeringSection(BaseModel):
    model_config = ConfigDict(extra="forbid")

    section_id: str = Field(min_length=1)
    section_path: list[str] = Field(min_length=1)
    content: str = Field(min_length=1)
    metadata: dict[str, Any] = Field(default_factory=dict)


class IdentifierMatch(BaseModel):
    model_config = ConfigDict(extra="forbid")

    external_identifier: str
    item_type: EngineeringItemType
    start: int = Field(ge=0)
    end: int = Field(gt=0)


class EngineeringItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    item_id: str
    item_type: EngineeringItemType
    organization_id: str
    project_id: str
    document_id: str
    version_id: str
    section_id: str
    external_identifier: str
    title: str
    content: str
    content_hash: str
    metadata: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_hash(self) -> "EngineeringItem":
        expected = content_hash(self.content)
        if self.content_hash != expected:
            raise ValueError("EngineeringItem content_hash mismatch")
        return self

    @staticmethod
    def stable_id(parts: dict[str, str]) -> str:
        canonical = json.dumps(parts, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        return f"item_{hashlib.sha256(canonical.encode('utf-8')).hexdigest()[:20]}"

