import hashlib
import json
import re
from pathlib import Path
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field, field_validator


_DOCUMENT_ID_PATTERN = re.compile(r"^[A-Za-z0-9._:-]+$")


def stable_document_id(
    *,
    document_id: Optional[str] = None,
    sha1_name: Optional[str] = None,
    source_identifier: Optional[str] = None,
) -> str:
    """Return a stable identifier without deriving identity from a display title."""
    explicit_id = (document_id or sha1_name or "").strip()
    if explicit_id:
        return explicit_id

    source = (source_identifier or "").strip()
    if not source:
        raise ValueError(
            "document_id requires an explicit id, sha1_name, or stable source identifier"
        )

    canonical_source = Path(source).name.casefold()
    return hashlib.sha1(canonical_source.encode("utf-8")).hexdigest()


def parse_tags(value: Any) -> List[str]:
    if value is None or value == "":
        return []
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    if isinstance(value, str):
        stripped = value.strip()
        if not stripped:
            return []
        if stripped.startswith("["):
            try:
                parsed = json.loads(stripped)
            except json.JSONDecodeError:
                parsed = None
            if isinstance(parsed, list):
                return [str(item).strip() for item in parsed if str(item).strip()]
        return [item.strip() for item in re.split(r"[,;]", stripped) if item.strip()]
    return [str(value).strip()]


class DocumentMetadata(BaseModel):
    document_id: str
    title: str
    document_type: str = "document"
    source: str
    source_url: Optional[str] = None
    category: Optional[str] = None
    tags: List[str] = Field(default_factory=list)
    legacy_company_name: Optional[str] = None

    @field_validator("document_id")
    @classmethod
    def validate_document_id(cls, value: str) -> str:
        value = value.strip()
        if not value or not _DOCUMENT_ID_PATTERN.fullmatch(value):
            raise ValueError(
                "document_id must be non-empty and contain only letters, numbers, '.', '_', ':', or '-'"
            )
        return value


def normalize_document_metadata(
    metainfo: Optional[Dict[str, Any]],
    *,
    source_identifier: Optional[str] = None,
) -> Dict[str, Any]:
    """Add the generic metadata model while retaining legacy metadata keys."""
    original = dict(metainfo or {})
    source = str(original.get("source") or source_identifier or "").strip()
    document_id = stable_document_id(
        document_id=original.get("document_id"),
        sha1_name=original.get("sha1_name"),
        source_identifier=source,
    )
    legacy_company_name = (
        original.get("legacy_company_name") or original.get("company_name") or None
    )
    title = str(
        original.get("title")
        or legacy_company_name
        or (Path(source).stem if source else document_id)
    ).strip()

    metadata = DocumentMetadata(
        document_id=document_id,
        title=title,
        document_type=str(original.get("document_type") or "document").strip(),
        source=source or document_id,
        source_url=original.get("source_url") or None,
        category=original.get("category") or None,
        tags=parse_tags(original.get("tags")),
        legacy_company_name=legacy_company_name,
    )

    normalized = original
    normalized.update(metadata.model_dump())
    if legacy_company_name and not normalized.get("company_name"):
        normalized["company_name"] = legacy_company_name
    return normalized
