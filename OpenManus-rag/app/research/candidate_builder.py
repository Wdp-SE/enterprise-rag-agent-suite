"""Atomic offline Candidate Package construction."""

from __future__ import annotations

import json
import os
import shutil
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

from app.research.candidate_package import (
    CandidateDocumentMetadata,
    CandidateReviewMetadata,
    CandidateSource,
)
from app.research.candidate_types import CandidateBuildResult, CandidateBuildStatus
from app.research.drafting import DeterministicDraftGenerator, DraftGenerator
from app.research.identifiers import assign_source_ids, stable_candidate_id, stable_document_id
from app.research.models import Evidence, ResearchProfile
from app.research.raw_source_archive import RawSourceArchive


class CandidateBuilderError(RuntimeError):
    pass


class CandidateBuilder:
    """Build in staging, validate, then atomically publish without overwriting."""

    def __init__(
        self,
        *,
        workspace_root: str | Path,
        output_root: str | Path = "candidate_knowledge",
        validator,
        draft_generator: DraftGenerator | None = None,
        clock: Callable[[], datetime] | None = None,
    ):
        self.workspace_root = Path(workspace_root).resolve()
        requested_output = Path(output_root)
        self.output_root = (
            requested_output.resolve()
            if requested_output.is_absolute()
            else (self.workspace_root / requested_output).resolve()
        )
        if not self.output_root.is_relative_to(self.workspace_root):
            raise CandidateBuilderError("Candidate output_root must remain inside workspace_root")
        self.validator = validator
        self.draft_generator = draft_generator or DeterministicDraftGenerator()
        self.clock = clock or (lambda: datetime.now(timezone.utc))

    @staticmethod
    def _write_json(path: Path, payload) -> None:
        path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )

    def _validate(
        self,
        package_path: Path,
        *,
        evidence_by_id: dict[str, Evidence],
        candidate_id: str,
        document_id: str,
    ):
        return self.validator.validate(
            package_path,
            evidence_by_id=evidence_by_id,
            expected_candidate_id=candidate_id,
            expected_document_id=document_id,
        )

    def build(
        self,
        *,
        profile: ResearchProfile,
        evidence_list: list[Evidence],
    ) -> CandidateBuildResult:
        minimum = profile.output_requirements.minimum_evidence_count
        if len(evidence_list) < minimum:
            return CandidateBuildResult(
                status=CandidateBuildStatus.INSUFFICIENT_EVIDENCE,
                reason=f"profile requires at least {minimum} Evidence records",
            )
        if len(evidence_list) > profile.max_sources:
            raise CandidateBuilderError("Evidence count exceeds ResearchProfile max_sources")
        evidence_ids = [evidence.evidence_id for evidence in evidence_list]
        if len(evidence_ids) != len(set(evidence_ids)):
            raise CandidateBuilderError("Evidence list contains duplicate evidence_id values")
        if any(evidence.local_file is None or evidence.source_url is None for evidence in evidence_list):
            return CandidateBuildResult(
                status=CandidateBuildStatus.INSUFFICIENT_EVIDENCE,
                reason="every Evidence record needs source_url and original local_file",
            )

        identity_args = {
            "domain": profile.domain,
            "research_topic": profile.research_topic,
            "category": profile.knowledge_category,
            "evidence_list": evidence_list,
        }
        candidate_id = stable_candidate_id(**identity_args)
        document_id = stable_document_id(**identity_args)
        final_path = self.output_root / candidate_id
        evidence_by_id = {
            evidence.evidence_id: evidence
            for evidence in evidence_list
            if evidence.evidence_id is not None
        }

        self.output_root.mkdir(parents=True, exist_ok=True)
        if final_path.exists():
            if final_path.is_symlink() or not final_path.is_dir():
                raise CandidateBuilderError("existing Candidate path is not a regular directory")
            validation = self._validate(
                final_path,
                evidence_by_id=evidence_by_id,
                candidate_id=candidate_id,
                document_id=document_id,
            )
            if not validation.accepted:
                codes = ", ".join(issue.code for issue in validation.issues)
                raise CandidateBuilderError(f"existing Candidate Package is invalid: {codes}")
            return CandidateBuildResult(
                status=CandidateBuildStatus.REUSED,
                candidate_id=candidate_id,
                document_id=document_id,
                package_path=final_path.relative_to(self.workspace_root).as_posix(),
            )

        staging_path = Path(
            tempfile.mkdtemp(prefix=".stage-", dir=self.output_root)
        )
        try:
            archive = RawSourceArchive(self.workspace_root, staging_path)
            assignments = assign_source_ids(evidence_list)
            candidate_sources: list[CandidateSource] = []
            for assignment in assignments:
                evidence = assignment.evidence
                archived = archive.archive(evidence)
                assert evidence.evidence_id is not None
                assert evidence.content_hash is not None
                assert evidence.source_url is not None
                candidate_sources.append(
                    CandidateSource(
                        source_id=assignment.source_id,
                        evidence_id=evidence.evidence_id,
                        title=evidence.title,
                        organization=evidence.organization,
                        url=evidence.source_url,
                        source_type=evidence.source_type,
                        document_number=evidence.document_number,
                        publish_date=evidence.publish_date,
                        effective_date=evidence.effective_date,
                        source_level=evidence.source_level,
                        retrieved_at=evidence.retrieved_at,
                        local_file=archived.local_file,
                        content_hash=evidence.content_hash,
                        raw_file_hash=archived.raw_file_hash,
                    )
                )

            document = self.draft_generator.generate(
                title=profile.research_topic,
                domain=profile.domain,
                category=profile.knowledge_category,
                sources=assignments,
                required_sections=profile.output_requirements.required_sections,
            )
            first_source = candidate_sources[0]
            metadata = CandidateDocumentMetadata(
                document_id=document_id,
                title=profile.research_topic,
                document_type=profile.output_requirements.document_type,
                source=(
                    first_source.organization
                    if len(candidate_sources) == 1
                    else "multiple_public_sources"
                ),
                source_url=first_source.url,
                category=profile.knowledge_category,
                tags=profile.output_requirements.tags,
                legacy_company_name=None,
                candidate=CandidateReviewMetadata(created_at=self.clock()),
            )

            (staging_path / "document.md").write_text(document, encoding="utf-8")
            self._write_json(staging_path / "metadata.json", metadata.model_dump(mode="json"))
            self._write_json(
                staging_path / "sources.json",
                [source.model_dump(mode="json") for source in candidate_sources],
            )

            validation = self._validate(
                staging_path,
                evidence_by_id=evidence_by_id,
                candidate_id=candidate_id,
                document_id=document_id,
            )
            if not validation.accepted:
                details = "; ".join(
                    f"{issue.code}: {issue.message}" for issue in validation.issues
                )
                raise CandidateBuilderError(f"Candidate validation rejected staging: {details}")
            if final_path.exists():
                raise CandidateBuilderError("Candidate appeared during atomic publication")
            os.replace(staging_path, final_path)
            return CandidateBuildResult(
                status=CandidateBuildStatus.CREATED,
                candidate_id=candidate_id,
                document_id=document_id,
                package_path=final_path.relative_to(self.workspace_root).as_posix(),
            )
        finally:
            if staging_path.exists():
                if staging_path.parent != self.output_root or not staging_path.name.startswith(".stage-"):
                    raise CandidateBuilderError("refusing to clean an unexpected staging path")
                shutil.rmtree(staging_path)
