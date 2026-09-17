import asyncio
import json
from pathlib import Path

import pytest


PROJECT_ROOT = Path(__file__).resolve().parents[2]
from app.research.candidate_types import CandidateBuildResult, CandidateBuildStatus
from app.research.evidence_store import EvidenceStore
from app.research.models import Evidence
from app.research.profile_loader import load_research_profile
from app.tool.knowledge_draft import KnowledgeDraftTool


EVIDENCE_FIXTURE = PROJECT_ROOT / "tests" / "fixtures" / "research" / "evidence.json"
PROFILE_PATH = PROJECT_ROOT / "config" / "research_profiles" / "special_equipment_validation.toml"


class RecordingBuilder:
    def __init__(self) -> None:
        self.calls = []

    def build(self, *, profile, evidence_list):
        self.calls.append((profile, evidence_list))
        return CandidateBuildResult(
            status=CandidateBuildStatus.CREATED,
            candidate_id="cand_test_1234567890abcdef",
            document_id="doc_test_1234567890abcdef",
            package_path="candidate_knowledge/cand_test_1234567890abcdef",
        )


def make_tool() -> tuple[KnowledgeDraftTool, RecordingBuilder, list[Evidence]]:
    evidence_payload = json.loads(EVIDENCE_FIXTURE.read_text(encoding="utf-8"))
    evidence = [Evidence.model_validate(item) for item in evidence_payload]
    store = EvidenceStore(PROJECT_ROOT, "workspace/research-test-evidence.json")
    for item in evidence:
        store.add(item)
    builder = RecordingBuilder()
    tool = KnowledgeDraftTool(
        profile=load_research_profile(PROFILE_PATH),
        evidence_store=store,
        candidate_builder=builder,
    )
    return tool, builder, evidence


def test_insufficient_evidence_does_not_call_builder() -> None:
    tool, builder, evidence = make_tool()

    result = asyncio.run(
        tool.execute(
            research_topic=tool.profile.research_topic,
            domain=tool.profile.domain,
            category=tool.profile.knowledge_category,
            evidence_ids=[evidence[0].evidence_id],
        )
    )
    payload = json.loads(result.output)

    assert payload["status"] == "INSUFFICIENT_EVIDENCE"
    assert builder.calls == []


def test_valid_evidence_is_forwarded_to_builder() -> None:
    tool, builder, evidence = make_tool()

    result = asyncio.run(
        tool.execute(
            research_topic=tool.profile.research_topic,
            domain=tool.profile.domain,
            category=tool.profile.knowledge_category,
            evidence_ids=[evidence[1].evidence_id, evidence[0].evidence_id],
        )
    )
    payload = json.loads(result.output)

    assert payload["status"] == "CREATED"
    assert len(builder.calls) == 1
    assert sorted(item.evidence_id for item in builder.calls[0][1]) == sorted(
        [evidence[0].evidence_id, evidence[1].evidence_id]
    )


def test_tool_schema_does_not_accept_approval_status() -> None:
    tool, _, _ = make_tool()

    assert "status" not in tool.parameters["properties"]
    assert tool.parameters["additionalProperties"] is False
