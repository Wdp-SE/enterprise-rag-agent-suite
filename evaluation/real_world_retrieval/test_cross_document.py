"""Regression checks for multi-source retrieval evaluation."""

from __future__ import annotations

import json

from evaluation.real_world_retrieval import benchmark, make_queries


def test_cross_document_truth_names_both_sources(tmp_path, monkeypatch):
    """A one-document label cannot measure a question requiring two sources."""
    monkeypatch.setattr(make_queries, "ROOT", tmp_path)
    make_queries.write_queries()
    truth = {
        row["id"]: row
        for row in (
            json.loads(line)
            for line in (tmp_path / "ground_truth.jsonl").read_text(encoding="utf-8").splitlines()
        )
    }

    assert {item["document_key"] for item in truth["ds-034"]["relevant"]} == {"release-notes"}
    assert {
        query_id: {item["document_key"] for item in truth[query_id]["relevant"]}
        for query_id in ("ds-035", "ds-036", "ds-037", "ds-038")
    } == {
        "ds-035": {"guide/task/dependent", "guide/parameter/priority"},
        "ds-036": {"guide/project/workflow-definition", "guide/project/workflow-instance"},
        "ds-037": {"guide/api/healthcheck", "guide/api/open-api"},
        "ds-038": {"guide/upgrade/incompatible", "release-notes"},
    }


def test_both_source_at_five_requires_distinct_required_sources():
    """Two hits from one source still leave a cross-document answer incomplete."""
    rows = [
        {
            "category": "cross_document", "answerable": True,
            "relevant_count": 2, "relevance": [1, 1, 0, 0, 0],
            "relevant_source_indices": [0, 0, None, None, None],
            "latency_ms": 1.0, "candidates": 5, "error": None,
        },
        {
            "category": "cross_document", "answerable": True,
            "relevant_count": 2, "relevance": [1, 0, 1, 0, 0],
            "relevant_source_indices": [0, None, 1, None, None],
            "latency_ms": 2.0, "candidates": 5, "error": None,
        },
    ]

    metrics = benchmark._measure(rows)

    assert metrics["hit_at_5"] == 1.0
    assert metrics["cross_document_both_source_at_5"] == 0.5


def test_relevant_source_index_distinguishes_documents_with_same_heading():
    truth = {
        "relevant": [
            {"document_key": "guide/first", "version": "3.4.3", "locale": "en", "heading": "Overview"},
            {"document_key": "guide/second", "version": "3.4.3", "locale": "en", "heading": "Overview"},
        ]
    }
    second_source = {"document_key": "guide/second", "version": "3.4.3", "locale": "en", "heading": "Overview"}
    unrelated = {"document_key": "guide/third", "version": "3.4.3", "locale": "en", "heading": "Overview"}

    assert benchmark.relevant_source_index(second_source, truth) == 1
    assert benchmark.relevant_source_index(unrelated, truth) is None
