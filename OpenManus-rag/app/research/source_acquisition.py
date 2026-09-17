"""Bounded raw-source acquisition without duplicating browser automation."""

from __future__ import annotations

import inspect
from datetime import datetime, timezone
from typing import Any, Callable

import httpx

from app.reliability.executor import OperationAttempt
from app.reliability.timeout import TimeoutEnforcement, TimeoutRule
from app.research.live_models import (
    AcquisitionMethod,
    AcquiredSource,
    ResearchErrorCode,
    SelectedSource,
)


class SourceAcquisitionError(RuntimeError):
    def __init__(
        self,
        code: ResearchErrorCode,
        message: str,
        *,
        source_url: str,
    ):
        super().__init__(message)
        self.code = code
        self.source_url = source_url


class HttpSourceAcquirer:
    """Acquire original PDF/HTML bytes through a bounded HTTP GET."""

    reliability_operation_name = "research.http_get"

    def __init__(
        self,
        client: httpx.AsyncClient | None = None,
        *,
        max_bytes: int = 20 * 1024 * 1024,
        request_timeout: float = 20.0,
        clock: Callable[[], datetime] | None = None,
    ):
        self.client = client
        self.max_bytes = max_bytes
        self.request_timeout = request_timeout
        self.clock = clock or (lambda: datetime.now(timezone.utc))

    @staticmethod
    def _detect_type(data: bytes, content_type: str) -> tuple[str, str]:
        normalized_type = content_type.split(";", 1)[0].strip().casefold()
        if data.startswith(b"%PDF-") or normalized_type == "application/pdf":
            if not data.startswith(b"%PDF-"):
                raise ValueError("PDF response has an invalid signature")
            return ".pdf", "application/pdf"
        if normalized_type in {"text/html", "application/xhtml+xml"} or b"<html" in data[:4096].lower():
            try:
                prefix = data[:4096].decode("utf-8-sig").casefold()
            except UnicodeDecodeError as exc:
                raise ValueError("raw HTML source must be UTF-8") from exc
            if "<html" not in prefix and "<!doctype html" not in prefix:
                raise ValueError("HTML response has an invalid signature")
            return ".html", "text/html"
        raise ValueError(f"unsupported content type: {normalized_type or '<missing>'}")

    @staticmethod
    def _native_timeout(rule: TimeoutRule) -> httpx.Timeout:
        default = rule.timeout_ms / 1000
        return httpx.Timeout(
            default,
            connect=(rule.connect_ms / 1000 if rule.connect_ms else default),
            read=(rule.read_ms / 1000 if rule.read_ms else default),
            write=(rule.write_ms / 1000 if rule.write_ms else default),
            pool=(rule.pool_ms / 1000 if rule.pool_ms else default),
        )

    async def acquire(self, source: SelectedSource, run_store) -> AcquiredSource:
        return await self._acquire(source, run_store)

    async def acquire_attempt(
        self,
        source: SelectedSource,
        run_store,
        attempt: OperationAttempt,
    ) -> AcquiredSource:
        timeout_rule = (
            attempt.timeout.rule
            if attempt.timeout.rule.enforcement is TimeoutEnforcement.NATIVE
            else None
        )
        return await self._acquire(source, run_store, timeout_rule=timeout_rule)

    async def _acquire(
        self,
        source: SelectedSource,
        run_store,
        *,
        timeout_rule: TimeoutRule | None = None,
    ) -> AcquiredSource:
        owns_client = self.client is None
        native_timeout = (
            self._native_timeout(timeout_rule)
            if timeout_rule is not None
            else self.request_timeout
        )
        client = self.client or httpx.AsyncClient(
            follow_redirects=True,
            timeout=native_timeout,
            headers={"User-Agent": "OpenManus-KnowledgeResearch/1.0"},
        )
        stream_options = (
            {"timeout": native_timeout}
            if timeout_rule is not None
            else {}
        )
        try:
            async with client.stream("GET", source.url, **stream_options) as response:
                response.raise_for_status()
                chunks: list[bytes] = []
                size = 0
                async for chunk in response.aiter_bytes():
                    size += len(chunk)
                    if size > self.max_bytes:
                        raise SourceAcquisitionError(
                            ResearchErrorCode.DOWNLOAD_FAILED,
                            f"source exceeds the {self.max_bytes}-byte acquisition limit",
                            source_url=source.url,
                        )
                    chunks.append(chunk)
                data = b"".join(chunks)
                if not data:
                    raise SourceAcquisitionError(
                        ResearchErrorCode.EMPTY_CONTENT,
                        "source returned no bytes",
                        source_url=source.url,
                    )
                extension, media_type = self._detect_type(
                    data, response.headers.get("content-type", "")
                )
                staged = run_store.stage_bytes(data, extension=extension)
                archived = run_store.archive_staged(staged)
                return AcquiredSource(
                    search_result_id=source.search_result_id,
                    title=source.title,
                    organization=source.organization,
                    source_url=source.url,
                    final_url=str(response.url),
                    source_type="pdf" if media_type == "application/pdf" else "webpage",
                    source_level=source.source_level,
                    media_type=media_type,
                    acquisition_method=AcquisitionMethod.HTTP,
                    retrieved_at=self.clock(),
                    local_file=archived.local_file,
                    raw_file_hash=archived.raw_file_hash,
                    reused=archived.reused,
                )
        except SourceAcquisitionError:
            raise
        except (httpx.HTTPError, ValueError, OSError) as exc:
            raise SourceAcquisitionError(
                ResearchErrorCode.DOWNLOAD_FAILED,
                f"HTTP acquisition failed: {exc}",
                source_url=source.url,
            ) from exc
        finally:
            if owns_client:
                await client.aclose()


class BrowserSourceAcquirer:
    """Use only Browser tool public methods; never access its context or page internals."""

    def __init__(
        self,
        browser_tool: Any,
        *,
        clock: Callable[[], datetime] | None = None,
    ):
        self.browser_tool = browser_tool
        self.clock = clock or (lambda: datetime.now(timezone.utc))

    async def acquire(self, source: SelectedSource, run_store) -> AcquiredSource:
        navigation = await self.browser_tool.execute(action="go_to_url", url=source.url)
        if getattr(navigation, "error", None):
            raise SourceAcquisitionError(
                ResearchErrorCode.DOWNLOAD_FAILED,
                f"browser navigation failed: {navigation.error}",
                source_url=source.url,
            )

        public_reader = getattr(self.browser_tool, "get_current_document", None)
        if public_reader is None or not callable(public_reader):
            raise SourceAcquisitionError(
                ResearchErrorCode.DOWNLOAD_FAILED,
                "BrowserUseTool has no public full-document interface; private page access is forbidden",
                source_url=source.url,
            )
        document = public_reader()
        if inspect.isawaitable(document):
            document = await document
        if not isinstance(document, dict):
            raise SourceAcquisitionError(
                ResearchErrorCode.DOWNLOAD_FAILED,
                "browser public document response is invalid",
                source_url=source.url,
            )
        html = document.get("html")
        if not isinstance(html, str) or not html.strip():
            raise SourceAcquisitionError(
                ResearchErrorCode.EMPTY_CONTENT,
                "browser public document response has no HTML",
                source_url=source.url,
            )
        staged = run_store.stage_bytes(html.encode("utf-8"), extension=".html")
        archived = run_store.archive_staged(staged)
        return AcquiredSource(
            search_result_id=source.search_result_id,
            title=str(document.get("title") or source.title),
            organization=source.organization,
            source_url=source.url,
            final_url=str(document.get("url") or source.url),
            source_type="webpage",
            source_level=source.source_level,
            media_type="text/html",
            acquisition_method=AcquisitionMethod.BROWSER,
            retrieved_at=self.clock(),
            local_file=archived.local_file,
            raw_file_hash=archived.raw_file_hash,
            reused=archived.reused,
        )


class CompositeSourceAcquirer:
    """Try direct HTTP first, then a public Browser interface, with URL reuse."""

    reliability_operation_name = "research.source_acquire"

    def __init__(
        self,
        http_acquirer: HttpSourceAcquirer,
        browser_acquirer: BrowserSourceAcquirer | None = None,
    ):
        self.http_acquirer = http_acquirer
        self.browser_acquirer = browser_acquirer
        self._by_url: dict[str, AcquiredSource] = {}

    async def acquire(self, source: SelectedSource, run_store) -> AcquiredSource:
        return await self._acquire(source, run_store)

    async def acquire_attempt(
        self,
        source: SelectedSource,
        run_store,
        attempt: OperationAttempt,
    ) -> AcquiredSource:
        return await self._acquire(source, run_store, attempt=attempt)

    async def _acquire(
        self,
        source: SelectedSource,
        run_store,
        *,
        attempt: OperationAttempt | None = None,
    ) -> AcquiredSource:
        existing = self._by_url.get(source.url)
        if existing is not None:
            return existing.model_copy(update={"reused": True})
        try:
            acquired = (
                await self.http_acquirer.acquire_attempt(source, run_store, attempt)
                if attempt is not None
                else await self.http_acquirer.acquire(source, run_store)
            )
        except SourceAcquisitionError as http_error:
            if self.browser_acquirer is None:
                raise
            try:
                acquired = await self.browser_acquirer.acquire(source, run_store)
            except SourceAcquisitionError as browser_error:
                raise SourceAcquisitionError(
                    browser_error.code,
                    f"{http_error}; browser fallback: {browser_error}",
                    source_url=source.url,
                ) from browser_error
        self._by_url[source.url] = acquired
        return acquired
