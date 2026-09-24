from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from src.public_knowledge import (
    ROOT, PublicKnowledgeIndex, verified_consistency_notes,
)


@pytest.fixture(scope="module")
def index() -> PublicKnowledgeIndex:
    return PublicKnowledgeIndex()


def test_pinned_bilingual_corpus_metadata_and_source_hashes(index):
    manifest = index.manifest
    assert manifest["workspace"] == "Apache DolphinScheduler"
    assert manifest["baseline_version"] == "3.4.2"
    assert manifest["current_version"] == "3.4.3"
    assert len(manifest["sources"]) == 52
    assert {row["locale"] for row in manifest["sources"]} == {"zh-CN", "en-US"}
    assert {row["source_type"] for row in manifest["sources"]} >= {
        "official_documentation", "github_release", "github_issue", "github_pull_request"
    }
    for row in manifest["sources"]:
        assert row["source_url"].startswith("https://github.com/apache/dolphinscheduler/")
        assert row["commit"] == manifest["commits"][row["version"]]
        assert hashlib.sha256((ROOT / row["local_path"]).read_bytes()).hexdigest() == row["sha256"]


def test_language_and_version_filters_keep_one_workspace(index):
    query = "DolphinScheduler 参数优先级从高到低是什么？"
    zh = index.search(query, language="zh", version="3.4.3")
    en = index.search("parameter priority", language="en", version="3.4.3")
    history = index.search(query, language="zh", version="3.4.2")
    assert zh and en and history
    assert all(row["locale"] == "zh-CN" and row["version"] == "3.4.3" for row in zh)
    assert all(row["locale"] == "en-US" for row in en)
    assert all(row["version"] == "3.4.2" for row in history)
    assert zh[0]["document_key"] == "guide/parameter/priority"


def test_benchmark_rankings_and_policy_are_reproducible(index):
    base = Path(__file__).resolve().parents[2] / "evaluation" / "real_world_retrieval"
    results = json.loads((base / "results" / "benchmark_results.json").read_text(encoding="utf-8"))
    queries = [json.loads(line) for line in (base / "queries.jsonl").read_text(encoding="utf-8").splitlines()]
    assert len(queries) >= 40
    assert results["corpus_sha256"] == hashlib.sha256((ROOT / "corpus_manifest.json").read_bytes()).hexdigest()
    for policy in ("dense", "bm25", "hybrid"):
        stored = json.loads((base / "results" / f"{policy}.json").read_text(encoding="utf-8"))
        for query, expected in zip(queries, stored):
            hits = index.search(query["query"], top_k=5, version=query["version_scope"], language="all", policy=policy)
            assert [row["chunk_id"] for row in hits] == expected["ranked_chunk_ids"]
    winner = max(
        ("dense", "bm25", "hybrid"),
        key=lambda name: (
            results["results"][name]["overall"]["hit_at_1"],
            results["results"][name]["overall"]["mrr"],
            results["results"][name]["overall"]["hit_at_5"],
            -results["results"][name]["overall"]["p95_ms"],
        ),
    )
    assert index.policy["default_policy"] == winner
    assert index.policy["reranker_enabled"] is False


def test_consistency_warning_only_reports_verifiable_version_text_difference():
    base = {
        "document_key": "guide/parameter/priority", "heading": "Parameter Priority",
        "locale": "en-US", "source_url": "https://github.com/apache/dolphinscheduler/example",
    }
    notes = verified_consistency_notes([
        {**base, "version": "3.4.2", "content": "context > local"},
        {**base, "version": "3.4.3", "content": "context > startup > local"},
    ])
    assert len(notes) == 1
    assert notes[0]["kind"] == "verified_version_text_difference"
    assert verified_consistency_notes([
        {**base, "version": "3.4.3", "content": "same"},
        {**base, "version": "3.4.3", "content": "different"},
    ]) == []



def test_consistency_warning_for_explicit_same_parameter_values():
    base = {
        "document_key": "architecture/configuration", "heading": "Configuration",
        "locale": "en-US", "source_url": "https://github.com/apache/dolphinscheduler/example",
    }
    notes = verified_consistency_notes([
        {**base, "version": "3.4.2", "content": "worker.threads=500"},
        {**base, "version": "3.4.3", "content": "worker.threads=1000"},
    ])
    assert any(note["kind"] == "verified_literal_value_difference" and note["values"] == ["500", "1000"] for note in notes)


def test_public_index_rejects_policy_from_a_different_corpus(tmp_path):
    for name in ("corpus_manifest.json", "chunks.json", "dense_vectors.npy", "retrieval_policy.json"):
        (tmp_path / name).write_bytes((ROOT / name).read_bytes())
    policy_path = tmp_path / "retrieval_policy.json"
    policy = json.loads(policy_path.read_text(encoding="utf-8"))
    policy["benchmark_corpus_sha256"] = "0" * 64
    policy_path.write_text(json.dumps(policy), encoding="utf-8")
    with pytest.raises(ValueError, match="does not match pinned corpus"):
        PublicKnowledgeIndex(tmp_path)
