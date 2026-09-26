"""Public FastAPI entrypoint serving only pinned official-source knowledge."""

from __future__ import annotations

import os
from contextlib import asynccontextmanager

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
from src.public_api import router as public_router
from src.public_knowledge import PublicKnowledgeIndex


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


def create_app(*, index: PublicKnowledgeIndex | None = None, generator=None) -> FastAPI:
    @asynccontextmanager
    async def lifespan(app: FastAPI):
        app.state.public_knowledge_index = index or PublicKnowledgeIndex()
        app.state.public_generator = generator
        generation_allowed = os.environ.get(
            "RD_V2_ALLOW_EXTERNAL_GENERATION", "false"
        ).strip().casefold() in ("1", "true", "yes", "on")
        generation_provider = os.environ.get(
            "RD_V2_GENERATION_PROVIDER", "dashscope"
        ).strip().casefold()
        api_key_env = generation_api_key_env(generation_provider)
        api_key_configured = bool(os.environ.get(api_key_env, "").strip())
        if app.state.public_generator is None and generation_allowed and api_key_configured:
            app.state.public_generator = StructuredAnswerGenerator(
                provider=generation_provider,
                model=os.environ.get(
                    "RD_V2_GENERATION_MODEL",
                    default_generation_model(generation_provider),
                ),
        )
        yield

    app = FastAPI(
        title="Apache DolphinScheduler Public Engineering Knowledge",
        version="official-corpus-3.4.3",
        lifespan=lifespan,
    )
    app.include_router(public_router)

    @app.get("/health")
    def health() -> dict:
        return {
            "alive": True, "rag_ready": bool(app.state.public_knowledge_index),
            "workspace": "Apache DolphinScheduler",
            "retrieval_policy": app.state.public_knowledge_index.policy["default_policy"],
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
