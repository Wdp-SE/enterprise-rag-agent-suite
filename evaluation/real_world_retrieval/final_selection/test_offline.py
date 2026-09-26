"""Focused checks that the isolated experiment matches production search semantics."""

from __future__ import annotations

from evaluation.real_world_retrieval.final_selection.chunks import build_chunks
from evaluation.real_world_retrieval.final_selection.offline import OfflineIndex
from src.public_knowledge import PublicKnowledgeIndex, ROOT


def test_baseline_bm25_matches_production_index():
    experimental = OfflineIndex(build_chunks(ROOT, "A"))
    production = PublicKnowledgeIndex()
    question = "How does Parameter Context override Startup Parameter?"

    hits, _ = experimental.search(question, version="3.4.3", strategy="bm25", top_k=5)
    expected = production.search(
        question, version="3.4.3", language="all", policy="bm25", top_k=5
    )

    assert [row["chunk_id"] for row in hits] == [row["chunk_id"] for row in expected]


def test_document_cap_only_changes_final_selection():
    chunks = [
        {"chunk_id": "a1", "document_id": "a", "document_key": "a", "version": "3.4.3",
         "heading": "H", "content": "token token token"},
        {"chunk_id": "a2", "document_id": "a", "document_key": "a", "version": "3.4.3",
         "heading": "H", "content": "token token"},
        {"chunk_id": "b1", "document_id": "b", "document_key": "b", "version": "3.4.3",
         "heading": "H", "content": "token"},
        {"chunk_id": "c1", "document_id": "c", "document_key": "c", "version": "3.4.2",
         "heading": "H", "content": "token"},
    ]
    index = OfflineIndex(chunks)

    uncapped, _ = index.search("token", version="3.4.3", strategy="bm25", top_k=3)
    capped, _ = index.search(
        "token", version="3.4.3", strategy="bm25", top_k=3,
        max_chunks_per_document=1,
    )

    assert [row["document_id"] for row in uncapped].count("a") == 2
    assert [row["document_id"] for row in capped] == ["a", "b"]
    assert all(row["version"] == "3.4.3" for row in capped)
