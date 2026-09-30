"""Public FastAPI entrypoint serving only pinned official-source knowledge."""

from __future__ import annotations

import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, ConfigDict, Field

from src.answer_generation import (
    StructuredAnswerGenerator,
    default_generation_model,
    generation_api_key_env,
)
from src.engineering_change import (
    EngineeringImpactService, EngineeringItem, TraceLink, compare_engineering_items,
)
from src.figure_sidecar_integrity import validate_reviewed_sidecar
from src.public_api import router as public_router
from src.public_knowledge import PublicKnowledgeIndex
from src.public_retrieval_runtime import PublicRetrievalRuntime
from src.public_retrieval_runtime import DEFAULT_CONFIG as DEFAULT_PUBLIC_RETRIEVAL_CONFIG


SERVICE_ROOT = Path(__file__).resolve().parents[1]


def _configured_public_corpus_root() -> Path:
    configured = os.environ.get("RAG_PUBLIC_CORPUS_ROOT", "").strip()
    if not configured:
        return Path(__file__).resolve().parents[1] / "public_corpus"
    path = Path(configured).expanduser()
    return path if path.is_absolute() else (SERVICE_ROOT / path).resolve()


def _configured_public_retrieval_config() -> Path:
    configured = os.environ.get("RAG_PUBLIC_RETRIEVAL_CONFIG", "").strip()
    if not configured:
        return DEFAULT_PUBLIC_RETRIEVAL_CONFIG
    path = Path(configured).expanduser()
    return path if path.is_absolute() else (SERVICE_ROOT / path).resolve()


class DiffRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    old_items: list[EngineeringItem]
    new_items: list[EngineeringItem]


class ImpactRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    changed_item_id: str = Field(min_length=1)
    items: list[EngineeringItem]
    trace_links: list[TraceLink] = Field(default_factory=list)
    dense_item_ids: list[str] = Field(default_factory=list)
    evidence_by_item: dict[str, list[str]] = Field(default_factory=dict)


def create_app(*, index: PublicKnowledgeIndex | None = None, generator=None,
               retrieval_config_path=None, figure_sidecar_path=None,
               figure_sidecar_lock_path=None) -> FastAPI:
    @asynccontextmanager
    async def lifespan(app: FastAPI):
        base_index = index or PublicKnowledgeIndex(root=_configured_public_corpus_root())
        sidecar_path = Path(figure_sidecar_path or base_index.root / "figure_evidence_reviewed.json")
        lock_path = Path(figure_sidecar_lock_path or base_index.root / "figure_evidence_reviewed.lock.json")
        validate_reviewed_sidecar(
            sidecar_path=sidecar_path,
            lock_path=lock_path,
            manifest_path=base_index.root / "corpus_manifest.json",
        )
        app.state.public_base_knowledge_index = base_index
        app.state.public_knowledge_index = PublicRetrievalRuntime(
            base_index,
            config_path=retrieval_config_path or _configured_public_retrieval_config(),
            sidecar_path=sidecar_path,
        )
        app.state.public_generator = generator
        generation_allowed = os.environ.get(
            "RD_V2_ALLOW_EXTERNAL_GENERATION", "false"
        ).strip().casefold() in ("1", "true", "yes", "on")
        generation_provider = os.environ.get(
            "RD_V2_GENERATION_PROVIDER", "dashscope"
        ).strip().casefold()
        try:
            api_key_env = generation_api_key_env(generation_provider)
            generation_model = (
                os.environ.get("RD_V2_GENERATION_MODEL", "").strip()
                or default_generation_model(generation_provider)
            )
        except ValueError:
            api_key_env = None
            generation_model = None
        api_key_configured = bool(api_key_env and os.environ.get(api_key_env, "").strip())
        if app.state.public_generator is None and generation_allowed and api_key_configured:
            app.state.public_generator = StructuredAnswerGenerator(
                provider=generation_provider,
                model=generation_model,
        )
        if app.state.public_generator is not None:
            status = "CONFIGURED_UNVERIFIED"
            generation_provider = getattr(app.state.public_generator, "provider", None)
            generation_model = getattr(app.state.public_generator, "model", None)
        elif not generation_allowed:
            status = "DISABLED"
        elif api_key_env is None:
            status = "INVALID_PROVIDER"
        else:
            status = "API_KEY_MISSING"
        app.state.public_generation_config = {
            "status": status,
            "provider": generation_provider if status == "CONFIGURED_UNVERIFIED" or api_key_env else None,
            "model": generation_model if status == "CONFIGURED_UNVERIFIED" or api_key_env else None,
        }
        yield

    app = FastAPI(
        title="Versioned Public Engineering Knowledge",
        version="0.1.0",
        lifespan=lifespan,
    )
    app.include_router(public_router)

    @app.get("/health")
    def health() -> dict:
        return {
            "alive": True, "rag_ready": bool(app.state.public_knowledge_index),
            "workspace": app.state.public_base_knowledge_index.manifest["workspace"],
            "retrieval_policy": app.state.public_knowledge_index.policy["default_policy"],
            "runtime_retrieval_policy": app.state.public_knowledge_index.runtime_policy,
            "approved_image_chunk_count": len(app.state.public_knowledge_index._images),
            "generation": app.state.public_generation_config,
        }

    @app.post("/engineering/items/diff")
    def engineering_diff(payload: DiffRequest) -> dict:
        try:
            return {"changes": [
                row.model_dump(mode="json")
                for row in compare_engineering_items(payload.old_items, payload.new_items)
            ]}
        except ValueError as exc:
            raise HTTPException(status_code=422, detail="ENGINEERING_DIFF_INVALID") from exc

    @app.post("/engineering/impacts/discover")
    def engineering_impacts(payload: ImpactRequest) -> dict:
        try:
            rows = EngineeringImpactService().discover(
                changed_item_id=payload.changed_item_id,
                items=payload.items,
                trace_links=payload.trace_links,
                dense_item_ids=payload.dense_item_ids,
                evidence_by_item=payload.evidence_by_item,
            )
            return {"impacts": [row.model_dump(mode="json") for row in rows]}
        except ValueError as exc:
            raise HTTPException(status_code=422, detail="ENGINEERING_IMPACT_INVALID") from exc

    return app


app = create_app()
