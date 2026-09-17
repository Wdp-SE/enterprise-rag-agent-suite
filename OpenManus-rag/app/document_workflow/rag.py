"""RAG query boundary and an offline synthetic demo query service."""

from __future__ import annotations

from datetime import datetime, timezone
import math
import re
from typing import Protocol

import httpx

from app.research.models import Evidence, SourceLevel


class QueryClient(Protocol):
    def query(self, question: str) -> dict: ...


class HTTPRAGClient:
    """Use only the frozen RAG V2 POST /query public contract."""

    def __init__(self, base_url: str, timeout: float = 30.0, retry_limit: int = 0):
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.retry_limit = retry_limit

    def query(self, question: str) -> dict:
        response = httpx.post(f"{self.base_url}/query", json={"question": question}, timeout=self.timeout)
        response.raise_for_status()
        return response.json()


class HTTPRetrieveClient:
    """Document workflow boundary for frozen retrieval-only POST /retrieve."""

    def __init__(self, base_url: str, timeout: float = 30.0, retry_limit: int = 0):
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.retry_limit = retry_limit

    def retrieve(self, query: str, top_k: int) -> dict:
        for attempt in range(self.retry_limit + 1):
            try:
                response = httpx.post(
                    f"{self.base_url}/retrieve",
                    json={"query": query, "top_k": top_k}, timeout=self.timeout,
                )
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
        required = {"chunk_id", "document_id", "section_id", "section_path",
                    "page_number", "content", "content_hash", "similarity", "rank"}
        for rank, item in enumerate(results, start=1):
            if not isinstance(item, dict) or not required.issubset(item):
                raise ValueError("malformed /retrieve hit")
            if (not all(isinstance(item[key], str) and item[key].strip()
                        for key in ("chunk_id", "document_id", "section_id", "content"))
                    or not isinstance(item["section_path"], list)
                    or not all(isinstance(part, str) for part in item["section_path"])
                    or type(item["page_number"]) is not int
                    or item["page_number"] < 1 or item["rank"] != rank):
                raise ValueError("invalid /retrieve metadata")
            if (type(item["rank"]) is not int
                    or not isinstance(item["content_hash"], str)
                    or not re.fullmatch(r"[0-9a-f]{64}", item["content_hash"])
                    or not isinstance(item["similarity"], (int, float))
                    or not math.isfinite(item["similarity"])):
                raise ValueError("invalid /retrieve score or hash")
        return payload


class DemoRAGClient:
    """Offline lexical retrieval over simulated documents; no index is persisted."""

    DOCUMENTS = (
        ("demo-plan-01", 1, "项目背景", "项目背景：示例研发项目需要统一管理需求、开发、测试和验收材料。"),
        ("demo-plan-01", 2, "项目目标", "项目目标：完成结构化研发文档整理，并形成可人工审核的项目计划草稿。"),
        ("demo-plan-02", 1, "阶段划分", "阶段划分：项目分为需求梳理、方案设计、开发测试、验收准备四个阶段。"),
        ("demo-plan-02", 2, "验收依据", "验收依据：以需求规格说明书、测试报告和验收检查表为依据。"),
    )

    def __init__(self):
        self.calls = 0

    def query(self, question: str) -> dict:
        self.calls += 1
        matches = [
            {"document_id": doc, "page_number": page, "section_id": section,
             "content": content}
            for doc, page, section, content in self.DOCUMENTS
            if section in question
        ]
        return {"answer": matches[0]["content"] if matches else "N/A",
                "sources": matches, "status": "OK" if matches else "ABSTAINED", "trace": []}


class RAGTool:
    def __init__(self, client: QueryClient, default_top_k: int = 5):
        self.client = client
        self.calls = 0
        self.default_top_k = default_top_k

    def retrieve_knowledge(self, query: str, top_k: int | None = None) -> list[Evidence]:
        top_k = self.default_top_k if top_k is None else top_k
        if not query.strip() or not 1 <= top_k <= 20:
            raise ValueError("query and top_k must be valid")
        self.calls += 1
        if isinstance(self.client, HTTPRetrieveClient):
            payload = self.client.retrieve(query, top_k)
            return [Evidence(
                title=hit["document_id"], content=hit["content"],
                organization="RAG retrieval service", source_type="RAG",
                document_number=hit["document_id"], chunk_id=hit["chunk_id"],
                query=query, section=hit["section_id"],
                section_path=hit["section_path"], page_number=hit["page_number"],
                content_hash=hit["content_hash"],
                source_level=SourceLevel.TIER3,
                retrieved_at=datetime.now(timezone.utc),
            ) for hit in payload["results"]]
        payload = self.client.query(query)
        if payload.get("status") not in {"OK"}:
            return []
        sources = payload.get("sources") or []
        answer = payload.get("answer")
        if not isinstance(sources, list):
            raise ValueError("RAG sources must be a list")
        result: list[Evidence] = []
        for source in sources[:top_k]:
            if not isinstance(source, dict):
                continue
            doc = source.get("document_id")
            page = source.get("page_number")
            if not isinstance(doc, str) or not doc.strip() or not isinstance(page, int) or page < 1:
                continue
            content = source.get("content") or source.get("text") or answer
            if not isinstance(content, str) or content.strip() in {"", "N/A"}:
                continue
            result.append(Evidence(
                title=doc, content=content, organization="RAG query service",
                source_type="RAG", document_number=doc, page_number=page,
                section=str(source.get("section_id") or "unmapped"),
                source_level=SourceLevel.TIER3, retrieved_at=datetime.now(timezone.utc),
            ))
        return result
