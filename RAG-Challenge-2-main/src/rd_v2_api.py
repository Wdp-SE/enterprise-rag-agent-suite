"""Minimal FastAPI surface for the frozen R&D V2 runtime."""

from __future__ import annotations

import asyncio
import base64
import hashlib
import re
import unicodedata
from contextlib import asynccontextmanager
from typing import Any, Callable, Optional

from fastapi import FastAPI, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field

from src.rd_v2_runtime import QueryRuntimeError, RDV2QueryRuntime, create_runtime
from src.document_lifecycle import RetrievalScope
from src.engineering_change import (
    CandidateVersionService,
    EngineeringImpactService,
    EngineeringItem,
    EngineeringItemRetriever,
    EngineeringRetrievalScope,
    OrganizationProfile,
    TraceLink,
    compare_engineering_items,
)


class QueryRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    question: str = Field(min_length=1, max_length=4000)
    scope: Optional[RetrievalScope] = None


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
    scope: Optional[RetrievalScope] = None


class RetrievalResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    chunk_id: str
    document_id: str
    version_id: str
    version_label: str
    version_status: str
    project_id: str
    document_type: str
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


class EngineeringDiffRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    old_items: list[EngineeringItem]
    new_items: list[EngineeringItem]


class EngineeringRetrieveRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    query: str = Field(min_length=1, max_length=4000)
    items: list[EngineeringItem]
    scope: EngineeringRetrievalScope = Field(default_factory=EngineeringRetrievalScope)
    dense_item_ids: list[str] = Field(default_factory=list)
    top_k: int = Field(default=5, ge=1, le=20)


class EngineeringImpactRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    changed_item_id: str = Field(min_length=1)
    items: list[EngineeringItem]
    trace_links: list[TraceLink]
    dense_item_ids: list[str] = Field(default_factory=list)
    evidence_by_item: dict[str, list[str]] = Field(default_factory=dict)


class CandidateBuildRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    document_id: str = Field(min_length=1)
    project_id: str = Field(min_length=1)
    document_type: str = Field(min_length=1)
    title: str = Field(min_length=1)
    version_id: str = Field(min_length=1)
    version_label: str = Field(min_length=1)
    source_base64: str = Field(min_length=1)
    source_name: str = Field(min_length=1)
    profile: OrganizationProfile
    expected_contents: list[str] = Field(default_factory=list)


class CandidateRetrieveRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    query_vector: list[float] = Field(min_length=1)
    scope: RetrievalScope = Field(default_factory=RetrievalScope)
    top_k: int = Field(default=5, ge=1, le=20)


def _serialize_retrieval_hit(hit: dict) -> dict:
    """Expose only provenance and raw text from a validated frozen chunk."""
    content = hit["text"]
    normalized = re.sub(r"\s+", " ", unicodedata.normalize("NFKC", content)).strip()
    return {
        "chunk_id": hit["chunk_id"],
        "document_id": hit["document_id"],
        "version_id": hit["version_id"],
        "version_label": hit["version_label"],
        "version_status": hit["version_status"],
        "project_id": hit["project_id"],
        "document_type": hit["document_type"],
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
    candidate_service: CandidateVersionService | None = None,
) -> FastAPI:
    """Create the service; startup fails if frozen artifacts fail validation."""

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        app.state.rd_v2_runtime = runtime or runtime_factory()
        app.state.engineering_candidate_service = candidate_service
        try:
            yield
        finally:
            app.state.rd_v2_runtime.close()

    app = FastAPI(
        title="R&D Document RAG V3",
        version="rd-v3-lifecycle-v1.0",
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
                request.app.state.rd_v2_runtime.query, payload.question, payload.scope
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
                runtime.retriever.retrieve,
                payload.query.strip(),
                top_k=payload.top_k,
                scope=payload.scope,
            )
            return {"query": payload.query, "results": [_serialize_retrieval_hit(hit) for hit in hits]}
        except QueryRuntimeError as exc:
            raise HTTPException(status_code=503, detail=exc.code) from exc
        except Exception as exc:
            raise HTTPException(status_code=500, detail="RETRIEVAL_FAILED") from exc

    @app.get("/documents")
    async def documents(request: Request) -> dict:
        return {"documents": request.app.state.rd_v2_runtime.catalog.document_rows()}

    @app.get("/documents/{document_id}/versions")
    async def document_versions(document_id: str, request: Request) -> dict:
        try:
            rows = request.app.state.rd_v2_runtime.catalog.version_rows(document_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="DOCUMENT_NOT_FOUND") from exc
        return {"document_id": document_id, "versions": rows}

    @app.get("/documents/{document_id}/diff")
    async def document_diff(
        document_id: str,
        from_version_id: str,
        to_version_id: str,
        request: Request,
    ) -> dict:
        try:
            result = request.app.state.rd_v2_runtime.catalog.diff(
                document_id, from_version_id, to_version_id
            )
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="VERSION_DIFF_NOT_AVAILABLE") from exc
        return result.model_dump(mode="json")

    @app.post("/engineering/items/diff")
    async def engineering_item_diff(payload: EngineeringDiffRequest) -> dict:
        try:
            changes = compare_engineering_items(payload.old_items, payload.new_items)
            return {"changes": [item.model_dump(mode="json") for item in changes]}
        except ValueError as exc:
            raise HTTPException(status_code=422, detail="ENGINEERING_DIFF_INVALID") from exc

    @app.post("/engineering/items/retrieve")
    async def engineering_item_retrieve(payload: EngineeringRetrieveRequest) -> dict:
        try:
            results = EngineeringItemRetriever().retrieve(
                payload.query,
                payload.items,
                payload.scope,
                dense_item_ids=payload.dense_item_ids,
                top_k=payload.top_k,
            )
            return {"query": payload.query, "results": [item.model_dump(mode="json") for item in results]}
        except ValueError as exc:
            raise HTTPException(status_code=422, detail="ENGINEERING_RETRIEVAL_INVALID") from exc

    @app.post("/engineering/impacts/discover")
    async def engineering_impacts(payload: EngineeringImpactRequest) -> dict:
        try:
            impacts = EngineeringImpactService().discover(
                changed_item_id=payload.changed_item_id,
                items=payload.items,
                trace_links=payload.trace_links,
                dense_item_ids=payload.dense_item_ids,
                evidence_by_item=payload.evidence_by_item,
            )
            return {"impacts": [item.model_dump(mode="json") for item in impacts]}
        except ValueError as exc:
            raise HTTPException(status_code=422, detail="ENGINEERING_IMPACT_INVALID") from exc

    @app.post("/engineering/candidates/build")
    async def build_engineering_candidate(payload: CandidateBuildRequest, request: Request) -> dict:
        service = request.app.state.engineering_candidate_service
        if service is None:
            raise HTTPException(status_code=503, detail="ENGINEERING_VERSION_SERVICE_UNAVAILABLE")
        try:
            source_bytes = base64.b64decode(payload.source_base64, validate=True)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail="CANDIDATE_SOURCE_INVALID") from exc
        record = await asyncio.to_thread(
            service.build_candidate,
            document_id=payload.document_id,
            project_id=payload.project_id,
            document_type=payload.document_type,
            title=payload.title,
            version_id=payload.version_id,
            version_label=payload.version_label,
            source_bytes=source_bytes,
            source_name=payload.source_name,
            profile=payload.profile,
            expected_contents=payload.expected_contents,
        )
        return record.model_dump(mode="json")

    @app.post("/engineering/candidates/{candidate_id}/activate")
    async def activate_engineering_candidate(candidate_id: str, request: Request) -> dict:
        service = request.app.state.engineering_candidate_service
        if service is None:
            raise HTTPException(status_code=503, detail="ENGINEERING_VERSION_SERVICE_UNAVAILABLE")
        try:
            record = await asyncio.to_thread(service.activate, candidate_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="CANDIDATE_NOT_FOUND") from exc
        except ValueError as exc:
            raise HTTPException(status_code=409, detail="CANDIDATE_NOT_VALIDATED") from exc
        return record.model_dump(mode="json")

    @app.get("/engineering/candidates/{candidate_id}")
    async def engineering_candidate(candidate_id: str, request: Request) -> dict:
        service = request.app.state.engineering_candidate_service
        if service is None:
            raise HTTPException(status_code=503, detail="ENGINEERING_VERSION_SERVICE_UNAVAILABLE")
        try:
            return service.get(candidate_id).model_dump(mode="json")
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="CANDIDATE_NOT_FOUND") from exc

    @app.post("/engineering/versions/retrieve")
    async def retrieve_engineering_version(payload: CandidateRetrieveRequest, request: Request) -> dict:
        service = request.app.state.engineering_candidate_service
        if service is None:
            raise HTTPException(status_code=503, detail="ENGINEERING_VERSION_SERVICE_UNAVAILABLE")
        try:
            results = await asyncio.to_thread(
                service.retrieve, payload.query_vector, payload.scope, top_k=payload.top_k
            )
        except ValueError as exc:
            raise HTTPException(status_code=422, detail="ENGINEERING_VERSION_RETRIEVAL_INVALID") from exc
        return {"results": results}

    return app


app = create_app()
