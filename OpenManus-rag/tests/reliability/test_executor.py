from __future__ import annotations

import asyncio
import ssl
from datetime import datetime, timedelta, timezone
from pathlib import Path

import httpx
import pytest

from app.reliability.errors import ErrorCode
from app.reliability.executor import (
    DeadlineSource,
    OperationDeadline,
    OperationSpec,
    ReliableOperationExecutor,
)
from app.reliability.result import ExecutionStatus
from app.reliability.retry import RetryOwner, RetryPolicy, RetryRule, SideEffectLevel
from app.reliability.timeout import TimeoutEnforcement, TimeoutPolicy, TimeoutRule
from app.reliability.trace import TraceContext, TraceEvent, TraceEventType, TraceRecorder


class FakeClock:
    def __init__(self) -> None:
        self.elapsed = 100.0
        self.current = datetime(2026, 8, 29, tzinfo=timezone.utc)

    def now(self) -> datetime:
        return self.current

    def monotonic(self) -> float:
        return self.elapsed

    def advance(self, seconds: float) -> None:
        self.elapsed += seconds
        self.current += timedelta(seconds=seconds)


class FakeSleeper:
    def __init__(self, clock: FakeClock):
        self.clock = clock
        self.calls: list[float] = []

    async def sleep(self, seconds: float) -> None:
        self.calls.append(seconds)
        self.clock.advance(seconds)


class FakeRandom:
    def __init__(self, value: float = 0.5):
        self.value = value

    def random(self) -> float:
        return self.value


def spec(
    *,
    owner: RetryOwner = RetryOwner.RELIABILITY,
    idempotent: bool = True,
    side_effect: SideEffectLevel = SideEffectLevel.READ_ONLY,
) -> OperationSpec:
    return OperationSpec(
        name="fixture.operation",
        idempotent=idempotent,
        side_effect_level=side_effect,
        retry_owner=owner,
        tool_name="fixture_tool",
        stage="ACQUIRE",
        workflow="knowledge_research",
    )


def retry_policy(max_attempts: int = 3) -> RetryPolicy:
    return RetryPolicy(
        operation_rules={
            "fixture.operation": RetryRule.transient_default(
                max_attempts=max_attempts,
                base_delay_ms=10,
                max_delay_ms=100,
                jitter_ratio=0,
            )
        }
    )


def executor(
    clock: FakeClock,
    *,
    timeout_policy: TimeoutPolicy | None = None,
    max_attempts: int = 3,
) -> tuple[ReliableOperationExecutor, FakeSleeper]:
    sleeper = FakeSleeper(clock)
    return (
        ReliableOperationExecutor(
            timeout_policy=timeout_policy,
            retry_policy=retry_policy(max_attempts),
            sleeper=sleeper,
            random_source=FakeRandom(),
            clock=clock,
        ),
        sleeper,
    )


def read_events(recorder: TraceRecorder, run_id: str) -> list[TraceEvent]:
    return [
        TraceEvent.model_validate_json(line)
        for line in recorder.path_for(run_id).read_text(encoding="utf-8").splitlines()
    ]


@pytest.mark.asyncio
async def test_native_timeout_is_passed_to_attempt_without_asyncio_wrapper() -> None:
    clock = FakeClock()
    native = TimeoutRule(
        timeout_ms=15_000,
        enforcement=TimeoutEnforcement.NATIVE,
        connect_ms=2_000,
        read_ms=12_000,
        write_ms=4_000,
        pool_ms=1_000,
    )
    runner, _ = executor(
        clock,
        timeout_policy=TimeoutPolicy(operation_rules={"fixture.operation": native}),
    )
    seen = []

    async def operation(attempt):
        seen.append(attempt.timeout.rule)
        return "ok"

    result = await runner.execute(spec(), operation)
    assert result.status is ExecutionStatus.SUCCESS
    assert seen == [native]


@pytest.mark.asyncio
async def test_asyncio_fallback_timeout_is_structured_and_runs_cleanup() -> None:
    clock = FakeClock()
    fallback = TimeoutRule(
        timeout_ms=1,
        enforcement=TimeoutEnforcement.ASYNCIO_FALLBACK,
    )
    runner, _ = executor(
        clock,
        timeout_policy=TimeoutPolicy(operation_rules={"fixture.operation": fallback}),
        max_attempts=1,
    )
    cleaned = []

    async def operation(attempt):
        await asyncio.Event().wait()

    async def cleanup(attempt, error):
        cleaned.append((attempt.attempt, error.code))

    result = await runner.execute(spec(), operation, cleanup=cleanup)
    assert result.status is ExecutionStatus.FAILED
    assert result.primary_error.code is ErrorCode.OPERATION_TIMEOUT
    assert result.primary_error.details["timeout_source"] == "ASYNCIO_TIMEOUT"
    assert cleaned == [(1, ErrorCode.OPERATION_TIMEOUT)]


@pytest.mark.asyncio
async def test_disabled_timeout_policy_does_not_wrap_operation() -> None:
    clock = FakeClock()
    runner, _ = executor(clock, timeout_policy=TimeoutPolicy.disabled())

    async def operation(attempt):
        assert attempt.timeout.enabled is False
        return "unchanged"

    result = await runner.execute(spec(), operation)
    assert result.value == "unchanged"
    assert result.metadata["timeout_enforcement"] == "DISABLED"


@pytest.mark.asyncio
async def test_stage_deadline_is_distinct_from_operation_timeout() -> None:
    clock = FakeClock()
    native = TimeoutRule(timeout_ms=30_000, enforcement=TimeoutEnforcement.NATIVE)
    runner, _ = executor(
        clock,
        timeout_policy=TimeoutPolicy(operation_rules={"fixture.operation": native}),
        max_attempts=1,
    )
    deadline = OperationDeadline(
        expires_at_monotonic=clock.monotonic(),
        source=DeadlineSource.STAGE_DEADLINE,
    )

    async def operation(attempt):
        raise AssertionError("expired deadline must prevent invocation")

    result = await runner.execute(spec(), operation, deadline=deadline)
    assert result.primary_error.code is ErrorCode.OPERATION_TIMEOUT
    assert result.primary_error.details["timeout_source"] == "STAGE_DEADLINE"
    assert result.primary_error.details["timeout_ms"] == 0
    assert result.primary_error.details["timeout_scope"] == "EXACT_OPERATION"


@pytest.mark.asyncio
async def test_tls_eof_retries_once_then_succeeds() -> None:
    clock = FakeClock()
    runner, sleeper = executor(clock)
    calls = 0

    async def operation(attempt):
        nonlocal calls
        calls += 1
        if calls == 1:
            raise ssl.SSLError("TLS EOF occurred")
        return "recovered"

    result = await runner.execute(spec(), operation)
    assert result.status is ExecutionStatus.SUCCESS
    assert result.value == "recovered"
    assert result.metadata["attempts"] == 2
    assert sleeper.calls == [0.01]


@pytest.mark.asyncio
async def test_connection_reset_retries() -> None:
    clock = FakeClock()
    runner, _ = executor(clock)
    calls = 0

    async def operation(attempt):
        nonlocal calls
        calls += 1
        if calls == 1:
            raise ConnectionResetError("connection reset by peer")
        return calls

    result = await runner.execute(spec(), operation)
    assert result.value == 2


def http_error(status: int, *, retry_after: str | None = None) -> httpx.HTTPStatusError:
    request = httpx.Request("GET", "https://example.test")
    headers = {"retry-after": retry_after} if retry_after is not None else None
    response = httpx.Response(status, request=request, headers=headers)
    return httpx.HTTPStatusError("HTTP failure", request=request, response=response)


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [429, 503])
async def test_429_and_503_retry(status: int) -> None:
    clock = FakeClock()
    runner, _ = executor(clock)
    calls = 0

    async def operation(attempt):
        nonlocal calls
        calls += 1
        if calls == 1:
            raise http_error(status, retry_after="0.02" if status == 429 else None)
        return "ok"

    result = await runner.execute(spec(), operation)
    assert result.status is ExecutionStatus.SUCCESS
    assert result.metadata["attempts"] == 2


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [401, 403])
async def test_401_and_403_never_retry(status: int) -> None:
    clock = FakeClock()
    runner, sleeper = executor(clock)
    calls = 0

    async def operation(attempt):
        nonlocal calls
        calls += 1
        raise http_error(status)

    result = await runner.execute(spec(), operation)
    assert result.status is ExecutionStatus.FAILED
    assert calls == 1
    assert sleeper.calls == []


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("failure", "expected"),
    [
        (ValueError("invalid input"), ErrorCode.INVALID_INPUT),
        (RuntimeError("capability unavailable"), ErrorCode.TOOL_CAPABILITY_UNAVAILABLE),
        (RuntimeError("unsupported content"), ErrorCode.UNSUPPORTED_CONTENT),
        (RuntimeError("novel failure"), ErrorCode.INTERNAL_ERROR),
    ],
)
async def test_non_retryable_classifications_stop_after_one_attempt(
    failure: Exception, expected: ErrorCode
) -> None:
    clock = FakeClock()
    runner, _ = executor(clock)
    calls = 0

    async def operation(attempt):
        nonlocal calls
        calls += 1
        raise failure

    result = await runner.execute(spec(), operation)
    assert calls == 1
    assert result.primary_error.code is expected


@pytest.mark.asyncio
async def test_non_idempotent_operation_does_not_retry() -> None:
    clock = FakeClock()
    runner, _ = executor(clock)
    calls = 0

    async def operation(attempt):
        nonlocal calls
        calls += 1
        raise ConnectionResetError("connection reset")

    result = await runner.execute(
        spec(idempotent=False, side_effect=SideEffectLevel.NON_IDEMPOTENT),
        operation,
    )
    assert result.status is ExecutionStatus.FAILED
    assert calls == 1


@pytest.mark.asyncio
async def test_delegated_retry_owner_prevents_attempt_multiplication() -> None:
    clock = FakeClock()
    runner, _ = executor(clock)
    calls = 0

    async def operation(attempt):
        nonlocal calls
        calls += 1
        raise ConnectionResetError("connection reset")

    result = await runner.execute(spec(owner=RetryOwner.DELEGATED), operation)
    assert calls == 1
    assert "delegated" in result.metadata["retry_stop_reason"]


@pytest.mark.asyncio
async def test_attempts_exhausted_returns_all_failures() -> None:
    clock = FakeClock()
    runner, sleeper = executor(clock, max_attempts=3)

    async def operation(attempt):
        raise ConnectionResetError(f"reset {attempt.attempt}")

    result = await runner.execute(spec(), operation)
    assert result.status is ExecutionStatus.FAILED
    assert result.metadata["attempts"] == 3
    assert len(result.errors) == 3
    assert len(sleeper.calls) == 2
    assert result.metadata["retry_stop_reason"] == "attempts exhausted"


@pytest.mark.asyncio
async def test_timeout_can_conditionally_retry_then_succeed() -> None:
    clock = FakeClock()
    native = TimeoutRule(timeout_ms=1_000, enforcement=TimeoutEnforcement.NATIVE)
    runner, _ = executor(
        clock,
        timeout_policy=TimeoutPolicy(operation_rules={"fixture.operation": native}),
    )

    async def operation(attempt):
        if attempt.attempt == 1:
            raise asyncio.TimeoutError("SDK request timed out")
        return "ok"

    result = await runner.execute(spec(), operation)
    assert result.status is ExecutionStatus.SUCCESS
    assert result.metadata["attempts"] == 2


@pytest.mark.asyncio
async def test_trace_reconstructs_complete_two_attempt_chain(tmp_path: Path) -> None:
    clock = FakeClock()
    runner, _ = executor(clock)
    recorder = TraceRecorder(tmp_path)
    trace_context = TraceContext("run_retry", "fixture", recorder, clock)

    async def operation(attempt):
        if attempt.attempt == 1:
            raise ssl.SSLError("TLS EOF")
        return "ok"

    result = await runner.execute(spec(), operation, trace_context=trace_context)
    events = read_events(recorder, "run_retry")
    assert result.status is ExecutionStatus.SUCCESS
    assert [event.event_type for event in events] == [
        TraceEventType.OPERATION_STARTED,
        TraceEventType.OPERATION_FAILED,
        TraceEventType.RETRY_SCHEDULED,
        TraceEventType.OPERATION_STARTED,
        TraceEventType.OPERATION_SUCCEEDED,
    ]
    starts = [event for event in events if event.event_type is TraceEventType.OPERATION_STARTED]
    assert [event.retry_count for event in starts] == [0, 1]
    assert len({event.span_id for event in starts}) == 2


@pytest.mark.asyncio
async def test_timeout_trace_contains_failed_operation_and_timeout_event(
    tmp_path: Path,
) -> None:
    clock = FakeClock()
    native = TimeoutRule(timeout_ms=1_000, enforcement=TimeoutEnforcement.NATIVE)
    runner, _ = executor(
        clock,
        timeout_policy=TimeoutPolicy(operation_rules={"fixture.operation": native}),
        max_attempts=1,
    )
    recorder = TraceRecorder(tmp_path)
    trace_context = TraceContext("run_timeout", "fixture", recorder, clock)

    async def operation(attempt):
        raise asyncio.TimeoutError("native timeout")

    await runner.execute(spec(), operation, trace_context=trace_context)
    events = read_events(recorder, "run_timeout")
    assert [event.event_type for event in events] == [
        TraceEventType.OPERATION_STARTED,
        TraceEventType.OPERATION_FAILED,
        TraceEventType.TIMEOUT,
    ]
    assert events[-1].output_summary["timeout_source"] == "SDK_TIMEOUT"
