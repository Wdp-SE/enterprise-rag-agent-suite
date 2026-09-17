import json
from pathlib import Path

from app.research.drafting import DeterministicDraftGenerator
from app.research.identifiers import assign_source_ids
from app.research.models import Evidence


PROJECT_ROOT = Path(__file__).resolve().parents[2]
EVIDENCE_FIXTURE = PROJECT_ROOT / "tests" / "fixtures" / "research" / "evidence.json"


def fixture_evidence() -> list[Evidence]:
    payload = json.loads(EVIDENCE_FIXTURE.read_text(encoding="utf-8"))
    return [Evidence.model_validate(item) for item in payload]


def test_deterministic_draft_is_stable_and_every_fact_has_source() -> None:
    evidence = fixture_evidence()
    generator = DeterministicDraftGenerator()
    kwargs = {
        "title": "离线研究主题",
        "domain": "generic_validation",
        "category": "safety_management",
        "required_sections": ["核心知识", "资料边界", "来源"],
    }

    first = generator.generate(sources=assign_source_ids(evidence), **kwargs)
    second = generator.generate(sources=assign_source_ids(list(reversed(evidence))), **kwargs)

    assert first == second
    for assignment in assign_source_ids(evidence):
        assert f"{assignment.evidence.content} [source:{assignment.source_id}]" in first


def test_deterministic_draft_adds_contract_sections() -> None:
    document = DeterministicDraftGenerator().generate(
        title="离线研究主题",
        domain="generic_validation",
        category="category",
        sources=assign_source_ids(fixture_evidence()),
        required_sections=["自定义章节"],
    )

    assert "## 自定义章节" in document
    assert "## 概述" in document
    assert "## 核心知识" in document
    assert "## 主要要求" in document
    assert "## 注意事项" in document
    assert "## 资料边界" in document
    assert "## 来源" in document
    assert "当前 Evidence 未支持" in document
