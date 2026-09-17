import hashlib
import hmac
import json
import re
import shutil
import tempfile
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import Any, Dict, List, Optional

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    ValidationError,
    field_validator,
    model_validator,
)

from src.document_metadata import DocumentMetadata


_SAFE_ID_PATTERN = re.compile(r"^[A-Za-z0-9._:-]+$")
_SOURCE_REFERENCE_PATTERN = re.compile(r"\[source:([^\]]+)\]")
_SHA256_PATTERN = re.compile(r"^[0-9a-fA-F]{64}$")

_V2_MARKER_FIELDS = {
    "organization", "url", "local_file", "content_hash", "raw_file_hash",
    "document_number", "publish_date", "effective_date", "source_level",
    "retrieved_at", "evidence_id",
}
_V1_SOURCE_FIELDS = {
    "source_id", "title", "source_type", "source_url", "raw_path",
}
_V2_SOURCE_FIELDS = {
    "source_id", "title", "organization", "url", "local_file",
    "content_hash", "raw_file_hash", "document_number", "publish_date",
    "effective_date", "source_level", "retrieved_at", "source_type",
    "evidence_id", "source_url", "raw_path",
}


class CandidateStatus(str, Enum):
    CANDIDATE = "CANDIDATE"
    APPROVED = "APPROVED"


class CandidateContractVersion(str, Enum):
    V1 = "v1"
    V2 = "v2"


class ContentHashValidationStatus(str, Enum):
    NOT_DECLARED = "NOT_DECLARED"
    DECLARED_AND_FORMAT_VALIDATED = "DECLARED_AND_FORMAT_VALIDATED"


class RawFileHashValidationStatus(str, Enum):
    NOT_DECLARED = "NOT_DECLARED"
    RECOMPUTED_AND_VERIFIED = "RECOMPUTED_AND_VERIFIED"


class CandidateMetadata(BaseModel):
    """Review state kept outside the reusable document metadata model."""

    status: CandidateStatus = CandidateStatus.CANDIDATE
    generated_by: str
    requires_review: bool = True
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    @field_validator("generated_by")
    @classmethod
    def validate_generated_by(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("generated_by must be non-empty")
        return value


class CandidatePackageMetadata(DocumentMetadata):
    candidate: CandidateMetadata


class CandidateSource(BaseModel):
    """Canonical internal source model shared by both external contracts."""

    model_config = ConfigDict(extra="forbid")

    source_id: str
    title: str
    organization: Optional[str] = None
    source_url: Optional[str] = None
    local_file: str
    content_hash: Optional[str] = None
    raw_file_hash: Optional[str] = None
    document_number: Optional[str] = None
    publish_date: Optional[str] = None
    effective_date: Optional[str] = None
    source_level: Optional[str] = None
    retrieved_at: Optional[str] = None
    source_type: str = "document"
    evidence_id: Optional[str] = None

    @field_validator("source_id")
    @classmethod
    def validate_source_id(cls, value: str) -> str:
        value = value.strip()
        if not re.fullmatch(r"S\d{2,}", value):
            raise ValueError("source_id must use the Sxx format, for example S01")
        return value

    @field_validator("title", "local_file", "source_type")
    @classmethod
    def validate_non_empty(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("field must be non-empty")
        return value


class NormalizedCandidateSources(BaseModel):
    model_config = ConfigDict(extra="forbid")

    contract_version: CandidateContractVersion
    sources: List[CandidateSource] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_unique_source_ids(self):
        source_ids = [source.source_id for source in self.sources]
        if len(source_ids) != len(set(source_ids)):
            raise ValueError("sources.json contains duplicate source_id values")
        return self


class ImportIssue(BaseModel):
    code: str
    message: str
    path: Optional[str] = None


class ImportResult(BaseModel):
    accepted: bool
    candidate_id: Optional[str] = None
    document_id: Optional[str] = None
    status: Optional[CandidateStatus] = None
    contract_version: Optional[CandidateContractVersion] = None
    content_hash_validation: Optional[ContentHashValidationStatus] = None
    raw_file_hash_validation: Optional[RawFileHashValidationStatus] = None
    stored_path: Optional[str] = None
    issues: List[ImportIssue] = Field(default_factory=list)
    ingestion_performed: bool = False


class ApprovalResult(BaseModel):
    approved: bool
    candidate_id: str
    document_id: Optional[str] = None
    previous_status: Optional[CandidateStatus] = None
    status: Optional[CandidateStatus] = None
    requires_review: Optional[bool] = None
    issues: List[ImportIssue] = Field(default_factory=list)
    ingestion_performed: bool = False


class CandidateSourceContractError(ValueError):
    def __init__(self, issues: List[ImportIssue]):
        super().__init__("; ".join(issue.message for issue in issues))
        self.issues = issues


def _source_issue(code: str, message: str, source_index: Optional[int] = None) -> ImportIssue:
    path = "sources.json" if source_index is None else f"sources.json[{source_index}]"
    return ImportIssue(code=code, message=message, path=path)


def detect_contract_version(payload: Any) -> CandidateContractVersion:
    """Detect v1 wrapper or v2 hash-aware sources at the external boundary."""
    if isinstance(payload, list):
        return CandidateContractVersion.V2
    if not isinstance(payload, dict):
        raise CandidateSourceContractError(
            [_source_issue("INVALID_SOURCES_ROOT", "sources.json root must be an object or array")]
        )
    unknown_root_fields = set(payload) - {"sources"}
    if unknown_root_fields:
        raise CandidateSourceContractError([
            _source_issue(
                "INVALID_SOURCES_ROOT",
                f"Unknown sources.json root fields: {sorted(unknown_root_fields)}",
            )
        ])
    source_items = payload.get("sources")
    if not isinstance(source_items, list):
        raise CandidateSourceContractError(
            [_source_issue("INVALID_SOURCES_ROOT", "v1 sources.json requires a 'sources' array")]
        )
    for item in source_items:
        if isinstance(item, dict) and set(item).intersection(_V2_MARKER_FIELDS):
            return CandidateContractVersion.V2
    return CandidateContractVersion.V1


def _normalize_url_value(value: Any) -> Optional[str]:
    if value is None:
        return None
    return value.strip() if isinstance(value, str) else None


def _normalize_local_file_value(value: Any) -> Optional[str]:
    if value is None:
        return None
    return value.strip().replace("\\", "/") if isinstance(value, str) else None


def _normalize_alias(
    record: Dict[str, Any], *, legacy_name: str, current_name: str,
    normalizer, source_index: int, issues: List[ImportIssue],
) -> Optional[str]:
    legacy_present = legacy_name in record
    current_present = current_name in record
    legacy_value = normalizer(record.get(legacy_name)) if legacy_present else None
    current_value = normalizer(record.get(current_name)) if current_present else None
    if legacy_present and record.get(legacy_name) is not None and legacy_value is None:
        issues.append(_source_issue(
            "sources_invalid", f"{legacy_name} must be a string or null", source_index
        ))
    if current_present and record.get(current_name) is not None and current_value is None:
        issues.append(_source_issue(
            "sources_invalid", f"{current_name} must be a string or null", source_index
        ))
    if legacy_present and current_present and legacy_value != current_value:
        issues.append(_source_issue(
            "SOURCE_ALIAS_CONFLICT",
            f"{legacy_name} and {current_name} normalize to different values",
            source_index,
        ))
    return current_value if current_present else legacy_value


def _normalize_sha256(
    value: Any, *, issue_code: str, field_name: str,
    source_index: int, issues: List[ImportIssue],
) -> Optional[str]:
    if not isinstance(value, str) or not _SHA256_PATTERN.fullmatch(value.strip()):
        issues.append(_source_issue(
            issue_code,
            f"{field_name} must be a 64-character SHA-256 hexadecimal digest",
            source_index,
        ))
        return None
    return value.strip().lower()


def normalize_candidate_sources(payload: Any) -> NormalizedCandidateSources:
    """Normalize v1/v2 sources into one strict internal representation."""
    contract_version = detect_contract_version(payload)
    source_items = payload if isinstance(payload, list) else payload["sources"]
    issues: List[ImportIssue] = []
    normalized_sources: List[CandidateSource] = []
    if not source_items:
        raise CandidateSourceContractError(
            [_source_issue("sources_invalid", "sources.json must contain at least one source")]
        )

    allowed_fields = (
        _V1_SOURCE_FIELDS if contract_version == CandidateContractVersion.V1
        else _V2_SOURCE_FIELDS
    )
    for source_index, record in enumerate(source_items):
        if not isinstance(record, dict):
            issues.append(_source_issue(
                "sources_invalid", "Each source must be a JSON object", source_index
            ))
            continue

        unknown_fields = set(record) - allowed_fields
        for field_name in sorted(unknown_fields):
            issues.append(_source_issue(
                "UNKNOWN_SOURCE_FIELD",
                f"Unknown Candidate Source field '{field_name}'",
                source_index,
            ))

        if contract_version == CandidateContractVersion.V1:
            source_url = _normalize_url_value(record.get("source_url"))
            local_file = _normalize_local_file_value(record.get("raw_path"))
            if not local_file:
                issues.append(_source_issue(
                    "INVALID_LOCAL_FILE", "v1 raw_path must be a non-empty string", source_index
                ))
            canonical_record = {
                "source_id": record.get("source_id"),
                "title": record.get("title"),
                "source_url": source_url,
                "local_file": local_file or "",
                "source_type": record.get("source_type") or "document",
            }
        else:
            source_url = _normalize_alias(
                record, legacy_name="source_url", current_name="url",
                normalizer=_normalize_url_value, source_index=source_index, issues=issues,
            )
            local_file = _normalize_alias(
                record, legacy_name="raw_path", current_name="local_file",
                normalizer=_normalize_local_file_value, source_index=source_index, issues=issues,
            )
            if not source_url:
                issues.append(_source_issue(
                    "sources_invalid", "v2 requires a non-empty url or source_url", source_index
                ))
            if not local_file:
                issues.append(_source_issue(
                    "INVALID_LOCAL_FILE",
                    "v2 requires a non-empty local_file or raw_path",
                    source_index,
                ))
            organization = record.get("organization")
            if not isinstance(organization, str) or not organization.strip():
                issues.append(_source_issue(
                    "sources_invalid", "v2 organization must be a non-empty string", source_index
                ))
                organization = None
            content_hash = _normalize_sha256(
                record.get("content_hash"), issue_code="INVALID_CONTENT_HASH",
                field_name="content_hash", source_index=source_index, issues=issues,
            )
            raw_file_hash = _normalize_sha256(
                record.get("raw_file_hash"), issue_code="INVALID_RAW_FILE_HASH",
                field_name="raw_file_hash", source_index=source_index, issues=issues,
            )
            canonical_record = {
                "source_id": record.get("source_id"),
                "title": record.get("title"),
                "organization": organization.strip() if organization else None,
                "source_url": source_url,
                "local_file": local_file or "",
                "content_hash": content_hash,
                "raw_file_hash": raw_file_hash,
                "document_number": record.get("document_number"),
                "publish_date": record.get("publish_date"),
                "effective_date": record.get("effective_date"),
                "source_level": record.get("source_level"),
                "retrieved_at": record.get("retrieved_at"),
                "source_type": record.get("source_type") or "document",
                "evidence_id": record.get("evidence_id"),
            }
        try:
            normalized_sources.append(CandidateSource.model_validate(canonical_record))
        except ValidationError as exc:
            issues.append(_source_issue(
                "sources_invalid",
                f"Candidate Source schema validation failed: {exc}",
                source_index,
            ))

    if issues:
        raise CandidateSourceContractError(issues)
    try:
        return NormalizedCandidateSources(
            contract_version=contract_version, sources=normalized_sources
        )
    except ValidationError as exc:
        raise CandidateSourceContractError(
            [_source_issue("sources_invalid", f"sources.json is invalid: {exc}")]
        ) from exc


def serialize_candidate_sources(normalized: NormalizedCandidateSources) -> Any:
    """Serialize canonical sources back to a re-importable external contract."""
    if normalized.contract_version == CandidateContractVersion.V1:
        return {"sources": [
            {
                "source_id": source.source_id,
                "title": source.title,
                "source_type": source.source_type,
                "source_url": source.source_url,
                "raw_path": source.local_file,
            }
            for source in normalized.sources
        ]}

    serialized_sources = []
    for source in normalized.sources:
        item = {
            "source_id": source.source_id,
            "title": source.title,
            "organization": source.organization,
            "url": source.source_url,
            "local_file": source.local_file,
            "content_hash": source.content_hash,
            "raw_file_hash": source.raw_file_hash,
            "document_number": source.document_number,
            "publish_date": source.publish_date,
            "effective_date": source.effective_date,
            "source_level": source.source_level,
            "retrieved_at": source.retrieved_at,
            "source_type": source.source_type,
            "evidence_id": source.evidence_id,
        }
        serialized_sources.append({key: value for key, value in item.items() if value is not None})
    return serialized_sources


class CandidateKnowledgeStore:
    REQUIRED_FILES = ("document.md", "metadata.json", "sources.json")

    def __init__(self, candidate_root: Path | str = "candidate_knowledge"):
        self.candidate_root = Path(candidate_root)

    @staticmethod
    def _load_json(path: Path):
        return json.loads(path.read_text(encoding="utf-8"))

    @staticmethod
    def _issue(code: str, message: str, path: Optional[Path | str] = None) -> ImportIssue:
        return ImportIssue(code=code, message=message, path=str(path) if path else None)

    @staticmethod
    def _validate_candidate_id(candidate_id: str) -> Optional[ImportIssue]:
        if (
            not candidate_id or candidate_id in {".", ".."}
            or not _SAFE_ID_PATTERN.fullmatch(candidate_id)
        ):
            return ImportIssue(
                code="invalid_candidate_id",
                message="candidate_id must contain only letters, numbers, '.', '_', ':', or '-'",
            )
        return None

    def _find_document_id_owner(self, document_id: str) -> Optional[str]:
        if not self.candidate_root.exists():
            return None
        for candidate_dir in self.candidate_root.iterdir():
            if not candidate_dir.is_dir() or candidate_dir.name.startswith("."):
                continue
            metadata_path = candidate_dir / "metadata.json"
            if not metadata_path.is_file():
                continue
            try:
                metadata = CandidatePackageMetadata.model_validate(self._load_json(metadata_path))
            except (OSError, json.JSONDecodeError, ValidationError) as exc:
                raise ValueError(
                    f"Candidate store contains invalid metadata at '{metadata_path}': {exc}"
                ) from exc
            if metadata.document_id == document_id:
                return candidate_dir.name
        return None

    @staticmethod
    def _calculate_file_sha256(path: Path) -> str:
        digest = hashlib.sha256()
        with path.open("rb") as source_file:
            for block in iter(lambda: source_file.read(1024 * 1024), b""):
                digest.update(block)
        return digest.hexdigest()

    def _validate_raw_source(
        self, package_path: Path, source: CandidateSource,
        contract_version: CandidateContractVersion,
    ) -> List[ImportIssue]:
        local_file = source.local_file
        windows_path = PureWindowsPath(local_file)
        posix_path = PurePosixPath(local_file.replace("\\", "/"))
        source_path_label = f"sources.json:{source.source_id}.local_file"

        if windows_path.drive or windows_path.is_absolute() or posix_path.is_absolute():
            return [self._issue(
                "INVALID_LOCAL_FILE",
                f"Source {source.source_id} local_file must not be an absolute or drive-qualified path",
                source_path_label,
            )]
        if ".." in posix_path.parts:
            return [self._issue(
                "PATH_ESCAPE",
                f"Source {source.source_id} local_file contains a parent-directory escape",
                source_path_label,
            )]
        if not posix_path.parts or posix_path.parts[0] != "raw_sources":
            return [self._issue(
                "INVALID_LOCAL_FILE",
                f"Source {source.source_id} local_file must be under raw_sources/",
                source_path_label,
            )]

        candidate_path = package_path.joinpath(*posix_path.parts)
        current_path = package_path
        for part in posix_path.parts:
            current_path = current_path / part
            if current_path.is_symlink():
                return [self._issue(
                    "SYMLINK_NOT_ALLOWED",
                    f"Source {source.source_id} local_file may not traverse a symbolic link",
                    current_path,
                )]

        resolved_package = package_path.resolve()
        resolved_source = candidate_path.resolve()
        try:
            resolved_source.relative_to(resolved_package)
        except ValueError:
            return [self._issue(
                "PATH_ESCAPE",
                f"Source {source.source_id} local_file resolves outside the Candidate Package",
                resolved_source,
            )]
        if not resolved_source.exists():
            return [self._issue(
                "RAW_SOURCE_NOT_FOUND",
                f"Source {source.source_id} raw source file does not exist",
                resolved_source,
            )]
        if not resolved_source.is_file():
            return [self._issue(
                "INVALID_LOCAL_FILE",
                f"Source {source.source_id} local_file is not a regular file",
                resolved_source,
            )]

        if contract_version == CandidateContractVersion.V2:
            try:
                actual_hash = self._calculate_file_sha256(resolved_source)
            except OSError as exc:
                return [self._issue(
                    "INVALID_LOCAL_FILE",
                    f"Source {source.source_id} raw source cannot be read: {exc}",
                    resolved_source,
                )]
            if not hmac.compare_digest(actual_hash, source.raw_file_hash or ""):
                return [self._issue(
                    "RAW_FILE_HASH_MISMATCH",
                    f"Source {source.source_id} raw_file_hash does not match the raw file bytes",
                    resolved_source,
                )]
        return []

    @staticmethod
    def _hash_validation_statuses(normalized: Optional[NormalizedCandidateSources]):
        if normalized is None:
            return None, None
        if normalized.contract_version == CandidateContractVersion.V2:
            return (
                ContentHashValidationStatus.DECLARED_AND_FORMAT_VALIDATED,
                RawFileHashValidationStatus.RECOMPUTED_AND_VERIFIED,
            )
        return (
            ContentHashValidationStatus.NOT_DECLARED,
            RawFileHashValidationStatus.NOT_DECLARED,
        )

    def import_candidate(self, package_path: Path | str) -> ImportResult:
        package_path = Path(package_path)
        candidate_id = package_path.name
        issues: List[ImportIssue] = []
        metadata = None
        normalized_sources = None

        if not package_path.is_dir():
            return ImportResult(
                accepted=False, candidate_id=candidate_id or None,
                issues=[self._issue(
                    "package_missing", "Candidate Package directory does not exist", package_path
                )],
            )
        if package_path.is_symlink():
            issues.append(self._issue(
                "SYMLINK_NOT_ALLOWED", "Candidate Package root may not be a symbolic link", package_path
            ))

        candidate_id_issue = self._validate_candidate_id(candidate_id)
        if candidate_id_issue:
            issues.append(candidate_id_issue)

        for filename in self.REQUIRED_FILES:
            required_path = package_path / filename
            if not required_path.is_file():
                issues.append(self._issue(
                    f"{filename.replace('.', '_')}_missing",
                    f"Required file '{filename}' is missing", required_path,
                ))
        raw_sources_path = package_path / "raw_sources"
        if not raw_sources_path.is_dir():
            issues.append(self._issue(
                "raw_sources_missing", "Required directory 'raw_sources/' is missing", raw_sources_path
            ))

        for child in package_path.rglob("*"):
            if child.is_symlink():
                issues.append(self._issue(
                    "SYMLINK_NOT_ALLOWED", "Candidate Packages may not contain symbolic links", child
                ))

        metadata_path = package_path / "metadata.json"
        if metadata_path.is_file():
            try:
                metadata = CandidatePackageMetadata.model_validate(self._load_json(metadata_path))
            except (OSError, json.JSONDecodeError, ValidationError) as exc:
                issues.append(self._issue(
                    "metadata_invalid", f"metadata.json is invalid: {exc}", metadata_path
                ))
            else:
                if metadata.candidate.status != CandidateStatus.CANDIDATE:
                    issues.append(self._issue(
                        "candidate_status_invalid",
                        "Imported Agent packages must have status CANDIDATE", metadata_path,
                    ))
                if not metadata.candidate.requires_review:
                    issues.append(self._issue(
                        "review_required",
                        "Imported Agent packages must set requires_review=true", metadata_path,
                    ))

        sources_path = package_path / "sources.json"
        if sources_path.is_file():
            try:
                normalized_sources = normalize_candidate_sources(self._load_json(sources_path))
            except (OSError, json.JSONDecodeError) as exc:
                issues.append(self._issue(
                    "sources_invalid", f"sources.json is invalid JSON: {exc}", sources_path
                ))
            except CandidateSourceContractError as exc:
                issues.extend(exc.issues)

        document_path = package_path / "document.md"
        if document_path.is_file() and normalized_sources is not None:
            try:
                document_text = document_path.read_text(encoding="utf-8")
            except OSError as exc:
                issues.append(self._issue(
                    "document_unreadable", f"document.md cannot be read: {exc}", document_path
                ))
            else:
                declared_source_ids = {
                    source.source_id for source in normalized_sources.sources
                }
                cited_source_ids = {
                    match.strip() for match in _SOURCE_REFERENCE_PATTERN.findall(document_text)
                }
                for missing_source_id in sorted(cited_source_ids - declared_source_ids):
                    issues.append(self._issue(
                        "unknown_source_reference",
                        f"document.md references unknown source_id '{missing_source_id}'",
                        document_path,
                    ))

        if normalized_sources is not None and raw_sources_path.is_dir():
            for source in normalized_sources.sources:
                issues.extend(self._validate_raw_source(
                    package_path, source, normalized_sources.contract_version
                ))

        destination = self.candidate_root / candidate_id
        if destination.exists():
            issues.append(self._issue(
                "candidate_id_exists",
                f"candidate_id '{candidate_id}' already exists in Candidate Zone", destination,
            ))

        if metadata is not None:
            try:
                owner = self._find_document_id_owner(metadata.document_id)
            except ValueError as exc:
                issues.append(self._issue(
                    "candidate_store_invalid", str(exc), self.candidate_root
                ))
            else:
                if owner is not None:
                    issues.append(self._issue(
                        "duplicate_document_id",
                        f"document_id '{metadata.document_id}' already belongs to candidate '{owner}'",
                        self.candidate_root / owner,
                    ))

        content_hash_status, raw_file_hash_status = self._hash_validation_statuses(
            normalized_sources
        )
        if issues:
            if normalized_sources and normalized_sources.contract_version == CandidateContractVersion.V2:
                raw_file_hash_status = None
            return ImportResult(
                accepted=False,
                candidate_id=candidate_id,
                document_id=metadata.document_id if metadata else None,
                status=metadata.candidate.status if metadata else None,
                contract_version=(
                    normalized_sources.contract_version if normalized_sources else None
                ),
                content_hash_validation=content_hash_status,
                raw_file_hash_validation=raw_file_hash_status,
                issues=issues,
            )

        self.candidate_root.mkdir(parents=True, exist_ok=True)
        staging_path = Path(tempfile.mkdtemp(
            prefix=f".{candidate_id}-", dir=self.candidate_root
        ))
        try:
            shutil.copytree(package_path, staging_path, dirs_exist_ok=True)
            (staging_path / "metadata.json").write_text(
                json.dumps(
                    metadata.model_dump(mode="json", exclude_none=True),
                    ensure_ascii=False, indent=2,
                ),
                encoding="utf-8",
            )
            (staging_path / "sources.json").write_text(
                json.dumps(
                    serialize_candidate_sources(normalized_sources),
                    ensure_ascii=False, indent=2,
                ),
                encoding="utf-8",
            )
            staging_path.rename(destination)
        except Exception:
            shutil.rmtree(staging_path, ignore_errors=True)
            raise

        return ImportResult(
            accepted=True,
            candidate_id=candidate_id,
            document_id=metadata.document_id,
            status=metadata.candidate.status,
            contract_version=normalized_sources.contract_version,
            content_hash_validation=content_hash_status,
            raw_file_hash_validation=raw_file_hash_status,
            stored_path=str(destination.resolve()),
        )

    def approve_candidate(self, candidate_id: str) -> ApprovalResult:
        candidate_id_issue = self._validate_candidate_id(candidate_id)
        if candidate_id_issue:
            return ApprovalResult(
                approved=False, candidate_id=candidate_id, issues=[candidate_id_issue]
            )

        candidate_dir = self.candidate_root / candidate_id
        metadata_path = candidate_dir / "metadata.json"
        if not metadata_path.is_file():
            return ApprovalResult(
                approved=False,
                candidate_id=candidate_id,
                issues=[self._issue(
                    "candidate_missing", "Candidate does not exist", candidate_dir
                )],
            )

        try:
            metadata = CandidatePackageMetadata.model_validate(self._load_json(metadata_path))
        except (OSError, json.JSONDecodeError, ValidationError) as exc:
            return ApprovalResult(
                approved=False,
                candidate_id=candidate_id,
                issues=[self._issue(
                    "metadata_invalid", f"metadata.json is invalid: {exc}", metadata_path
                )],
            )

        previous_status = metadata.candidate.status
        if previous_status != CandidateStatus.APPROVED:
            metadata = metadata.model_copy(update={
                "candidate": metadata.candidate.model_copy(update={
                    "status": CandidateStatus.APPROVED,
                    "requires_review": False,
                })
            })
            temporary_path = metadata_path.with_suffix(".json.tmp")
            temporary_path.write_text(
                json.dumps(
                    metadata.model_dump(mode="json", exclude_none=True),
                    ensure_ascii=False, indent=2,
                ),
                encoding="utf-8",
            )
            temporary_path.replace(metadata_path)

        return ApprovalResult(
            approved=True,
            candidate_id=candidate_id,
            document_id=metadata.document_id,
            previous_status=previous_status,
            status=CandidateStatus.APPROVED,
            requires_review=False,
        )


def import_candidate(
    package_path: Path | str,
    candidate_root: Path | str = "candidate_knowledge",
) -> ImportResult:
    return CandidateKnowledgeStore(candidate_root).import_candidate(package_path)


def approve_candidate(
    candidate_id: str,
    candidate_root: Path | str = "candidate_knowledge",
) -> ApprovalResult:
    return CandidateKnowledgeStore(candidate_root).approve_candidate(candidate_id)
