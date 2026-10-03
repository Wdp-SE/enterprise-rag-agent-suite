from __future__ import annotations

import hashlib
import json
import shutil
from pathlib import Path

from fastapi.testclient import TestClient

from src.public_knowledge import PublicKnowledgeIndex
from src.public_server import create_app


SOURCE_CORPUS = Path(__file__).resolve().parents[1] / "public_corpus_edge_ai"


def _client(tmp_path: Path, monkeypatch) -> TestClient:
    monkeypatch.setenv("RD_V2_ALLOW_EXTERNAL_GENERATION", "false")
    root = tmp_path / "public_corpus_edge_ai"
    shutil.copytree(SOURCE_CORPUS, root)
    manifest_sha = hashlib.sha256((root / "corpus_manifest.json").read_bytes()).hexdigest()
    inventory = {
        "schema_version": 1,
        "corpus_manifest_sha256": manifest_sha,
        "figures": [],
    }
    (root / "figure_evidence.json").write_text(json.dumps(inventory) + "\n", encoding="utf-8")
    sidecar_bytes = (json.dumps({
        "schema_version": 1,
        "corpus_manifest_sha256": manifest_sha,
        "chunks": [],
    }, separators=(",", ":")) + "\n").encode("utf-8")
    sidecar = root / "figure_evidence_reviewed.json"
    sidecar.write_bytes(sidecar_bytes)
    (root / "figure_evidence_reviewed.lock.json").write_text(json.dumps({
        "schema_version": 1,
        "sidecar_sha256": hashlib.sha256(sidecar_bytes).hexdigest(),
        "corpus_manifest_sha256": manifest_sha,
    }), encoding="utf-8")
    return TestClient(create_app(
        index=PublicKnowledgeIndex(root),
        retrieval_config_path=root / "public_retrieval_runtime.json",
    ))


def test_workspace_and_health_identify_only_the_chinese_edge_ai_profile(tmp_path, monkeypatch):
    with _client(tmp_path, monkeypatch) as client:
        workspace = client.get("/public/workspace").json()
        health = client.get("/health").json()

    assert workspace["workspace_id"] == "edge_ai_device"
    assert workspace["domain_profile"]["id"] == "edge_ai_device"
    assert workspace["languages"] == ["zh"]
    assert workspace["source_count"] == 18
    assert workspace["chunk_count"] == 394
    assert workspace["current_version"] == "wiki-1eadc6584f96"
    assert workspace["snapshots"][0]["commit"] == "1eadc6584f962b6efdbdb3e49b2b4ce30c85be08"
    assert len(workspace["source_registry"]) == workspace["source_count"]
    assert all({"source_id", "source_url", "repository", "source_snapshot", "commit", "sha256"} <= set(row)
               for row in workspace["source_registry"])
    assert "JetPack 7.2 (L4T 39.2.0)" in workspace["software_baselines"]
    assert "reComputer Industrial J4012" in workspace["hardware_models"]
    assert workspace["retrieval_evaluation_status"] == "new_corpus_pending_rebenchmark"
    assert workspace["frozen_benchmark_query_count"] == 0
    assert "retrieval_evaluation" not in workspace
    assert "change_review_evaluation" not in workspace
    assert health["workspace"] == workspace["workspace"]
    assert workspace["workspace_id"] == "edge_ai_device"


def test_search_and_query_apply_the_same_hard_device_and_baseline_scope(tmp_path, monkeypatch):
    query = "J4012 JetPack 7.2 工业视觉监控部署"
    payload = {
        "query": query,
        "top_k": 5,
        "device_model": "reComputer Industrial J4012",
        "software_baseline": "JetPack 7.2 (L4T 39.2.0)",
    }
    with _client(tmp_path, monkeypatch) as client:
        search = client.post("/public/search", json=payload)
        query_response = client.post("/public/query", json=payload)

    assert search.status_code == 200
    search_hits = search.json()["results"]
    assert search_hits
    assert all(row["language"] == "zh" for row in search_hits)
    assert all(row["software_baselines"] == ["JetPack 7.2 (L4T 39.2.0)"] for row in search_hits if row["software_baselines"] != ["*"])
    assert search_hits[0]["source_id"] == "seeed-industrial-vision-monitoring"
    assert query_response.status_code == 200
    assert query_response.json()["evidence"]
    assert query_response.json()["status"] == "GENERATION_NOT_CONFIGURED"
    assert all(row["source_id"] != "seeed-jetson-flashing-troubleshooting" for row in query_response.json()["evidence"])


def test_api_rejects_unknown_hardware_baseline_and_non_chinese_language(tmp_path, monkeypatch):
    with _client(tmp_path, monkeypatch) as client:
        unknown_model = client.post("/public/search", json={
            "query": "设备刷写 JetPack",
            "device_model": "unknown board",
        })
        unknown_baseline = client.post("/public/search", json={
            "query": "设备刷写 JetPack",
            "software_baseline": "JetPack 99.0",
        })
        english = client.post("/public/search", json={
            "query": "How do I flash JetPack?",
            "language": "en",
        })

    assert unknown_model.status_code == 422
    assert unknown_baseline.status_code == 422
    assert english.status_code == 422


def test_review_advice_cannot_reuse_evidence_outside_selected_device_scope(tmp_path, monkeypatch):
    with _client(tmp_path, monkeypatch) as client:
        search = client.post("/public/search", json={
            "query": "工业视觉 JetPack 7.2",
            "device_model": "reComputer Industrial J4012",
            "software_baseline": "JetPack 7.2 (L4T 39.2.0)",
        }).json()
        chunk_id = search["results"][0]["chunk_id"]
        response = client.post("/public/review-advice", json={
            "change_summary": "更新工业视觉运行环境",
            "evidence_chunk_ids": [chunk_id],
            "device_model": "reComputer Industrial J3011",
        })

    assert response.status_code == 422
    assert response.json()["detail"] == "INVALID_REVIEW_EVIDENCE"


def test_review_advice_accepts_evidence_only_with_matching_confirmed_scope(tmp_path, monkeypatch):
    scope = {
        "device_model": "reComputer Industrial J4012",
        "software_baseline": "JetPack 7.2 (L4T 39.2.0)",
    }
    with _client(tmp_path, monkeypatch) as client:
        search = client.post("/public/search", json={
            "query": "工业视觉监控部署环境", **scope,
        }).json()
        chunk_id = search["results"][0]["chunk_id"]
        response = client.post("/public/review-advice", json={
            "change_summary": "更新 J4012 工业视觉部署环境",
            "evidence_chunk_ids": [chunk_id], **scope,
        })

    assert response.status_code == 200
    assert response.json()["status"] == "GENERATION_NOT_CONFIGURED"
    assert [row["chunk_id"] for row in response.json()["evidence"]] == [chunk_id]
