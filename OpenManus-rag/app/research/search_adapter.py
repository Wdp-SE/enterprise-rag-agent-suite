"""Structured adapter around OpenManus WebSearch."""

from __future__ import annotations

from typing import Any

from app.research.live_models import ResearchSearchResult
from app.research.models import ResearchProfile


class SearchAdapterError(RuntimeError):
    pass


class WebSearchAdapter:
    """Read SearchResponse.results directly without a Memory/string round trip."""

    MAX_CANDIDATES = 8

    def __init__(
        self,
        web_search: Any,
        *,
        lang: str | None = None,
        country: str | None = None,
    ):
        self.web_search = web_search
        self.lang = lang
        self.country = country
        self.last_metadata: list[dict] = []

    async def search(
        self,
        profile: ResearchProfile,
        *,
        max_candidates: int,
    ) -> list[ResearchSearchResult]:
        if not 1 <= max_candidates <= self.MAX_CANDIDATES:
            raise SearchAdapterError("max_candidates must be between 1 and 8")

        # V1 intentionally performs one bounded query. Research questions guide
        # synthesis and limitations; they do not trigger unbounded search fan-out.
        response = await self.web_search.execute(
            query=profile.research_topic,
            num_results=max_candidates,
            lang=self.lang,
            country=self.country,
            fetch_content=False,
        )
        if getattr(response, "error", None):
            raise SearchAdapterError(str(response.error))
        results = getattr(response, "results", None)
        if not isinstance(results, list):
            raise SearchAdapterError("WebSearch returned no structured results list")

        metadata = getattr(response, "metadata", None)
        self.last_metadata = [metadata.model_dump(mode="json")] if metadata is not None else []

        deduplicated: dict[str, ResearchSearchResult] = {}
        for item in results:
            try:
                mapped = ResearchSearchResult(
                    query=getattr(response, "query", profile.research_topic),
                    title=item.title or "Untitled public source",
                    url=item.url,
                    snippet=item.description or "",
                    engine=item.source,
                    position=item.position,
                )
            except (AttributeError, TypeError, ValueError):
                continue
            deduplicated.setdefault(mapped.url, mapped)
            if len(deduplicated) >= max_candidates:
                break
        return list(deduplicated.values())

