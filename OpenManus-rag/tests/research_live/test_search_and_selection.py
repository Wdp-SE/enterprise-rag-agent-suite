from __future__ import annotations

from pathlib import Path

import pytest

from app.research.live_models import AcquisitionMethod, AcquiredSource, ResearchSearchResult
from app.research.models import SourceLevel
from app.research.profile_loader import load_research_profile
from app.research.search_adapter import SearchAdapterError, WebSearchAdapter
from app.research.source_policy import SourcePolicy
from app.research.source_selection import SourceSelector
from app.tool.web_search import SearchMetadata, SearchResponse, SearchResult


PROJECT_ROOT = Path(__file__).resolve().parents[2]
PROFILE_PATH = PROJECT_ROOT / "config/research_profiles/special_equipment_validation.toml"
POLICY_PATH = PROJECT_ROOT / "config/research_policies/default.toml"


class FakeWebSearch:
    def __init__(self, response: SearchResponse):
        self.response = response
        self.calls: list[dict] = []

    async def execute(self, **kwargs):
        self.calls.append(kwargs)
        return self.response


@pytest.mark.asyncio
async def test_profile_to_web_search_preserves_structured_results() -> None:
    response = SearchResponse(
        query="structured query",
        results=[
            SearchResult(
                position=1,
                url="https://example.gov.cn/a",
                title="Official A",
                description="Discovery only",
                source="bing",
            )
        ],
        metadata=SearchMetadata(total_results=1, language="zh", country="cn"),
    )
    response.output = "this string must not be parsed"
    fake = FakeWebSearch(response)
    adapter = WebSearchAdapter(fake, lang="zh", country="cn")

    results = await adapter.search(load_research_profile(PROFILE_PATH), max_candidates=8)

    assert results[0].title == "Official A"
    assert results[0].snippet == "Discovery only"
    assert results[0].engine == "bing"
    assert fake.calls[0]["fetch_content"] is False
    assert adapter.last_metadata[0]["total_results"] == 1


@pytest.mark.asyncio
async def test_search_adapter_deduplicates_url_and_caps_candidates() -> None:
    items = [
        SearchResult(
            position=index,
            url=f"https://example.com/{min(index, 8)}",
            title=f"Result {index}",
            description="",
            source="bing",
        )
        for index in range(1, 10)
    ]
    adapter = WebSearchAdapter(FakeWebSearch(SearchResponse(query="q", results=items)))

    results = await adapter.search(load_research_profile(PROFILE_PATH), max_candidates=8)

    assert len(results) == 8
    with pytest.raises(SearchAdapterError, match="between 1 and 8"):
        await adapter.search(load_research_profile(PROFILE_PATH), max_candidates=9)


def test_source_policy_ranking_and_max_sources() -> None:
    profile = load_research_profile(PROFILE_PATH)
    selector = SourceSelector(SourcePolicy.from_toml(POLICY_PATH))
    results = [
        ResearchSearchResult(
            query="q",
            title=title,
            url=url,
            snippet="",
            engine="bing",
            position=position,
        )
        for position, title, url in [
            (1, "Ordinary", "https://example.com/a"),
            (2, "Official PDF", "https://samr.gov.cn/a.pdf"),
            (3, "Official HTML", "https://www.gov.cn/b"),
            (4, "Extra", "https://other.example/c"),
        ]
    ]

    selected = selector.select(results, profile, max_sources=2)

    assert len(selected) == 2
    assert all(source.source_level.value == "TIER1" for source in selected)
    assert selected[0].organization == "samr.gov.cn"
    assert selected[0].selection_reason


def test_source_selection_is_stable_after_input_shuffle() -> None:
    profile = load_research_profile(PROFILE_PATH)
    selector = SourceSelector(SourcePolicy.from_toml(POLICY_PATH))
    results = [
        ResearchSearchResult(
            query="q",
            title=str(index),
            url=f"https://example{index}.com/doc",
            engine="bing",
            position=index,
        )
        for index in range(1, 5)
    ]

    first = selector.select(results, profile)
    second = selector.select(list(reversed(results)), profile)

    assert [item.search_result_id for item in first] == [
        item.search_result_id for item in second
    ]


def test_final_redirect_url_is_reclassified_by_same_source_policy() -> None:
    selector = SourceSelector(SourcePolicy.from_toml(POLICY_PATH))
    acquired = AcquiredSource(
        search_result_id="sr_11111111111111111111",
        title="Redirected official source",
        organization="search.example",
        source_url="https://search.example/redirect",
        final_url="https://www.samr.gov.cn/official/page",
        source_type="webpage",
        source_level=SourceLevel.TIER3,
        media_type="text/html",
        acquisition_method=AcquisitionMethod.HTTP,
        retrieved_at="2026-08-28T00:00:00Z",
        local_file="research_runs/run/raw_sources/" + "a" * 64 + ".html",
        raw_file_hash="a" * 64,
    )

    refined = selector.refine_acquired(acquired)

    assert refined.organization == "www.samr.gov.cn"
    assert refined.source_level is SourceLevel.TIER1
