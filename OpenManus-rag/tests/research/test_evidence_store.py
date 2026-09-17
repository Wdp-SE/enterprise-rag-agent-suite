import json
from pathlib import Path

from app.research.evidence_store import EvidenceAddStatus, EvidenceStore
from app.research.models import Evidence


PROJECT_ROOT = Path(__file__).resolve().parents[2]
EVIDENCE_FIXTURE = PROJECT_ROOT / "tests" / "fixtures" / "research" / "evidence.json"


def fixture_evidence() -> list[Evidence]:
    payload = json.loads(EVIDENCE_FIXTURE.read_text(encoding="utf-8"))
    return [Evidence.model_validate(item) for item in payload]


def test_evidence_store_deduplicates_by_source_identity_and_content_hash(tmp_path: Path) -> None:
    source = fixture_evidence()[0]
    payload = source.model_dump(mode="json", exclude={"evidence_id", "content_hash"})
    payload["local_file"] = None
    source_without_file = Evidence.model_validate(payload)
    second_payload = source_without_file.model_dump(
        mode="json", exclude={"evidence_id", "content_hash"}
    )
    second_payload["section"] = "同来源中的另一个位置"
    same_fact_other_location = Evidence.model_validate(second_payload)
    store = EvidenceStore(tmp_path, "state/evidence.json")

    assert store.add(source_without_file) is EvidenceAddStatus.ADDED
    assert store.add(source_without_file) is EvidenceAddStatus.DUPLICATE
    assert store.add(same_fact_other_location) is EvidenceAddStatus.DUPLICATE
    assert len(store) == 1
    assert store.deduplicate(
        [same_fact_other_location, source_without_file, source_without_file]
    ) == [source_without_file]


def test_evidence_store_persists_and_loads_stably(tmp_path: Path) -> None:
    store = EvidenceStore(tmp_path, "state/evidence.json")
    evidence = fixture_evidence()
    for item in reversed(evidence):
        assert store.add(item) is EvidenceAddStatus.ADDED

    store.save()
    reloaded = EvidenceStore(tmp_path, store.store_path).load()

    expected_ids = sorted(item.evidence_id for item in evidence)
    assert [item.evidence_id for item in reloaded.list()] == expected_ids
    assert reloaded.store_path.read_text(encoding="utf-8").endswith("\n")
