from __future__ import annotations

import json
import zipfile
from pathlib import Path

import pytest
import requests

from config import DemoConfig
from services.agent_client import AgentClient
from services.rag_client import RAGClient, ServiceError


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
    assert result["workflow_status"] == "PARTIAL"
    assert result["requires_human_review"] is True
    assert result["missing_field_count"] > 0
    draft = Path(result["artifacts"]["draft"])
    assert zipfile.is_zipfile(draft)
    for key in ("evidence", "trace"):
        payload = json.loads(client.artifact_bytes(result["artifacts"][key]))
        assert isinstance(payload, dict)

