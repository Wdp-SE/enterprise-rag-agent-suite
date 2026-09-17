import asyncio
import hashlib
import json
import shutil
from datetime import datetime, timezone
from pathlib import Path

from app.research.candidate_builder import CandidateBuilder
from app.research.candidate_types import CandidateBuildStatus
from app.research.candidate_validator import CandidateValidator
from app.research.evidence_store import EvidenceStore
from app.research.models import Evidence
from app.research.profile_loader import load_research_profile
from app.research.source_policy import SourcePolicy
from app.tool.knowledge_draft import KnowledgeDraftTool


PROJECT_ROOT = Path(__file__).resolve().parents[2]
EVIDENCE_FIXTURE = PROJECT_ROOT / "tests" / "fixtures" / "research" / "evidence.json"
PROFILE_PATH = PROJECT_ROOT / "config" / "research_profiles" / "special_equipment_validation.toml"
POLICY_PATH = PROJECT_ROOT / "config" / "research_policies" / "default.toml"


def package_digest(package: Path) -> str:
    digest = hashlib.sha256()
    for path in sorted(item for item in package.rglob("*") if item.is_file()):
        digest.update(path.relative_to(package).as_posix().encode("utf-8"))
        digest.update(path.read_bytes())
    return digest.hexdigest()


def test_offline_evidence_to_candidate_package_is_valid_and_repeatable(tmp_path: Path) -> None:
    profile = load_research_profile(PROFILE_PATH)
    policy = SourcePolicy.from_toml(POLICY_PATH)
    payload = json.loads(EVIDENCE_FIXTURE.read_text(encoding="utf-8"))
    evidence_list: list[Evidence] = []
    for item in payload:
        source = PROJECT_ROOT / item["local_file"]
        local_source = tmp_path / "raw_input" / source.name
        local_source.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, local_source)
        item["local_file"] = local_source.relative_to(tmp_path).as_posix()
        item["source_level"] = policy.classify(
            source_url=item["source_url"], source_type=item["source_type"]
        ).level.value
        evidence_list.append(Evidence.model_validate(item))

    store = EvidenceStore(tmp_path, "research_state/evidence.json")
    for evidence in evidence_list:
        store.add(evidence)
    store.save()
    store = EvidenceStore(tmp_path, "research_state/evidence.json").load()

    validator = CandidateValidator()
    builder = CandidateBuilder(
        workspace_root=tmp_path,
        validator=validator,
        clock=lambda: datetime(2026, 8, 28, tzinfo=timezone.utc),
    )
    tool = KnowledgeDraftTool(
        profile=profile,
        evidence_store=store,
        candidate_builder=builder,
    )
    call = {
        "research_topic": profile.research_topic,
        "domain": profile.domain,
        "category": profile.knowledge_category,
        "evidence_ids": [item.evidence_id for item in reversed(evidence_list)],
    }

    first = json.loads(asyncio.run(tool.execute(**call)).output)
    package = tmp_path / first["package_path"]
    first_digest = package_digest(package)
    validation = validator.validate(
        package,
        evidence_by_id={item.evidence_id: item for item in evidence_list},
        expected_candidate_id=first["candidate_id"],
        expected_document_id=first["document_id"],
    )
    sources = json.loads((package / "sources.json").read_text(encoding="utf-8"))

    assert first["status"] == CandidateBuildStatus.CREATED.value
    assert validation.accepted, validation.issues
    assert all(source["content_hash"] != source["raw_file_hash"] for source in sources)

    call["evidence_ids"] = list(reversed(call["evidence_ids"]))
    second = json.loads(asyncio.run(tool.execute(**call)).output)

    assert second["status"] == CandidateBuildStatus.REUSED.value
    assert second["candidate_id"] == first["candidate_id"]
    assert second["document_id"] == first["document_id"]
    assert package_digest(package) == first_digest
