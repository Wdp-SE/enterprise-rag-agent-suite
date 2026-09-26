"""Focused contracts for frozen retrieval selection metrics."""

from __future__ import annotations

from evaluation.real_world_retrieval.final_selection.metrics import (
    by_category,
    score_hits,
    summarize,
)


def _query(query_id: str = "ds-001", category: str = "zh") -> dict:
    return {"id": query_id, "query": "where is the marker?", "category": category, "version_scope": "3.4.3"}


def _source(key: str, marker: str) -> dict:
    return {
        "document_key": key,
        "version": "3.4.3",
        "locale": "en-US",
        "heading": "Shared heading",
        "evidence_marker": marker,
    }


def _hit(key: str, chunk_id: str, content: str) -> dict:
    return {
        "document_key": key,
        "document_id": f"3.4.3:en:{key}",
        "chunk_id": chunk_id,
        "version": "3.4.3",
        "locale": "en-US",
        "heading": "Shared heading",
        "content": content,
    }


def test_same_heading_without_frozen_marker_is_not_relevant():
    """Matching document metadata alone must not credit the wrong fragment."""
    truth = {"id": "ds-001", "answerable_in_corpus": True, "relevant": [_source("guide/api", "exact marker")]}
    wrong_fragment = _hit("guide/api", "chunk-1", "A different part of this heading.")
    right_fragment = _hit("guide/api", "chunk-2", "The Exact Marker is here.")

    row = score_hits(_query(), truth, [wrong_fragment, right_fragment], 12.5)

    assert row["id"] == "ds-001"
    assert row["category"] == "zh"
    assert row["relevant_source_indices"] == [None, 0]
    assert row["relevance"] == [0, 1]
    assert row["ranked_chunk_ids"] == ["chunk-1", "chunk-2"]
    assert row["ranked_document_ids"] == ["3.4.3:en:guide/api"] * 2
    assert summarize([row])["hit_at_1"] == 0.0
    assert summarize([row])["hit_at_5"] == 1.0


def test_cross_document_completion_requires_both_distinct_sources():
    """Two fragments from one source cannot satisfy two-source recall."""
    truth = {
        "id": "ds-035",
        "answerable_in_corpus": True,
        "relevant": [_source("guide/dependent", "first marker"), _source("guide/priority", "second marker")],
    }
    query = _query("ds-035", "cross_document")
    repeated = score_hits(
        query,
        truth,
        [_hit("guide/dependent", "a1", "first marker"), _hit("guide/dependent", "a2", "first marker")],
        10.0,
    )
    complete = score_hits(
        query,
        truth,
        [_hit("guide/dependent", "a1", "first marker"), _hit("guide/priority", "b1", "second marker")],
        20.0,
    )

    assert repeated["relevant_source_indices"] == [0, 0]
    assert complete["relevant_source_indices"] == [0, 1]
    metrics = summarize([repeated, complete])
    assert metrics["hit_at_5"] == 1.0
    assert metrics["cross_document_both_source_at_5"] == 0.5
    assert metrics["ndcg_at_5"] <= 1.0
    assert by_category([repeated, complete])["cross_document"]["cross_document_both_source_at_5"] == 0.5


def test_no_answer_candidates_are_not_counted_as_false_answers():
    """Retrieval candidates reveal no answer generation behavior."""
    truth = {"id": "ds-044", "answerable_in_corpus": False, "relevant": []}
    query = _query("ds-044", "no_answer")
    candidate = score_hits(query, truth, [_hit("guide/api", "chunk-1", "unrelated")], 1.0)
    rejected = score_hits(query, truth, [], 3.0)

    assert candidate["rejection"] == 0
    assert rejected["rejection"] == 1
    metrics = summarize([candidate, rejected])
    assert metrics["no_answer_candidate_count"] == 1
    assert metrics["no_answer_rejection_count"] == 1
    assert metrics["false_answer_count"] == "NOT_EVALUATED"
    assert metrics["hit_at_5"] is None


def test_summary_uses_answerable_denominator_and_all_query_latencies():
    """No-answer probes should affect latency, but not retrieval quality rates."""
    truth = {"id": "ds-001", "answerable_in_corpus": True, "relevant": [_source("guide/api", "marker")]}
    delayed = score_hits(
        _query("ds-001", "zh"),
        truth,
        [_hit("wrong", "x", "text"), _hit("guide/api", "y", "marker")],
        10.0,
    )
    immediate = score_hits(
        _query("ds-002", "zh"),
        {**truth, "id": "ds-002"},
        [_hit("guide/api", "z", "marker")],
        30.0,
    )
    no_answer = score_hits(
        _query("ds-044", "no_answer"),
        {"id": "ds-044", "answerable_in_corpus": False, "relevant": []},
        [],
        50.0,
    )

    metrics = summarize([delayed, immediate, no_answer])

    assert metrics["queries"] == 3
    assert metrics["answerable"] == 2
    assert metrics["hit_at_1"] == 0.5
    assert metrics["hit_at_3"] == 1.0
    assert metrics["mrr"] == 0.75
    assert metrics["ndcg_at_5"] == 0.8155
    assert metrics["p50_ms"] == 30.0
    assert metrics["p95_ms"] == 48.0
