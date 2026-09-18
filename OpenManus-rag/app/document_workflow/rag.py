"""Narrow retrieval boundary for the external version-aware RAG service."""

from __future__ import annotations

import hashlib
import math
import re
from datetime import datetime, timezone
from typing import Protocol

import httpx

from .evidence_models import Evidence, SourceLevel, normalize_text
from .scope import WorkflowScope


class RetrievalClient(Protocol):
    def retrieve(self, query: str, top_k: int, scope: dict | None = None) -> dict: ...
    def active_versions(self) -> dict[str, str]: ...


class HTTPRetrieveClient:
    def __init__(self, base_url: str, timeout: float = 30.0, retry_limit: int = 0):
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.retry_limit = retry_limit

    def retrieve(self, query: str, top_k: int, scope: dict | None = None) -> dict:
        payload: dict | None = None
        for attempt in range(self.retry_limit + 1):
            try:
                request_payload: dict[str, object] = {"query": query, "top_k": top_k}
                if scope is not None:
                    request_payload["scope"] = scope
                response = httpx.post(f"{self.base_url}/retrieve", json=request_payload, timeout=self.timeout)
                response.raise_for_status()
                payload = response.json()
                break
            except (httpx.TimeoutException, httpx.ConnectError, httpx.HTTPStatusError) as exc:
                retryable = not isinstance(exc, httpx.HTTPStatusError) or exc.response.status_code >= 500
                if attempt >= self.retry_limit or not retryable:
                    raise
        if not isinstance(payload, dict) or payload.get("query") != query:
            raise ValueError("malformed /retrieve response")
        results = payload.get("results")
        if not isinstance(results, list) or len(results) > top_k:
            raise ValueError("malformed /retrieve results")
        required = {"chunk_id", "document_id", "section_id", "section_path", "page_number", "content", "content_hash", "similarity", "rank"}
        for rank, item in enumerate(results, start=1):
            if not isinstance(item, dict) or not required.issubset(item):
                raise ValueError("malformed /retrieve hit")
            if item["rank"] != rank or type(item["page_number"]) is not int or item["page_number"] < 1:
                raise ValueError("invalid /retrieve rank or page")
            if not re.fullmatch(r"[0-9a-f]{64}", str(item["content_hash"])) or not math.isfinite(float(item["similarity"])):
                raise ValueError("invalid /retrieve score or hash")
        return payload

    def active_versions(self) -> dict[str, str]:
        response = httpx.get(f"{self.base_url}/documents", timeout=self.timeout)
        response.raise_for_status()
        payload = response.json()
        documents = payload.get("documents") if isinstance(payload, dict) else None
        if not isinstance(documents, list):
            raise ValueError("malformed /documents response")
        return {
            str(item["document_id"]): str(item["active_version"]["version_id"])
            for item in documents if isinstance(item, dict) and item.get("active_version")
        }


class DemoRAGClient:
    """Offline synthetic corpus used by tests and the safe demo."""

    DOCUMENTS = (
        {"project_id": "DEMO-RD", "document_id": "REQ-001", "document_type": "REQUIREMENT", "version_id": "REQ-001@2.0", "version_label": "V2.0", "section": "变更内容", "page": 12, "content": "变更内容：最大并发由500提升到1000，并增加峰值保护。"},
        {"project_id": "DEMO-RD", "document_id": "DESIGN-001", "document_type": "DESIGN", "version_id": "DESIGN-001@1.0", "version_label": "V1.0", "section": "变更内容", "page": 8, "content": "设计影响：连接池和限流器需要按1000并发重新配置。"},
        {"project_id": "DEMO-RD", "document_id": "REQ-001", "document_type": "REQUIREMENT", "version_id": "REQ-001@2.0", "version_label": "V2.0", "section": "影响范围", "page": 13, "content": "影响范围：接口网关、连接池、容量测试和上线监控。"},
        {"project_id": "DEMO-RD", "document_id": "TEST-001", "document_type": "TEST", "version_id": "TEST-001@1.0", "version_label": "V1.0", "section": "验证结果", "page": 21, "content": "验证结果：1000并发持续30分钟，错误率低于0.1%。"},
    )

    def __init__(self):
        self.calls = 0

    def active_versions(self) -> dict[str, str]:
        return {item["document_id"]: item["version_id"] for item in self.DOCUMENTS}

    def retrieve(self, query: str, top_k: int, scope: dict | None = None) -> dict:
        self.calls += 1
        selected = list(self.DOCUMENTS)
        scope = scope or {"active_only": True}
        for key, singular in (("project_ids", "project_id"), ("document_ids", "document_id"), ("document_types", "document_type"), ("version_ids", "version_id")):
            values = set(scope.get(key) or [])
            if values:
                selected = [item for item in selected if item[singular] in values]
        terms = {term for term in re.split(r"\s+", query) if len(term) >= 2}
        scored = [
            (sum(term in (item["section"] + item["content"]) for term in terms), item)
            for item in selected
        ]
        ranked = [
            item
            for score, item in sorted(scored, key=lambda pair: pair[0], reverse=True)
            if score > 0
        ]
        results = []
        for rank, item in enumerate(ranked[:top_k], start=1):
            content_hash = hashlib.sha256(normalize_text(item["content"]).encode("utf-8")).hexdigest()
            results.append({
                "rank": rank, "similarity": max(0.1, 1.0 - rank * 0.05),
                "chunk_id": f"{item['version_id']}:{item['page']}:{item['section']}",
                "document_id": item["document_id"], "project_id": item["project_id"],
                "document_type": item["document_type"], "version_id": item["version_id"],
                "version_label": item["version_label"], "version_status": "ACTIVE",
                "section_id": item["section"], "section_path": [item["section"]],
                "page_number": item["page"], "content": item["content"], "content_hash": content_hash,
            })
        return {"query": query, "results": results}


class RAGTool:
    def __init__(self, client: RetrievalClient, default_top_k: int = 5, retrieval_scope: WorkflowScope | None = None):
        self.client = client
        self.calls = 0
        self.default_top_k = default_top_k
        self.retrieval_scope = retrieval_scope or WorkflowScope()

    def retrieve_knowledge(self, query: str, top_k: int | None = None) -> list[Evidence]:
        top_k = self.default_top_k if top_k is None else top_k
        if not query.strip() or not 1 <= top_k <= 20:
            raise ValueError("query and top_k must be valid")
        self.calls += 1
        payload = self.client.retrieve(query, top_k, self.retrieval_scope.to_dict())
        historical_ids = set(self.retrieval_scope.version_ids)
        result: list[Evidence] = []
        for hit in payload["results"]:
            version_id = hit.get("version_id")
            status = hit.get("version_status")
            result.append(Evidence(
                title=str(hit.get("title") or hit["document_id"]), content=hit["content"],
                organization="RAG retrieval service", source_type="RAG",
                document_number=hit["document_id"], document_id=hit["document_id"],
                project_id=hit.get("project_id"), document_type=hit.get("document_type"),
                version_id=version_id, version_label=hit.get("version_label"), version_status=status,
                freshness="FRESH" if status == "ACTIVE" or version_id in historical_ids else "UNKNOWN",
                chunk_id=hit["chunk_id"], query=query, section=hit["section_id"],
                section_path=hit["section_path"], page_number=hit["page_number"],
                content_hash=hit["content_hash"], similarity=float(hit["similarity"]),
                source_level=SourceLevel.TIER3, retrieved_at=datetime.now(timezone.utc),
            ))
        return result
