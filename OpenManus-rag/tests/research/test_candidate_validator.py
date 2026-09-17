import json
import shutil
from pathlib import Path

from app.research.candidate_validator import CandidateValidator
from app.research.models import Evidence


PROJECT_ROOT = Path(__file__).resolve().parents[2]
VALID_PACKAGE = PROJECT_ROOT / "tests" / "fixtures" / "candidate" / "valid_candidate"
EVIDENCE_FIXTURE = PROJECT_ROOT / "tests" / "fixtures" / "research" / "evidence.json"


def evidence_by_id() -> dict[str, Evidence]:
    payload = json.loads(EVIDENCE_FIXTURE.read_text(encoding="utf-8"))
    evidence = [Evidence.model_validate(item) for item in payload]
    return {item.evidence_id: item for item in evidence}


def copy_package(tmp_path: Path) -> Path:
    target = tmp_path / "candidate"
    shutil.copytree(VALID_PACKAGE, target)
    return target


def issue_codes(result) -> set[str]:
    return {issue.code for issue in result.issues}


def test_valid_fixture_accepts_distinct_content_and_raw_hashes() -> None:
    result = CandidateValidator().validate(
        VALID_PACKAGE,
        evidence_by_id=evidence_by_id(),
        expected_candidate_id="cand_fixture-valid_0000000000000001",
        expected_document_id="doc_fixture-valid_0000000000000001",
    )
    sources = json.loads((VALID_PACKAGE / "sources.json").read_text(encoding="utf-8"))

    assert result.accepted, result.issues
    assert all(item["content_hash"] != item["raw_file_hash"] for item in sources)


def test_wrong_evidence_content_hash_is_rejected(tmp_path: Path) -> None:
    package = copy_package(tmp_path)
    sources_path = package / "sources.json"
    sources = json.loads(sources_path.read_text(encoding="utf-8"))
    sources[0]["content_hash"] = "0" * 64
    sources_path.write_text(json.dumps(sources, ensure_ascii=False), encoding="utf-8")

    result = CandidateValidator().validate(package, evidence_by_id=evidence_by_id())

    assert not result.accepted
    assert "CONTENT_HASH_MISMATCH" in issue_codes(result)
    assert "RAW_FILE_HASH_MISMATCH" not in issue_codes(result)


def test_wrong_raw_file_hash_is_rejected_separately(tmp_path: Path) -> None:
    package = copy_package(tmp_path)
    sources = json.loads((package / "sources.json").read_text(encoding="utf-8"))
    raw_path = package / sources[0]["local_file"]
    raw_path.write_bytes(raw_path.read_bytes() + b"tampered")

    result = CandidateValidator().validate(package, evidence_by_id=evidence_by_id())

    assert not result.accepted
    assert "RAW_FILE_HASH_MISMATCH" in issue_codes(result)
    assert "CONTENT_HASH_MISMATCH" not in issue_codes(result)


def test_unknown_source_citation_is_rejected(tmp_path: Path) -> None:
    package = copy_package(tmp_path)
    document_path = package / "document.md"
    document_path.write_text(
        document_path.read_text(encoding="utf-8") + "\n非法引用。[source:S99]\n",
        encoding="utf-8",
    )

    result = CandidateValidator().validate(package, evidence_by_id=evidence_by_id())

    assert "UNKNOWN_CITATION" in issue_codes(result)


def test_missing_raw_source_is_rejected(tmp_path: Path) -> None:
    package = copy_package(tmp_path)
    sources = json.loads((package / "sources.json").read_text(encoding="utf-8"))
    (package / sources[0]["local_file"]).unlink()

    result = CandidateValidator().validate(package, evidence_by_id=evidence_by_id())

    assert "MISSING_RAW_SOURCE" in issue_codes(result)


def test_approved_metadata_is_rejected(tmp_path: Path) -> None:
    package = copy_package(tmp_path)
    metadata_path = package / "metadata.json"
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    metadata["candidate"]["status"] = "APPROVED"
    metadata_path.write_text(json.dumps(metadata, ensure_ascii=False), encoding="utf-8")

    result = CandidateValidator().validate(package, evidence_by_id=evidence_by_id())

    assert "INVALID_METADATA" in issue_codes(result)
