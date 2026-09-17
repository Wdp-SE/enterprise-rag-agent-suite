"""Minimal FastAPI surface for the frozen R&D V2 runtime."""

from __future__ import annotations

import asyncio
import hashlib
import re
import unicodedata
from contextlib import asynccontextmanager
from typing import Any, Callable, Optional

from fastapi import FastAPI, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field

from src.rd_v2_runtime import QueryRuntimeError, RDV2QueryRuntime, create_runtime


class QueryRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    question: str = Field(min_length=1, max_length=4000)


class QueryResponse(BaseModel):
    answer: Any
    sources: list[dict]
    status: str
    trace: list[dict] = Field(default_factory=list)
    trusted_qa: Optional[dict] = None


class RetrieveRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    query: str = Field(min_length=1, max_length=4000)
    top_k: int = Field(default=5, ge=1, le=20)


class RetrievalResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    chunk_id: str
    document_id: str
    section_id: str
    section_path: list[str]
    page_number: int = Field(ge=1)
    content: str
    content_hash: str
    similarity: float
    rank: int = Field(ge=1)


class RetrieveResponse(BaseModel):
    query: str
    results: list[RetrievalResult]


def _serialize_retrieval_hit(hit: dict) -> dict:
    """Expose only provenance and raw text from a validated frozen chunk."""
    content = hit["text"]
    normalized = re.sub(r"\s+", " ", unicodedata.normalize("NFKC", content)).strip()
    return {
        "chunk_id": hit["chunk_id"],
        "document_id": hit["document_id"],
        "section_id": hit["section_id"],
        "section_path": hit["section_path"],
        "page_number": hit["page_number"],
        "content": content,
        "content_hash": hashlib.sha256(normalized.encode("utf-8")).hexdigest(),
        "similarity": hit["dense_score"],
        "rank": hit["retrieval_rank"],
    }


def create_app(
    runtime: RDV2QueryRuntime | None = None,
    *,
    runtime_factory: Callable[[], RDV2QueryRuntime] = create_runtime,
) -> FastAPI:
    """Create the service; startup fails if frozen artifacts fail validation."""

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        app.state.rd_v2_runtime = runtime or runtime_factory()
        try:
            yield
        finally:
            app.state.rd_v2_runtime.close()

    app = FastAPI(
        title="R&D Document RAG V2",
        version="rd-v2-retrieval-final-v1.0",
        lifespan=lifespan,
    )

    @app.get("/health")
    async def health(request: Request) -> dict:
        return request.app.state.rd_v2_runtime.health()

    @app.get("/artifacts/status")
    async def artifact_status(request: Request) -> dict:
        health_state = request.app.state.rd_v2_runtime.health()
        return {
            "artifact_status": health_state["artifact_status"],
            "retrieval_policy_version": health_state["retrieval_policy_version"],
            "retrieval_policy": health_state["retrieval_policy"],
            "dense_representation": health_state["dense_representation"],
        }

    @app.post("/query", response_model=QueryResponse)
    async def query(payload: QueryRequest, request: Request) -> dict:
        try:
            return await asyncio.to_thread(
                request.app.state.rd_v2_runtime.query, payload.question
            )
        except QueryRuntimeError as exc:
            raise HTTPException(status_code=503, detail=exc.code) from exc
        except Exception as exc:
            # Do not expose exception messages: they may contain sensitive input.
            raise HTTPException(status_code=500, detail="QUERY_FAILED") from exc

    @app.post("/retrieve", response_model=RetrieveResponse)
    async def retrieve(payload: RetrieveRequest, request: Request) -> dict:
        runtime = request.app.state.rd_v2_runtime
        if runtime.health().get("artifact_status") != "COMPLETE":
            raise HTTPException(status_code=503, detail="ARTIFACT_NOT_COMPLETE")
        try:
            hits = await asyncio.to_thread(
                runtime.retriever.retrieve, payload.query.strip(), top_k=payload.top_k
            )
            return {"query": payload.query, "results": [_serialize_retrieval_hit(hit) for hit in hits]}
        except QueryRuntimeError as exc:
            raise HTTPException(status_code=503, detail=exc.code) from exc
        except Exception as exc:
            raise HTTPException(status_code=500, detail="RETRIEVAL_FAILED") from exc

    return app


app = create_app()
