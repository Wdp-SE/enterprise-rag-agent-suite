from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from src.public_knowledge import PublicKnowledgeIndex
from src.public_server import create_app


SERVICE = Path(__file__).resolve().parents[1]
CORPUS = SERVICE / "public_corpus_industrial_inspection"
REPOSITORY = "xbs0325/industrial-inspection"


def test_unlicensed_project_corpus_is_loadable_for_status_but_never_searchable():
    index = PublicKnowledgeIndex(CORPUS)

    assert index.manifest["project_id"] == "industrial-inspection"
    assert index.ready is False
    assert index.project_status["reason"] == "pending_redistribution_license"
    assert index.chunks == []
    with pytest.raises(ValueError, match="license"):
        index.search("camera health check")


def test_workspace_health_and_search_report_one_project_without_legacy_fallback():
    with TestClient(create_app(
        index=PublicKnowledgeIndex(CORPUS),
        retrieval_config_path=CORPUS / "public_retrieval_runtime.json",
    )) as client:
        workspace = client.get("/public/workspace")
        health = client.get("/health")
        search = client.post("/public/search", json={"query": "camera health check"})
        sha_search = client.post("/public/search", json={
            "query": "camera health check", "version": "6d0df954f26b1810910db9f50727ca8bd19afa9f",
        })
        sha_review = client.post("/public/review-advice", json={
            "change_summary": "change camera health check",
            "evidence_chunk_ids": ["untrusted-chunk"],
            "version": "6d0df954f26b1810910db9f50727ca8bd19afa9f",
        })

    assert workspace.status_code == 200
    body = workspace.json()
    assert body["workspace_id"] == "industrial-inspection"
    assert body["repository"] == REPOSITORY
    assert body["repositories"] == [REPOSITORY]
    assert body["project_primary_count"] == 0
    assert body["dependency_reference_count"] == 0
    assert body["public_body_indexing_enabled"] is False
    assert body["source_status"] == "pending_redistribution_license"
    assert health.json()["rag_ready"] is False
    assert health.json()["workspace_id"] == "industrial-inspection"
    assert search.status_code == 503
    assert search.json()["detail"] == "PROJECT_CORPUS_INACTIVE_LICENSE_PENDING"
    assert sha_search.status_code == 503
    assert sha_search.json()["detail"] == "PROJECT_CORPUS_INACTIVE_LICENSE_PENDING"
    assert sha_review.status_code == 503
    assert sha_review.json()["detail"] == "PROJECT_CORPUS_INACTIVE_LICENSE_PENDING"


def test_clients_cannot_choose_namespace_or_repository_and_empty_dependency_opt_in_is_rejected():
    with TestClient(create_app(
        index=PublicKnowledgeIndex(CORPUS),
        retrieval_config_path=CORPUS / "public_retrieval_runtime.json",
    )) as client:
        namespace = client.post("/public/search", json={
            "query": "camera health check", "namespace": "dependency_reference",
        })
        repository = client.post("/public/search", json={
            "query": "camera health check", "repository": "attacker/other",
        })
        dependency = client.post("/public/search", json={
            "query": "JetPack version", "include_dependency_reference": True,
        })

    assert namespace.status_code == 422
    assert repository.status_code == 422
    assert dependency.status_code == 422
    assert dependency.json()["detail"] == "DEPENDENCY_REFERENCE_NOT_AVAILABLE"


def test_unlicensed_project_cannot_run_agent_review_generation():
    class Generator:
        calls = 0

        def generate_review(self, **kwargs):
            self.calls += 1
            raise AssertionError("inactive project must not call the model")

    generator = Generator()
    with TestClient(create_app(
        index=PublicKnowledgeIndex(CORPUS),
        generator=generator,
        retrieval_config_path=CORPUS / "public_retrieval_runtime.json",
    )) as client:
        response = client.post("/public/review-advice", json={
            "change_summary": "change camera health check",
            "evidence_chunk_ids": ["untrusted-chunk"],
        })

    assert response.status_code == 503
    assert response.json()["detail"] == "PROJECT_CORPUS_INACTIVE_LICENSE_PENDING"
    assert generator.calls == 0


def test_public_demo_rejects_a_legacy_corpus_even_if_environment_points_to_it(monkeypatch):
    monkeypatch.setenv("APP_ENV", "public_demo")
    legacy_root = SERVICE / "public_corpus_edge_ai"
    with TestClient(create_app(
        index=PublicKnowledgeIndex(legacy_root),
        retrieval_config_path=legacy_root / "public_retrieval_runtime.json",
    )) as client:
        response = client.get("/public/workspace")

    assert response.status_code == 503
    assert response.json()["detail"] == "PUBLIC_CORPUS_PROFILE_MISMATCH"
