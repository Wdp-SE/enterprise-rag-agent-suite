"""Immutable business retrieval scope for one workflow."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Iterable


def _normalized(values: Iterable[str]) -> tuple[str, ...]:
    result = tuple(sorted({str(value).strip() for value in values if str(value).strip()}))
    return result


@dataclass(frozen=True)
class WorkflowScope:
    project_ids: tuple[str, ...] = ()
    document_ids: tuple[str, ...] = ()
    document_types: tuple[str, ...] = ()
    version_ids: tuple[str, ...] = ()
    active_only: bool = True

    def __post_init__(self) -> None:
        for name in ("project_ids", "document_ids", "document_types", "version_ids"):
            object.__setattr__(self, name, _normalized(getattr(self, name)))
        if self.version_ids and self.active_only:
            raise ValueError("explicit version scope requires active_only=false")

    @classmethod
    def from_dict(cls, payload: dict | None) -> "WorkflowScope":
        data = payload or {}
        allowed = {"project_ids", "document_ids", "document_types", "version_ids", "active_only"}
        if set(data) - allowed:
            raise ValueError("unknown workflow scope field")
        return cls(
            project_ids=tuple(data.get("project_ids") or ()),
            document_ids=tuple(data.get("document_ids") or ()),
            document_types=tuple(data.get("document_types") or ()),
            version_ids=tuple(data.get("version_ids") or ()),
            active_only=bool(data.get("active_only", True)),
        )

    def to_dict(self) -> dict:
        payload: dict[str, object] = {"active_only": self.active_only}
        for name in ("project_ids", "document_ids", "document_types", "version_ids"):
            values = list(getattr(self, name))
            if values:
                payload[name] = values
        return payload

    def fingerprint(self) -> str:
        canonical = json.dumps(self.to_dict(), ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()
