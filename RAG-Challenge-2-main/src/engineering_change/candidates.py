"""Candidate-version construction and catalog-last safe activation."""

from __future__ import annotations

import hashlib
import json
import zipfile
from enum import Enum
from pathlib import Path
from typing import Any, Sequence

from pydantic import BaseModel, ConfigDict, Field

from src.document_lifecycle import (
    RetrievalScope,
    SectionSnapshot,
    VersionLifecycleService,
    _atomic_json,
)

from .extraction import DocxEngineeringParser
from .models import OrganizationProfile, normalize_text


class CandidateStatus(str, Enum):
    BUILDING = "BUILDING"
    VALIDATED = "VALIDATED"
    ACTIVE = "ACTIVE"
    FAILED = "FAILED"


class CandidateVersionRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")

    candidate_id: str
    document_id: str
    version_id: str
    version_label: str
    source_name: str
    source_hash: str
    previous_active_version_id: str | None = None
    status: CandidateStatus
    validations: dict[str, bool] = Field(default_factory=dict)
    build_report: dict[str, Any] | None = None
    failure_reason: str | None = None
    failure_detail: str | None = None


class CandidateVersionService:
    """Build inactive versions, validate them, then atomically activate."""

    def __init__(self, root: str | Path, embedder):
        self.root = Path(root).resolve()
        self.lifecycle = VersionLifecycleService(self.root / "version_store")
        self.embedder = embedder
        self.candidates_root = self.root / "candidates"
        self.candidates_root.mkdir(parents=True, exist_ok=True)
        self.records_path = self.root / "candidate_records.json"
        self.records: dict[str, CandidateVersionRecord] = {}
        if self.records_path.is_file():
            payload = json.loads(self.records_path.read_text(encoding="utf-8"))
            self.records = {
                item["candidate_id"]: CandidateVersionRecord.model_validate(item)
                for item in payload.get("candidates", [])
            }
        else:
            self._save()

    def _save(self) -> None:
        _atomic_json(self.records_path, {
            "schema_version": "engineering-candidate-version-v1",
            "candidates": [
                item.model_dump(mode="json")
                for item in sorted(self.records.values(), key=lambda value: value.candidate_id)
            ],
        })

    def build_candidate(
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
        profile: OrganizationProfile,
        expected_contents: Sequence[str] = (),
    ) -> CandidateVersionRecord:
        source_hash = hashlib.sha256(source_bytes).hexdigest()
        identity = f"{document_id}|{version_id}|{source_hash}"
        candidate_id = f"candidate_{hashlib.sha256(identity.encode()).hexdigest()[:20]}"
        existing = self.records.get(candidate_id)
        if existing is not None and existing.status in {CandidateStatus.VALIDATED, CandidateStatus.ACTIVE}:
            return existing
        current = self.lifecycle.catalog.active_version(document_id)
        record = CandidateVersionRecord(
            candidate_id=candidate_id,
            document_id=document_id,
            version_id=version_id,
            version_label=version_label,
            source_name=source_name,
            source_hash=source_hash,
            previous_active_version_id=current.version_id if current else None,
            status=CandidateStatus.BUILDING,
        )
        self.records[candidate_id] = record
        self._save()
        try:
            if not source_name.lower().endswith(".docx") or len(source_bytes) > 10 * 1024 * 1024:
                raise ValueError("candidate source must be a DOCX no larger than 10 MiB")
            candidate_root = self.candidates_root / candidate_id
            candidate_root.mkdir(parents=True, exist_ok=True)
            source_path = candidate_root / "candidate.docx"
            source_path.write_bytes(source_bytes)
            if not zipfile.is_zipfile(source_path):
                raise ValueError("candidate DOCX package is invalid")
            parsed = DocxEngineeringParser().parse(source_path, profile)
            sections = [
                SectionSnapshot(
                    section_id=item.section_id,
                    section_path=item.section_path,
                    content=item.content,
                    page_start=index,
                    page_end=index,
                )
                for index, item in enumerate(parsed, start=1)
            ]
            combined = "\n".join(item.content for item in sections)
            business_valid = all(normalize_text(expected) in combined for expected in expected_contents)
            if not business_valid:
                raise ValueError("candidate business integrity validation failed")
            report = self.lifecycle.ingest_version(
                document_id=document_id,
                project_id=project_id,
                document_type=document_type,
                title=title,
                version_id=version_id,
                version_label=version_label,
                source_bytes=source_bytes,
                source_name=source_name,
                sections=sections,
                embedder=self.embedder,
                activate=False,
            )
            record.status = CandidateStatus.VALIDATED
            record.validations = {
                "docx": True,
                "structure": bool(sections),
                "chunk_generation": report.total_sections == len(sections),
                "embedding": report.reused_embeddings + report.new_embeddings == len(sections),
                "index": version_id in self.lifecycle.version_artifacts,
                "business_integrity": business_valid,
            }
            if not all(record.validations.values()):
                raise ValueError("candidate validation did not complete")
            record.build_report = report.__dict__.copy()
            record.failure_reason = None
        except Exception as exc:
            record.status = CandidateStatus.FAILED
            record.failure_reason = "CANDIDATE_BUILD_FAILED"
            record.failure_detail = type(exc).__name__
            record.validations = {**record.validations, "safe_activation": False}
        self._save()
        return record

    def activate(self, candidate_id: str) -> CandidateVersionRecord:
        try:
            record = self.records[candidate_id]
        except KeyError as exc:
            raise KeyError("candidate version not found") from exc
        if record.status is CandidateStatus.ACTIVE:
            return record
        if record.status is not CandidateStatus.VALIDATED:
            raise ValueError("only a validated candidate can be activated")
        try:
            self.lifecycle.activate_version(record.version_id)
            active = self.lifecycle.catalog.active_version(record.document_id)
            if active is None or active.version_id != record.version_id:
                raise ValueError("candidate activation verification failed")
            record.status = CandidateStatus.ACTIVE
            record.validations["safe_activation"] = True
            record.failure_reason = None
        except Exception:
            record.status = CandidateStatus.FAILED
            record.failure_reason = "CANDIDATE_ACTIVATION_FAILED"
            record.validations["safe_activation"] = False
        self._save()
        return record

    def get(self, candidate_id: str) -> CandidateVersionRecord:
        return self.records[candidate_id]

    def retrieve(
        self,
        query_vector: Sequence[float],
        scope: RetrievalScope | None = None,
        *,
        top_k: int = 5,
    ) -> list[dict[str, Any]]:
        return self.lifecycle.search(query_vector, scope, top_k=top_k)


