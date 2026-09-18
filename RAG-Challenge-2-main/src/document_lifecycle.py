"""Version-aware document lifecycle primitives for the R&D RAG V3 layer.

The frozen V2 retrieval representation remains unchanged.  This module adds
business metadata, scope validation, deterministic section diffs, and a small
local incremental store that can reuse persisted embeddings.  Scope filtering
is deliberately performed before ranking.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
import time
import unicodedata
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Mapping, Protocol, Sequence

import numpy as np
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
CATALOG_SCHEMA_VERSION = "rd-document-catalog-v3"
STORE_SCHEMA_VERSION = "rd-version-store-v3"


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _normalize_text(value: str) -> str:
    return re.sub(r"\s+", " ", unicodedata.normalize("NFKC", value)).strip()


def _content_hash(value: str) -> str:
    return hashlib.sha256(_normalize_text(value).encode("utf-8")).hexdigest()


def _canonical_hash(value: Mapping[str, Any]) -> str:
    return hashlib.sha256(
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")
    ).hexdigest()


def _atomic_json(path: Path, value: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            "w", encoding="utf-8", dir=path.parent, prefix=f".{path.name}.", suffix=".tmp", delete=False
        ) as handle:
            temporary = Path(handle.name)
            json.dump(value, handle, ensure_ascii=False, sort_keys=True, indent=2, default=str)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        if temporary is not None and temporary.exists():
            temporary.unlink()


class VersionStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUPERSEDED = "SUPERSEDED"


class ChangeType(str, Enum):
    ADDED = "ADDED"
    REMOVED = "REMOVED"
    MODIFIED = "MODIFIED"
    UNCHANGED = "UNCHANGED"


class RetrievalScope(BaseModel):
    """One validated scope shared by /retrieve and /query."""

    model_config = ConfigDict(extra="forbid")

    project_ids: list[str] = Field(default_factory=list)
    document_ids: list[str] = Field(default_factory=list)
    document_types: list[str] = Field(default_factory=list)
    version_ids: list[str] = Field(default_factory=list)
    active_only: bool = True

    @field_validator("project_ids", "document_ids", "document_types", "version_ids")
    @classmethod
    def normalize_values(cls, values: list[str]) -> list[str]:
        normalized = [_normalize_text(value) for value in values]
        if any(not value for value in normalized):
            raise ValueError("scope values cannot be blank")
        if len(normalized) != len(set(normalized)):
            raise ValueError("scope values must be unique")
        return normalized

    @model_validator(mode="after")
    def reject_history_conflict(self) -> "RetrievalScope":
        if self.version_ids and self.active_only:
            raise ValueError("explicit version_ids require active_only=false")
        return self


class Document(BaseModel):
    model_config = ConfigDict(extra="forbid")

    document_id: str = Field(min_length=1)
    project_id: str = Field(min_length=1)
    document_type: str = Field(min_length=1)
    title: str = Field(min_length=1)
    created_at: datetime = Field(default_factory=_now)


class DocumentVersion(BaseModel):
    model_config = ConfigDict(extra="forbid")

    version_id: str = Field(min_length=1)
    document_id: str = Field(min_length=1)
    version_label: str = Field(min_length=1)
    status: VersionStatus
    source_hash: str
    created_at: datetime = Field(default_factory=_now)
    activated_at: datetime | None = None
    superseded_at: datetime | None = None
    previous_version_id: str | None = None
    source_path: str | None = None
    source_name: str | None = None
    source_document_id: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("source_hash")
    @classmethod
    def validate_source_hash(cls, value: str) -> str:
        if not SHA256_RE.fullmatch(value):
            raise ValueError("source_hash must be a lowercase SHA256 digest")
        return value


class SectionSnapshot(BaseModel):
    model_config = ConfigDict(extra="forbid")

    section_id: str = Field(min_length=1)
    section_path: list[str] = Field(min_length=1)
    content: str = Field(min_length=1)
    page_start: int = Field(ge=1)
    page_end: int = Field(ge=1)
    content_hash: str | None = None

    @model_validator(mode="after")
    def finalize(self) -> "SectionSnapshot":
        if self.page_end < self.page_start:
            raise ValueError("page_end must be >= page_start")
        self.section_path = [_normalize_text(item) for item in self.section_path]
        if any(not item for item in self.section_path):
            raise ValueError("section_path values cannot be blank")
        expected = _content_hash(self.content)
        if self.content_hash is not None and self.content_hash != expected:
            raise ValueError("section content_hash mismatch")
        self.content_hash = expected
        return self

    @property
    def identity(self) -> str:
        return " / ".join(part.casefold() for part in self.section_path)


class SectionDiff(BaseModel):
    model_config = ConfigDict(extra="forbid")

    section_path: list[str]
    change_type: ChangeType
    old_section_id: str | None = None
    new_section_id: str | None = None
    old_page_range: list[int] | None = None
    new_page_range: list[int] | None = None
    old_content_hash: str | None = None
    new_content_hash: str | None = None


class DocumentVersionDiff(BaseModel):
    model_config = ConfigDict(extra="forbid")

    document_id: str
    from_version: str
    to_version: str
    summary: dict[str, int]
    sections: list[SectionDiff]


def compare_section_versions(
    document_id: str,
    from_version: str,
    to_version: str,
    old_sections: Sequence[SectionSnapshot],
    new_sections: Sequence[SectionSnapshot],
) -> DocumentVersionDiff:
    """Deterministic path-aligned section diff; no model call is involved."""

    old_by_key = {section.identity: section for section in old_sections}
    new_by_key = {section.identity: section for section in new_sections}
    if len(old_by_key) != len(old_sections) or len(new_by_key) != len(new_sections):
        raise ValueError("section paths must be unique inside a version")
    rows: list[SectionDiff] = []
    counts = {change.value: 0 for change in ChangeType}
    for key in sorted(set(old_by_key) | set(new_by_key)):
        old = old_by_key.get(key)
        new = new_by_key.get(key)
        if old is None:
            change = ChangeType.ADDED
        elif new is None:
            change = ChangeType.REMOVED
        elif old.content_hash == new.content_hash:
            change = ChangeType.UNCHANGED
        else:
            change = ChangeType.MODIFIED
        counts[change.value] += 1
        representative = new or old
        assert representative is not None
        rows.append(
            SectionDiff(
                section_path=representative.section_path,
                change_type=change,
                old_section_id=old.section_id if old else None,
                new_section_id=new.section_id if new else None,
                old_page_range=[old.page_start, old.page_end] if old else None,
                new_page_range=[new.page_start, new.page_end] if new else None,
                old_content_hash=old.content_hash if old else None,
                new_content_hash=new.content_hash if new else None,
            )
        )
    return DocumentVersionDiff(
        document_id=document_id,
        from_version=from_version,
        to_version=to_version,
        summary=counts,
        sections=rows,
    )


class DocumentCatalog:
    """Validated in-memory catalog used by the frozen runtime and V3 store."""

    def __init__(
        self,
        documents: Sequence[Document],
        versions: Sequence[DocumentVersion],
        *,
        sections_by_version: Mapping[str, Sequence[SectionSnapshot]] | None = None,
    ):
        self.documents = list(documents)
        self.versions = list(versions)
        self.sections_by_version = {
            key: list(value) for key, value in (sections_by_version or {}).items()
        }
        self.by_document = {item.document_id: item for item in self.documents}
        self.by_version = {item.version_id: item for item in self.versions}
        self.validate()

    def validate(self) -> None:
        if len(self.by_document) != len(self.documents):
            raise ValueError("duplicate document_id")
        if len(self.by_version) != len(self.versions):
            raise ValueError("duplicate version_id")
        active_counts: dict[str, int] = {}
        for version in self.versions:
            if version.document_id not in self.by_document:
                raise ValueError("version references unknown document")
            if version.previous_version_id and version.previous_version_id not in self.by_version:
                raise ValueError("previous_version_id references unknown version")
            if version.status == VersionStatus.ACTIVE:
                active_counts[version.document_id] = active_counts.get(version.document_id, 0) + 1
        if any(count > 1 for count in active_counts.values()):
            raise ValueError("a document may have at most one ACTIVE version")
        if any(version_id not in self.by_version for version_id in self.sections_by_version):
            raise ValueError("sections reference unknown version")

    @classmethod
    def from_payload(cls, payload: Mapping[str, Any]) -> "DocumentCatalog":
        if payload.get("schema_version") != CATALOG_SCHEMA_VERSION:
            raise ValueError("catalog schema version mismatch")
        claimed = payload.get("catalog_sha256")
        if claimed:
            digest_payload = dict(payload)
            digest_payload.pop("catalog_sha256", None)
            if claimed != _canonical_hash(digest_payload):
                raise ValueError("version catalog hash mismatch")
        sections = {
            key: [SectionSnapshot.model_validate(item) for item in values]
            for key, values in dict(payload.get("sections_by_version", {})).items()
        }
        return cls(
            [Document.model_validate(item) for item in payload.get("documents", [])],
            [DocumentVersion.model_validate(item) for item in payload.get("versions", [])],
            sections_by_version=sections,
        )

    def payload(self, *, include_sections: bool = True) -> dict[str, Any]:
        value: dict[str, Any] = {
            "schema_version": CATALOG_SCHEMA_VERSION,
            "documents": [item.model_dump(mode="json") for item in self.documents],
            "versions": [item.model_dump(mode="json") for item in self.versions],
        }
        if include_sections:
            value["sections_by_version"] = {
                key: [item.model_dump(mode="json") for item in rows]
                for key, rows in sorted(self.sections_by_version.items())
            }
        value["catalog_sha256"] = _canonical_hash(value)
        return value

    @classmethod
    def from_legacy(
        cls,
        corpus_documents: Sequence[Mapping[str, Any]],
        chunks: Sequence[Mapping[str, Any]],
        metadata_documents: Sequence[Mapping[str, Any]] | None = None,
    ) -> "DocumentCatalog":
        metadata = {
            str(item.get("document_id")): item for item in (metadata_documents or [])
            if item.get("document_id")
        }
        corpus = {str(item.get("document_id")): item for item in corpus_documents if item.get("document_id")}
        document_ids = sorted(corpus or {str(item["document_id"]): {} for item in chunks})
        documents: list[Document] = []
        versions: list[DocumentVersion] = []
        for document_id in document_ids:
            row = corpus.get(document_id, {})
            display = metadata.get(document_id, {})
            source_name = str(display.get("source_file_name") or row.get("source_name") or document_id)
            documents.append(
                Document(
                    document_id=document_id,
                    project_id=str(display.get("project_id") or "rd-v2"),
                    document_type=str(display.get("document_type") or "document"),
                    title=str(display.get("title") or source_name),
                )
            )
            source_hash = str(row.get("source_sha256") or hashlib.sha256(document_id.encode()).hexdigest())
            versions.append(
                DocumentVersion(
                    version_id=f"{document_id}:v1",
                    document_id=document_id,
                    version_label=str(display.get("version_label") or "V1.0"),
                    status=VersionStatus.ACTIVE,
                    source_hash=source_hash,
                    activated_at=_now(),
                    source_name=source_name,
                    source_document_id=document_id,
                    metadata={"legacy_v2_compatibility_mapping": True},
                )
            )
        return cls(documents, versions)

    def active_version(self, document_id: str) -> DocumentVersion | None:
        return next(
            (item for item in self.versions if item.document_id == document_id and item.status == VersionStatus.ACTIVE),
            None,
        )

    def version_for_chunk(self, chunk: Mapping[str, Any]) -> DocumentVersion | None:
        version_id = chunk.get("version_id")
        if version_id:
            return self.by_version.get(str(version_id))
        physical_id = str(chunk.get("document_id") or "")
        return next(
            (item for item in self.versions if (item.source_document_id or item.document_id) == physical_id),
            None,
        )

    def enrich_chunk(self, chunk: Mapping[str, Any]) -> dict[str, Any]:
        result = dict(chunk)
        version = self.version_for_chunk(result)
        if version is None:
            raise ValueError("chunk version reference is invalid")
        document = self.by_document[version.document_id]
        result.setdefault("physical_document_id", result.get("document_id"))
        result["document_id"] = document.document_id
        result["version_id"] = version.version_id
        result["version_label"] = version.version_label
        result["version_status"] = version.status.value
        result["project_id"] = document.project_id
        result["document_type"] = document.document_type
        result["document_title"] = document.title
        return result

    def matches(self, chunk: Mapping[str, Any], scope: RetrievalScope) -> bool:
        version = self.version_for_chunk(chunk)
        if version is None:
            return False
        document = self.by_document.get(version.document_id)
        if document is None:
            return False
        if scope.active_only and version.status != VersionStatus.ACTIVE:
            return False
        if scope.version_ids and version.version_id not in scope.version_ids:
            return False
        if scope.document_ids and document.document_id not in scope.document_ids:
            return False
        if scope.project_ids and document.project_id not in scope.project_ids:
            return False
        if scope.document_types and document.document_type not in scope.document_types:
            return False
        return True

    def document_rows(self) -> list[dict[str, Any]]:
        rows = []
        for document in sorted(self.documents, key=lambda item: item.document_id):
            versions = [item for item in self.versions if item.document_id == document.document_id]
            active = self.active_version(document.document_id)
            rows.append(
                {
                    **document.model_dump(mode="json"),
                    "active_version": active.model_dump(mode="json") if active else None,
                    "version_count": len(versions),
                    "versions": [item.model_dump(mode="json") for item in sorted(versions, key=lambda row: row.created_at)],
                }
            )
        return rows

    def version_rows(self, document_id: str) -> list[dict[str, Any]]:
        if document_id not in self.by_document:
            raise KeyError(document_id)
        return [
            item.model_dump(mode="json")
            for item in sorted(
                (row for row in self.versions if row.document_id == document_id),
                key=lambda row: row.created_at,
            )
        ]

    def diff(self, document_id: str, from_version_id: str, to_version_id: str) -> DocumentVersionDiff:
        old = self.by_version.get(from_version_id)
        new = self.by_version.get(to_version_id)
        if old is None or new is None or old.document_id != document_id or new.document_id != document_id:
            raise KeyError("version does not belong to document")
        if from_version_id not in self.sections_by_version or to_version_id not in self.sections_by_version:
            raise KeyError("section snapshots unavailable")
        return compare_section_versions(
            document_id,
            from_version_id,
            to_version_id,
            self.sections_by_version[from_version_id],
            self.sections_by_version[to_version_id],
        )


class SectionEmbedder(Protocol):
    def encode(self, texts: Sequence[str]) -> np.ndarray: ...


@dataclass(frozen=True)
class IncrementalBuildReport:
    total_sections: int
    unchanged_sections: int
    modified_sections: int
    added_sections: int
    removed_sections: int
    reused_embeddings: int
    new_embeddings: int
    active_chunks: int
    processing_time: float
    index_refresh_strategy: str = "CACHED_VECTOR_EXACT_MATRIX_REFRESH"


class DuplicateVersionError(ValueError):
    pass


class VersionLifecycleService:
    """Small local version service with catalog-last atomic activation.

    Parsed sections are supplied by the existing parsing pipeline.  Version
    artifacts and cached embeddings are written first; the catalog pointer is
    replaced only after validation, so a failed build leaves the prior ACTIVE
    version available.
    """

    def __init__(self, root: Path | str):
        self.root = Path(root).resolve()
        self.catalog_path = self.root / "catalog.json"
        self.cache_path = self.root / "embedding_cache.json"
        self.root.mkdir(parents=True, exist_ok=True)
        (self.root / "versions").mkdir(exist_ok=True)
        (self.root / "active_indexes").mkdir(exist_ok=True)
        if not self.cache_path.exists():
            _atomic_json(self.cache_path, {"schema_version": STORE_SCHEMA_VERSION, "vectors": {}})
        if not self.catalog_path.exists():
            self._commit_catalog([], [], {}, active_index=None, refresh_version=0)
        self._load_state()

    def _load_state(self) -> None:
        payload = json.loads(self.catalog_path.read_text(encoding="utf-8"))
        if payload.get("schema_version") != STORE_SCHEMA_VERSION or payload.get("status") != "COMPLETE":
            raise ValueError("version store catalog is not COMPLETE")
        claimed = payload.get("manifest_sha256")
        digest_payload = dict(payload)
        digest_payload.pop("manifest_sha256", None)
        if claimed != _canonical_hash(digest_payload):
            raise ValueError("version store manifest hash mismatch")
        cache_record = dict(payload.get("embedding_cache", {}))
        cache_file = (self.root / str(cache_record.get("path", ""))).resolve()
        try:
            cache_file.relative_to(self.root)
        except ValueError as exc:
            raise ValueError("embedding cache path outside store") from exc
        if (not cache_file.is_file()
                or cache_file.stat().st_size != int(cache_record.get("bytes", -1))
                or hashlib.sha256(cache_file.read_bytes()).hexdigest() != cache_record.get("sha256")):
            raise ValueError("embedding cache hash mismatch")
        self.version_artifacts = dict(payload.get("version_artifacts", {}))
        sections: dict[str, list[SectionSnapshot]] = {}
        embedding_dimensions: set[int] = set()
        for version_id, record in self.version_artifacts.items():
            path = self.root / str(record["path"])
            if not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest() != record.get("sha256"):
                raise ValueError("version artifact hash mismatch")
            artifact = json.loads(path.read_text(encoding="utf-8"))
            if artifact.get("version_id") != version_id:
                raise ValueError("version artifact identity mismatch")
            rows = [SectionSnapshot.model_validate(item) for item in artifact.get("sections", [])]
            chunks = artifact.get("chunks", [])
            embeddings = np.asarray(artifact.get("embeddings", []), dtype=np.float32)
            if any(chunk.get("version_id") != version_id for chunk in chunks):
                raise ValueError("chunk version reference invalid")
            if len(rows) != len(chunks) or embeddings.ndim != 2 or len(rows) != embeddings.shape[0]:
                raise ValueError("version artifact count mismatch")
            if len(rows):
                if not np.isfinite(embeddings).all():
                    raise ValueError("version embedding is non-finite")
                if not np.allclose(np.linalg.norm(embeddings, axis=1), 1.0, atol=1e-4):
                    raise ValueError("version embedding is not normalized")
                embedding_dimensions.add(int(embeddings.shape[1]))
            sections[version_id] = rows
        self.catalog = DocumentCatalog(
            [Document.model_validate(item) for item in payload.get("documents", [])],
            [DocumentVersion.model_validate(item) for item in payload.get("versions", [])],
            sections_by_version=sections,
        )
        if set(self.version_artifacts) != set(self.catalog.by_version):
            raise ValueError("version catalog and artifacts are inconsistent")
        if len(embedding_dimensions) > 1:
            raise ValueError("version embedding dimensions do not match")
        self.active_index = payload.get("active_index")
        if self.active_index:
            path = self.root / self.active_index["path"]
            if not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest() != self.active_index.get("sha256"):
                raise ValueError("active index hash mismatch")
            active_payload = json.loads(path.read_text(encoding="utf-8"))
            rows = active_payload.get("rows", [])
            vectors = np.asarray(active_payload.get("vectors", []), dtype=np.float32)
            if len(rows) != int(self.active_index.get("row_count", -1)) or vectors.ndim != 2 or len(rows) != vectors.shape[0]:
                raise ValueError("active index count mismatch")
            if any(
                row.get("version_id") not in self.catalog.by_version
                or self.catalog.by_version[row["version_id"]].status != VersionStatus.ACTIVE
                for row in rows
            ):
                raise ValueError("active index contains inactive or unknown version")
            if len(rows) and embedding_dimensions and vectors.shape[1] not in embedding_dimensions:
                raise ValueError("active index dimension mismatch")
        self.refresh_version = int(payload.get("index_refresh_version", 0))

    def _artifact_path(self, version_id: str) -> Path:
        safe = re.sub(r"[^A-Za-z0-9_.-]", "_", version_id)
        return self.root / "versions" / f"{safe}.json"

    def _read_artifact(self, version_id: str) -> dict[str, Any]:
        record = self.version_artifacts[version_id]
        return json.loads((self.root / record["path"]).read_text(encoding="utf-8"))

    def _commit_catalog(
        self,
        documents: Sequence[Document],
        versions: Sequence[DocumentVersion],
        artifacts: Mapping[str, Any],
        *,
        active_index: Mapping[str, Any] | None,
        refresh_version: int,
    ) -> None:
        payload: dict[str, Any] = {
            "schema_version": STORE_SCHEMA_VERSION,
            "status": "COMPLETE",
            "document_catalog_version": CATALOG_SCHEMA_VERSION,
            "documents": [item.model_dump(mode="json") for item in documents],
            "versions": [item.model_dump(mode="json") for item in versions],
            "version_artifacts": dict(artifacts),
            "embedding_cache": {
                "path": self.cache_path.relative_to(self.root).as_posix(),
                "sha256": hashlib.sha256(self.cache_path.read_bytes()).hexdigest(),
                "bytes": self.cache_path.stat().st_size,
            },
            "active_index": dict(active_index) if active_index else None,
            "index_refresh_version": refresh_version,
            "updated_at": _now().isoformat(),
        }
        payload["manifest_sha256"] = _canonical_hash(payload)
        _atomic_json(self.catalog_path, payload)

    def _load_cache(self) -> dict[str, list[float]]:
        payload = json.loads(self.cache_path.read_text(encoding="utf-8"))
        if payload.get("schema_version") != STORE_SCHEMA_VERSION or not isinstance(payload.get("vectors"), dict):
            raise ValueError("embedding cache invalid")
        return dict(payload["vectors"])

    @staticmethod
    def _normalize_vectors(vectors: np.ndarray) -> np.ndarray:
        matrix = np.asarray(vectors, dtype=np.float32)
        if matrix.ndim != 2 or not np.isfinite(matrix).all():
            raise ValueError("embedding batch must be a finite matrix")
        norms = np.linalg.norm(matrix, axis=1, keepdims=True)
        if np.any(norms <= 0):
            raise ValueError("embedding vectors cannot be zero")
        return matrix / norms

    def ingest_version(
        self,
        *,
        document_id: str,
        project_id: str,
        document_type: str,
        title: str,
        version_id: str,
        version_label: str,
        source_bytes: bytes,
        source_name: str,
        sections: Sequence[SectionSnapshot | Mapping[str, Any]],
        embedder: SectionEmbedder,
        activate: bool = True,
    ) -> IncrementalBuildReport:
        started = time.monotonic()
        if version_id in self.catalog.by_version:
            raise DuplicateVersionError("version_id already exists")
        source_hash = hashlib.sha256(source_bytes).hexdigest()
        if any(
            item.document_id == document_id and item.source_hash == source_hash
            for item in self.catalog.versions
        ):
            raise DuplicateVersionError("identical source file was already ingested")
        parsed = [item if isinstance(item, SectionSnapshot) else SectionSnapshot.model_validate(item) for item in sections]
        if not parsed:
            raise ValueError("a version must contain at least one section")
        if len({item.identity for item in parsed}) != len(parsed):
            raise ValueError("section paths must be unique inside a version")
        current = self.catalog.active_version(document_id)
        old_sections = self.catalog.sections_by_version.get(current.version_id, []) if current else []
        provisional = compare_section_versions(
            document_id,
            current.version_id if current else "EMPTY",
            version_id,
            old_sections,
            parsed,
        )
        counts = provisional.summary
        cache = self._load_cache()
        missing_by_hash = {}
        for item in parsed:
            if item.content_hash not in cache:
                missing_by_hash.setdefault(item.content_hash, item)
        missing = list(missing_by_hash.values())
        if missing:
            encoded = self._normalize_vectors(embedder.encode([item.content for item in missing]))
            if encoded.shape[0] != len(missing):
                raise ValueError("embedding batch count mismatch")
            for item, vector in zip(missing, encoded):
                assert item.content_hash is not None
                cache[item.content_hash] = [float(value) for value in vector]
        dimensions = {len(cache[str(item.content_hash)]) for item in parsed}
        if len(dimensions) != 1:
            raise ValueError("embedding dimensions do not match")
        chunks = []
        embeddings = []
        for position, section in enumerate(parsed):
            chunk_id = f"{version_id}:chunk:{hashlib.sha256(section.identity.encode()).hexdigest()[:16]}"
            chunks.append(
                {
                    "chunk_id": chunk_id,
                    "document_id": document_id,
                    "version_id": version_id,
                    "project_id": project_id,
                    "document_type": document_type,
                    "section_id": section.section_id,
                    "section_path": section.section_path,
                    "page_number": section.page_start,
                    "page_end": section.page_end,
                    "content_hash": section.content_hash,
                    "text": section.content,
                    "position": position,
                }
            )
            embeddings.append(cache[str(section.content_hash)])
        artifact = {
            "schema_version": STORE_SCHEMA_VERSION,
            "version_id": version_id,
            "document_id": document_id,
            "source_hash": source_hash,
            "sections": [item.model_dump(mode="json") for item in parsed],
            "chunks": chunks,
            "embeddings": embeddings,
        }
        artifact_path = self._artifact_path(version_id)
        _atomic_json(artifact_path, artifact)
        artifact_record = {
            "path": artifact_path.relative_to(self.root).as_posix(),
            "sha256": hashlib.sha256(artifact_path.read_bytes()).hexdigest(),
            "chunk_count": len(chunks),
        }
        documents = list(self.catalog.documents)
        if document_id not in self.catalog.by_document:
            documents.append(Document(
                document_id=document_id,
                project_id=project_id,
                document_type=document_type,
                title=title,
            ))
        else:
            document = self.catalog.by_document[document_id]
            if (document.project_id, document.document_type) != (project_id, document_type):
                raise ValueError("stable document metadata cannot change during version ingest")
        timestamp = _now()
        versions = []
        for item in self.catalog.versions:
            if activate and item.document_id == document_id and item.status == VersionStatus.ACTIVE:
                versions.append(item.model_copy(update={"status": VersionStatus.SUPERSEDED, "superseded_at": timestamp}))
            else:
                versions.append(item)
        versions.append(
            DocumentVersion(
                version_id=version_id,
                document_id=document_id,
                version_label=version_label,
                status=VersionStatus.ACTIVE if activate else VersionStatus.SUPERSEDED,
                source_hash=source_hash,
                activated_at=timestamp if activate else None,
                previous_version_id=current.version_id if current else None,
                source_name=source_name,
            )
        )
        artifacts = dict(self.version_artifacts)
        artifacts[version_id] = artifact_record
        new_refresh = self.refresh_version + 1
        active_index = self._build_active_index(versions, artifacts, new_refresh)
        _atomic_json(self.cache_path, {"schema_version": STORE_SCHEMA_VERSION, "vectors": cache})
        self._commit_catalog(
            documents,
            versions,
            artifacts,
            active_index=active_index,
            refresh_version=new_refresh,
        )
        self._load_state()
        return IncrementalBuildReport(
            total_sections=len(parsed),
            unchanged_sections=counts[ChangeType.UNCHANGED.value],
            modified_sections=counts[ChangeType.MODIFIED.value],
            added_sections=counts[ChangeType.ADDED.value],
            removed_sections=counts[ChangeType.REMOVED.value],
            reused_embeddings=len(parsed) - len(missing),
            new_embeddings=len(missing),
            active_chunks=sum(
                int(row["chunk_count"])
                for vid, row in artifacts.items()
                if next(item for item in versions if item.version_id == vid).status == VersionStatus.ACTIVE
            ),
            processing_time=round(time.monotonic() - started, 6),
        )

    def _build_active_index(
        self,
        versions: Sequence[DocumentVersion],
        artifacts: Mapping[str, Any],
        refresh_version: int,
    ) -> dict[str, Any]:
        rows: list[dict[str, Any]] = []
        vectors: list[list[float]] = []
        for version in sorted(versions, key=lambda item: item.version_id):
            if version.status != VersionStatus.ACTIVE:
                continue
            record = artifacts[version.version_id]
            artifact = json.loads((self.root / record["path"]).read_text(encoding="utf-8"))
            rows.extend(artifact["chunks"])
            vectors.extend(artifact["embeddings"])
        value = {
            "schema_version": STORE_SCHEMA_VERSION,
            "refresh_version": refresh_version,
            "strategy": "CACHED_VECTOR_EXACT_MATRIX_REFRESH",
            "rows": rows,
            "vectors": vectors,
        }
        path = self.root / "active_indexes" / f"active-{refresh_version}.json"
        _atomic_json(path, value)
        return {
            "path": path.relative_to(self.root).as_posix(),
            "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            "row_count": len(rows),
            "strategy": value["strategy"],
        }

    def activate_version(self, version_id: str) -> None:
        target = self.catalog.by_version.get(version_id)
        if target is None:
            raise KeyError(version_id)
        timestamp = _now()
        versions = [
            item.model_copy(
                update={
                    "status": VersionStatus.ACTIVE if item.version_id == version_id else VersionStatus.SUPERSEDED,
                    "activated_at": timestamp if item.version_id == version_id else item.activated_at,
                    "superseded_at": (
                        None if item.version_id == version_id
                        else timestamp if item.document_id == target.document_id
                        else item.superseded_at
                    ),
                }
            )
            if item.document_id == target.document_id
            else item
            for item in self.catalog.versions
        ]
        refresh = self.refresh_version + 1
        active_index = self._build_active_index(versions, self.version_artifacts, refresh)
        self._commit_catalog(
            self.catalog.documents,
            versions,
            self.version_artifacts,
            active_index=active_index,
            refresh_version=refresh,
        )
        self._load_state()

    def search(self, query_vector: Sequence[float], scope: RetrievalScope | None = None, *, top_k: int = 5) -> list[dict[str, Any]]:
        if top_k < 1:
            raise ValueError("top_k must be positive")
        scope = scope or RetrievalScope()
        rows: list[dict[str, Any]] = []
        vectors: list[list[float]] = []
        for version_id in sorted(self.version_artifacts):
            artifact = self._read_artifact(version_id)
            for row, vector in zip(artifact["chunks"], artifact["embeddings"]):
                if self.catalog.matches(row, scope):
                    rows.append(self.catalog.enrich_chunk(row))
                    vectors.append(vector)
        if not rows:
            return []
        matrix = np.asarray(vectors, dtype=np.float32)
        query = self._normalize_vectors(np.asarray([query_vector], dtype=np.float32))[0]
        if matrix.shape[1] != query.shape[0]:
            raise ValueError("query embedding dimension mismatch")
        scores = matrix @ query
        order = np.lexsort((np.arange(len(rows)), -scores))[:top_k]
        result = []
        for rank, index in enumerate(order, start=1):
            item = dict(rows[int(index)])
            item["similarity"] = float(scores[int(index)])
            item["rank"] = rank
            result.append(item)
        return result

    def diff(self, document_id: str, from_version_id: str, to_version_id: str) -> DocumentVersionDiff:
        return self.catalog.diff(document_id, from_version_id, to_version_id)


