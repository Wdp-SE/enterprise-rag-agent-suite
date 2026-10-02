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

    def search(
        self, question: str, *, version: str, language: str = "zh", top_k: int = 5,
        device_model: str | None = None, module_sku: str | None = None,
        carrier_board: str | None = None, software_baseline: str | None = None,
    ) -> dict:
        payload = {"query": question, "version": version, "language": language, "top_k": top_k}
        payload.update({
            key: value for key, value in {
                "device_model": device_model, "module_sku": module_sku,
                "carrier_board": carrier_board, "software_baseline": software_baseline,
            }.items() if value is not None
        })
        return self._request("POST", "/public/search", json=payload)

    def query_official(
        self, question: str, *, version: str, language: str = "zh", top_k: int = 5,
        device_model: str | None = None, module_sku: str | None = None,
        carrier_board: str | None = None, software_baseline: str | None = None,
    ) -> dict:
        payload = {"query": question, "version": version, "language": language, "top_k": top_k}
        payload.update({
            key: value for key, value in {
                "device_model": device_model, "module_sku": module_sku,
                "carrier_board": carrier_board, "software_baseline": software_baseline,
            }.items() if value is not None
        })
        return self._request(
            "POST", "/public/query", retry_limit=0, request_timeout=max(60.0, self.timeout),
            json=payload,
        )

    def review_advice(
        self, change_summary: str, evidence_chunk_ids: list[str], *, version: str = "current",
        device_model: str | None = None, module_sku: str | None = None,
        carrier_board: str | None = None, software_baseline: str | None = None,
    ) -> dict:
        payload = {
            "change_summary": change_summary,
            "evidence_chunk_ids": evidence_chunk_ids,
        }
        if version != "current":
            payload["version"] = version
        payload.update({
            key: value for key, value in {
                "device_model": device_model, "module_sku": module_sku,
                "carrier_board": carrier_board, "software_baseline": software_baseline,
            }.items() if value is not None
        })
        return self._request(
            "POST", "/public/review-advice", retry_limit=0, request_timeout=max(60.0, self.timeout),
            json=payload,
        )

    def review_advice_for_version(
        self, change_summary: str, evidence_chunk_ids: list[str], *, version: str,
    ) -> dict:
        return self.review_advice(change_summary, evidence_chunk_ids, version=version)

    def engineering_diff(self, old_items: list[dict], new_items: list[dict]) -> dict:
        return self._request(
            "POST", "/engineering/items/diff",
            json={"old_items": old_items, "new_items": new_items},
        )

    def engineering_impacts(self, payload: dict) -> dict:
        return self._request("POST", "/engineering/impacts/discover", json=payload)
