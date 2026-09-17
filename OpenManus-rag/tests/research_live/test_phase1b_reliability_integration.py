from __future__ import annotations

import ssl
from datetime import datetime, timezone
from pathlib import Path

import httpx
import pytest

from app.reliability.errors import ErrorCode
from app.reliability.executor import ReliableOperationExecutor
from app.reliability.retry import RetryOwner, RetryPolicy, RetryRule
from app.reliability.timeout import TimeoutEnforcement, TimeoutPolicy, TimeoutRule
from app.reliability.trace import TraceEvent, TraceEventType, TraceRecorder
from app.research.evidence_extraction import CompositeEvidenceExtractor
from app.research.live_models import ResearchSearchResult
from app.research.profile_loader import load_research_profile
from app.research.research_result import ResearchResultBuilder
from app.research.research_synthesis import DeterministicResearchSynthesizer
from app.research.search_adapter import SearchAdapterError
from app.research.source_acquisition import HttpSourceAcquirer
from app.research.source_policy import SourcePolicy
from app.research.source_selection import SourceSelector
from app.research.workflow import KnowledgeResearchWorkflow


PROJECT_ROOT = Path(__file__).resolve().parents[2]
PROFILE = load_research_profile(
    PROJECT_ROOT / "config/research_profiles/special_equipment_validation.toml"
)
POLICY = SourcePolicy.from_toml(PROJECT_ROOT / "config/research_policies/default.toml")
NOW = datetime(2026, 8, 29, 8, 0, 0, 123456, timezone.utc)
HTML = (
    b"<!doctype html><html><head><title>Fixture</title></head><body><article>"
    b"<h1>Public requirements</h1><p>A complete public-source fact with enough "
    b"context for deterministic Evidence extraction and validation.</p>"
    b"</article></body></html>"
)


class FakeSleeper:
    def __init__(self) -> None:
        self.calls: list[float] = []

    async def sleep(self, seconds: float) -> None:
        self.calls.append(seconds)


class FakeRandom:
    def random(self) -> float:
        return 0.5


class TimeoutStream(httpx.AsyncByteStream):
    def __init__(self) -> None:
        self.closed = False

    async def __aiter__(self):
        yield b"<!doctype html>"
        raise httpx.ReadTimeout("native read timeout")

    async def aclose(self) -> None:
        self.closed = True


class OneSourceSearch:
    def __init__(self) -> None:
        self.calls = 0

    async def search(self, profile, *, max_candidates):
        self.calls += 1
        return [
            ResearchSearchResult(
                query=profile.research_topic,
                title="Official fixture source",
                url="https://fixture.gov.cn/requirements",
                snippet="search discovery metadata only",
                engine="fake",
                position=1,
            )
        ]


class FailingSearch:
    def __init__(self) -> None:
        self.calls = 0

    async def search(self, profile, *, max_candidates):
        self.calls += 1
        raise SearchAdapterError("TLS EOF in delegated WebSearch")


class FlakyLLMSynthesizer:
    reliability_retry_owner = RetryOwner.RELIABILITY

    def __init__(self) -> None:
        self.calls = 0
        self.delegate = DeterministicResearchSynthesizer()

    async def synthesize(self, profile, evidence):
        self.calls += 1
        if self.calls == 1:
            raise ssl.SSLError("TLS EOF from one-shot synthesis client")
        return await self.delegate.synthesize(profile, evidence)


def retry_rule() -> RetryRule:
    return RetryRule.transient_default(
        max_attempts=3,
        base_delay_ms=10,
        max_delay_ms=100,
        jitter_ratio=0,
    )


def make_executor(
    *,
    retry_operations: tuple[str, ...] = ("research.http_get",),
    native_http_timeout: bool = True,
) -> tuple[ReliableOperationExecutor, FakeSleeper]:
    sleeper = FakeSleeper()
    timeout_policy = TimeoutPolicy.disabled()
    if native_http_timeout:
        timeout_policy = TimeoutPolicy(
            operation_rules={
                "research.http_get": TimeoutRule(
                    timeout_ms=15_000,
                    enforcement=TimeoutEnforcement.NATIVE,
                    connect_ms=2_000,
                    read_ms=12_000,
                    write_ms=4_000,
                    pool_ms=1_000,
                )
            }
        )
    return (
        ReliableOperationExecutor(
            timeout_policy=timeout_policy,
            retry_policy=RetryPolicy(
                operation_rules={name: retry_rule() for name in retry_operations}
            ),
            sleeper=sleeper,
            random_source=FakeRandom(),
        ),
        sleeper,
    )


def make_workflow(
    workspace: Path,
    *,
    search_provider,
    source_acquirer,
    executor: ReliableOperationExecutor,
    recorder: TraceRecorder,
    synthesizer=None,
) -> KnowledgeResearchWorkflow:
    return KnowledgeResearchWorkflow(
        workspace_root=workspace,
        search_provider=search_provider,
        source_selector=SourceSelector(POLICY),
        source_acquirer=source_acquirer,
        evidence_extractor=CompositeEvidenceExtractor(),
        synthesizer=synthesizer or DeterministicResearchSynthesizer(),
        output_adapters=[],
        result_builder=ResearchResultBuilder(clock=lambda: NOW),
        clock=lambda: NOW,
        trace_recorder=recorder,
        operation_executor=executor,
    )


def read_trace(recorder: TraceRecorder, run_id: str) -> list[TraceEvent]:
    return [
        TraceEvent.model_validate_json(line)
        for line in recorder.path_for(run_id).read_text(encoding="utf-8").splitlines()
    ]


@pytest.mark.asyncio
async def test_http_403_replay_is_access_denied_with_one_attempt(tmp_path: Path) -> None:
    calls = 0

    def handler(request):
        nonlocal calls
        calls += 1
        return httpx.Response(403, request=request)

    executor, sleeper = make_executor()
    recorder = TraceRecorder(tmp_path)
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        outcome = await make_workflow(
            tmp_path,
            search_provider=OneSourceSearch(),
            source_acquirer=HttpSourceAcquirer(client, clock=lambda: NOW),
            executor=executor,
            recorder=recorder,
        ).run(PROFILE)

    events = read_trace(recorder, outcome.result.run_id)
    operation_events = [event for event in events if event.operation == "research.http_get"]
    assert calls == 1
    assert sleeper.calls == []
    assert outcome.metrics.download_failure == 1
    assert any(
        event.event_type is TraceEventType.OPERATION_FAILED
        and event.error_code is ErrorCode.ACCESS_DENIED
        for event in operation_events
    )
    assert not any(event.event_type is TraceEventType.RETRY_SCHEDULED for event in operation_events)


@pytest.mark.asyncio
async def test_tls_eof_replay_retries_http_once_and_preserves_native_timeout(
    tmp_path: Path,
) -> None:
    calls = 0
    timeout_extensions: list[dict] = []

    def handler(request):
        nonlocal calls
        calls += 1
        timeout_extensions.append(dict(request.extensions["timeout"]))
        if calls == 1:
            raise httpx.ReadError("TLS EOF from fixture", request=request)
        return httpx.Response(
            200,
            request=request,
            headers={"content-type": "text/html"},
            content=HTML,
        )

    executor, sleeper = make_executor()
    recorder = TraceRecorder(tmp_path)
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        outcome = await make_workflow(
            tmp_path,
            search_provider=OneSourceSearch(),
            source_acquirer=HttpSourceAcquirer(client, clock=lambda: NOW),
            executor=executor,
            recorder=recorder,
        ).run(PROFILE)

    events = read_trace(recorder, outcome.result.run_id)
    operation_events = [event for event in events if event.operation == "research.http_get"]
    assert calls == 2
    assert sleeper.calls == [0.01]
    assert outcome.metrics.download_success == 1
    assert timeout_extensions == [
        {"connect": 2.0, "read": 12.0, "write": 4.0, "pool": 1.0},
        {"connect": 2.0, "read": 12.0, "write": 4.0, "pool": 1.0},
    ]
    assert [
        event.event_type
        for event in operation_events
        if event.event_type
        in {
            TraceEventType.OPERATION_STARTED,
            TraceEventType.OPERATION_FAILED,
            TraceEventType.RETRY_SCHEDULED,
            TraceEventType.OPERATION_SUCCEEDED,
        }
    ] == [
        TraceEventType.OPERATION_STARTED,
        TraceEventType.OPERATION_FAILED,
        TraceEventType.RETRY_SCHEDULED,
        TraceEventType.OPERATION_STARTED,
        TraceEventType.OPERATION_SUCCEEDED,
    ]


@pytest.mark.asyncio
async def test_native_http_timeout_closes_response_stream(tmp_path: Path) -> None:
    stream = TimeoutStream()

    def handler(request):
        return httpx.Response(
            200,
            request=request,
            headers={"content-type": "text/html"},
            stream=stream,
        )

    executor, sleeper = make_executor(retry_operations=())
    recorder = TraceRecorder(tmp_path)
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        outcome = await make_workflow(
            tmp_path,
            search_provider=OneSourceSearch(),
            source_acquirer=HttpSourceAcquirer(client, clock=lambda: NOW),
            executor=executor,
            recorder=recorder,
        ).run(PROFILE)

    events = read_trace(recorder, outcome.result.run_id)
    timeouts = [event for event in events if event.event_type is TraceEventType.TIMEOUT]
    assert stream.closed is True
    assert sleeper.calls == []
    assert outcome.metrics.download_failure == 1
    assert len(timeouts) == 1
    assert timeouts[0].error_code is ErrorCode.OPERATION_TIMEOUT
    assert timeouts[0].output_summary["timeout_source"] == "SDK_TIMEOUT"


@pytest.mark.asyncio
async def test_search_retry_owner_is_delegated_and_never_multiplies_outer_attempts(
    tmp_path: Path,
) -> None:
    search = FailingSearch()
    executor, sleeper = make_executor(
        retry_operations=("research.search",),
        native_http_timeout=False,
    )
    recorder = TraceRecorder(tmp_path)
    outcome = await make_workflow(
        tmp_path,
        search_provider=search,
        source_acquirer=HttpSourceAcquirer(),
        executor=executor,
        recorder=recorder,
    ).run(PROFILE)

    events = read_trace(recorder, outcome.result.run_id)
    search_events = [event for event in events if event.operation == "research.search"]
    assert search.calls == 1
    assert sleeper.calls == []
    assert len(
        [event for event in search_events if event.event_type is TraceEventType.OPERATION_STARTED]
    ) == 1
    assert not any(event.event_type is TraceEventType.RETRY_SCHEDULED for event in search_events)


@pytest.mark.asyncio
async def test_optional_one_shot_llm_synthesis_can_use_reliability_retry_owner(
    tmp_path: Path,
) -> None:
    synthesizer = FlakyLLMSynthesizer()
    executor, sleeper = make_executor(
        retry_operations=("research.llm_synthesis",),
        native_http_timeout=False,
    )
    recorder = TraceRecorder(tmp_path)
    transport = httpx.MockTransport(
        lambda request: httpx.Response(
            200,
            request=request,
            headers={"content-type": "text/html"},
            content=HTML,
        )
    )
    async with httpx.AsyncClient(transport=transport) as client:
        outcome = await make_workflow(
            tmp_path,
            search_provider=OneSourceSearch(),
            source_acquirer=HttpSourceAcquirer(client, clock=lambda: NOW),
            executor=executor,
            recorder=recorder,
            synthesizer=synthesizer,
        ).run(PROFILE)

    events = read_trace(recorder, outcome.result.run_id)
    synthesis_events = [
        event for event in events if event.operation == "research.llm_synthesis"
    ]
    assert synthesizer.calls == 2
    assert sleeper.calls == [0.01]
    assert outcome.metrics.evidence_count == 1
    assert any(event.event_type is TraceEventType.RETRY_SCHEDULED for event in synthesis_events)
