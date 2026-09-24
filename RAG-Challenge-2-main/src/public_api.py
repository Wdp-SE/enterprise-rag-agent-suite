"""Official public-source knowledge endpoints beside the frozen synthetic API."""

from __future__ import annotations

import asyncio
from typing import Literal

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field

from src.public_knowledge import (
    PublicKnowledgeIndex, verified_consistency_notes,
)
from src.rd_v2_runtime import _format_context, validate_citation_membership


router = APIRouter(prefix="/public", tags=["official-public-knowledge"])


class SearchRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    query: str = Field(min_length=1, max_length=4000)
    top_k: int = Field(default=5, ge=1, le=20)
    version: Literal["3.4.2", "3.4.3", "all"] = "3.4.3"
    language: Literal["zh_preferred", "all", "zh", "en"] = "zh_preferred"


class DocumentRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    document_id: str = Field(min_length=1, max_length=250)


def _index(request: Request) -> PublicKnowledgeIndex:
    index = getattr(request.app.state, "public_knowledge_index", None)
    if index is None:
        raise HTTPException(status_code=503, detail="PUBLIC_CORPUS_NOT_READY")
    return index


@router.get("/workspace")
def workspace(request: Request) -> dict:
    index = _index(request)
    manifest = index.manifest
    return {
        "workspace": manifest["workspace"], "repository": manifest["repository"],
        "baseline_version": manifest["baseline_version"],
        "current_version": manifest["current_version"],
        "source_count": len(manifest["sources"]), "chunk_count": len(index.chunks),
        "languages": ["zh-CN", "en-US"],
        "retrieval_policy": index.policy["default_policy"],
        "data_origin": "Apache DolphinScheduler official public materials",
        "upstream_writes_enabled": False,
    }


@router.get("/documents")
def documents(request: Request) -> dict:
    index = _index(request)
    first_heading = {}
    for chunk in index.chunks:
        first_heading.setdefault(chunk["document_id"], chunk["heading"] or chunk["document_key"])
    rows = []
    for source in index.manifest["sources"]:
        key = f"{source['version']}:{source['language']}:{source['document_key']}"
        first_line = (index.root / source["local_path"]).read_text(encoding="utf-8").splitlines()[0].strip()
        title = first_line.removeprefix("# ").strip() if first_line.startswith("# ") else first_heading.get(key, source["document_key"])
        rows.append({
            "document_id": key, "document_key": source["document_key"],
            "title": title,
            "version": source["version"], "locale": source["locale"],
            "source_type": source["source_type"], "source_url": source["source_url"],
        })
    return {"documents": rows}


@router.post("/document")
def document(payload: DocumentRequest, request: Request) -> dict:
    rows = [row for row in _index(request).chunks if row["document_id"] == payload.document_id]
    if not rows:
        raise HTTPException(status_code=404, detail="OFFICIAL_DOCUMENT_NOT_FOUND")
    return {"document_id": payload.document_id, "chunks": rows}


@router.post("/search")
def search(payload: SearchRequest, request: Request) -> dict:
    try:
        hits = _index(request).search(
            payload.query, top_k=payload.top_k, version=payload.version, language=payload.language,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail="INVALID_PUBLIC_SEARCH") from exc
    return {
        "query": payload.query, "results": hits,
        "retrieval_policy": _index(request).policy["default_policy"],
        "consistency_notes": verified_consistency_notes(hits),
    }


@router.post("/query")
async def query(payload: SearchRequest, request: Request) -> dict:
    index = _index(request)
    hits = await asyncio.to_thread(
        index.search, payload.query, top_k=5, version=payload.version, language=payload.language
    )
    notes = verified_consistency_notes(hits)
    base = {"answer": "N/A", "sources": [], "evidence": hits, "consistency_notes": notes}
    if not hits:
        return {**base, "status": "NO_EVIDENCE"}
    generator = request.app.state.public_generator
    if generator is None:
        return {**base, "status": "GENERATION_NOT_CONFIGURED"}
    budget = request.app.state.public_query_budget
    if budget is not None:
        try:
            allowed = budget.consume(request.headers.get("X-Demo-Session-ID", ""))
        except ValueError as exc:
            raise HTTPException(status_code=400, detail="PUBLIC_DEMO_SESSION_REQUIRED") from exc
        if not allowed:
            raise HTTPException(status_code=429, detail="LLM_SESSION_BUDGET_EXHAUSTED")
    generator_hits = [
        {
            "document_id": hit["chunk_id"], "page_number": 1,
            "section_id": hit["heading"], "section_path": [hit["document_key"], hit["heading"]],
            "chunk_id": hit["chunk_id"], "text": hit["content"],
        }
        for hit in hits
    ]
    provenance = "\n".join(
        f"{row['chunk_id']} | version={row['version']} | locale={row['locale']} | source={row['source_url']}"
        for row in hits
    )
    context = (
        "以下内容均是 Apache DolphinScheduler 官方公开资料。仅使用这些证据；"
        "不同版本或语言的资料若有明显差异，说明来源并避免静默混用。"
        "page_number=1 只是内部引用槽位，并非原文页码。\n"
        + provenance + "\n" + _format_context(generator_hits)
    )
    try:
        generated = await asyncio.to_thread(generator.generate, question=payload.query, context=context)
        answer = generated["final_answer"]
        citations = validate_citation_membership(generated["relevant_sources"], generator_hits)
        if not isinstance(answer, str) or not answer.strip() or answer == "N/A" or not citations:
            return {**base, "status": "ABSTAINED"}
        cited_ids = {row["document_id"] for row in citations}
        return {
            **base, "answer": answer, "sources": [hit for hit in hits if hit["chunk_id"] in cited_ids],
            "status": "OK",
        }
    except Exception:
        return {**base, "status": "FAIL_CLOSED"}
