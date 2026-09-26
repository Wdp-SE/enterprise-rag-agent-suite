from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from pydantic import ValidationError

from app.reliability.errors import ErrorCategory, ErrorCode, ExecutionError
from app.reliability.trace import (
    NoopTraceRecorder,
    TraceContext,
    TraceEvent,
    TraceEventType,
    TraceRecorder,
    TraceRecorderError,
    TraceSpanKind,
    TraceStatus,
)


class FakeClock:
    def __init__(self) -> None:
        self.current = datetime(2026, 8, 28, 8, 0, tzinfo=timezone.utc)
        self.elapsed = 100.0

    def now(self) -> datetime:
        return self.current

    def monotonic(self) -> float:
        return self.elapsed

    def advance(self, seconds: float) -> None:
        self.current += timedelta(seconds=seconds)
        self.elapsed += seconds


def read_events(recorder: TraceRecorder, run_id: str) -> list[TraceEvent]:
    return [
        TraceEvent.model_validate_json(line)
        for line in recorder.path_for(run_id).read_text(encoding="utf-8").splitlines()
    ]


def fixture_error() -> ExecutionError:
    return ExecutionError(
        code=ErrorCode.ACCESS_DENIED,
        category=ErrorCategory.SECURITY,
        message="forbidden",
        retryable=False,
        source="fixture",
        operation="get",
    )


def test_trace_span_writes_valid_start_and_success_events(tmp_path: Path) -> None:
    clock = FakeClock()
    recorder = TraceRecorder(tmp_path)
    context = TraceContext("run_fixture", "fixture_workflow", recorder, clock)
    span = context.start_span(TraceSpanKind.RUN, operation="fixture.run")
    clock.advance(1.25)
    span.succeed(output_summary={"count": 2})

    events = read_events(recorder, "run_fixture")
    assert [event.event_type for event in events] == [
        TraceEventType.RUN_STARTED,
        TraceEventType.RUN_SUCCEEDED,
    ]
    assert [event.sequence for event in events] == [1, 2]
    assert events[1].duration_ms == pytest.approx(1250.0)
    assert events[0].span_id == events[1].span_id


def test_failed_span_requires_and_writes_structured_error(tmp_path: Path) -> None:
    recorder = TraceRecorder(tmp_path)
    context = TraceContext("run_failure", "fixture", recorder)
    span = context.start_span(TraceSpanKind.OPERATION, operation="http.get")
    span.fail(fixture_error())
    event = read_events(recorder, "run_failure")[-1]
    assert event.event_type is TraceEventType.OPERATION_FAILED
    assert event.error_code is ErrorCode.ACCESS_DENIED
    assert event.retryable is False


def test_trace_event_rejects_failed_event_without_error() -> None:
    now = datetime.now(timezone.utc)
    with pytest.raises(ValidationError, match="structured error"):
        TraceEvent(
            sequence=1,
            event_id="evt_1234567890abcdef12345678",
            run_id="run_invalid",
            workflow="fixture",
            span_id="span_1234567890abcdef1234",
            event_type=TraceEventType.RUN_FAILED,
            status=TraceStatus.FAILED,
            timestamp=now,
            started_at=now,
            ended_at=now,
            duration_ms=0,
        )


def test_recorder_resumes_append_only_sequence(tmp_path: Path) -> None:
    first = TraceRecorder(tmp_path)
    first_context = TraceContext("run_resume", "fixture", first)
    first_context.start_span(TraceSpanKind.RUN, operation="one").succeed()

    second = TraceRecorder(tmp_path)
    second_context = TraceContext("run_resume", "fixture", second)
    second_context.start_span(TraceSpanKind.OPERATION, operation="two").succeed()
    events = read_events(second, "run_resume")
    assert [event.sequence for event in events] == [1, 2, 3, 4]


def test_trace_sanitizes_prompt_content_credentials_and_url_query(tmp_path: Path) -> None:
    recorder = TraceRecorder(tmp_path)
    context = TraceContext("run_safe", "fixture", recorder)
    span = context.start_span(
        TraceSpanKind.OPERATION,
        operation="safe",
        input_summary={
            "prompt": "full private prompt",
            "authorization": "Bearer auth-secret",
            "nested": {"cookie": "cookie-secret", "password": "password-secret"},
            "url": "https://example.test/a?token=query-secret&x=1",
        },
    )
    span.succeed(
        output_summary={
            "content": "full tool output",
            "note": "API Key=api-secret https://example.test/b?access_token=url-secret",
        }
    )
    raw = recorder.path_for("run_safe").read_text(encoding="utf-8")
    for secret in (
        "full private prompt",
        "auth-secret",
        "cookie-secret",
        "password-secret",
        "query-secret",
        "full tool output",
        "api-secret",
        "url-secret",
    ):
        assert secret not in raw
    events = read_events(recorder, "run_safe")
    assert events[0].input_summary["url"]["host"] == "example.test"
    assert "query" not in events[0].input_summary["url"]


@pytest.mark.parametrize(
    "run_id",
    ["../escape", "a/b", r"a\b", r"C:\absolute", r"\\server\share", "/absolute"],
)
def test_trace_run_id_rejects_path_escape_and_absolute_forms(
    tmp_path: Path, run_id: str
) -> None:
    recorder = TraceRecorder(tmp_path)
    with pytest.raises(TraceRecorderError, match="invalid trace run_id"):
        recorder.path_for(run_id)
    with pytest.raises(TraceRecorderError, match="invalid trace run_id"):
        TraceContext(run_id, "fixture", recorder)


def test_traces_root_must_stay_in_workspace(tmp_path: Path) -> None:
    with pytest.raises(TraceRecorderError, match="workspace-relative"):
        TraceRecorder(tmp_path, traces_root="../outside")
    with pytest.raises(TraceRecorderError, match="workspace-relative"):
        TraceRecorder(tmp_path, traces_root=tmp_path.resolve())


class FailingRecorder(TraceRecorder):
    def _append_line(self, target: Path, line: str) -> None:
        raise OSError("Authorization: Bearer should-not-leak")


def test_strict_trace_write_failure_raises_trace_recorder_error(tmp_path: Path) -> None:
    recorder = FailingRecorder(tmp_path, best_effort=False)
    context = TraceContext("run_strict", "fixture", recorder)
    with pytest.raises(TraceRecorderError, match="trace write failed") as caught:
        context.start_span(TraceSpanKind.RUN, operation="fixture")
    assert "should-not-leak" not in str(caught.value)
    assert recorder.healthy is False


def test_best_effort_trace_failure_is_detectable_without_raising(tmp_path: Path) -> None:
    recorder = FailingRecorder(tmp_path, best_effort=True)
    context = TraceContext("run_best_effort", "fixture", recorder)
    span = context.start_span(TraceSpanKind.RUN, operation="fixture")
    span.succeed()
    assert recorder.healthy is False
    assert len(recorder.errors) == 2
    assert isinstance(recorder.last_error, TraceRecorderError)


def test_noop_recorder_produces_no_file(tmp_path: Path) -> None:
    context = TraceContext("run_noop", "fixture", NoopTraceRecorder())
    context.start_span(TraceSpanKind.RUN, operation="fixture").succeed()
    assert not (tmp_path / "traces").exists()


def test_context_manager_records_unhandled_exception(tmp_path: Path) -> None:
    recorder = TraceRecorder(tmp_path)
    context = TraceContext("run_exception", "fixture", recorder)
    with pytest.raises(RuntimeError, match="boom"):
        with context.start_span(TraceSpanKind.OPERATION, operation="explode"):
            raise RuntimeError("boom")
    event = read_events(recorder, "run_exception")[-1]
    assert event.event_type is TraceEventType.OPERATION_FAILED
    assert event.error_code is ErrorCode.INTERNAL_ERROR


def test_concurrent_records_have_monotonic_unique_sequences(tmp_path: Path) -> None:
    recorder = TraceRecorder(tmp_path)
    context = TraceContext("run_threads", "fixture", recorder)

    def write(index: int) -> None:
        span = context.start_span(
            TraceSpanKind.OPERATION,
            operation=f"fixture.{index}",
            input_summary={"index": index},
        )
        span.succeed(output_summary={"index": index})

    with ThreadPoolExecutor(max_workers=5) as executor:
        list(executor.map(write, range(10)))

    events = read_events(recorder, "run_threads")
    sequences = [event.sequence for event in events]
    assert sequences == list(range(1, 21))
    assert len({event.event_id for event in events}) == 20


def test_trace_defines_future_events_without_emitting_behavior(tmp_path: Path) -> None:
    assert TraceEventType.RETRY_SCHEDULED.value == "RETRY_SCHEDULED"
    assert TraceEventType.TIMEOUT.value == "TIMEOUT"
    assert TraceEventType.NO_PROGRESS.value == "NO_PROGRESS"
    assert TraceEventType.BUDGET_EXCEEDED.value == "BUDGET_EXCEEDED"
    assert TraceEventType.POLICY_DENIED.value == "POLICY_DENIED"
    assert not (tmp_path / "traces").exists()
