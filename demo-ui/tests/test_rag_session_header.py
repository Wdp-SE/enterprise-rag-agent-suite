from __future__ import annotations

from services.rag_client import RAGClient


class Response:
    status_code = 200

    def raise_for_status(self):
        return None

    def json(self):
        return {"status": "healthy"}


class Session:
    def __init__(self):
        self.kwargs = None

    def request(self, method, url, timeout, **kwargs):
        self.kwargs = kwargs
        return Response()


def test_ui_rag_client_sends_session_header() -> None:
    session = Session()
    client = RAGClient("https://rag.example.test", session=session, session_id="session_12345678")
    assert client.health()["status"] == "healthy"
    assert session.kwargs["headers"] == {"X-Demo-Session-ID": "session_12345678"}
