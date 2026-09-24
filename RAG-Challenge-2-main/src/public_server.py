"""Public FastAPI entrypoint serving only pinned official-source knowledge."""

from __future__ import annotations

import os
import re
import threading
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, ConfigDict, Field

from src.answer_generation import StructuredAnswerGenerator
from src.engineering_change import (
    EngineeringImpactService, EngineeringItem, TraceLink, compare_engineering_items,
)
from src.public_api import router as public_router
from src.public_knowledge import PublicKnowledgeIndex


class SessionBudget:
    _VALID = re.compile(r"^[A-Za-z0-9_-]{8,64}$")

    def __init__(self, limit: int, total_limit: int):
        if limit < 0 or total_limit < 0:
            raise ValueError("generation limits must be nonnegative")
        self.limit = limit
        self.total_limit = total_limit
        self.total_used = 0
        self.counts: dict[str, int] = {}
        self.lock = threading.Lock()

    def consume(self, session_id: str) -> bool:
        if not self._VALID.fullmatch(session_id or ""):
            raise ValueError("invalid public session")
        with self.lock:
            used = self.counts.get(session_id, 0)
            if used >= self.limit or self.total_used >= self.total_limit:
                return False
            self.counts[session_id] = used + 1
            self.total_used += 1
            return True


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
        api_key_configured = bool(os.environ.get("DASHSCOPE_API_KEY", "").strip())
        if app.state.public_generator is None and generation_allowed and api_key_configured:
            app.state.public_generator = StructuredAnswerGenerator(
                provider=os.environ.get("RD_V2_GENERATION_PROVIDER", "dashscope"),
                model=os.environ.get("RD_V2_GENERATION_MODEL", "qwen-turbo"),
            )
        app.state.public_query_budget = SessionBudget(
            int(os.environ.get("MAX_LLM_CALLS_PER_SESSION", "3")),
            int(os.environ.get("MAX_LLM_CALLS_PER_PROCESS", "30")),
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
