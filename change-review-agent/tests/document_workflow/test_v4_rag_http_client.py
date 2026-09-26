from __future__ import annotations

from app.document_workflow.rag import HTTPRetrieveClient


class Response:
    def __init__(self, payload):
        self.payload = payload
        self.status_code = 200

    def raise_for_status(self):
        return None

    def json(self):
        return self.payload


def test_existing_http_client_exposes_engineering_change_endpoints(monkeypatch) -> None:
    calls = []

    def post(url, *, json, timeout):
        calls.append((url, json, timeout))
        if url.endswith("/engineering/items/diff"):
            return Response({"changes": [{"change_type": "MODIFIED"}]})
        if url.endswith("/engineering/items/retrieve"):
            return Response({"query": json["query"], "results": [{"discovery_source": "EXACT_IDENTIFIER"}]})
        if url.endswith("/engineering/impacts/discover"):
            return Response({"impacts": [{"discovery_source": "EXPLICIT_TRACE"}]})
        raise AssertionError(url)

    monkeypatch.setattr("app.document_workflow.rag.httpx.post", post)
    client = HTTPRetrieveClient("http://rag.local", timeout=7.0)

    assert client.diff_engineering_items([{"item_id": "old"}], [{"item_id": "new"}])["changes"][0]["change_type"] == "MODIFIED"
    assert client.retrieve_engineering_items(
        "REQ-023", [{"item_id": "new"}], {"project_ids": ["PAYMENT"]},
        dense_item_ids=["design"], top_k=5,
    )["results"][0]["discovery_source"] == "EXACT_IDENTIFIER"
    assert client.discover_engineering_impacts(
        "new", [{"item_id": "new"}], [{"trace_link_id": "t1"}],
        dense_item_ids=["design"], evidence_by_item={"design": ["ev1"]},
    )["impacts"][0]["discovery_source"] == "EXPLICIT_TRACE"

    assert [url.rsplit("/", 3)[-3:] for url, _, _ in calls] == [
        ["engineering", "items", "diff"],
        ["engineering", "items", "retrieve"],
        ["engineering", "impacts", "discover"],
    ]
    assert all(timeout == 7.0 for _, _, timeout in calls)

