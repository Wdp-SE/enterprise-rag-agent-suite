from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from src.public_knowledge import PublicKnowledgeIndex
from src.public_server import create_app


CORPUS = Path(__file__).resolve().parents[1] / "public_corpus_edge_ai"
QUESTION = "J4012 JetPack 7.2 工业视觉监控部署"


class StructuredGenerator:
    provider = "deepseek"
    model = "test-model"

    def __init__(self, chunk_id: str, *, valid: bool = True, error: Exception | None = None):
        self.chunk_id = chunk_id
        self.valid = valid
        self.error = error
        self.calls = 0

    def generate(self, *, question: str, context: str) -> dict:
        self.calls += 1
        if self.error:
            raise self.error
        evidence_id = self.chunk_id if self.valid else "not-in-current-retrieval"
        return {
            "claims": [{"text": "请按目标设备核对 JetPack 与部署环境。", "evidence_ids": [evidence_id]}],
            "relevant_sources": [{"document_id": evidence_id, "page_number": 1}],
        }


def _index() -> PublicKnowledgeIndex:
    return PublicKnowledgeIndex(CORPUS)


def test_default_index_and_health_use_the_pinned_chinese_edge_device_corpus():
    index = PublicKnowledgeIndex()
    with TestClient(create_app(index=index)) as client:
        workspace = client.get("/public/workspace").json()
        health = client.get("/health").json()

    assert index.manifest["workspace_id"] == "edge_ai_device"
    assert workspace["workspace_id"] == "edge_ai_device"
    assert workspace["languages"] == ["zh"]
    assert workspace["source_count"] == 18
    assert workspace["current_version"] == "wiki-1eadc6584f96"
    assert health["workspace"] == workspace["workspace"]
    assert workspace["workspace_id"] == "edge_ai_device"


def test_query_without_generation_returns_retrieved_evidence_without_fabricating_answer():
    index = _index()
    with TestClient(create_app(index=index)) as client:
        response = client.post("/public/query", json={"query": QUESTION, "language": "zh"})

    body = response.json()
    assert response.status_code == 200
    assert body["status"] == "GENERATION_NOT_CONFIGURED"
    assert body["answer"] == "N/A"
    assert body["evidence"]
    assert body["evidence"][0]["source_id"] == "seeed-industrial-vision-monitoring"
    assert all(row["language"] == "zh" for row in body["evidence"])


def test_generation_claims_and_source_citations_must_belong_to_this_retrieval():
    index = _index()
    hit = index.search(QUESTION, top_k=1, version="current", language="zh")[0]
    generator = StructuredGenerator(hit["chunk_id"])
    with TestClient(create_app(index=index, generator=generator)) as client:
        accepted = client.post("/public/query", json={"query": QUESTION, "top_k": 1, "language": "zh"}).json()

    assert accepted["status"] == "OK"
    assert accepted["sources"][0]["chunk_id"] == hit["chunk_id"]
    assert accepted["claims"][0]["evidence_ids"] == [hit["chunk_id"]]

    invalid = StructuredGenerator(hit["chunk_id"], valid=False)
    with TestClient(create_app(index=index, generator=invalid)) as client:
        rejected = client.post("/public/query", json={"query": QUESTION, "top_k": 1, "language": "zh"}).json()
    assert rejected["status"] == "ABSTAINED"
    assert rejected["evidence"]
    assert rejected["generation"]["failure_reason"] == "NO_VALID_EVIDENCE_CITATIONS"


def test_no_positive_retrieval_match_skips_model_call_and_reports_evidence_gap():
    index = _index()
    generator = StructuredGenerator("unused")
    with TestClient(create_app(index=index, generator=generator)) as client:
        response = client.post("/public/query", json={"query": "qzxv-not-in-the-document-corpus", "language": "zh"})

    assert response.json()["status"] == "NO_EVIDENCE"
    assert response.json()["evidence"] == []
    assert response.json()["generation"]["failure_reason"] == "NO_POSITIVE_RETRIEVAL_EVIDENCE"
    assert generator.calls == 0


def test_provider_failure_keeps_retrieval_evidence_and_returns_actionable_status():
    index = _index()
    generator = StructuredGenerator("unused", error=ConnectionError("private provider detail"))
    with TestClient(create_app(index=index, generator=generator)) as client:
        response = client.post("/public/query", json={"query": QUESTION, "language": "zh"})

    body = response.json()
    assert body["status"] == "GENERATION_PROVIDER_UNAVAILABLE"
    assert body["evidence"]
    assert "private provider detail" not in str(body)


def test_public_generation_has_no_application_call_budget():
    index = _index()
    hit = index.search(QUESTION, top_k=1, version="current", language="zh")[0]
    generator = StructuredGenerator(hit["chunk_id"])
    with TestClient(create_app(index=index, generator=generator)) as client:
        bodies = [client.post("/public/query", json={"query": QUESTION, "top_k": 1, "language": "zh"}).json()
                  for _ in range(5)]

    assert generator.calls == 5
    assert all(body["status"] == "OK" for body in bodies)


def test_private_company_request_is_stopped_before_retrieval_or_generation():
    index = _index()

    def unexpected_search(*args, **kwargs):
        raise AssertionError("private company requests must be stopped before retrieval")

    index.search = unexpected_search
    generator = StructuredGenerator("unused")
    with TestClient(create_app(index=index, generator=generator)) as client:
        response = client.post("/public/query", json={
            "query": "查询本公司的内部 API 与私有工单", "language": "zh",
        })

    assert response.json()["status"] == "OUT_OF_SCOPE"
    assert response.json()["evidence"] == []
    assert generator.calls == 0
