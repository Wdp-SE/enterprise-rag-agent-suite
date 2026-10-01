from __future__ import annotations

import pytest

from run_rag_benchmark import _search_policy, evaluate_retrieval, normalize_query, validate_rag_cases


def rag_case(case_id, family_id, split, required_sources, *, answerable=True, category="single_fact"):
    versions = {"documentation": "docs-main", "universe": "0.52.0"}
    return {
        "case_id": case_id,
        "family_id": family_id,
        "split": split,
        "category": category if answerable else "unanswerable_scope",
        "query": f"How is the documented behavior checked for {case_id}?",
        "query_language": "en",
        "version": "latest",
        "expected_component_versions": versions,
        "language": "all",
        "required_sources": required_sources,
        "required_answer_points": ["The source documents the expected behavior."] if answerable else [],
        "expected_image_ids": [],
        "answerable": answerable,
        "expected_relation_state": "none",
    }


def test_v2_validator_rejects_family_leakage_and_unknown_source():
    cases = [
        rag_case("a", "launch-family", "dev", ["docs-main:en:guide/start"]),
        rag_case("b", "launch-family", "holdout", ["docs-main:en:guide/start"]),
    ]
    with pytest.raises(ValueError, match="family"):
        validate_rag_cases(
            cases,
            known_sources={"docs-main:en:guide/start": "docs-main"},
            forbidden_families=set(),
            forbidden_queries=set(),
        )

    with pytest.raises(ValueError, match="unknown|required source"):
        validate_rag_cases(
            [rag_case("unknown", "unique-family", "dev", ["missing:en:guide/start"])],
            known_sources={},
            forbidden_families=set(),
            forbidden_queries=set(),
        )


def test_v2_validator_rejects_old_family_query_and_wrong_component_version():
    source_id = "docs-main:en:guide/start"
    allowed_dev = rag_case("dev-old-family", "known-old-family", "dev", [source_id])
    validate_rag_cases(
        [allowed_dev],
        known_sources={source_id: {"version": "docs-main", "component": "documentation"}},
        forbidden_families={"known-old-family"},
        forbidden_queries=set(),
    )

    old_holdout_family = rag_case("holdout-old-family", "known-old-family", "holdout", [source_id])
    with pytest.raises(ValueError, match="family"):
        validate_rag_cases(
            [old_holdout_family],
            known_sources={source_id: {"version": "docs-main", "component": "documentation"}},
            forbidden_families={"known-old-family"},
            forbidden_queries=set(),
        )

    old_query = rag_case("old-query", "new-family", "dev", [source_id])
    with pytest.raises(ValueError, match="query"):
        validate_rag_cases(
            [old_query],
            known_sources={source_id: {"version": "docs-main", "component": "documentation"}},
            forbidden_families=set(),
            forbidden_queries={normalize_query(old_query["query"])},
        )

    wrong_version = rag_case("wrong-version", "another-family", "dev", [source_id])
    wrong_version["expected_component_versions"]["documentation"] = "1.9.0"
    with pytest.raises(ValueError, match="version"):
        validate_rag_cases(
            [wrong_version],
            known_sources={source_id: {"version": "docs-main", "component": "documentation"}},
            forbidden_families=set(),
            forbidden_queries=set(),
        )


def test_metrics_keep_complete_sources_and_no_answer_candidates_separate():
    cases = [
        rag_case("cross", "cross-family", "dev", ["docs-main:en:guide/a", "docs-main:en:guide/b"], category="cross_source"),
        rag_case("none", "no-answer-family", "holdout", [], answerable=False),
    ]
    hits = {
        "cross": [{"document_id": "docs-main:en:guide/a", "version": "docs-main", "retrieval_score": 1.0}],
        "none": [{"document_id": "docs-main:en:unrelated", "version": "docs-main", "retrieval_score": 0.2}],
    }
    report = evaluate_retrieval(cases, hits, {"cross": [1.0], "none": [1.0]})

    assert report["metrics"]["required_source_recall_at_5"] == 0.5
    assert report["metrics"]["complete_required_sources_at_5"] == 0.0
    assert report["metrics"]["unanswerable_candidate_rate"] == 1.0
    assert report["metrics"]["answer_accuracy"] is None


def test_explicit_version_mismatch_and_image_hits_are_reported_separately():
    case = rag_case("image-version", "unique-image-family", "dev", ["0.52.0:en:planning/guide/start"], category="explicit_version")
    case["expected_component_versions"] = {"universe": "0.52.0"}
    case["version"] = "0.52.0"
    case["expected_image_ids"] = ["figure-1"]
    hit = {
        "document_id": "0.51.0:en:planning/guide/start",
        "document_key": "planning/guide/start",
        "version": "0.51.0",
        "retrieval_score": 1.0,
        "modality": "image_ocr",
        "figure_id": "figure-1",
    }
    report = evaluate_retrieval([case], {case["case_id"]: [hit]}, {case["case_id"]: [2.0]})

    assert report["metrics"]["explicit_version_mismatch_count"] == 1
    assert report["metrics"]["image_evidence_hit_at_5"] == 1.0
    assert report["metrics"]["explicit_version_mismatch_count"] == 1


def test_offline_hybrid_figure_ocr_candidate_keeps_reviewed_image_evidence():
    document = {"chunk_id": "doc-1", "document_id": "guide/a", "version": "latest"}
    figure = {"chunk_id": "figure-1", "document_id": "guide/a", "version": "latest", "figure_id": "fig-a"}

    class BaseIndex:
        def search(self, query, *, top_k, version, language, policy):
            assert policy == "hybrid"
            return [document]

    class Runtime:
        base_index = BaseIndex()
        last_retrieval_call_count = 0

        @staticmethod
        def _search_images(query, *, top_k, version, language):
            return [figure]

        @staticmethod
        def _add_image_evidence(document_hits, image_hits, *, top_k):
            return [*document_hits, *image_hits][:top_k]

    runtime = Runtime()
    hits = _search_policy(
        runtime, "hybrid_figure_ocr", "query", top_k=5, version="latest", language="all",
    )

    assert [row["chunk_id"] for row in hits] == ["doc-1", "figure-1"]
    assert {row["retrieval_policy"] for row in hits} == {"hybrid_figure_ocr"}
    assert runtime.last_retrieval_call_count == 2
