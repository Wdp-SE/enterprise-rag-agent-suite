"""Validated, frozen corpus manifest models."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import List, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, model_validator


CorpusStatus = Literal["ACTIVE", "SUPERSEDED", "REFERENCE"]
ParseStatus = Literal["READY", "PARTIAL_PARSE", "OCR_REQUIRED", "PARSE_FAILED"]
OcrStatus = Literal[
    "NOT_REQUIRED",
    "OCR_REQUIRED",
    "OCR_SUCCEEDED",
    "OCR_PARTIAL",
    "OCR_FAILED",
]


class CorpusDocument(BaseModel):
    model_config = ConfigDict(extra="forbid")

    document_id: str
    title: str
    source_filename: str
    document_type: str
    organization: str
    document_number: Optional[str] = None
    publish_date: Optional[str] = None
    effective_date: Optional[str] = None
    version_family: Optional[str] = None
    version: Optional[str] = None
    status: CorpusStatus
    source_level: str
    source_path: str
    source_url: Optional[str] = None
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    size_bytes: int = Field(ge=0)
    pages_total: int = Field(ge=0)
    pages_with_text: int = Field(ge=0)
    empty_pages: int = Field(ge=0)
    parse_status: ParseStatus
    # Optional keeps frozen v0.1 manifests loadable without mutation.
    ocr_status: Optional[OcrStatus] = None
    included_in_default_index: bool
    evaluation_role: Optional[str] = None
    target_default_priority: Optional[int] = None


class DuplicateAudit(BaseModel):
    model_config = ConfigDict(extra="forbid")

    exact_sha256_duplicate_groups: List[List[str]]
    normalized_text_sha256_duplicate_groups: List[List[str]]
    result: str
    note: str


class VersionRelation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    older_document_id: str
    newer_document_id: str
    relation: str
    effective_date: Optional[str] = None
    note: str = ""


class CorpusManifest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: str
    corpus_id: str
    corpus_version: str
    frozen_at: str
    status: Literal["FROZEN"]
    scenario: str
    identity_note: str
    source_directory: str
    default_index_document_ids: List[str]
    target_current_document_ids_blocked_by_ocr: List[str]
    version_test_document_ids: List[str]
    reference_document_ids_blocked_by_ocr: List[str]
    duplicate_audit: DuplicateAudit
    version_relations: List[VersionRelation]
    documents: List[CorpusDocument]

    @model_validator(mode="after")
    def validate_document_references(self):
        ids = [document.document_id for document in self.documents]
        if len(ids) != len(set(ids)):
            raise ValueError("corpus manifest contains duplicate document_id values")

        known = set(ids)
        referenced = set(self.default_index_document_ids)
        referenced.update(self.target_current_document_ids_blocked_by_ocr)
        referenced.update(self.version_test_document_ids)
        referenced.update(self.reference_document_ids_blocked_by_ocr)
        for relation in self.version_relations:
            referenced.add(relation.older_document_id)
            referenced.add(relation.newer_document_id)
        unknown = referenced - known
        if unknown:
            raise ValueError(f"corpus manifest references unknown document ids: {sorted(unknown)}")

        default_by_flag = {
            document.document_id
            for document in self.documents
            if document.included_in_default_index
        }
        if default_by_flag != set(self.default_index_document_ids):
            raise ValueError(
                "default_index_document_ids does not match included_in_default_index flags"
            )
        return self


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def load_corpus_manifest(
    path: Path | str,
    *,
    verify_source_files: bool = False,
) -> CorpusManifest:
    manifest_path = Path(path)
    payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest = CorpusManifest.model_validate(payload)
    if verify_source_files:
        root = manifest_path.parent.resolve()
        for document in manifest.documents:
            source_path = (root / document.source_path).resolve()
            if not source_path.is_relative_to(root):
                raise ValueError(f"source_path escapes corpus root: {document.source_path}")
            if not source_path.is_file():
                raise ValueError(f"corpus source is missing: {document.source_path}")
            if source_path.stat().st_size != document.size_bytes:
                raise ValueError(f"corpus source size mismatch: {document.document_id}")
            if _sha256_file(source_path) != document.sha256:
                raise ValueError(f"corpus source hash mismatch: {document.document_id}")
    return manifest
