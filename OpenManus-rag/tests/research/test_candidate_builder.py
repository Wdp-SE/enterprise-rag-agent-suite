import json
import shutil
from datetime import datetime, timezone
from pathlib import Path

import pytest

from app.research.candidate_builder import CandidateBuilder, CandidateBuilderError
from app.research.candidate_types import (
    CandidateBuildStatus,
    CandidateValidationResult,
    ValidationIssue,
)
from app.research.models import Evidence
from app.research.profile_loader import load_research_profile


PROJECT_ROOT = Path(__file__).resolve().parents[2]
EVIDENCE_FIXTURE = PROJECT_ROOT / "tests" / "fixtures" / "research" / "evidence.json"
PROFILE_PATH = PROJECT_ROOT / "config" / "research_profiles" / "special_equipment_validation.toml"


def prepare_workspace(tmp_path: Path) -> tuple[list[Evidence], object]:
    payload = json.loads(EVIDENCE_FIXTURE.read_text(encoding="utf-8"))
    for index, item in enumerate(payload, start=1):
        source = PROJECT_ROOT / item["local_file"]
        target = tmp_path / "raw_input" / source.name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, target)
        item["local_file"] = target.relative_to(tmp_path).as_posix()
    return [Evidence.model_validate(item) for item in payload], load_research_profile(PROFILE_PATH)


class ObservingValidator:
    def __init__(self, output_root: Path, accepted: bool = True):
        self.output_root = output_root
        self.accepted = accepted
        self.calls = 0

    def validate(self, package_path, **kwargs):
        self.calls += 1
        candidate_id = kwargs["expected_candidate_id"]
        assert not (self.output_root / candidate_id).exists()
        assert (Path(package_path) / "document.md").is_file()
        assert (Path(package_path) / "metadata.json").is_file()
        assert (Path(package_path) / "sources.json").is_file()
        if self.accepted:
            return CandidateValidationResult(accepted=True)
        return CandidateValidationResult(
            accepted=False,
            issues=[ValidationIssue(code="TEST_REJECTION", message="forced rejection")],
        )


class AcceptExistingValidator(ObservingValidator):
    def validate(self, package_path, **kwargs):
        self.calls += 1
        return CandidateValidationResult(accepted=True)


def test_candidate_builder_publishes_atomically_with_fixed_candidate_metadata(tmp_path: Path) -> None:
    evidence, profile = prepare_workspace(tmp_path)
    output_root = tmp_path / "candidate_knowledge"
    validator = ObservingValidator(output_root)
    builder = CandidateBuilder(
        workspace_root=tmp_path,
        validator=validator,
        clock=lambda: datetime(2026, 8, 28, tzinfo=timezone.utc),
    )

    result = builder.build(profile=profile, evidence_list=evidence[:2])
    package = tmp_path / result.package_path
    metadata = json.loads((package / "metadata.json").read_text(encoding="utf-8"))

    assert result.status is CandidateBuildStatus.CREATED
    assert metadata["candidate"] == {
        "created_at": "2026-08-28T00:00:00Z",
        "generated_by": "openmanus-agent",
        "requires_review": True,
        "status": "CANDIDATE",
    }
    assert not list(output_root.glob(".stage-*"))


def test_candidate_builder_does_not_publish_rejected_staging(tmp_path: Path) -> None:
    evidence, profile = prepare_workspace(tmp_path)
    output_root = tmp_path / "candidate_knowledge"
    builder = CandidateBuilder(
        workspace_root=tmp_path,
        validator=ObservingValidator(output_root, accepted=False),
    )

    with pytest.raises(CandidateBuilderError, match="TEST_REJECTION"):
        builder.build(profile=profile, evidence_list=evidence[:2])

    assert not [path for path in output_root.iterdir() if path.is_dir()]


def test_second_identical_build_returns_reused_without_overwrite(tmp_path: Path) -> None:
    evidence, profile = prepare_workspace(tmp_path)
    output_root = tmp_path / "candidate_knowledge"
    validator = AcceptExistingValidator(output_root)
    builder = CandidateBuilder(
        workspace_root=tmp_path,
        validator=validator,
        clock=lambda: datetime(2026, 8, 28, tzinfo=timezone.utc),
    )
    first = builder.build(profile=profile, evidence_list=evidence[:2])
    metadata_path = tmp_path / first.package_path / "metadata.json"
    original_bytes = metadata_path.read_bytes()
    original_mtime = metadata_path.stat().st_mtime_ns

    second = builder.build(profile=profile, evidence_list=list(reversed(evidence[:2])))

    assert first.candidate_id == second.candidate_id
    assert first.document_id == second.document_id
    assert second.status is CandidateBuildStatus.REUSED
    assert metadata_path.read_bytes() == original_bytes
    assert metadata_path.stat().st_mtime_ns == original_mtime
