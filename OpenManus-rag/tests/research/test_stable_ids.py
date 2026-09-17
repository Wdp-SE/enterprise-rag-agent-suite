import json
import random
from pathlib import Path

from app.research.identifiers import (
    assign_source_ids,
    stable_candidate_id,
    stable_document_id,
)
from app.research.models import Evidence


PROJECT_ROOT = Path(__file__).resolve().parents[2]
EVIDENCE_FIXTURE = PROJECT_ROOT / "tests" / "fixtures" / "research" / "evidence.json"


def fixture_evidence() -> list[Evidence]:
    payload = json.loads(EVIDENCE_FIXTURE.read_text(encoding="utf-8"))
    return [Evidence.model_validate(item) for item in payload]


def identity_args(evidence: list[Evidence]) -> dict:
    return {
        "domain": "special_equipment_validation",
        "research_topic": "特种设备使用单位基本安全管理要求",
        "category": "safety_management",
        "evidence_list": evidence,
    }


def test_candidate_id_is_stable() -> None:
    evidence = fixture_evidence()

    first = stable_candidate_id(**identity_args(evidence))
    second = stable_candidate_id(**identity_args(list(reversed(evidence))))

    assert first == second
    assert first.startswith("cand_special-equipment-validation_")


def test_document_id_is_stable_and_distinct_from_candidate_id() -> None:
    evidence = fixture_evidence()

    document_id = stable_document_id(**identity_args(evidence))

    assert document_id == stable_document_id(**identity_args(evidence.copy()))
    assert document_id.startswith("doc_special-equipment-validation_")
    assert document_id != stable_candidate_id(**identity_args(evidence))


def test_source_ids_do_not_change_when_evidence_order_is_shuffled() -> None:
    evidence = fixture_evidence()
    shuffled = evidence.copy()
    random.Random(20260828).shuffle(shuffled)

    first = {item.evidence.evidence_id: item.source_id for item in assign_source_ids(evidence)}
    second = {item.evidence.evidence_id: item.source_id for item in assign_source_ids(shuffled)}

    assert first == second
    assert sorted(first.values()) == ["S01", "S02", "S03"]
