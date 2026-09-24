from __future__ import annotations

from fastapi.testclient import TestClient

from src.public_knowledge import PublicKnowledgeIndex
from src.public_server import create_app


QUESTION = "DolphinScheduler 参数优先级从高到低是什么？"


def test_public_deployment_exposes_only_official_corpus_and_engineering_support():
    with TestClient(create_app(index=PublicKnowledgeIndex())) as client:
        health = client.get("/health").json()
        assert health["alive"] and health["rag_ready"]
        assert health["retrieval_policy"] == "bm25"
        paths = client.get("/openapi.json").json()["paths"]
        assert "/public/search" in paths and "/public/query" in paths
        assert "/engineering/items/diff" in paths and "/engineering/impacts/discover" in paths
        assert "/retrieve" not in paths and "/query" not in paths
        assert "/public/change/analyze" not in paths
        proposal = next(
            row for row in client.get("/public/documents").json()["documents"]
            if row["document_key"] == "proposals/dsip-107-proposal"
        )
        assert "DSIP-107" in proposal["title"]
        workspace = client.get("/public/workspace").json()
        assert workspace["source_count"] == 52
        assert workspace["upstream_writes_enabled"] is False
        response = client.post("/public/search", json={"query": QUESTION})
        assert response.status_code == 200
        assert response.json()["results"][0]["source_url"].startswith(
            "https://github.com/apache/dolphinscheduler/blob/"
        )


def test_public_query_without_generator_returns_evidence_not_fake_answer():
    with TestClient(create_app(index=PublicKnowledgeIndex())) as client:
        payload = client.post("/public/query", json={"query": QUESTION}).json()
        assert payload["status"] == "GENERATION_NOT_CONFIGURED"
        assert payload["answer"] == "N/A"
        assert payload["sources"] == []
        assert payload["evidence"]


def test_public_query_checks_citation_membership_and_budget(monkeypatch):
    class Generator:
        def __init__(self, citation_id):
            self.citation_id = citation_id

        def generate(self, *, question, context):
            return {
                "final_answer": "上游传递参数优先。",
                "relevant_sources": [{"document_id": self.citation_id, "page_number": 1}],
            }

    index = PublicKnowledgeIndex()
    top = index.search(QUESTION)[0]
    monkeypatch.setenv("MAX_LLM_CALLS_PER_SESSION", "1")
    with TestClient(create_app(index=index, generator=Generator(top["chunk_id"]))) as client:
        headers = {"X-Demo-Session-ID": "publictestsession"}
        first = client.post("/public/query", json={"query": QUESTION}, headers=headers)
        assert first.status_code == 200
        assert first.json()["status"] == "OK"
        assert first.json()["sources"][0]["chunk_id"] == top["chunk_id"]
        assert client.post("/public/query", json={"query": QUESTION}, headers=headers).status_code == 429
    with TestClient(create_app(index=index, generator=Generator("invented-chunk"))) as client:
        result = client.post(
            "/public/query", json={"query": QUESTION},
            headers={"X-Demo-Session-ID": "anotherpublicsession"},
        ).json()
        assert result["status"] == "ABSTAINED"
        assert result["sources"] == []
def test_public_query_has_a_total_budget_even_when_session_ids_rotate(monkeypatch):
    class Generator:
        def __init__(self, citation_id):
            self.citation_id = citation_id
            self.calls = 0

        def generate(self, *, question, context):
            self.calls += 1
            return {
                "final_answer": "supported answer",
                "relevant_sources": [{"document_id": self.citation_id, "page_number": 1}],
            }

    index = PublicKnowledgeIndex()
    generator = Generator(index.search(QUESTION)[0]["chunk_id"])
    monkeypatch.setenv("MAX_LLM_CALLS_PER_SESSION", "1")
    monkeypatch.setenv("MAX_LLM_CALLS_PER_PROCESS", "2")
    with TestClient(create_app(index=index, generator=generator)) as client:
        responses = [
            client.post(
                "/public/query", json={"query": QUESTION},
                headers={"X-Demo-Session-ID": f"session_{number:08d}"},
            )
            for number in range(3)
        ]
    assert [response.status_code for response in responses] == [200, 200, 429]
    assert generator.calls == 2
