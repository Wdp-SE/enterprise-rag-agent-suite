"""Thin HTTP client for the frozen RAG V2 public API."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import requests


@dataclass
class ServiceError(RuntimeError):
    public_message: str
    detail: str = ""
    code: str = "SERVICE_ERROR"

    def __str__(self) -> str:
        return self.public_message


class RAGClient:
    def __init__(self, base_url: str, timeout: float = 45.0, session: requests.Session | None = None):
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.session = session or requests.Session()

    def _request(self, method: str, endpoint: str, **kwargs) -> dict[str, Any]:
        try:
            response = self.session.request(
                method, f"{self.base_url}{endpoint}", timeout=self.timeout, **kwargs
            )
            response.raise_for_status()
        except requests.Timeout as exc:
            raise ServiceError("RAG 请求超时，请稍后重试。", type(exc).__name__, "RAG_TIMEOUT") from exc
        except requests.ConnectionError as exc:
            raise ServiceError(
                "RAG Service Unavailable。请先启动本地 RAG 服务。",
                type(exc).__name__, "RAG_UNAVAILABLE",
            ) from exc
        except requests.HTTPError as exc:
            status = exc.response.status_code if exc.response is not None else "unknown"
            raise ServiceError(
                f"RAG 服务返回 HTTP {status}。", f"HTTPStatus={status}", "RAG_HTTP_ERROR"
            ) from exc
        try:
            payload = response.json()
        except ValueError as exc:
            raise ServiceError("RAG 返回了无法解析的响应。", "Malformed JSON", "RAG_MALFORMED") from exc
        if not isinstance(payload, dict):
            raise ServiceError("RAG 返回结构不符合契约。", "Expected JSON object", "RAG_SCHEMA_INVALID")
        return payload

    def health(self) -> dict[str, Any]:
        return self._request("GET", "/health")

    def artifact_status(self) -> dict[str, Any]:
        payload = self._request("GET", "/artifacts/status")
        required = {"artifact_status", "retrieval_policy", "dense_representation"}
        if not required.issubset(payload):
            raise ServiceError("Artifact 状态响应不完整。", "Missing required fields", "RAG_SCHEMA_INVALID")
        return payload

    def query(self, question: str) -> dict[str, Any]:
        if not question.strip():
            raise ValueError("Question 不能为空")
        payload = self._request("POST", "/query", json={"question": question.strip()})
        if not {"answer", "sources", "status"}.issubset(payload) or not isinstance(payload["sources"], list):
            raise ServiceError("RAG 问答响应不符合契约。", "Invalid /query schema", "RAG_SCHEMA_INVALID")
        return payload

    def retrieve(self, question: str, top_k: int = 5) -> dict[str, Any]:
        question = question.strip()
        if not question or not 3 <= top_k <= 10:
            raise ValueError("Question 不能为空，Top K 必须为 3 到 10")
        payload = self._request("POST", "/retrieve", json={"query": question, "top_k": top_k})
        results = payload.get("results")
        if payload.get("query") != question or not isinstance(results, list) or len(results) > top_k:
            raise ServiceError("Evidence Retrieval 响应不符合契约。", "Invalid /retrieve envelope", "RAG_SCHEMA_INVALID")
        required = {"rank", "document_id", "page_number", "section_path", "similarity", "content", "chunk_id"}
        if any(not isinstance(item, dict) or not required.issubset(item) for item in results):
            raise ServiceError("Evidence 结果字段不完整。", "Invalid retrieval hit", "RAG_SCHEMA_INVALID")
        return payload

