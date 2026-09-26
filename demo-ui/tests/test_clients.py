from __future__ import annotations

import json
import zipfile
from pathlib import Path

import pytest
import requests

from config import DemoConfig
from services.agent_client import AgentClient
from services.rag_client import RAGClient, ServiceError
from services.public_knowledge_client import PublicKnowledgeClient


class Response:
    def __init__(self, payload, status=200):
        self.payload = payload
        self.status_code = status

    def raise_for_status(self):
        if self.status_code >= 400:
            error = requests.HTTPError("failed")
            error.response = self
            raise error

    def json(self):
        if isinstance(self.payload, Exception):
            raise self.payload
        return self.payload


class Session:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def request(self, method, url, timeout, **kwargs):
        self.calls.append((method, url, timeout, kwargs))
        value = self.responses.pop(0)
        if isinstance(value, Exception):
            raise value
        return value


def test_rag_health_and_retrieve_contract():
    hit = {"rank": 1, "document_id": "safe", "page_number": 2,
           "section_path": ["项目", "目标"], "similarity": 0.82,
           "content": "项目目标：形成草稿。", "chunk_id": "safe:2"}
    session = Session([Response({"status": "healthy"}),
                       Response({"query": "项目目标", "results": [hit]})])
    client = RAGClient("http://localhost:8765", session=session)
    assert client.health()["status"] == "healthy"
    assert client.retrieve("项目目标", 3)["results"][0]["page_number"] == 2
    assert session.calls[1][3]["json"] == {"query": "项目目标", "top_k": 3}


def test_candidate_knowledge_calls_keep_selected_case_scope_and_session():
    hit = {
        "rank": 1, "document_id": "requirements", "version_id": "requirements-v2",
        "version_label": "V2.0", "version_status": "ACTIVE", "project_id": "PAYMENT",
        "document_type": "REQUIREMENT", "section_id": "REQ-023",
        "section_path": ["容量"], "page_number": 1, "chunk_id": "req-23",
        "text": "REQ-023 最大并发为 1000。", "similarity": 0.8,
    }
    session = Session([
        Response({"results": [hit]}),
        Response({"answer": "最大并发为 1000。", "status": "OK", "sources": [hit]}),
    ])
    client = RAGClient("http://localhost:8765", session=session, session_id="session_12345678")
    scope = {"project_ids": ["PAYMENT"], "active_only": True}

    assert client.search_candidate_versions("最大并发量是多少？", 5, scope)["results"][0]["document_id"] == "requirements"
    assert client.query_candidate_versions("最大并发量是多少？", scope)["status"] == "OK"
    assert [call[1] for call in session.calls] == [
        "http://localhost:8765/engineering/versions/search",
        "http://localhost:8765/engineering/versions/query",
    ]
    assert session.calls[0][3]["json"] == {"query": "最大并发量是多少？", "top_k": 5, "scope": scope}
    assert session.calls[1][3]["json"] == {"question": "最大并发量是多少？", "scope": scope}
    assert all(call[3]["headers"]["X-Demo-Session-ID"] == "session_12345678" for call in session.calls)


def test_public_query_budget_error_is_actionable():
    client = RAGClient("http://localhost:8765", session=Session([Response({}, status=429)]))
    with pytest.raises(ServiceError, match="仍可继续检索引用依据") as failure:
        client.query_candidate_versions("最大并发量是多少？", {"active_only": True})
    assert failure.value.code == "LLM_BUDGET_EXHAUSTED"


def test_rag_unavailable_and_malformed_handling():
    client = RAGClient("http://localhost:8765", session=Session([
        requests.ConnectionError("refused")
    ]))
    with pytest.raises(ServiceError) as failure:
        client.health()
    assert failure.value.code == "RAG_UNAVAILABLE"
    malformed = RAGClient("http://localhost:8765", session=Session([Response(ValueError())]))
    with pytest.raises(ServiceError, match="无法解析"):
        malformed.health()


def test_agent_safe_demo_invalid_docx_and_artifacts(tmp_path):
    config = DemoConfig(runtime_root=tmp_path).validate()
    client = AgentClient(config)
    assert client.status()["ready"] is True
    with pytest.raises(ValueError, match="有效"):
        client.save_upload("broken.docx", b"not-a-docx")
    record = client.load_demo_template()
    assert record["summary"]["section_count"] > 0
    assert record["summary"]["tasks"]
    result = client.run_workflow(record, use_demo_rag=True)
    assert result["workflow_status"] == "REVIEW_REQUIRED"
    assert result["requires_human_review"] is True
    assert result["missing_field_count"] > 0
    draft = Path(result["artifacts"]["draft"])
    assert zipfile.is_zipfile(draft)
    for key in ("evidence", "trace"):
        payload = json.loads(client.artifact_bytes(result["artifacts"][key]))
        assert isinstance(payload, dict)

def test_public_generation_timeout_is_never_retried():
    session = Session([requests.Timeout("late answer"), Response({"status": "OK"})])
    client = PublicKnowledgeClient(
        "http://localhost:8765", session=session, retry_limit=2, session_id="session_12345678",
    )
    with pytest.raises(ServiceError) as failure:
        client.query_official("parameter priority", version="3.4.3", language="all")
    assert failure.value.code == "RAG_TIMEOUT"
    assert len(session.calls) == 1


def test_review_advice_posts_selected_evidence_once_without_retry():
    session = Session([Response({"status": "OK", "answer": "advice", "sources": []})])
    client = PublicKnowledgeClient(
        "http://localhost:8769", session=session, retry_limit=3, session_id="session_12345678",
    )

    result = client.review_advice("change summary", ["chunk-a", "chunk-b"])

    assert result["status"] == "OK"
    assert len(session.calls) == 1
    method, url, _, kwargs = session.calls[0]
    assert method == "POST"
    assert url == "http://localhost:8769/public/review-advice"
    assert session.calls[0][2] == 60.0
    assert kwargs["json"] == {
        "change_summary": "change summary",
        "evidence_chunk_ids": ["chunk-a", "chunk-b"],
    }


def test_public_generation_budget_error_keeps_retrieval_available():
    session = Session([Response({}, status=429)])
    client = PublicKnowledgeClient("http://localhost:8765", session=session)
    with pytest.raises(ServiceError) as failure:
        client.query_official("parameter priority", version="3.4.3", language="all")
    assert failure.value.code == "LLM_BUDGET_EXHAUSTED"
    assert "\u68c0\u7d22" in failure.value.public_message
