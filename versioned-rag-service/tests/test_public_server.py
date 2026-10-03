from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from src.public_knowledge import PublicKnowledgeIndex
from src.public_server import create_app


CORPUS = Path(__file__).resolve().parents[1] / "public_corpus_pphuman"
QUESTION = "行人跟踪模型切换后，推理配置和跟踪参数需要核对哪些内容？"


class StructuredGenerator:
    provider = "deepseek"
    model = "test-model"

    def __init__(
        self,
        evidence_id: str | list[str],
        *,
        relevant_sources: list[dict] | None = None,
        error: Exception | None = None,
    ):
        self.evidence_id = evidence_id
        self.evidence_ids = evidence_id if isinstance(evidence_id, list) else [evidence_id]
        self.relevant_sources = relevant_sources
        self.error = error
        self.calls = 0
        self.last_context = ""

    def generate(self, *, question: str, context: str) -> dict:
        self.calls += 1
        self.last_context = context
        if self.error:
            raise self.error
        return {
            "claims": [{"text": "请核对跟踪配置及其对应参数。", "evidence_ids": self.evidence_ids}],
            "relevant_sources": self.relevant_sources or [],
        }


def _index() -> PublicKnowledgeIndex:
    return PublicKnowledgeIndex(CORPUS)


def test_only_the_pphuman_corpus_is_shipped_for_public_retrieval():
    service = CORPUS.parent

    assert CORPUS.is_dir()
    assert not (service / "public_corpus_edge_ai").exists()
    assert not (service / "public_corpus_industrial_inspection").exists()


def test_default_index_and_health_use_the_pphuman_corpus(monkeypatch):
    monkeypatch.setenv("APP_ENV", "public_demo")
    monkeypatch.setenv("RAG_PUBLIC_CORPUS_ROOT", "retired_corpus_should_not_load")
    monkeypatch.setenv(
        "RAG_PUBLIC_RETRIEVAL_CONFIG",
        "retired_corpus_should_not_load/public_retrieval_runtime.json",
    )
    with TestClient(create_app()) as client:
        workspace = client.get("/public/workspace").json()
        health = client.get("/health").json()

    assert workspace["workspace_id"] == "pphuman"
    assert workspace["languages"] == ["zh"]
    assert workspace["source_count"] == 83
    assert workspace["current_version"] == "v2.9.0"
    assert workspace["rag_ready"] is True
    assert workspace["retrieval_evaluation_status"] == "new_corpus_pending_rebenchmark"
    assert health["rag_ready"] is True
    assert health["workspace"] == workspace["workspace"]
    assert workspace["workspace_id"] == "pphuman"


def test_query_without_generation_returns_retrieved_evidence_without_fabricating_answer():
    index = _index()
    with TestClient(create_app(index=index)) as client:
        response = client.post("/public/query", json={"query": QUESTION, "language": "zh"})

    body = response.json()
    assert response.status_code == 200
    assert body["status"] == "GENERATION_NOT_CONFIGURED"
    assert body["answer"] == "N/A"
    assert body["evidence"]
    assert all(row["language"] == "zh" for row in body["evidence"])


def test_generation_resolves_short_evidence_aliases_and_derives_sources_from_claims():
    index = _index()
    hits = index.search(QUESTION, top_k=5, version="latest", language="zh")
    hit = hits[1]
    generator = StructuredGenerator(
        "E2",
        relevant_sources=[{"document_id": "untrusted-model-source", "page_number": 999}],
    )
    with TestClient(create_app(index=index, generator=generator)) as client:
        response = client.post("/public/query", json={
            "query": QUESTION, "top_k": 5, "version": "latest", "language": "zh",
        })

    accepted = response.json()
    assert response.status_code == 200
    assert accepted["status"] == "OK"
    assert accepted["sources"][0]["chunk_id"] == hit["chunk_id"]
    assert accepted["claims"][0]["evidence_ids"] == [hit["chunk_id"]]
    assert "E2" in generator.last_context

    invalid = StructuredGenerator(["E1", "not-in-current-retrieval"])
    with TestClient(create_app(index=index, generator=invalid)) as client:
        rejected = client.post("/public/query", json={
            "query": QUESTION, "top_k": 5, "version": "latest", "language": "zh",
        }).json()
    assert rejected["status"] == "ABSTAINED"
    assert rejected["evidence"]
    assert rejected["generation"]["failure_reason"] == "NO_VALID_EVIDENCE_CITATIONS"
    assert rejected["generation"]["claimed_citation_count"] == 2
    assert rejected["generation"]["valid_citation_count"] == 1


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
    generator = StructuredGenerator("E1", relevant_sources=[])
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
