"""Atomic local persistence for document-workflow Evidence."""

from __future__ import annotations

import json
import os
import tempfile
from enum import Enum
from pathlib import Path

from pydantic import ValidationError

from .evidence_models import Evidence


class EvidenceStoreError(ValueError):
    pass


class EvidenceAddStatus(str, Enum):
    ADDED = "ADDED"
    DUPLICATE = "DUPLICATE"


class EvidenceStore:
    FORMAT_VERSION = 1

    def __init__(self, workspace_root: str | Path, store_path: str | Path):
        self.workspace_root = Path(workspace_root).resolve()
        requested = Path(store_path)
        self.store_path = requested.resolve() if requested.is_absolute() else (self.workspace_root / requested).resolve()
        if not self.store_path.is_relative_to(self.workspace_root):
            raise EvidenceStoreError("EvidenceStore path must remain inside workspace_root")
        self._evidence: dict[str, Evidence] = {}
        self._dedup_index: dict[tuple[str, str], str] = {}

    def _validate_scope(self, evidence: Evidence) -> None:
        if evidence.local_file is not None:
            local_path = (self.workspace_root / evidence.local_file).resolve(strict=False)
            if not local_path.is_relative_to(self.workspace_root):
                raise EvidenceStoreError("Evidence local_file escapes workspace_root")

    @staticmethod
    def _key(evidence: Evidence) -> tuple[str, str]:
        assert evidence.content_hash is not None
        identity = evidence.canonical_source_identity()
        if evidence.chunk_id is not None:
            identity = f"{identity}|{evidence.chunk_id}"
        return identity, evidence.content_hash

    def add(self, evidence: Evidence) -> EvidenceAddStatus:
        self._validate_scope(evidence)
        assert evidence.evidence_id is not None
        key = self._key(evidence)
        if evidence.evidence_id in self._evidence or key in self._dedup_index:
            return EvidenceAddStatus.DUPLICATE
        self._evidence[evidence.evidence_id] = evidence
        self._dedup_index[key] = evidence.evidence_id
        return EvidenceAddStatus.ADDED

    def get(self, evidence_id: str) -> Evidence | None:
        return self._evidence.get(evidence_id)

    def list(self) -> list[Evidence]:
        return [self._evidence[key] for key in sorted(self._evidence)]

    def __len__(self) -> int:
        return len(self._evidence)

    def save(self) -> None:
        self.store_path.parent.mkdir(parents=True, exist_ok=True)
        payload = {"format_version": self.FORMAT_VERSION, "evidence": [item.model_dump(mode="json") for item in self.list()]}
        temporary: Path | None = None
        try:
            with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=self.store_path.parent, prefix=f".{self.store_path.name}.", suffix=".tmp", delete=False) as handle:
                temporary = Path(handle.name)
                json.dump(payload, handle, ensure_ascii=False, indent=2, sort_keys=True)
                handle.write("\n")
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, self.store_path)
        finally:
            if temporary is not None and temporary.exists():
                temporary.unlink()

    def load(self) -> "EvidenceStore":
        try:
            payload = json.loads(self.store_path.read_text(encoding="utf-8"))
            if payload.get("format_version") != self.FORMAT_VERSION or not isinstance(payload.get("evidence"), list):
                raise EvidenceStoreError("unsupported or malformed EvidenceStore")
            self._evidence.clear()
            self._dedup_index.clear()
            for record in payload["evidence"]:
                if self.add(Evidence.model_validate(record)) is EvidenceAddStatus.DUPLICATE:
                    raise EvidenceStoreError("persisted EvidenceStore contains duplicates")
            return self
        except (OSError, json.JSONDecodeError, ValidationError, AttributeError) as exc:
            raise EvidenceStoreError(f"invalid EvidenceStore {self.store_path}: {exc}") from exc
