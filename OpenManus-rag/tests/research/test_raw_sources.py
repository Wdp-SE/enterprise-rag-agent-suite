import json
from pathlib import Path

import pytest

from app.research.models import Evidence
from app.research.raw_source_archive import RawSourceArchive, RawSourceArchiveError


PROJECT_ROOT = Path(__file__).resolve().parents[2]
EVIDENCE_FIXTURE = PROJECT_ROOT / "tests" / "fixtures" / "research" / "evidence.json"


def fixture_evidence() -> list[Evidence]:
    payload = json.loads(EVIDENCE_FIXTURE.read_text(encoding="utf-8"))
    return [Evidence.model_validate(item) for item in payload]


def test_raw_source_archive_rejects_path_escape(tmp_path: Path) -> None:
    archive = RawSourceArchive(tmp_path, tmp_path / "candidate")

    with pytest.raises(RawSourceArchiveError, match="escapes"):
        archive.archive_path("../outside.pdf")


def test_raw_source_archive_rejects_symlink(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    source = tmp_path / "source.txt"
    source.write_text("offline source", encoding="utf-8")
    original_is_symlink = Path.is_symlink

    def pretend_source_is_symlink(path: Path) -> bool:
        return path == source or original_is_symlink(path)

    monkeypatch.setattr(Path, "is_symlink", pretend_source_is_symlink)
    archive = RawSourceArchive(tmp_path, tmp_path / "candidate")

    with pytest.raises(RawSourceArchiveError, match="symlinks"):
        archive.archive_path("source.txt")


def test_raw_file_hash_uses_original_bytes_and_is_separate_from_content_hash(
    tmp_path: Path,
) -> None:
    evidence = fixture_evidence()[0]
    archive = RawSourceArchive(PROJECT_ROOT, tmp_path / "candidate")

    archived = archive.archive(evidence)

    assert archived.raw_file_hash == "32f87daacbdcb603a9c587ae8c0b278139546f8dbcc104766537f639de84ebf9"
    assert archived.raw_file_hash != evidence.content_hash
    assert (tmp_path / "candidate" / archived.local_file).is_file()


def test_same_raw_source_is_archived_only_once(tmp_path: Path) -> None:
    evidence = fixture_evidence()[1]
    archive = RawSourceArchive(PROJECT_ROOT, tmp_path / "candidate")

    first = archive.archive(evidence)
    second = archive.archive(evidence)

    assert first.local_file == second.local_file
    assert first.raw_file_hash == second.raw_file_hash
    assert not first.reused
    assert second.reused
    assert len(list((tmp_path / "candidate" / "raw_sources").iterdir())) == 1
