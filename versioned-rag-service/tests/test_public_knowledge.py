from __future__ import annotations

import hashlib
import json
import shutil
from pathlib import Path

import numpy as np
import pytest

from src.public_knowledge import (
    ROOT, PublicKnowledgeIndex, _parts, build_index, verified_consistency_notes,
)


@pytest.fixture(scope="module")
def index() -> PublicKnowledgeIndex:
    return PublicKnowledgeIndex()


def test_pinned_bilingual_corpus_metadata_and_source_hashes(index):
    manifest = index.manifest
    assert manifest["workspace"] == "Apache DolphinScheduler"
    assert manifest["baseline_version"] == "3.4.2"
    assert manifest["current_version"] == "3.4.3"
    assert len(manifest["sources"]) >= 52
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


def test_frozen_benchmark_is_preserved_but_expanded_corpus_is_pending_rebenchmark(index):
    base = Path(__file__).resolve().parents[2] / "evaluation" / "real_world_retrieval"
    results = json.loads((base / "results" / "benchmark_results.json").read_text(encoding="utf-8"))
    queries = [json.loads(line) for line in (base / "queries.jsonl").read_text(encoding="utf-8").splitlines()]
    assert len(queries) >= 40
    frozen = index.policy["frozen_selection_evidence"]
    assert results["corpus_sha256"] == frozen["corpus_sha256"]
    assert results["query_count"] == frozen["query_count"]
    assert index.policy["benchmark_corpus_sha256"] == hashlib.sha256((ROOT / "corpus_manifest.json").read_bytes()).hexdigest()
    assert index.policy["selection_status"] == "expanded_corpus_pending_rebenchmark"
    assert index.policy["benchmark_query_count"] == 0
    corpus_ids = {chunk["chunk_id"] for chunk in index.chunks}
    for policy in ("dense", "bm25", "hybrid"):
        stored = json.loads((base / "results" / f"{policy}.json").read_text(encoding="utf-8"))
        assert len(stored) == len(queries)
        assert all(chunk_id in corpus_ids for row in stored for chunk_id in row["ranked_chunk_ids"])
    winner = max(
        ("dense", "bm25", "hybrid"),
        key=lambda name: (
            results["results"][name]["overall"]["hit_at_1"],
            results["results"][name]["overall"]["mrr"],
            results["results"][name]["overall"]["hit_at_5"],
            -results["results"][name]["overall"]["p95_ms"],
        ),
    )
    assert frozen["selected_policy"] == winner
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


def test_consistency_warning_does_not_compare_different_languages_as_version_conflicts():
    base = {
        "document_key": "autoware-documentation/design/planning",
        "heading": "Planning Architecture", "source_url": "https://example.invalid/source",
    }

    assert verified_consistency_notes([
        {**base, "version": "docs-main", "language": "en", "content": "Plan a safe trajectory."},
        {**base, "version": "docs-main", "language": "zh", "content": "规划安全轨迹。"},
    ]) == []


def test_current_scope_can_include_latest_snapshots_from_two_release_lines(tmp_path):
    sources = []
    for version, language, locale, key, text in (
        ("docs-main", "en", "en-US", "autoware-documentation/design/planning", "planning architecture safe route"),
        ("docs-main", "zh", "zh-CN", "autoware-documentation/design/planning", "规划架构 安全路线"),
        ("0.52.0", "en", "en-US", "universe/planning/validator", "planning validator trajectory validation"),
        ("0.51.0", "en", "en-US", "universe/planning/validator", "planning validator old trajectory validation"),
    ):
        local_path = f"sources/{version}/{language}/{len(sources)}.md"
        raw = f"# Planning\n\n{text}\n".encode("utf-8")
        target = tmp_path / local_path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(raw)
        sources.append({
            "version": version, "language": language, "locale": locale,
            "document_key": key, "document_path": f"docs/{len(sources)}.md",
            "local_path": local_path, "source_type": "official_documentation",
            "source_url": f"https://github.com/example/repo/blob/pinned/docs/{len(sources)}.md",
            "repository": "example/repo", "commit": "pinned",
            "sha256": hashlib.sha256(raw).hexdigest(),
        })
    manifest = {
        "workspace": "Autoware", "repository": "example/repo",
        "baseline_version": "0.51.0", "current_version": "latest",
        "available_versions": ["latest", "docs-main", "0.52.0", "0.51.0"],
        "version_scopes": {"latest": {"versions": ["docs-main", "0.52.0"]}},
        "commits": {}, "sources": sources,
    }
    manifest_path = tmp_path / "corpus_manifest.json"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    (tmp_path / "retrieval_policy.json").write_text(json.dumps({
        "default_policy": "bm25", "benchmark_query_count": 0,
        "benchmark_corpus_sha256": hashlib.sha256(manifest_path.read_bytes()).hexdigest(),
        "index_artifacts_sha256": {},
    }), encoding="utf-8")

    build_index(tmp_path)
    latest = PublicKnowledgeIndex(tmp_path).search("planning", version="current", language="all")
    exact = PublicKnowledgeIndex(tmp_path).search("planning", version="docs-main", language="all")
    historical = PublicKnowledgeIndex(tmp_path).search("planning", version="0.51.0", language="all")

    assert {row["version"] for row in latest} == {"docs-main", "0.52.0"}
    assert {row["version"] for row in exact} == {"docs-main"}
    assert {row["version"] for row in historical} == {"0.51.0"}


def test_parts_keep_inherited_heading_path():
    parts = _parts("# API\n## Workflow\n### Recovery\nDefault: retry")
    assert parts[0] == ("Recovery", ["API", "Workflow", "Recovery"], "Default: retry")


def test_heading_match_ranks_above_body_repetition_with_bm25_fields(tmp_path):
    source_root = tmp_path / "sources" / "3.4.3" / "en"
    source_root.mkdir(parents=True)
    documents = [
        ("guide/missed-fire", "# Scheduling Guide\n## Missed Fire Policy\nDefault: CONTINUE"),
        ("guide/operations", "# Operations Guide\n## General Notes\n" + "missed fire policy " * 20),
    ]
    sources = []
    for key, content in documents:
        local_path = f"sources/3.4.3/en/{key.rsplit('/', 1)[-1]}.md"
        path = tmp_path / local_path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content.encode("utf-8"))
        sources.append({
            "version": "3.4.3", "language": "en", "locale": "en-US",
            "document_key": key, "document_path": f"docs/docs/en/{key.rsplit('/', 1)[-1]}.md",
            "local_path": local_path, "source_type": "official_documentation",
            "source_url": "https://github.com/apache/dolphinscheduler/blob/pinned/docs.md",
            "repository": "apache/dolphinscheduler", "commit": "pinned",
            "sha256": hashlib.sha256(content.encode("utf-8")).hexdigest(),
        })
    manifest = {
        "workspace": "Apache DolphinScheduler", "repository": "apache/dolphinscheduler",
        "baseline_version": "3.4.2", "current_version": "3.4.3",
        "commits": {"3.4.3": "pinned"}, "sources": sources,
    }
    manifest_path = tmp_path / "corpus_manifest.json"
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False), encoding="utf-8")
    (tmp_path / "retrieval_policy.json").write_text(json.dumps({
        "default_policy": "bm25", "benchmark_query_count": 0,
        "benchmark_corpus_sha256": hashlib.sha256(manifest_path.read_bytes()).hexdigest(),
        "index_artifacts_sha256": {},
    }), encoding="utf-8")

    build_index(tmp_path)
    policy_path = tmp_path / "retrieval_policy.json"
    policy = json.loads(policy_path.read_text(encoding="utf-8"))
    assert policy["default_policy"] == "bm25"
    assert policy["benchmark_corpus_sha256"] == hashlib.sha256(manifest_path.read_bytes()).hexdigest()
    assert policy["index_artifacts_sha256"] == {
        name: hashlib.sha256((tmp_path / name).read_bytes()).hexdigest()
        for name in ("chunks.json", "dense_vectors.npy")
    }

    index = PublicKnowledgeIndex(tmp_path)
    baseline = index.search("missed fire policy", version="3.4.3", language="en", policy="bm25")
    candidate = index.search("missed fire policy", version="3.4.3", language="en", policy="bm25_fields")
    assert baseline[0]["document_key"] == "guide/operations"
    assert candidate[0]["document_key"] == "guide/missed-fire"
    assert candidate[0]["heading_path"] == ["Scheduling Guide", "Missed Fire Policy"]


def test_fielded_bm25_does_not_compute_dense_or_baseline_scores(index, monkeypatch):
    def unexpected(*_args, **_kwargs):
        pytest.fail("bm25_fields must calculate only its selected score")

    monkeypatch.setattr(index, "_bm25", unexpected)
    monkeypatch.setattr("src.public_knowledge.dense_vector", unexpected)

    hits = index.search(
        "DolphinScheduler parameter priority", version="3.4.3", language="en", policy="bm25_fields"
    )

    assert hits
    assert all(hit["retrieval_policy"] == "bm25_fields" for hit in hits)


def test_source_diverse_bm25_exposes_more_relevant_documents_without_changing_default(monkeypatch):
    candidate_index = object.__new__(PublicKnowledgeIndex)
    candidate_index.manifest = {
        "current_version": "3.4.3",
        "sources": [{"version": "3.4.3"}, {"version": "3.4.2"}],
    }
    candidate_index.policy = {"default_policy": "bm25"}
    candidate_index.chunks = [
        {"chunk_id": "a:1", "document_id": "3.4.3:en:a", "version": "3.4.3", "language": "en"},
        {"chunk_id": "a:2", "document_id": "3.4.3:en:a", "version": "3.4.3", "language": "en"},
        {"chunk_id": "a:3", "document_id": "3.4.3:en:a", "version": "3.4.3", "language": "en"},
        {"chunk_id": "b:1", "document_id": "3.4.3:en:b", "version": "3.4.3", "language": "en"},
        {"chunk_id": "c:1", "document_id": "3.4.3:en:c", "version": "3.4.3", "language": "en"},
        {"chunk_id": "old-a:1", "document_id": "3.4.2:en:a", "version": "3.4.2", "language": "en"},
    ]
    monkeypatch.setattr(candidate_index, "_bm25", lambda _query: np.array([10, 9, 8, 7, 6, 5], dtype=np.float32))

    default = candidate_index.search("recovery", top_k=3, version="current", language="en")
    diverse = candidate_index.search(
        "recovery", top_k=3, version="current", language="en", policy="bm25_source_diverse"
    )
    top2 = candidate_index.search(
        "recovery", top_k=4, version="current", language="en", policy="bm25_top2_diverse"
    )
    top3 = candidate_index.search(
        "recovery", top_k=5, version="current", language="en", policy="bm25_top3_diverse"
    )
    across_versions = candidate_index.search(
        "recovery", top_k=6, version="all", language="en", policy="bm25_source_diverse"
    )

    assert [row["chunk_id"] for row in default] == ["a:1", "a:2", "a:3"]
    assert [row["chunk_id"] for row in diverse] == ["a:1", "b:1", "c:1"]
    assert [row["retrieval_score"] for row in diverse] == [10, 7, 6]
    assert all(row["retrieval_policy"] == "bm25_source_diverse" for row in diverse)
    assert [row["chunk_id"] for row in top2] == ["a:1", "a:2", "b:1", "c:1"]
    assert [row["chunk_id"] for row in top3] == ["a:1", "a:2", "a:3", "b:1", "c:1"]
    assert [row["chunk_id"] for row in across_versions[:4]] == ["a:1", "b:1", "c:1", "old-a:1"]


def test_source_diverse_bm25_keeps_matching_siblings_before_zero_score_documents(monkeypatch):
    candidate_index = object.__new__(PublicKnowledgeIndex)
    candidate_index.manifest = {"current_version": "3.4.3", "sources": [{"version": "3.4.3"}]}
    candidate_index.policy = {"default_policy": "bm25"}
    candidate_index.chunks = [
        {"chunk_id": "a:1", "document_id": "a", "version": "3.4.3", "language": "en"},
        {"chunk_id": "a:2", "document_id": "a", "version": "3.4.3", "language": "en"},
        {"chunk_id": "b:1", "document_id": "b", "version": "3.4.3", "language": "en"},
    ]
    monkeypatch.setattr(candidate_index, "_bm25", lambda _query: np.array([10, 9, 0], dtype=np.float32))

    hits = candidate_index.search("recovery", top_k=2, policy="bm25_source_diverse")

    assert [row["chunk_id"] for row in hits] == ["a:1", "a:2"]



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


@pytest.mark.parametrize("artifact", ["chunks.json", "dense_vectors.npy"])
def test_public_index_rejects_tampered_prebuilt_artifact(tmp_path, artifact):
    for name in ("corpus_manifest.json", "chunks.json", "dense_vectors.npy", "retrieval_policy.json"):
        (tmp_path / name).write_bytes((ROOT / name).read_bytes())
    shutil.copytree(ROOT / "sources", tmp_path / "sources")

    artifact_path = tmp_path / artifact
    if artifact == "chunks.json":
        chunks = json.loads(artifact_path.read_text(encoding="utf-8"))
        chunks[0]["content"] = "伪造的官方资料内容"
        artifact_path.write_text(json.dumps(chunks, ensure_ascii=False), encoding="utf-8")
    else:
        tampered = bytearray(artifact_path.read_bytes())
        tampered[-1] ^= 1
        artifact_path.write_bytes(tampered)

    with pytest.raises(ValueError, match="public corpus index artifact hash mismatch"):
        PublicKnowledgeIndex(tmp_path)
