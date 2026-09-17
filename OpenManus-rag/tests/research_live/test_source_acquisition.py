from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from pathlib import Path

import httpx
import pytest

from app.research.live_models import ResearchSearchResult, SelectedSource, SourceLevel
from app.research.profile_loader import load_research_profile
from app.research.run_store import ResearchRunStore, create_run_id
from app.research.source_acquisition import (
    BrowserSourceAcquirer,
    CompositeSourceAcquirer,
    HttpSourceAcquirer,
    SourceAcquisitionError,
)
from app.tool.base import ToolResult


PROJECT_ROOT = Path(__file__).resolve().parents[2]
PROFILE_PATH = PROJECT_ROOT / "config/research_profiles/special_equipment_validation.toml"
NOW = datetime(2026, 8, 28, tzinfo=timezone.utc)


def selected(url: str) -> SelectedSource:
    result = ResearchSearchResult(
        query="q", title="Source", url=url, engine="fake", position=1
    )
    return SelectedSource(
        search_result_id=result.search_result_id,
        title=result.title,
        url=result.url,
        organization="example.gov.cn",
        source_type="pdf" if url.endswith("pdf") else "webpage",
        source_level=SourceLevel.TIER1,
        selection_reason="fixture",
        search_engine="fake",
        search_position=1,
    )


def run_store(tmp_path: Path) -> ResearchRunStore:
    profile = load_research_profile(PROFILE_PATH)
    store = ResearchRunStore(tmp_path, create_run_id(profile, NOW))
    store.initialize()
    return store


@pytest.mark.asyncio
async def test_html_acquisition_archives_original_bytes(tmp_path: Path) -> None:
    data = b"<!doctype html><html><body><p>complete source</p></body></html>"
    transport = httpx.MockTransport(
        lambda request: httpx.Response(200, headers={"content-type": "text/html"}, content=data)
    )
    async with httpx.AsyncClient(transport=transport) as client:
        acquired = await HttpSourceAcquirer(client, clock=lambda: NOW).acquire(
            selected("https://example.gov.cn/page"), run_store(tmp_path)
        )

    assert acquired.media_type == "text/html"
    assert acquired.raw_file_hash == hashlib.sha256(data).hexdigest()
    assert (tmp_path / acquired.local_file).read_bytes() == data


@pytest.mark.asyncio
async def test_pdf_acquisition_uses_original_file_hash(tmp_path: Path) -> None:
    data = b"%PDF-1.7\nfixture"
    transport = httpx.MockTransport(
        lambda request: httpx.Response(200, headers={"content-type": "application/pdf"}, content=data)
    )
    async with httpx.AsyncClient(transport=transport) as client:
        acquired = await HttpSourceAcquirer(client, clock=lambda: NOW).acquire(
            selected("https://example.gov.cn/file.pdf"), run_store(tmp_path)
        )

    assert acquired.media_type == "application/pdf"
    assert acquired.raw_file_hash == hashlib.sha256(data).hexdigest()


@pytest.mark.asyncio
async def test_duplicate_url_is_not_downloaded_twice(tmp_path: Path) -> None:
    calls = 0

    def handler(request):
        nonlocal calls
        calls += 1
        return httpx.Response(
            200,
            headers={"content-type": "text/html"},
            content=b"<html><body>same</body></html>",
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        acquirer = CompositeSourceAcquirer(HttpSourceAcquirer(client, clock=lambda: NOW))
        source = selected("https://example.gov.cn/page")
        store = run_store(tmp_path)
        first = await acquirer.acquire(source, store)
        second = await acquirer.acquire(source, store)

    assert calls == 1
    assert second.local_file == first.local_file
    assert second.reused is True


@pytest.mark.asyncio
async def test_different_urls_with_identical_bytes_share_one_raw_archive(tmp_path: Path) -> None:
    data = b"<html><body>identical original bytes</body></html>"
    transport = httpx.MockTransport(
        lambda request: httpx.Response(
            200, headers={"content-type": "text/html"}, content=data
        )
    )
    async with httpx.AsyncClient(transport=transport) as client:
        acquirer = CompositeSourceAcquirer(HttpSourceAcquirer(client, clock=lambda: NOW))
        store = run_store(tmp_path)
        first = await acquirer.acquire(selected("https://example.gov.cn/one"), store)
        second = await acquirer.acquire(selected("https://example.gov.cn/two"), store)

    assert first.raw_file_hash == second.raw_file_hash
    assert first.local_file == second.local_file
    assert second.reused is True
    assert len(list(store.context.raw_sources_root.iterdir())) == 1


class PublicFakeBrowser:
    def __init__(self, with_document: bool = True):
        self.with_document = with_document

    async def execute(self, **kwargs):
        return ToolResult(output="navigated")

    async def get_current_document(self):
        if not self.with_document:
            return {}
        return {
            "url": "https://example.gov.cn/rendered",
            "title": "Rendered",
            "html": "<html><body>rendered body</body></html>",
        }


@pytest.mark.asyncio
async def test_browser_adapter_uses_only_public_document_method(tmp_path: Path) -> None:
    acquired = await BrowserSourceAcquirer(
        PublicFakeBrowser(), clock=lambda: NOW
    ).acquire(selected("https://example.gov.cn/rendered"), run_store(tmp_path))

    assert acquired.acquisition_method.value == "BROWSER"
    assert (tmp_path / acquired.local_file).read_text(encoding="utf-8").startswith("<html")


@pytest.mark.asyncio
async def test_browser_without_public_full_document_interface_is_rejected(tmp_path: Path) -> None:
    class NavigationOnlyBrowser:
        async def execute(self, **kwargs):
            return ToolResult(output="navigated")

    with pytest.raises(SourceAcquisitionError, match="no public full-document interface"):
        await BrowserSourceAcquirer(NavigationOnlyBrowser()).acquire(
            selected("https://example.gov.cn/rendered"), run_store(tmp_path)
        )


@pytest.mark.asyncio
async def test_download_failure_is_explicit(tmp_path: Path) -> None:
    transport = httpx.MockTransport(lambda request: httpx.Response(404))
    async with httpx.AsyncClient(transport=transport) as client:
        with pytest.raises(SourceAcquisitionError) as raised:
            await HttpSourceAcquirer(client).acquire(
                selected("https://example.gov.cn/missing"), run_store(tmp_path)
            )

    assert raised.value.code.value == "DOWNLOAD_FAILED"
