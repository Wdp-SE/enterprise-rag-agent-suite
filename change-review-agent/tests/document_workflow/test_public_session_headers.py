from __future__ import annotations

from app.document_workflow.rag import HTTPRetrieveClient


class Response:
    status_code = 200

    def raise_for_status(self):
        return None

    def json(self):
        return {"documents": []}


def test_http_retrieve_client_sends_demo_session_header(monkeypatch) -> None:
    captured = {}

    def get(url, *, timeout, headers):
        captured.update({"url": url, "timeout": timeout, "headers": headers})
        return Response()

    monkeypatch.setattr("app.document_workflow.rag.httpx.get", get)
    client = HTTPRetrieveClient("https://rag.example.test", session_id="session_12345678")
    assert client.candidate_version_documents() == {"documents": []}
    assert captured["headers"] == {"X-Demo-Session-ID": "session_12345678"}
