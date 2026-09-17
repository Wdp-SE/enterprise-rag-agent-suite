import json
from datetime import date
from pathlib import Path

import faiss
import numpy as np

from src.evaluation.corpus import CorpusManifest
from src.evaluation.dataset import load_evaluation_dataset
from src.retrieval import HybridRetriever, VectorRetriever
from src.vector_utils import faiss_index_has_unit_norm_vectors
from src.versioning import (
    DatePrecision,
    VersionAction,
    VersionIntent,
    VersionResolver,
    apply_version_policy,
)


def _document(
    document_id,
    *,
    title="Shared Rule",
    number=None,
    version_family=None,
    version=None,
    status="ACTIVE",
    effective_date="2020-01-01",
    default=True,
):
    return {
        "document_id": document_id,
        "title": title,
        "source_filename": f"{document_id}.pdf",
        "document_type": "policy",
        "organization": "Fixture Authority",
        "document_number": number,
        "publish_date": effective_date,
        "effective_date": effective_date,
        "version_family": version_family,
        "version": version,
        "status": status,
        "source_level": "OFFICIAL",
        "source_path": f"source_pdfs/{document_id}.pdf",
        "source_url": f"https://example.test/{document_id}",
        "sha256": "a" * 64,
        "size_bytes": 1,
        "pages_total": 1,
        "pages_with_text": 1,
        "empty_pages": 0,
        "parse_status": "READY",
        "ocr_status": "NOT_REQUIRED",
        "included_in_default_index": default,
    }


def _manifest(*extra_documents):
    documents = [
        _document(
            "rule-old",
            number="RULE X—2020",
            version_family="RULE_X",
            version="2020",
            status="SUPERSEDED",
            effective_date="2020-01-01",
            default=False,
        ),
        _document(
            "rule-new",
            number="RULE X—2026",
            version_family="RULE_X",
            version="2026",
            effective_date="2026-05-01",
        ),
        _document("unrelated", title="Unrelated Active Policy"),
        *extra_documents,
    ]
    return CorpusManifest.model_validate(
        {
            "schema_version": "1.0",
            "corpus_id": "fixture",
            "corpus_version": "test",
            "frozen_at": "2026-01-01T00:00:00+08:00",
            "status": "FROZEN",
            "scenario": "fixture",
            "identity_note": "fixture",
            "source_directory": "source_pdfs",
            "default_index_document_ids": [
                item["document_id"] for item in documents if item["included_in_default_index"]
            ],
            "target_current_document_ids_blocked_by_ocr": [],
            "version_test_document_ids": ["rule-old"],
            "reference_document_ids_blocked_by_ocr": [],
            "duplicate_audit": {
                "exact_sha256_duplicate_groups": [],
                "normalized_text_sha256_duplicate_groups": [],
                "result": "NO_DUPLICATES",
                "note": "fixture",
            },
            "version_relations": [
                {
                    "older_document_id": "rule-old",
                    "newer_document_id": "rule-new",
                    "relation": "SUPERSEDED_BY",
                    "effective_date": "2026-05-01",
                }
            ],
            "documents": documents,
        }
    )


def _resolver(*extra_documents):
    return VersionResolver(_manifest(*extra_documents), as_of_date=date(2026, 9, 1))


def _resolve(question, *extra_documents):
    resolver = _resolver(*extra_documents)
    available = [item.document_id for item in resolver.metadata]
    return resolver.resolve(question, available_document_ids=available)


def test_intent_detection_is_deterministic_for_required_intents():
    detector = _resolver().detector
    cases = {
        "现行 Shared Rule 有什么要求？": VersionIntent.CURRENT,
        "旧版 Shared Rule 如何规定？": VersionIntent.HISTORICAL,
        "RULE X—2020 如何规定？": VersionIntent.EXPLICIT_VERSION,
        "2025年 Shared Rule 适用哪版？": VersionIntent.TEMPORAL_DATE,
        "普通安全管理问题": VersionIntent.UNSPECIFIED,
    }
    for question, expected in cases.items():
        first = detector.detect(question)
        second = detector.detect(question)
        assert first == second
        assert first.intent == expected


def test_active_default_and_superseded_default_exclusion():
    plan = _resolve("Shared Rule 有什么要求？")
    assert plan.context.intent == VersionIntent.UNSPECIFIED
    assert "rule-new" in plan.eligible_document_ids
    assert "rule-old" not in plan.eligible_document_ids
    assert plan.decision_for("rule-old").action == VersionAction.EXCLUDE


def test_current_explicit_old_explicit_new_and_dual_version_resolution():
    current = _resolve("现行 Shared Rule 是哪一版？")
    old = _resolve("RULE X—2020 如何规定？")
    new = _resolve("RULE X—2026 如何规定？")
    dual = _resolve("RULE X—2020 和 RULE X—2026 有什么区别？")

    assert current.decision_for("rule-new").action == VersionAction.PREFER
    assert old.eligible_document_ids == ["rule-old", "unrelated"]
    assert old.decision_for("rule-old").action == VersionAction.PREFER
    assert "rule-new" not in old.eligible_document_ids
    assert new.decision_for("rule-new").action == VersionAction.PREFER
    assert {"rule-old", "rule-new"}.issubset(dual.eligible_document_ids)


def test_temporal_past_current_boundary_and_ambiguous_year():
    past = _resolve("2025年 Shared Rule 适用哪一版？")
    current = _resolve("2026年6月 Shared Rule 适用哪一版？")
    boundary = _resolve("2026年5月1日 Shared Rule 适用哪一版？")
    ambiguous = _resolve("2026年 Shared Rule 适用哪一版？")

    assert past.context.date_precision == DatePrecision.YEAR
    assert "rule-old" in past.eligible_document_ids
    assert "rule-new" not in past.eligible_document_ids
    assert "rule-new" in current.eligible_document_ids
    assert "rule-old" not in current.eligible_document_ids
    assert "rule-new" in boundary.eligible_document_ids
    assert "rule-old" not in boundary.eligible_document_ids
    assert ambiguous.context.temporal_ambiguity is True
    assert {"rule-old", "rule-new"}.issubset(ambiguous.eligible_document_ids)


def test_bare_date_without_version_family_does_not_enable_historical_assets():
    plan = _resolve("2025年全国统一最低月薪是多少？")
    assert plan.context.intent == VersionIntent.TEMPORAL_DATE
    assert plan.context.matched_version_families == []
    assert "rule-old" not in plan.eligible_document_ids
    assert "rule-new" in plan.eligible_document_ids


def test_relationship_and_status_serialize_and_effective_to_is_explained():
    resolver = _resolver()
    old = resolver.by_id["rule-old"]
    new = resolver.by_id["rule-new"]
    assert old.status == "SUPERSEDED"
    assert old.superseded_by == ["rule-new"]
    assert old.effective_to == date(2026, 5, 1)
    assert old.effective_to_source == "derived_from_version_relation:rule-old->rule-new"
    assert new.supersedes == ["rule-old"]
    assert old.model_dump(mode="json")["status"] == "SUPERSEDED"


def test_missing_version_metadata_is_allowed_and_traced():
    incomplete = _document(
        "incomplete-version",
        version_family="RULE_Y",
        version=None,
        effective_date=None,
    )
    plan = _resolve("普通问题", incomplete)
    assert "incomplete-version" in plan.eligible_document_ids
    assert "VERSION_METADATA_MISSING:incomplete-version" in plan.issues


def test_independent_family_and_unrelated_active_receive_no_global_boost():
    other_old = _document(
        "other-old",
        title="Other Rule",
        number="OTHER—2019",
        version_family="OTHER",
        version="2019",
        status="SUPERSEDED",
        effective_date="2019-01-01",
        default=False,
    )
    plan = _resolve("RULE X—2020 如何规定？", other_old)
    assert plan.decision_for("other-old").action == VersionAction.EXCLUDE
    assert plan.decision_for("unrelated").adjustment == 0.0
    candidate = apply_version_policy(
        {"document_id": "unrelated", "distance": 0.9}, plan
    )
    assert candidate["original_score"] == 0.9
    assert candidate["version_adjustment"] == 0.0
    assert candidate["final_pre_rerank_score"] == 0.9


def test_shared_version_number_is_scoped_by_matched_family_title():
    other_same_version = _document(
        "other-2020",
        title="Other Rule",
        number="OTHER—2020",
        version_family="OTHER",
        version="2020",
        status="SUPERSEDED",
        effective_date="2020-02-01",
        default=False,
    )
    plan = _resolve("2020版 Shared Rule 如何规定？", other_same_version)
    assert plan.context.matched_document_ids == ["rule-old"]
    assert "other-2020" not in plan.eligible_document_ids


def _write_retrieval_document(root, document_id, score, *, metadata=None):
    documents = root / "documents"
    vectors = root / "vectors"
    documents.mkdir(parents=True, exist_ok=True)
    vectors.mkdir(parents=True, exist_ok=True)
    metainfo = {
        "document_id": document_id,
        "title": document_id,
        "document_type": "policy",
        "source": f"{document_id}.pdf",
        **(metadata or {}),
    }
    payload = {
        "metainfo": metainfo,
        "content": {
            "pages": [{"page": 1, "text": f"{document_id} page"}],
            "chunks": [{"page": 1, "text": f"{document_id} chunk"}],
        },
    }
    (documents / f"{document_id}.json").write_text(json.dumps(payload), encoding="utf-8")
    index = faiss.IndexFlatIP(2)
    index.add(np.asarray([[score, (1 - score**2) ** 0.5]], dtype=np.float32))
    faiss.write_index(index, str(vectors / f"{document_id}.faiss"))
    return vectors, documents


def test_historical_asset_is_opt_in_and_metadata_projection_is_compatible(
    tmp_path, monkeypatch
):
    current_root = tmp_path / "current"
    history_root = tmp_path / "history"
    current_vectors, current_documents = _write_retrieval_document(
        current_root,
        "rule-new",
        0.8,
        metadata={
            "document_number": "RULE X—2026",
            "version": "2026",
            "status": "ACTIVE",
            "effective_date": "2026-05-01",
        },
    )
    history_vectors, history_documents = _write_retrieval_document(
        history_root,
        "rule-old",
        1.0,
        metadata={"version": "2020", "status": "SUPERSEDED"},
    )

    off = VectorRetriever(current_vectors, current_documents)
    on = VectorRetriever(
        current_vectors,
        current_documents,
        additional_corpora=[(history_vectors, history_documents)],
    )
    monkeypatch.setattr(off, "_get_embedding", lambda query: [1.0, 0.0])
    monkeypatch.setattr(on, "_get_embedding", lambda query: [1.0, 0.0])

    assert off.document_ids == ["rule-new"]
    assert set(on.document_ids) == {"rule-new", "rule-old"}
    filtered = on.retrieve("query", document_ids=["rule-new"], top_n=5)
    assert [item["document_id"] for item in filtered] == ["rule-new"]
    assert filtered[0]["document_number"] == "RULE X—2026"
    assert filtered[0]["status"] == "ACTIVE"


def test_hybrid_retriever_passes_document_filter_without_changing_rerank(
    tmp_path, monkeypatch
):
    root = tmp_path / "corpus"
    vectors, documents = _write_retrieval_document(root, "doc-a", 1.0)
    _write_retrieval_document(root, "doc-b", 0.8)
    retriever = HybridRetriever(vectors, documents)
    monkeypatch.setattr(
        retriever.vector_retriever, "_get_embedding", lambda query: [1.0, 0.0]
    )
    monkeypatch.setattr(
        retriever.reranker,
        "rerank_documents",
        lambda **kwargs: kwargs["documents"],
    )
    results = retriever.retrieve("query", document_ids=["doc-b"], top_n=5)
    assert [item["document_id"] for item in results] == ["doc-b"]


def test_version_module_contains_no_corpus_specific_version_hardcode():
    source = "\n".join(
        path.read_text(encoding="utf-8")
        for path in Path("src/versioning").glob("*.py")
    )
    assert "TSG 08" not in source
    assert "tsg-08" not in source.casefold()


def test_real_historical_asset_is_present_normalized_and_opt_in_only():
    corpus_root = Path("data/domain_corpus_v0_2")
    historical_root = corpus_root / "historical_retrieval_assets"
    chunk_path = (
        historical_root / "databases" / "chunked_reports" / "tsg-08-2017.json"
    )
    index_path = historical_root / "databases" / "vector_dbs" / "tsg-08-2017.faiss"
    document = json.loads(chunk_path.read_text(encoding="utf-8"))
    index = faiss.read_index(str(index_path))

    assert document["metainfo"]["document_id"] == "tsg-08-2017"
    assert document["metainfo"]["status"] == "SUPERSEDED"
    assert len(document["content"]["pages"]) == 46
    assert len(document["content"]["chunks"]) == index.ntotal == 110
    assert faiss_index_has_unit_norm_vectors(index)

    current = VectorRetriever(
        corpus_root / "databases" / "vector_dbs",
        corpus_root / "databases" / "chunked_reports",
    )
    version_enabled = VectorRetriever(
        corpus_root / "databases" / "vector_dbs",
        corpus_root / "databases" / "chunked_reports",
        additional_corpora=[
            (
                historical_root / "databases" / "vector_dbs",
                historical_root / "databases" / "chunked_reports",
            )
        ],
    )
    assert "tsg-08-2017" not in current.document_ids
    assert "tsg-08-2017" in version_enabled.document_ids


def test_version_evaluation_extension_is_valid_and_bounded():
    items = load_evaluation_dataset("data/evaluation/version_eval_v0_1.jsonl")
    assert 6 <= len(items) <= 10
    assert all(item.question_type == "version_temporal" for item in items)
