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
        assert "/public/review-advice" in paths
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


def test_generation_enabled_without_api_key_stays_in_evidence_only_mode(monkeypatch):
    monkeypatch.setenv("RD_V2_ALLOW_EXTERNAL_GENERATION", "true")
    monkeypatch.setenv("RD_V2_GENERATION_PROVIDER", "dashscope")
    monkeypatch.delenv("DASHSCOPE_API_KEY", raising=False)

    with TestClient(create_app(index=PublicKnowledgeIndex())) as client:
        response = client.post(
            "/public/query", json={"query": QUESTION},
            headers={"X-Demo-Session-ID": "publictestsession"},
        )

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "GENERATION_NOT_CONFIGURED"
    assert payload["answer"] == "N/A"
    assert payload["sources"] == []
    assert payload["evidence"]


def test_deepseek_provider_without_deepseek_key_stays_in_evidence_only_mode(monkeypatch):
    monkeypatch.setenv("RD_V2_ALLOW_EXTERNAL_GENERATION", "true")
    monkeypatch.setenv("RD_V2_GENERATION_PROVIDER", "deepseek")
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    monkeypatch.setenv("DASHSCOPE_API_KEY", "must-not-be-used-for-deepseek")

    with TestClient(create_app(index=PublicKnowledgeIndex())) as client:
        response = client.post(
            "/public/query", json={"query": QUESTION},
            headers={"X-Demo-Session-ID": "publictestsession"},
        )

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "GENERATION_NOT_CONFIGURED"
    assert payload["answer"] == "N/A"
    assert payload["sources"] == []
    assert payload["evidence"]


def test_generation_enabled_with_api_key_wires_qwen_provider(monkeypatch):
    monkeypatch.setenv("RD_V2_ALLOW_EXTERNAL_GENERATION", "true")
    monkeypatch.setenv("DASHSCOPE_API_KEY", "unit-test-placeholder")
    index = PublicKnowledgeIndex()
    cited_chunk = index.search(QUESTION)[0]["chunk_id"]
    constructed = {}

    class ConfiguredGenerator:
        def __init__(self, *, provider: str, model: str):
            constructed["provider"] = provider
            constructed["model"] = model

        def generate(self, *, question: str, context: str) -> dict:
            return {
                "final_answer": "由检索证据支持的测试回答。",
                "relevant_sources": [{"document_id": cited_chunk, "page_number": 1}],
            }

    monkeypatch.setattr("src.public_server.StructuredAnswerGenerator", ConfiguredGenerator)
    with TestClient(create_app(index=index)) as client:
        response = client.post(
            "/public/query", json={"query": QUESTION},
            headers={"X-Demo-Session-ID": "publictestsession"},
        )

    assert response.status_code == 200
    payload = response.json()
    assert constructed == {"provider": "dashscope", "model": "qwen-turbo"}
    assert payload["status"] == "OK"
    assert payload["answer"] == "由检索证据支持的测试回答。"
    assert payload["sources"][0]["chunk_id"] == cited_chunk


def test_generation_enabled_with_deepseek_key_wires_deepseek_provider(monkeypatch):
    monkeypatch.setenv("RD_V2_ALLOW_EXTERNAL_GENERATION", "true")
    monkeypatch.setenv("RD_V2_GENERATION_PROVIDER", "deepseek")
    monkeypatch.delenv("RD_V2_GENERATION_MODEL", raising=False)
    monkeypatch.delenv("DASHSCOPE_API_KEY", raising=False)
    monkeypatch.setenv("DEEPSEEK_API_KEY", "unit-test-placeholder")
    index = PublicKnowledgeIndex()
    cited_chunk = index.search(QUESTION)[0]["chunk_id"]
    constructed = {}

    class ConfiguredGenerator:
        def __init__(self, *, provider: str, model: str):
            constructed["provider"] = provider
            constructed["model"] = model

        def generate(self, *, question: str, context: str) -> dict:
            return {
                "final_answer": "由检索证据支持的 DeepSeek 测试回答。",
                "relevant_sources": [{"document_id": cited_chunk, "page_number": 1}],
            }

    monkeypatch.setattr("src.public_server.StructuredAnswerGenerator", ConfiguredGenerator)
    with TestClient(create_app(index=index)) as client:
        response = client.post(
            "/public/query", json={"query": QUESTION},
            headers={"X-Demo-Session-ID": "publictestsession"},
        )

    assert response.status_code == 200
    payload = response.json()
    assert constructed == {"provider": "deepseek", "model": "deepseek-v4-flash"}
    assert payload["status"] == "OK"
    assert payload["answer"] == "由检索证据支持的 DeepSeek 测试回答。"
    assert payload["sources"][0]["chunk_id"] == cited_chunk


def test_public_query_checks_citation_membership_without_call_budget(monkeypatch):
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
        repeated = client.post("/public/query", json={"query": QUESTION}, headers=headers)
        assert repeated.status_code == 200
        assert repeated.json()["status"] == "OK"
    with TestClient(create_app(index=index, generator=Generator("invented-chunk"))) as client:
        result = client.post(
            "/public/query", json={"query": QUESTION},
            headers={"X-Demo-Session-ID": "anotherpublicsession"},
        ).json()
        assert result["status"] == "ABSTAINED"
        assert result["sources"] == []


def test_public_generation_has_no_application_call_limit(monkeypatch):
    class Generator:
        def __init__(self, citation_id):
            self.citation_id = citation_id

        def generate(self, *, question, context):
            return {
                "final_answer": "supported answer",
                "relevant_sources": [{"document_id": self.citation_id, "page_number": 1}],
            }

    # Old deployment variables must not silently reintroduce the retired cap.
    monkeypatch.setenv("MAX_LLM_CALLS_PER_SESSION", "10")
    monkeypatch.setenv("MAX_LLM_CALLS_PER_PROCESS", "30")
    index = PublicKnowledgeIndex()
    generator = Generator(index.search(QUESTION)[0]["chunk_id"])
    with TestClient(create_app(index=index, generator=generator)) as client:
        responses = [
            client.post(
                "/public/query", json={"query": QUESTION},
                headers={"X-Demo-Session-ID": "publictestsession"},
            )
            for _ in range(35)
        ]
    assert [response.status_code for response in responses] == [200] * 35
def test_public_query_does_not_enforce_a_process_budget(monkeypatch):
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
            for number in range(35)
        ]
    assert [response.status_code for response in responses] == [200] * 35
    assert generator.calls == 35


def test_provider_connection_error_fails_closed_with_actionable_status():
    class Generator:
        def generate(self, *, question, context):
            raise ConnectionError("provider is unreachable")

    with TestClient(create_app(index=PublicKnowledgeIndex(), generator=Generator())) as client:
        response = client.post(
            "/public/query", json={"query": QUESTION},
            headers={"X-Demo-Session-ID": "connectiontestsession"},
        )

    payload = response.json()
    assert response.status_code == 200
    assert payload["status"] == "GENERATION_PROVIDER_UNAVAILABLE"
    assert payload["answer"] == "N/A"
    assert payload["sources"] == []
    assert payload["evidence"]


def test_provider_rejection_returns_actionable_status_without_provider_details():
    class Generator:
        def generate(self, *, question, context):
            raise RuntimeError("provider rejected request; never expose this detail")

    with TestClient(create_app(index=PublicKnowledgeIndex(), generator=Generator())) as client:
        response = client.post("/public/query", json={"query": QUESTION})

    payload = response.json()
    assert payload["status"] == "GENERATION_PROVIDER_REJECTED"
    assert "never expose" not in str(payload)
    assert payload["answer"] == "N/A"
    assert payload["sources"] == []
    assert payload["evidence"]


def test_invalid_structured_generation_returns_evidence_only_status():
    class Generator:
        def generate(self, *, question, context):
            raise ValueError("invalid model response")

    with TestClient(create_app(index=PublicKnowledgeIndex(), generator=Generator())) as client:
        response = client.post("/public/query", json={"query": QUESTION})

    payload = response.json()
    assert payload["status"] == "GENERATION_RESPONSE_INVALID"
    assert payload["answer"] == "N/A"
    assert payload["sources"] == []
    assert payload["evidence"]


def test_public_review_advice_is_limited_to_submitted_current_evidence():
    index = PublicKnowledgeIndex()
    allowed = index.search(QUESTION, top_k=2, version="3.4.3", language="all")
    constructed = {}

    class Generator:
        def generate(self, *, question, context):
            constructed["question"] = question
            constructed["context"] = context
            return {
                "final_answer": "建议核对启动参数的优先级及其对下游说明的影响。",
                "relevant_sources": [{"document_id": allowed[0]["chunk_id"], "page_number": 1}],
            }

    with TestClient(create_app(index=index, generator=Generator())) as client:
        response = client.post("/public/review-advice", json={
            "change_summary": "将启动参数调整为最高优先级",
            "evidence_chunk_ids": [row["chunk_id"] for row in allowed],
        })

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "OK"
    assert payload["answer"].startswith("建议核对")
    assert [row["chunk_id"] for row in payload["sources"]] == [allowed[0]["chunk_id"]]
    assert {row["chunk_id"] for row in payload["evidence"]} == {row["chunk_id"] for row in allowed}
    assert "将启动参数调整为最高优先级" in constructed["question"]
    assert all(row["chunk_id"] in constructed["context"] for row in allowed)


def test_public_review_advice_rejects_unknown_or_historical_evidence():
    index = PublicKnowledgeIndex()
    historical = index.search(QUESTION, top_k=1, version="3.4.2", language="all")[0]
    with TestClient(create_app(index=index, generator=object())) as client:
        unknown = client.post("/public/review-advice", json={
            "change_summary": "假设变更", "evidence_chunk_ids": ["invented-chunk"],
        })
        old_version = client.post("/public/review-advice", json={
            "change_summary": "假设变更", "evidence_chunk_ids": [historical["chunk_id"]],
        })

    assert unknown.status_code == 422
    assert old_version.status_code == 422


def test_public_review_advice_without_generator_returns_evidence_only():
    index = PublicKnowledgeIndex()
    hit = index.search(QUESTION, top_k=1, version="3.4.3", language="all")[0]
    with TestClient(create_app(index=index)) as client:
        response = client.post("/public/review-advice", json={
            "change_summary": "假设变更", "evidence_chunk_ids": [hit["chunk_id"]],
        })

    assert response.status_code == 200
    assert response.json()["status"] == "GENERATION_NOT_CONFIGURED"
    assert response.json()["answer"] == "N/A"
    assert response.json()["sources"] == []
    assert response.json()["evidence"][0]["chunk_id"] == hit["chunk_id"]
