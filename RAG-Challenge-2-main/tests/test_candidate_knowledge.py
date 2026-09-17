import hashlib
import json
from pathlib import Path

import pytest

from src.candidate_knowledge import (
    CandidateContractVersion,
    CandidateSourceContractError,
    CandidateStatus,
    ContentHashValidationStatus,
    RawFileHashValidationStatus,
    approve_candidate,
    detect_contract_version,
    import_candidate,
    normalize_candidate_sources,
)
from src.document_metadata import DocumentMetadata


def _create_package(tmp_path, candidate_id="candidate-001", document_id="document-001"):
    package = tmp_path / "incoming" / candidate_id
    raw_sources = package / "raw_sources"
    raw_sources.mkdir(parents=True)
    (package / "document.md").write_text(
        "# Candidate\n\nA reviewed fact [source:S01].\n",
        encoding="utf-8",
    )
    metadata = {
        "document_id": document_id,
        "title": "Candidate Document",
        "document_type": "technical_note",
        "source": "agent_research",
        "source_url": "https://example.test/source",
        "category": "engineering",
        "tags": ["candidate"],
        "legacy_company_name": None,
        "candidate": {
            "status": "CANDIDATE",
            "generated_by": "test-agent",
            "requires_review": True,
            "created_at": "2026-08-28T00:00:00+08:00",
        },
    }
    (package / "metadata.json").write_text(
        json.dumps(metadata), encoding="utf-8"
    )
    sources = {
        "sources": [
            {
                "source_id": "S01",
                "title": "Source One",
                "source_type": "html",
                "source_url": "https://example.test/source",
                "raw_path": "raw_sources/source.html",
            }
        ]
    }
    (package / "sources.json").write_text(json.dumps(sources), encoding="utf-8")
    (raw_sources / "source.html").write_text(
        "<html><body>A reviewed fact.</body></html>", encoding="utf-8"
    )
    return package


def _create_v2_package(
    tmp_path,
    candidate_id="candidate-v2",
    document_id="document-v2",
    *,
    local_file="raw_sources/source.html",
    content_hash=None,
    raw_file_hash=None,
):
    package = _create_package(tmp_path, candidate_id, document_id)
    raw_bytes = b"<html><body>Hash-aware raw source.</body></html>"
    raw_file = package / "raw_sources" / "source.html"
    raw_file.write_bytes(raw_bytes)
    source = {
        "source_id": "S01",
        "title": "Hash-aware Source",
        "organization": "Example Organization",
        "url": "https://example.test/v2-source",
        "local_file": local_file,
        "content_hash": content_hash or ("A" * 64),
        "raw_file_hash": raw_file_hash or hashlib.sha256(raw_bytes).hexdigest(),
        "document_number": "DOC-2026-01",
        "publish_date": "2026-01-01",
        "effective_date": "2026-02-01",
        "source_level": "TIER1",
        "retrieved_at": "2026-08-28T08:00:00Z",
        "source_type": "webpage",
        "evidence_id": "ev_example_001",
    }
    (package / "sources.json").write_text(
        json.dumps([source]), encoding="utf-8"
    )
    return package


def _read_sources(package):
    return json.loads((package / "sources.json").read_text(encoding="utf-8"))


def _write_sources(package, payload):
    (package / "sources.json").write_text(json.dumps(payload), encoding="utf-8")


def _issue_codes(result):
    return {issue.code for issue in result.issues}


def test_valid_candidate_package_is_imported(tmp_path):
    package = _create_package(tmp_path)
    candidate_root = tmp_path / "candidate_knowledge"

    result = import_candidate(package, candidate_root)

    assert result.accepted is True
    assert result.status == CandidateStatus.CANDIDATE
    assert result.document_id == "document-001"
    assert result.ingestion_performed is False
    assert (candidate_root / "candidate-001" / "document.md").is_file()
    assert (candidate_root / "candidate-001" / "raw_sources" / "source.html").is_file()


def test_candidate_metadata_remains_compatible_with_document_metadata(tmp_path):
    package = _create_package(tmp_path)
    payload = json.loads((package / "metadata.json").read_text(encoding="utf-8"))

    metadata = DocumentMetadata.model_validate(payload)

    assert metadata.document_id == "document-001"


@pytest.mark.parametrize(
    ("missing_path", "expected_code"),
    [
        ("metadata.json", "metadata_json_missing"),
        ("sources.json", "sources_json_missing"),
        ("document.md", "document_md_missing"),
    ],
)
def test_missing_required_candidate_file_is_rejected(
    tmp_path, missing_path, expected_code
):
    package = _create_package(tmp_path)
    (package / missing_path).unlink()
    candidate_root = tmp_path / "candidate_knowledge"

    result = import_candidate(package, candidate_root)

    assert result.accepted is False
    assert expected_code in _issue_codes(result)
    assert not (candidate_root / package.name).exists()


def test_unknown_document_source_reference_is_rejected(tmp_path):
    package = _create_package(tmp_path)
    (package / "document.md").write_text(
        "Unsupported citation [source:S99].", encoding="utf-8"
    )

    result = import_candidate(package, tmp_path / "candidate_knowledge")

    assert result.accepted is False
    assert "unknown_source_reference" in _issue_codes(result)


def test_duplicate_document_id_is_rejected(tmp_path):
    candidate_root = tmp_path / "candidate_knowledge"
    first_package = _create_package(
        tmp_path, candidate_id="candidate-001", document_id="same-document"
    )
    assert import_candidate(first_package, candidate_root).accepted is True
    second_package = _create_package(
        tmp_path, candidate_id="candidate-002", document_id="same-document"
    )

    result = import_candidate(second_package, candidate_root)

    assert result.accepted is False
    assert "duplicate_document_id" in _issue_codes(result)
    assert not (candidate_root / "candidate-002").exists()


def test_import_never_writes_vector_database(tmp_path):
    package = _create_package(tmp_path)
    candidate_root = tmp_path / "candidate_knowledge"
    vector_dir = tmp_path / "vector_dbs"
    vector_dir.mkdir()
    sentinel = vector_dir / "existing.faiss"
    sentinel.write_bytes(b"unchanged")

    result = import_candidate(package, candidate_root)

    assert result.accepted is True
    assert sentinel.read_bytes() == b"unchanged"
    assert list(candidate_root.rglob("*.faiss")) == []
    assert result.ingestion_performed is False


def test_approve_candidate_only_changes_review_state(tmp_path):
    package = _create_package(tmp_path)
    candidate_root = tmp_path / "candidate_knowledge"
    assert import_candidate(package, candidate_root).accepted is True

    result = approve_candidate("candidate-001", candidate_root)
    stored_metadata = json.loads(
        (candidate_root / "candidate-001" / "metadata.json").read_text(encoding="utf-8")
    )

    assert result.approved is True
    assert result.previous_status == CandidateStatus.CANDIDATE
    assert result.status == CandidateStatus.APPROVED
    assert result.requires_review is False
    assert result.ingestion_performed is False
    assert stored_metadata["candidate"]["status"] == "APPROVED"
    assert stored_metadata["candidate"]["requires_review"] is False
    assert list(candidate_root.rglob("*.faiss")) == []


def test_agent_cannot_import_a_preapproved_package(tmp_path):
    package = _create_package(tmp_path)
    metadata_path = package / "metadata.json"
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    metadata["candidate"]["status"] = "APPROVED"
    metadata["candidate"]["requires_review"] = False
    metadata_path.write_text(json.dumps(metadata), encoding="utf-8")

    result = import_candidate(package, tmp_path / "candidate_knowledge")

    assert result.accepted is False
    assert "candidate_status_invalid" in _issue_codes(result)


def test_repository_sample_candidate_package_is_importable(tmp_path):
    sample_package = (
        Path(__file__).resolve().parents[1] / "examples" / "sample_candidate_package"
    )

    result = import_candidate(sample_package, tmp_path / "candidate_knowledge")

    assert result.accepted is True
    assert result.document_id == "sample-generic-rag-interface-v1"


def test_contract_version_detection_supports_v1_wrapper_and_v2_list():
    v1_payload = {
        "sources": [{
            "source_id": "S01",
            "title": "Source",
            "source_url": "https://example.test/source",
            "raw_path": "raw_sources/source.html",
        }]
    }
    v2_payload = [{
        "source_id": "S01",
        "title": "Source",
        "organization": "Organization",
        "url": "https://example.test/source",
        "local_file": "raw_sources/source.html",
        "content_hash": "a" * 64,
        "raw_file_hash": "b" * 64,
    }]

    assert detect_contract_version(v1_payload) == CandidateContractVersion.V1
    assert detect_contract_version(v2_payload) == CandidateContractVersion.V2


def test_v1_import_preserves_wrapper_and_legacy_aliases(tmp_path):
    package = _create_package(tmp_path)
    candidate_root = tmp_path / "candidate_knowledge"

    result = import_candidate(package, candidate_root)
    stored_sources = _read_sources(candidate_root / package.name)

    assert result.accepted is True
    assert result.contract_version == CandidateContractVersion.V1
    assert isinstance(stored_sources, dict)
    assert stored_sources["sources"][0]["source_url"] == "https://example.test/source"
    assert stored_sources["sources"][0]["raw_path"] == "raw_sources/source.html"


def test_v2_root_list_hashes_and_optional_metadata_are_preserved(tmp_path):
    package = _create_v2_package(tmp_path)
    candidate_root = tmp_path / "candidate_knowledge"

    result = import_candidate(package, candidate_root)
    stored_sources = _read_sources(candidate_root / package.name)

    assert result.accepted is True
    assert result.contract_version == CandidateContractVersion.V2
    assert result.content_hash_validation == (
        ContentHashValidationStatus.DECLARED_AND_FORMAT_VALIDATED
    )
    assert result.raw_file_hash_validation == (
        RawFileHashValidationStatus.RECOMPUTED_AND_VERIFIED
    )
    assert isinstance(stored_sources, list)
    assert stored_sources[0]["url"] == "https://example.test/v2-source"
    assert stored_sources[0]["local_file"] == "raw_sources/source.html"
    assert stored_sources[0]["content_hash"] == "a" * 64
    assert stored_sources[0]["document_number"] == "DOC-2026-01"
    assert stored_sources[0]["evidence_id"] == "ev_example_001"


def test_valid_content_hash_may_differ_from_verified_raw_file_hash(tmp_path):
    package = _create_v2_package(tmp_path, content_hash="1" * 64)
    declared = _read_sources(package)[0]

    result = import_candidate(package, tmp_path / "candidate_knowledge")

    assert declared["content_hash"] != declared["raw_file_hash"]
    assert result.accepted is True
    assert result.content_hash_validation.value == "DECLARED_AND_FORMAT_VALIDATED"
    assert result.raw_file_hash_validation.value == "RECOMPUTED_AND_VERIFIED"


def test_raw_file_hash_mismatch_is_rejected(tmp_path):
    package = _create_v2_package(tmp_path, raw_file_hash="0" * 64)

    result = import_candidate(package, tmp_path / "candidate_knowledge")

    assert result.accepted is False
    assert "RAW_FILE_HASH_MISMATCH" in _issue_codes(result)
    assert result.raw_file_hash_validation is None


@pytest.mark.parametrize(
    ("field_name", "field_value", "expected_code"),
    [
        ("content_hash", "not-a-sha256", "INVALID_CONTENT_HASH"),
        ("raw_file_hash", "1234", "INVALID_RAW_FILE_HASH"),
    ],
)
def test_v2_hash_format_is_strict(tmp_path, field_name, field_value, expected_code):
    package = _create_v2_package(tmp_path)
    sources = _read_sources(package)
    sources[0][field_name] = field_value
    _write_sources(package, sources)

    result = import_candidate(package, tmp_path / "candidate_knowledge")

    assert result.accepted is False
    assert expected_code in _issue_codes(result)


def test_v2_fields_inside_v1_wrapper_cannot_bypass_hash_requirements(tmp_path):
    package = _create_v2_package(tmp_path)
    source = _read_sources(package)[0]
    source.pop("content_hash")
    _write_sources(package, {"sources": [source]})

    result = import_candidate(package, tmp_path / "candidate_knowledge")

    assert result.accepted is False
    assert "INVALID_CONTENT_HASH" in _issue_codes(result)


@pytest.mark.parametrize(
    ("unsafe_path", "expected_code"),
    [
        (r"C:\temp\source.html", "INVALID_LOCAL_FILE"),
        (r"D:\source.html", "INVALID_LOCAL_FILE"),
        (r"\\server\share\source.html", "INVALID_LOCAL_FILE"),
        ("/tmp/source.html", "INVALID_LOCAL_FILE"),
        ("raw_sources/../outside.html", "PATH_ESCAPE"),
        (r"raw_sources\..\outside.html", "PATH_ESCAPE"),
    ],
)
def test_cross_platform_unsafe_local_file_is_rejected(
    tmp_path, unsafe_path, expected_code
):
    package = _create_v2_package(tmp_path, local_file=unsafe_path)

    result = import_candidate(package, tmp_path / "candidate_knowledge")

    assert result.accepted is False
    assert expected_code in _issue_codes(result)


def test_missing_v2_raw_source_is_rejected(tmp_path):
    package = _create_v2_package(
        tmp_path, local_file="raw_sources/missing.html"
    )

    result = import_candidate(package, tmp_path / "candidate_knowledge")

    assert result.accepted is False
    assert "RAW_SOURCE_NOT_FOUND" in _issue_codes(result)


def test_symlinked_v2_raw_source_is_rejected(tmp_path, monkeypatch):
    package = _create_v2_package(tmp_path)
    raw_file = package / "raw_sources" / "source.html"
    path_type = type(raw_file)
    original_is_symlink = path_type.is_symlink

    def fake_is_symlink(path):
        return path == raw_file or original_is_symlink(path)

    monkeypatch.setattr(path_type, "is_symlink", fake_is_symlink)

    result = import_candidate(package, tmp_path / "candidate_knowledge")

    assert result.accepted is False
    assert "SYMLINK_NOT_ALLOWED" in _issue_codes(result)


def test_unknown_v2_source_field_is_not_silently_accepted(tmp_path):
    package = _create_v2_package(tmp_path)
    sources = _read_sources(package)
    sources[0]["organziation"] = "misspelled field"
    _write_sources(package, sources)

    result = import_candidate(package, tmp_path / "candidate_knowledge")

    assert result.accepted is False
    assert "UNKNOWN_SOURCE_FIELD" in _issue_codes(result)


def test_equal_legacy_and_v2_aliases_are_allowed(tmp_path):
    package = _create_v2_package(tmp_path)
    sources = _read_sources(package)
    sources[0]["source_url"] = sources[0]["url"]
    sources[0]["raw_path"] = r"raw_sources\source.html"
    _write_sources(package, sources)

    result = import_candidate(package, tmp_path / "candidate_knowledge")

    assert result.accepted is True


@pytest.mark.parametrize(
    ("legacy_name", "legacy_value"),
    [
        ("source_url", "https://different.example.test/source"),
        ("raw_path", "raw_sources/different.html"),
    ],
)
def test_conflicting_source_aliases_are_rejected(
    tmp_path, legacy_name, legacy_value
):
    package = _create_v2_package(tmp_path)
    sources = _read_sources(package)
    sources[0][legacy_name] = legacy_value
    _write_sources(package, sources)

    result = import_candidate(package, tmp_path / "candidate_knowledge")

    assert result.accepted is False
    assert "SOURCE_ALIAS_CONFLICT" in _issue_codes(result)


def test_v1_and_v2_normalize_to_the_same_common_source_semantics():
    v1 = normalize_candidate_sources({
        "sources": [{
            "source_id": "S01",
            "title": "Source",
            "source_type": "webpage",
            "source_url": "https://example.test/source",
            "raw_path": r"raw_sources\source.html",
        }]
    }).sources[0]
    v2 = normalize_candidate_sources([{
        "source_id": "S01",
        "title": "Source",
        "organization": "Organization",
        "source_type": "webpage",
        "url": "https://example.test/source",
        "local_file": "raw_sources/source.html",
        "content_hash": "1" * 64,
        "raw_file_hash": "2" * 64,
    }]).sources[0]

    assert (v1.source_id, v1.title, v1.source_url, v1.local_file, v1.source_type) == (
        v2.source_id,
        v2.title,
        v2.source_url,
        v2.local_file,
        v2.source_type,
    )


def test_v2_import_still_does_not_write_faiss_or_approve(tmp_path):
    package = _create_v2_package(tmp_path)
    candidate_root = tmp_path / "candidate_knowledge"
    vector_dir = tmp_path / "vector_dbs"
    vector_dir.mkdir()
    sentinel = vector_dir / "existing.faiss"
    sentinel.write_bytes(b"unchanged")

    result = import_candidate(package, candidate_root)
    stored_metadata = json.loads(
        (candidate_root / package.name / "metadata.json").read_text(encoding="utf-8")
    )

    assert result.accepted is True
    assert result.ingestion_performed is False
    assert sentinel.read_bytes() == b"unchanged"
    assert list(candidate_root.rglob("*.faiss")) == []
    assert stored_metadata["candidate"]["status"] == "CANDIDATE"


def test_repository_v2_sample_candidate_package_is_importable(tmp_path):
    sample_package = (
        Path(__file__).resolve().parents[1]
        / "examples"
        / "sample_candidate_package_v2"
    )

    result = import_candidate(sample_package, tmp_path / "candidate_knowledge")

    assert result.accepted is True
    assert result.contract_version == CandidateContractVersion.V2
    assert result.document_id == "sample-candidate-interface-v2"
    assert result.content_hash_validation.value == "DECLARED_AND_FORMAT_VALIDATED"
    assert result.raw_file_hash_validation.value == "RECOMPUTED_AND_VERIFIED"
