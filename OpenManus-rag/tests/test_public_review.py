from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from app.public_review import PublicReviewAgent


CORPUS = Path(__file__).resolve().parents[2] / "RAG-Challenge-2-main" / "public_corpus"
CHUNKS = json.loads((CORPUS / "chunks.json").read_text(encoding="utf-8"))


class Gateway:
    def __init__(self):
        self.calls = []

    def workspace(self):
        return {"current_version": "3.4.3"}

    def document(self, document_id):
        self.calls.append(("document", document_id))
        return [row for row in CHUNKS if row["document_id"] == document_id]

    def search(self, question, *, version, language, top_k=5):
        self.calls.append(("search", version, language, top_k))
        rows = [
            row for row in CHUNKS
            if row["version"] == version
            and row["document_key"] == "guide/upgrade/incompatible"
        ]
        return {"results": rows[:top_k]}

    def engineering_diff(self, old_items, new_items):
        self.calls.append(("diff", old_items, new_items))
        assert old_items[0]["content_hash"] != new_items[0]["content_hash"]
        return {"changes": [{
            "change_type": "MODIFIED", "external_identifier": old_items[0]["external_identifier"],
            "old_content": old_items[0]["content"], "new_content": new_items[0]["content"],
        }]}

    def engineering_impacts(self, payload):
        self.calls.append(("impact", payload))
        confirmed = {row["target_item_id"] for row in payload["trace_links"]}
        return {"impacts": [
            {"impacted_item_id": item_id,
             "review_status": "CONFIRMED" if item_id in confirmed else "SUGGESTED"}
            for item_id in payload["dense_item_ids"]
        ]}


def test_official_change_calls_rag_http_diff_search_impact_without_baseline_write():
    gateway = Gateway()
    selected = next(row for row in CHUNKS if row["document_key"] == "guide/parameter/priority" and row["language"] == "zh" and row["version"] == "3.4.3")
    before = hashlib.sha256((CORPUS / "corpus_manifest.json").read_bytes()).hexdigest()
    result = PublicReviewAgent(gateway).analyze(selected, selected["content"] + " 假设性更新。")
    assert result["change"]["change_type"] == "MODIFIED"
    assert result["sandbox_only"] and not result["public_baseline_written"]
    assert result["patch_candidate"]["status"] == "REQUIRES_HUMAN_REVIEW"
    assert all(row["relation"] == "suggested" for row in result["impacts"])
    assert [row[0] for row in gateway.calls] == ["diff", "search", "impact"]
    assert hashlib.sha256((CORPUS / "corpus_manifest.json").read_bytes()).hexdigest() == before


def test_dsip_reference_confirms_documents_without_confirming_unrelated_paragraph_impact():
    gateway = Gateway()
    selected = next(
        row for row in CHUNKS
        if row["document_key"] == "proposals/dsip-107-proposal"
        and row["heading"] == "Code of Conduct"
    )
    result = PublicReviewAgent(gateway).analyze(selected, selected["content"] + " Hypothetical review change.")
    assert result["confirmed_relations"] == [{
        "relation_type": "DOCUMENT_REFERENCE",
        "source_document_id": "3.4.3:en:proposals/dsip-107-implementation",
        "target_document_id": "3.4.3:en:proposals/dsip-107-proposal",
        "source_chunk_id": "3.4.3:en:proposals/dsip-107-implementation:2",
        "source_heading": "Purpose of the pull request",
        "source_url": "https://github.com/apache/dolphinscheduler/pull/18464",
        "source_excerpt": next(
            row["content"] for row in CHUNKS
            if row["chunk_id"] == "3.4.3:en:proposals/dsip-107-implementation:2"
        ),
    }]
    assert "independent part of DSIP #18454" in result["confirmed_relations"][0]["source_excerpt"]
    assert result["impacts"]
    assert all(row["relation"] == "suggested" for row in result["impacts"])
    assert all(
        row["evidence"]["chunk_id"] != "3.4.3:en:proposals/dsip-107-implementation:2"
        for row in result["impacts"]
    )


def test_rejects_history_unknown_source_and_unchanged_content():
    gateway = Gateway()
    selected = next(row for row in CHUNKS if row["document_key"] == "guide/parameter/priority" and row["language"] == "zh" and row["version"] == "3.4.3")
    with pytest.raises(ValueError, match="相同"):
        PublicReviewAgent(gateway).analyze(selected, selected["content"])
    with pytest.raises(ValueError, match="官方"):
        PublicReviewAgent(gateway).analyze({**selected, "source_url": "https://example.com"}, "new")
    with pytest.raises(ValueError, match="当前"):
        PublicReviewAgent(gateway).analyze({**selected, "version": "3.4.2"}, "new")
