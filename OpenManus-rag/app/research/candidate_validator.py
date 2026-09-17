"""Independent validation for offline Candidate Packages."""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Mapping

from pydantic import ValidationError

from app.research.candidate_package import CandidateDocumentMetadata, CandidateSource
from app.research.candidate_types import CandidateValidationResult, ValidationIssue
from app.research.models import Evidence, normalize_text, sha256_text


class CandidateValidator:
    """Validate package structure, citations, Evidence hashes, and raw byte hashes."""

    CANDIDATE_ID_PATTERN = re.compile(r"^cand_[a-z0-9-]+_[0-9a-f]{16}$")
    CITATION_PATTERN = re.compile(r"\[source:([^\]]+)\]")
    SOURCE_ID_PATTERN = re.compile(r"^S[0-9]{2}$")

    @staticmethod
    def _file_hash(path: Path) -> str:
        digest = hashlib.sha256()
        with path.open("rb") as source_file:
            for chunk in iter(lambda: source_file.read(1024 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest()

    @staticmethod
    def _issue(issues: list[ValidationIssue], code: str, message: str) -> None:
        issues.append(ValidationIssue(code=code, message=message))

    def validate(
        self,
        package_path: str | Path,
        *,
        evidence_by_id: Mapping[str, Evidence],
        expected_candidate_id: str | None = None,
        expected_document_id: str | None = None,
    ) -> CandidateValidationResult:
        package = Path(package_path)
        issues: list[ValidationIssue] = []
        if not package.exists() or not package.is_dir() or package.is_symlink():
            self._issue(issues, "INVALID_PACKAGE_DIRECTORY", "package must be a regular directory")
            return CandidateValidationResult(accepted=False, issues=issues)
        if expected_candidate_id and not self.CANDIDATE_ID_PATTERN.fullmatch(expected_candidate_id):
            self._issue(issues, "INVALID_CANDIDATE_ID", "expected candidate_id has invalid syntax")

        required_paths = {
            "document.md": package / "document.md",
            "metadata.json": package / "metadata.json",
            "sources.json": package / "sources.json",
            "raw_sources": package / "raw_sources",
        }
        for name, path in required_paths.items():
            expected_directory = name == "raw_sources"
            if not path.exists() or path.is_symlink():
                self._issue(issues, "MISSING_PACKAGE_ENTRY", f"missing regular package entry: {name}")
            elif expected_directory != path.is_dir():
                self._issue(issues, "INVALID_PACKAGE_ENTRY", f"wrong package entry type: {name}")

        document = ""
        document_path = required_paths["document.md"]
        if document_path.is_file() and not document_path.is_symlink():
            try:
                document = document_path.read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError) as exc:
                self._issue(issues, "INVALID_DOCUMENT", str(exc))
            if not document.strip():
                self._issue(issues, "INVALID_DOCUMENT", "document.md cannot be empty")

        metadata: CandidateDocumentMetadata | None = None
        metadata_path = required_paths["metadata.json"]
        if metadata_path.is_file() and not metadata_path.is_symlink():
            try:
                metadata = CandidateDocumentMetadata.model_validate_json(
                    metadata_path.read_text(encoding="utf-8")
                )
            except (OSError, UnicodeDecodeError, ValidationError, json.JSONDecodeError) as exc:
                self._issue(issues, "INVALID_METADATA", str(exc))
        if metadata and expected_document_id and metadata.document_id != expected_document_id:
            self._issue(
                issues,
                "DOCUMENT_ID_MISMATCH",
                "metadata document_id does not match the stable expected document_id",
            )

        sources: list[CandidateSource] = []
        sources_path = required_paths["sources.json"]
        if sources_path.is_file() and not sources_path.is_symlink():
            try:
                raw_payload = json.loads(sources_path.read_text(encoding="utf-8"))
                if not isinstance(raw_payload, list) or not raw_payload:
                    raise ValueError("sources.json must be a non-empty list")
                sources = [CandidateSource.model_validate(item) for item in raw_payload]
            except (OSError, UnicodeDecodeError, json.JSONDecodeError, ValidationError, ValueError) as exc:
                self._issue(issues, "INVALID_SOURCES", str(exc))

        if sources:
            source_ids = [source.source_id for source in sources]
            expected_source_ids = [f"S{index:02d}" for index in range(1, len(sources) + 1)]
            if source_ids != expected_source_ids:
                self._issue(
                    issues,
                    "INVALID_SOURCE_ID_SEQUENCE",
                    f"source IDs must be sequential: {expected_source_ids}",
                )

            declared_ids = set(source_ids)
            citations = self.CITATION_PATTERN.findall(document)
            malformed = sorted(
                citation for citation in citations if not self.SOURCE_ID_PATTERN.fullmatch(citation)
            )
            if malformed:
                self._issue(issues, "MALFORMED_CITATION", f"malformed citations: {malformed}")
            valid_citations = {
                citation for citation in citations if self.SOURCE_ID_PATTERN.fullmatch(citation)
            }
            unknown = sorted(valid_citations - declared_ids)
            if unknown:
                self._issue(issues, "UNKNOWN_CITATION", f"unknown source citations: {unknown}")
            unused = sorted(declared_ids - valid_citations)
            if unused:
                self._issue(issues, "UNCITED_SOURCE", f"sources not cited by document.md: {unused}")

            referenced_raw_files: set[Path] = set()
            for source in sources:
                evidence = evidence_by_id.get(source.evidence_id)
                if evidence is None:
                    self._issue(
                        issues,
                        "EVIDENCE_NOT_FOUND",
                        f"no Evidence supplied for {source.evidence_id}",
                    )
                else:
                    expected_content_hash = sha256_text(normalize_text(evidence.content))
                    if source.content_hash != expected_content_hash:
                        self._issue(
                            issues,
                            "CONTENT_HASH_MISMATCH",
                            f"{source.source_id} content_hash does not match Evidence text",
                        )
                    mapped_values = (
                        source.title == evidence.title,
                        source.organization == evidence.organization,
                        source.url == evidence.source_url,
                        source.source_type == evidence.source_type,
                        source.source_level == evidence.source_level,
                    )
                    if not all(mapped_values):
                        self._issue(
                            issues,
                            "SOURCE_EVIDENCE_MISMATCH",
                            f"{source.source_id} metadata does not match its Evidence",
                        )

                relative_raw = Path(source.local_file)
                raw_path = (package / relative_raw).resolve(strict=False)
                try:
                    stays_inside = raw_path.is_relative_to(package.resolve())
                except OSError:
                    stays_inside = False
                if not stays_inside:
                    self._issue(
                        issues,
                        "RAW_SOURCE_PATH_ESCAPE",
                        f"{source.source_id} raw source escapes package",
                    )
                    continue
                referenced_raw_files.add(raw_path)
                if (
                    not raw_path.exists()
                    or not raw_path.is_file()
                    or raw_path.is_symlink()
                ):
                    self._issue(
                        issues,
                        "MISSING_RAW_SOURCE",
                        f"{source.source_id} raw source is missing or not a regular file",
                    )
                    continue
                if raw_path.stem != source.raw_file_hash:
                    self._issue(
                        issues,
                        "RAW_FILENAME_HASH_MISMATCH",
                        f"{source.source_id} raw filename does not match raw_file_hash",
                    )
                if self._file_hash(raw_path) != source.raw_file_hash:
                    self._issue(
                        issues,
                        "RAW_FILE_HASH_MISMATCH",
                        f"{source.source_id} raw_file_hash does not match original file bytes",
                    )

            raw_root = required_paths["raw_sources"]
            if raw_root.is_dir() and not raw_root.is_symlink():
                for raw_path in raw_root.iterdir():
                    if raw_path.is_symlink():
                        self._issue(issues, "RAW_SOURCE_SYMLINK", f"symlink not allowed: {raw_path.name}")
                    elif not raw_path.is_file():
                        self._issue(issues, "INVALID_RAW_SOURCE", f"not a regular file: {raw_path.name}")
                    elif raw_path.resolve() not in referenced_raw_files:
                        self._issue(
                            issues,
                            "UNREFERENCED_RAW_SOURCE",
                            f"raw source is not declared: {raw_path.name}",
                        )

        return CandidateValidationResult(accepted=not issues, issues=issues)
