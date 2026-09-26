"""Append-only structured execution traces, independent from application logging."""

from __future__ import annotations

import hashlib
import json
import os
import re
import threading
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from time import monotonic
from typing import Any, Literal, Protocol

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.reliability.errors import (
    ErrorCategory,
    ErrorClassifier,
    ErrorCode,
    ExecutionError,
    SensitiveDataSanitizer,
)


_RUN_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,127}$")
_SPAN_ID_PATTERN = re.compile(r"^span_[0-9a-f]{20}$")
_EVENT_ID_PATTERN = re.compile(r"^evt_[0-9a-f]{24}$")


class TraceRecorderError(RuntimeError):
    """Raised or exposed through recorder health when a trace cannot be persisted."""


class TraceEventType(str, Enum):
    RUN_STARTED = "RUN_STARTED"
    RUN_SUCCEEDED = "RUN_SUCCEEDED"
    RUN_FAILED = "RUN_FAILED"
    STAGE_STARTED = "STAGE_STARTED"
    STAGE_SUCCEEDED = "STAGE_SUCCEEDED"
    STAGE_FAILED = "STAGE_FAILED"
    OPERATION_STARTED = "OPERATION_STARTED"
    OPERATION_SUCCEEDED = "OPERATION_SUCCEEDED"
    OPERATION_FAILED = "OPERATION_FAILED"
    RETRY_SCHEDULED = "RETRY_SCHEDULED"
    TIMEOUT = "TIMEOUT"
    NO_PROGRESS = "NO_PROGRESS"
    BUDGET_CONSUMED = "BUDGET_CONSUMED"
    BUDGET_EXCEEDED = "BUDGET_EXCEEDED"
    POLICY_DECISION = "POLICY_DECISION"
    POLICY_DENIED = "POLICY_DENIED"


class TraceStatus(str, Enum):
    STARTED = "STARTED"
    SUCCESS = "SUCCESS"
    PARTIAL = "PARTIAL"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


class TraceSpanKind(str, Enum):
    RUN = "RUN"
    STAGE = "STAGE"
    OPERATION = "OPERATION"


class Clock(Protocol):
    def now(self) -> datetime: ...

    def monotonic(self) -> float: ...


class SystemClock:
    def now(self) -> datetime:
        return datetime.now(timezone.utc)

    def monotonic(self) -> float:
        return monotonic()


class TraceSanitizer(SensitiveDataSanitizer):
    """Trace-specific name for the shared recursive safety sanitizer."""

    def __init__(self) -> None:
        super().__init__(max_text_length=512, max_collection_items=50)


_TRACE_SANITIZER = TraceSanitizer()


def validate_trace_run_id(run_id: str) -> str:
    candidate = str(run_id).strip()
    path = Path(candidate)
    if (
        not _RUN_ID_PATTERN.fullmatch(candidate)
        or path.is_absolute()
        or bool(path.drive)
        or candidate.startswith(("\\\\", "//"))
        or "/" in candidate
        or "\\" in candidate
        or ".." in candidate
    ):
        raise TraceRecorderError("invalid trace run_id")
    return candidate


class TraceEvent(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)

    schema_version: Literal["1.0"] = "1.0"
    sequence: int = Field(ge=1)
    event_id: str = Field(pattern=_EVENT_ID_PATTERN.pattern)

    run_id: str
    workflow: str = Field(min_length=1, max_length=128)
    stage: str | None = Field(default=None, max_length=128)
    step_id: str | None = Field(default=None, max_length=128)

    span_id: str = Field(pattern=_SPAN_ID_PATTERN.pattern)
    parent_span_id: str | None = Field(default=None, pattern=_SPAN_ID_PATTERN.pattern)

    event_type: TraceEventType
    status: TraceStatus

    tool_name: str | None = Field(default=None, max_length=128)
    tool_call_id: str | None = Field(default=None, max_length=128)
    operation: str | None = Field(default=None, max_length=128)

    timestamp: datetime
    started_at: datetime | None = None
    ended_at: datetime | None = None
    duration_ms: float | None = Field(default=None, ge=0)

    error_code: ErrorCode | None = None
    error_category: ErrorCategory | None = None
    retryable: bool | None = None
    retry_count: int = Field(default=0, ge=0)

    input_summary: dict[str, Any] = Field(default_factory=dict)
    output_summary: dict[str, Any] = Field(default_factory=dict)
    token_usage: dict[str, Any] = Field(default_factory=dict)

    @field_validator("run_id")
    @classmethod
    def safe_run_id(cls, value: str) -> str:
        return validate_trace_run_id(value)

    @field_validator(
        "workflow",
        "stage",
        "step_id",
        "tool_name",
        "tool_call_id",
        "operation",
        mode="before",
    )
    @classmethod
    def sanitize_labels(cls, value: Any) -> Any:
        if value is None:
            return None
        return _TRACE_SANITIZER.sanitize_text(str(value))

    @field_validator("timestamp", "started_at", "ended_at")
    @classmethod
    def timezone_required(cls, value: datetime | None) -> datetime | None:
        if value is not None and (value.tzinfo is None or value.utcoffset() is None):
            raise ValueError("trace timestamps must include a timezone")
        return value

    @field_validator("input_summary", "output_summary", "token_usage", mode="before")
    @classmethod
    def sanitize_summaries(cls, value: Any) -> dict[str, Any]:
        if value is None:
            return {}
        if not isinstance(value, dict):
            value = {"value": value}
        return _TRACE_SANITIZER.sanitize(value)

    @model_validator(mode="after")
    def validate_event_semantics(self) -> "TraceEvent":
        if self.event_type.value.endswith("_STARTED") and self.status is not TraceStatus.STARTED:
            raise ValueError("started event must have STARTED status")
        if self.event_type.value.endswith("_FAILED"):
            if self.status not in {TraceStatus.FAILED, TraceStatus.CANCELLED}:
                raise ValueError("failed event must have FAILED or CANCELLED status")
            if self.error_code is None or self.error_category is None:
                raise ValueError("failed event requires structured error fields")
        if self.event_type.value.endswith("_SUCCEEDED") and self.status not in {
            TraceStatus.SUCCESS,
            TraceStatus.PARTIAL,
        }:
            raise ValueError("succeeded event must have SUCCESS or PARTIAL status")
        if self.ended_at is not None and self.started_at is None:
            raise ValueError("ended event requires started_at")
        if self.started_at is not None and self.ended_at is not None and self.ended_at < self.started_at:
            raise ValueError("ended_at cannot precede started_at")
        return self


class TraceRecorderProtocol(Protocol):
    best_effort: bool

    def record(self, **event_fields: Any) -> TraceEvent | None: ...

    @property
    def healthy(self) -> bool: ...

    @property
    def errors(self) -> tuple[TraceRecorderError, ...]: ...


class TraceRecorder:
    """Append one validated JSON object per line under a workspace trace root."""

    def __init__(
        self,
        workspace_root: str | Path,
        *,
        traces_root: str | Path = "traces",
        best_effort: bool = True,
    ) -> None:
        self.workspace_root = Path(workspace_root).resolve()
        relative_root = Path(traces_root)
        if relative_root.is_absolute() or relative_root.drive or ".." in relative_root.parts:
            raise TraceRecorderError("traces_root must be workspace-relative")
        requested_root = self.workspace_root / relative_root
        if requested_root.exists() and requested_root.is_symlink():
            raise TraceRecorderError("traces_root cannot be a symlink")
        self.traces_root = requested_root.resolve()
        if not self.traces_root.is_relative_to(self.workspace_root):
            raise TraceRecorderError("traces_root escapes workspace_root")
        if self.traces_root.exists() and self.traces_root.is_symlink():
            raise TraceRecorderError("traces_root cannot be a symlink")
        self.best_effort = best_effort
        self._lock = threading.RLock()
        self._sequences: dict[str, int] = {}
        self._errors: list[TraceRecorderError] = []

    @property
    def healthy(self) -> bool:
        return not self._errors

    @property
    def errors(self) -> tuple[TraceRecorderError, ...]:
        return tuple(self._errors)

    @property
    def last_error(self) -> TraceRecorderError | None:
        return self._errors[-1] if self._errors else None

    def path_for(self, run_id: str) -> Path:
        safe_id = validate_trace_run_id(run_id)
        requested_target = self.traces_root / f"{safe_id}.jsonl"
        if requested_target.exists() and requested_target.is_symlink():
            raise TraceRecorderError("trace file cannot be a symlink")
        target = requested_target.resolve()
        if not target.is_relative_to(self.traces_root):
            raise TraceRecorderError("trace path escapes traces_root")
        if target.exists() and target.is_symlink():
            raise TraceRecorderError("trace file cannot be a symlink")
        return target

    def _existing_sequence(self, run_id: str, target: Path) -> int:
        if not target.exists():
            return 0
        maximum = 0
        try:
            for line in target.read_text(encoding="utf-8").splitlines():
                if not line.strip():
                    continue
                event = TraceEvent.model_validate_json(line)
                if event.run_id != run_id or event.sequence <= maximum:
                    raise TraceRecorderError("existing trace has an invalid sequence")
                maximum = event.sequence
        except TraceRecorderError:
            raise
        except (OSError, UnicodeDecodeError, ValueError) as exc:
            raise TraceRecorderError(f"cannot resume existing trace: {type(exc).__name__}") from exc
        return maximum

    def _next_sequence(self, run_id: str, target: Path) -> int:
        if run_id not in self._sequences:
            self._sequences[run_id] = self._existing_sequence(run_id, target)
        self._sequences[run_id] += 1
        return self._sequences[run_id]

    def _append_line(self, target: Path, line: str) -> None:
        self.traces_root.mkdir(parents=True, exist_ok=True)
        if self.traces_root.is_symlink() or (target.exists() and target.is_symlink()):
            raise TraceRecorderError("unsafe trace storage path")
        with target.open("a", encoding="utf-8", newline="\n") as stream:
            stream.write(line)
            stream.flush()
            os.fsync(stream.fileno())

    def record(self, **event_fields: Any) -> TraceEvent | None:
        try:
            with self._lock:
                run_id = validate_trace_run_id(event_fields["run_id"])
                target = self.path_for(run_id)
                sequence = self._next_sequence(run_id, target)
                event_id = hashlib.sha256(f"{run_id}|{sequence}".encode()).hexdigest()[:24]
                event = TraceEvent(
                    **event_fields,
                    sequence=sequence,
                    event_id=f"evt_{event_id}",
                )
                line = json.dumps(
                    event.model_dump(mode="json"),
                    ensure_ascii=False,
                    sort_keys=True,
                    separators=(",", ":"),
                ) + "\n"
                self._append_line(target, line)
                return event
        except Exception as exc:
            recorder_error = exc if isinstance(exc, TraceRecorderError) else TraceRecorderError(
                f"trace write failed: {type(exc).__name__}"
            )
            self._errors.append(recorder_error)
            if not self.best_effort:
                raise recorder_error from exc
            return None


class NoopTraceRecorder:
    """Drop all events while preserving the integration call contract."""

    best_effort = True

    @property
    def healthy(self) -> bool:
        return True

    @property
    def errors(self) -> tuple[TraceRecorderError, ...]:
        return ()

    @property
    def last_error(self) -> None:
        return None

    def record(self, **event_fields: Any) -> None:
        return None


@dataclass
class TraceContext:
    run_id: str
    workflow: str
    recorder: TraceRecorderProtocol = field(default_factory=NoopTraceRecorder)
    clock: Clock = field(default_factory=SystemClock)
    _span_counter: int = field(default=0, init=False, repr=False)
    _lock: threading.Lock = field(default_factory=threading.Lock, init=False, repr=False)

    def __post_init__(self) -> None:
        self.run_id = validate_trace_run_id(self.run_id)
        if not str(self.workflow).strip():
            raise ValueError("workflow cannot be blank")

    def _next_span_id(self, label: str) -> str:
        with self._lock:
            self._span_counter += 1
            digest = hashlib.sha256(
                f"{self.run_id}|{self._span_counter}|{label}".encode("utf-8")
            ).hexdigest()[:20]
        return f"span_{digest}"

    def allocate_span_id(self, label: str) -> str:
        """Allocate a valid span identifier for a non-span structured event."""

        return self._next_span_id(label)

    def emit(self, **event_fields: Any) -> TraceEvent | None:
        return self.recorder.record(
            run_id=self.run_id,
            workflow=self.workflow,
            timestamp=self.clock.now(),
            **event_fields,
        )

    def start_span(
        self,
        kind: TraceSpanKind,
        *,
        stage: str | None = None,
        step_id: str | None = None,
        parent_span_id: str | None = None,
        tool_name: str | None = None,
        tool_call_id: str | None = None,
        operation: str | None = None,
        input_summary: dict[str, Any] | None = None,
        retry_count: int = 0,
    ) -> "TraceSpan":
        return TraceSpan(
            context=self,
            kind=kind,
            span_id=self._next_span_id(operation or stage or kind.value),
            stage=stage,
            step_id=step_id,
            parent_span_id=parent_span_id,
            tool_name=tool_name,
            tool_call_id=tool_call_id,
            operation=operation,
            input_summary=input_summary or {},
            retry_count=retry_count,
        )


@dataclass
class TraceSpan:
    context: TraceContext
    kind: TraceSpanKind
    span_id: str
    stage: str | None
    step_id: str | None
    parent_span_id: str | None
    tool_name: str | None
    tool_call_id: str | None
    operation: str | None
    input_summary: dict[str, Any]
    retry_count: int = 0
    _started_at: datetime = field(init=False)
    _started_monotonic: float = field(init=False)
    _ended: bool = field(default=False, init=False)

    def __post_init__(self) -> None:
        self._started_at = self.context.clock.now()
        self._started_monotonic = self.context.clock.monotonic()
        self.context.emit(
            event_type=TraceEventType[f"{self.kind.value}_STARTED"],
            status=TraceStatus.STARTED,
            stage=self.stage,
            step_id=self.step_id,
            span_id=self.span_id,
            parent_span_id=self.parent_span_id,
            tool_name=self.tool_name,
            tool_call_id=self.tool_call_id,
            operation=self.operation,
            started_at=self._started_at,
            retry_count=self.retry_count,
            input_summary=self.input_summary,
        )

    def __enter__(self) -> "TraceSpan":
        return self

    def __exit__(self, exc_type, exc, traceback) -> bool:
        if self._ended:
            return False
        if exc is None:
            self.succeed()
        else:
            error = ErrorClassifier().classify(
                exc,
                source=self.tool_name or self.context.workflow,
                operation=self.operation or self.kind.value.casefold(),
            )
            self.fail(error)
        return False

    @property
    def ended(self) -> bool:
        return self._ended

    def succeed(
        self,
        *,
        status: TraceStatus = TraceStatus.SUCCESS,
        output_summary: dict[str, Any] | None = None,
        token_usage: dict[str, Any] | None = None,
    ) -> TraceEvent | None:
        if status not in {TraceStatus.SUCCESS, TraceStatus.PARTIAL}:
            raise ValueError("successful span status must be SUCCESS or PARTIAL")
        return self._finish(
            event_type=TraceEventType[f"{self.kind.value}_SUCCEEDED"],
            status=status,
            output_summary=output_summary or {},
            token_usage=token_usage or {},
        )

    def fail(
        self,
        error: ExecutionError,
        *,
        status: TraceStatus = TraceStatus.FAILED,
        output_summary: dict[str, Any] | None = None,
    ) -> TraceEvent | None:
        if status not in {TraceStatus.FAILED, TraceStatus.CANCELLED}:
            raise ValueError("failed span status must be FAILED or CANCELLED")
        return self._finish(
            event_type=TraceEventType[f"{self.kind.value}_FAILED"],
            status=status,
            error=error,
            output_summary=output_summary or {},
        )

    def _finish(
        self,
        *,
        event_type: TraceEventType,
        status: TraceStatus,
        error: ExecutionError | None = None,
        output_summary: dict[str, Any],
        token_usage: dict[str, Any] | None = None,
    ) -> TraceEvent | None:
        if self._ended:
            raise RuntimeError("trace span is already complete")
        ended_at = self.context.clock.now()
        duration_ms = max(
            0.0,
            (self.context.clock.monotonic() - self._started_monotonic) * 1000,
        )
        self._ended = True
        return self.context.emit(
            event_type=event_type,
            status=status,
            stage=self.stage,
            step_id=self.step_id,
            span_id=self.span_id,
            parent_span_id=self.parent_span_id,
            tool_name=self.tool_name,
            tool_call_id=self.tool_call_id,
            operation=self.operation,
            started_at=self._started_at,
            ended_at=ended_at,
            duration_ms=duration_ms,
            error_code=error.code if error else None,
            error_category=error.category if error else None,
            retryable=error.retryable if error else None,
            retry_count=self.retry_count,
            output_summary=output_summary,
            token_usage=token_usage or {},
        )
