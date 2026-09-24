"""Thin client for the official public-source knowledge workspace."""

from __future__ import annotations

from services.rag_client import RAGClient


class PublicKnowledgeClient(RAGClient):
    def workspace(self) -> dict:
        return self._request("GET", "/public/workspace")

    def documents(self) -> list[dict]:
        return self._request("GET", "/public/documents")["documents"]

    def document(self, document_id: str) -> list[dict]:
        return self._request("POST", "/public/document", json={"document_id": document_id})["chunks"]

    def search(self, question: str, *, version: str, language: str, top_k: int = 5) -> dict:
        return self._request(
            "POST", "/public/search",
            json={"query": question, "version": version, "language": language, "top_k": top_k},
        )

    def query_official(self, question: str, *, version: str, language: str) -> dict:
        return self._request(
            "POST", "/public/query", retry_limit=0,
            json={"query": question, "version": version, "language": language},
        )

    def engineering_diff(self, old_items: list[dict], new_items: list[dict]) -> dict:
        return self._request(
            "POST", "/engineering/items/diff",
            json={"old_items": old_items, "new_items": new_items},
        )

    def engineering_impacts(self, payload: dict) -> dict:
        return self._request("POST", "/engineering/impacts/discover", json=payload)
