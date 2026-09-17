import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from app.research.models import Evidence, normalize_text, sha256_text


PROJECT_ROOT = Path(__file__).resolve().parents[2]
EVIDENCE_FIXTURE = PROJECT_ROOT / "tests" / "fixtures" / "research" / "evidence.json"


def load_fixture_evidence() -> list[Evidence]:
    payload = json.loads(EVIDENCE_FIXTURE.read_text(encoding="utf-8"))
    return [Evidence.model_validate(item) for item in payload]


def test_evidence_fixture_has_stable_ids_and_content_hashes() -> None:
    evidence = load_fixture_evidence()

    assert [item.evidence_id for item in evidence] == [
        "ev_29b64be93258e9e36d0e",
        "ev_56822dcb35945736f4b5",
        "ev_5e31792d904fd1097ad2",
    ]
    assert all(item.content_hash == sha256_text(normalize_text(item.content)) for item in evidence)


def test_evidence_id_is_stable_across_equivalent_whitespace() -> None:
    original = load_fixture_evidence()[0]
    payload = original.model_dump(mode="json", exclude={"evidence_id", "content_hash"})
    payload["content"] = f"\n  {original.content}  \n"

    rebuilt = Evidence.model_validate(payload)

    assert rebuilt.evidence_id == original.evidence_id
    assert rebuilt.content_hash == original.content_hash


def test_evidence_location_participates_in_stable_id() -> None:
    original = load_fixture_evidence()[0]
    payload = original.model_dump(mode="json", exclude={"evidence_id", "content_hash"})
    payload["section"] = "另一章节"

    rebuilt = Evidence.model_validate(payload)

    assert rebuilt.evidence_id != original.evidence_id
    assert rebuilt.content_hash == original.content_hash


def test_different_content_produces_different_evidence_id() -> None:
    original = load_fixture_evidence()[0]
    payload = original.model_dump(mode="json", exclude={"evidence_id", "content_hash"})
    payload["content"] = f"{original.content} 新的 Evidence 文本。"

    rebuilt = Evidence.model_validate(payload)

    assert rebuilt.evidence_id != original.evidence_id
    assert rebuilt.content_hash != original.content_hash


def test_incorrect_content_hash_is_rejected() -> None:
    payload = json.loads(EVIDENCE_FIXTURE.read_text(encoding="utf-8"))[0]
    payload["content_hash"] = "0" * 64

    with pytest.raises(ValidationError, match="normalized Evidence content"):
        Evidence.model_validate(payload)


@pytest.mark.parametrize("local_file", ["../outside.pdf", "C:/outside.pdf", "/outside.pdf"])
def test_invalid_evidence_local_path_is_rejected(local_file: str) -> None:
    payload = json.loads(EVIDENCE_FIXTURE.read_text(encoding="utf-8"))[0]
    payload["local_file"] = local_file

    with pytest.raises(ValidationError, match="local_file"):
        Evidence.model_validate(payload)
