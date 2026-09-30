import hashlib
import json

import pytest

from src.document_relations import DocumentRelationIndex


MANIFEST = {
    "sources": [
        {"version": "docs-main", "language": "zh", "document_key": "guide/start"},
        {"version": "docs-main", "language": "en", "document_key": "guide/start"},
        {"version": "docs-main", "language": "zh", "document_key": "market/eu"},
        {"version": "docs-main", "language": "en", "document_key": "market/eu"},
    ]
}


def _write_registry(tmp_path, relations, *, manifest=MANIFEST, digest=None):
    manifest_bytes = json.dumps(manifest).encode("utf-8")
    (tmp_path / "corpus_manifest.json").write_bytes(manifest_bytes)
    expected = hashlib.sha256(manifest_bytes).hexdigest()
    registry = {
        "schema_version": 1,
        "corpus_manifest_sha256": digest or expected,
        "relations": relations,
    }
    (tmp_path / "document_relations.json").write_text(json.dumps(registry), encoding="utf-8")


def _relation(relation_id="pair-1", relation_type="translation_of", status="candidate", source="zh", target="en"):
    return {
        "relation_id": relation_id,
        "relation_type": relation_type,
        "verification_status": status,
        "source_document_id": f"docs-main:{source}:guide/start",
        "target_document_id": f"docs-main:{target}:guide/start",
        "verification_evidence": "Matching path only; content not reviewed.",
    }


def test_candidate_translation_pair_is_not_a_verified_drift_relation(tmp_path):
    _write_registry(tmp_path, [_relation()])

    relations = DocumentRelationIndex.from_corpus(tmp_path, MANIFEST)

    assert relations.available
    assert relations.for_document("docs-main:zh:guide/start")[0]["verification_status"] == "candidate"
    assert relations.summary()["verified_translation_pairs"] == 0


def test_only_verified_translation_of_counts_as_verified_pair(tmp_path):
    _write_registry(tmp_path, [_relation(status="verified")])

    relations = DocumentRelationIndex.from_corpus(tmp_path, MANIFEST)

    assert relations.summary()["verified_translation_pairs"] == 1
    assert relations.for_document("docs-main:en:guide/start")[0]["relation_type"] == "translation_of"


def test_localized_variant_without_rule_is_not_a_translation_pair(tmp_path):
    relation = _relation(relation_type="localized_variant_of", status="verified")
    relation["source_document_id"] = "docs-main:zh:market/eu"
    relation["target_document_id"] = "docs-main:en:market/eu"
    _write_registry(tmp_path, [relation])

    relations = DocumentRelationIndex.from_corpus(tmp_path, MANIFEST)

    assert relations.summary()["verified_translation_pairs"] == 0
    assert relations.for_document("docs-main:zh:market/eu")[0]["relation_type"] == "localized_variant_of"


def test_unknown_document_has_no_relationships(tmp_path):
    _write_registry(tmp_path, [_relation()])

    relations = DocumentRelationIndex.from_corpus(tmp_path, MANIFEST)

    assert relations.for_document("missing:en:document") == []


@pytest.mark.parametrize("mutate", [
    lambda rows: [rows[0], dict(rows[0])],
    lambda rows: [{**rows[0], "relation_type": "similar_to"}],
    lambda rows: [{**rows[0], "verification_status": "confirmed"}],
    lambda rows: [{**rows[0], "source_document_id": "missing:zh:guide/start"}],
])
def test_malformed_registry_fails_closed_without_returning_claims(tmp_path, mutate):
    _write_registry(tmp_path, mutate([_relation()]))

    relations = DocumentRelationIndex.from_corpus(tmp_path, MANIFEST)

    assert not relations.available
    assert relations.for_document("docs-main:zh:guide/start") == []
    assert relations.summary()["verified_translation_pairs"] == 0


def test_stale_registry_hash_fails_closed_without_affecting_document_identity(tmp_path):
    _write_registry(tmp_path, [_relation()], digest="0" * 64)

    relations = DocumentRelationIndex.from_corpus(tmp_path, MANIFEST)

    assert not relations.available
    assert relations.summary()["status"] == "invalid"
    assert relations.summary()["verified_translation_pairs"] == 0
