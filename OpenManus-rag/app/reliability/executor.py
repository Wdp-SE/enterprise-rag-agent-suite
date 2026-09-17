"""Explicit opt-in execution of one operation under timeout and retry policies."""

from __future__ import annotations

import asyncio
import inspect
from dataclasses import dataclass
from enum import Enum
from typing import Any, Awaitable, Callable, Generic, TypeVar

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.reliability.budget import (
    BudgetDimension,
    BudgetExceededError,
    BudgetLedger,
    BudgetPreview,
    BudgetReservation,
)
from app.reliability.errors import ErrorClassifier, ErrorCode, ExecutionError
from app.reliability.result import ExecutionResult, ExecutionStatus
from app.reliability.retry import (
    AsyncioSleeper,
    RandomSource,
    RetryContext,
    RetryOwner,
    RetryPolicy,
    SideEffectLevel,
    Sleeper,
    SystemRandomSource,
    parse_retry_after_ms,
)
from app.reliability.timeout import (
    TimeoutEnforcement,
    TimeoutPolicy,
    TimeoutResolution,
    TimeoutResolver,
)
from app.reliability.trace import (
    Clock,
    SystemClock,
    TraceContext,
    TraceEventType,
    TraceSpan,
    TraceSpanKind,
    TraceStatus,
)


T = TypeVar("T")


class DeadlineSource(str, Enum):
    STAGE_DEADLINE = "STAGE_DEADLINE"
    WORKFLOW_DEADLINE = "WORKFLOW_DEADLINE"
    CALLER_DEADLINE = "CALLER_DEADLINE"
    EXECUTION_BUDGET = "EXECUTION_BUDGET"


class OperationSpec(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)

    name: str = Field(min_length=1, max_length=128)
    idempotent: bool
    side_effect_level: SideEffectLevel
    retry_owner: RetryOwner = RetryOwner.NONE
    tool_name: str | None = Field(default=None, max_length=128)
    stage: str | None = Field(default=None, max_length=128)
    workflow: str | None = Field(default=None, max_length=128)
    budget_costs: dict[BudgetDimension, int] = Field(default_factory=dict)
    budget_observational_dimensions: frozenset[BudgetDimension] = Field(
        default_factory=frozenset
    )

    @model_validator(mode="after")
    def validate_idempotency_metadata(self) -> "OperationSpec":
        if self.side_effect_level is SideEffectLevel.READ_ONLY and not self.idempotent:
            raise ValueError("READ_ONLY operation must be idempotent")
        if self.side_effect_level is SideEffectLevel.IDEMPOTENT_WRITE and not self.idempotent:
            raise ValueError("IDEMPOTENT_WRITE operation must be idempotent")
        if self.side_effect_level is SideEffectLevel.NON_IDEMPOTENT and self.idempotent:
            raise ValueError("NON_IDEMPOTENT operation cannot be marked idempotent")
        if any(amount <= 0 for amount in self.budget_costs.values()):
            raise ValueError("budget costs must be positive")
        overlap = set(self.budget_costs).intersection(
            self.budget_observational_dimensions
        )
        if overlap:
            raise ValueError(
                "a budget dimension cannot be both reserved and observational"
            )
        return self


class OperationDeadline(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    expires_at_monotonic: float
    source: DeadlineSource

    @classmethod
    def after(
        cls,
        clock: Clock,
        timeout_ms: int,
        *,
        source: DeadlineSource,
    ) -> "OperationDeadline":
        if timeout_ms <= 0:
            raise ValueError("deadline timeout_ms must be positive")
        return cls(
            expires_at_monotonic=clock.monotonic() + (timeout_ms / 1000),
            source=source,
        )


@dataclass(frozen=True)
class OperationAttempt:
    attempt: int
    max_attempts: int
    timeout: TimeoutResolution
    deadline: OperationDeadline | None


Cleanup = Callable[[OperationAttempt, ExecutionError], Awaitable[None] | None]
Operation = Callable[[OperationAttempt], Awaitable[T]]
OutputSummarizer = Callable[[T], dict[str, Any]]
TokenUsageSummarizer = Callable[[T], dict[str, Any]]


class ReliableOperationExecutor(Generic[T]):
    def __init__(
        self,
        *,
        timeout_policy: TimeoutPolicy | None = None,
        retry_policy: RetryPolicy | None = None,
        classifier: ErrorClassifier | None = None,
        sleeper: Sleeper | None = None,
        random_source: RandomSource | None = None,
        clock: Clock | None = None,
        budget_ledger: BudgetLedger | None = None,
    ) -> None:
        self.timeout_policy = timeout_policy or TimeoutPolicy.disabled()
        self.timeout_resolver = TimeoutResolver(self.timeout_policy)
        self.retry_policy = retry_policy or RetryPolicy.disabled()
        self.classifier = classifier or ErrorClassifier()
        self.sleeper = sleeper or AsyncioSleeper()
        self.random_source = random_source or SystemRandomSource()
        self.budget_ledger = budget_ledger
        # A task-wide duration deadline and an operation deadline must share
        # the same monotonic origin. Explicit caller clocks still take
        # precedence; otherwise inherit the ledger's clock.
        self.clock = (
            clock
            or (budget_ledger.clock if budget_ledger is not None else None)
            or SystemClock()
        )

    async def execute(
        self,
        spec: OperationSpec,
        operation: Operation[T],
        *,
        trace_context: TraceContext | None = None,
        parent_span_id: str | None = None,
        tool_call_id: str | None = None,
        input_summary: dict[str, Any] | None = None,
        output_summarizer: OutputSummarizer[T] | None = None,
        token_usage_summarizer: TokenUsageSummarizer[T] | None = None,
        cleanup: Cleanup | None = None,
        deadline: OperationDeadline | None = None,
    ) -> ExecutionResult[T]:
        timeout = self.timeout_resolver.resolve(
            operation=spec.name,
            tool_name=spec.tool_name,
            stage=spec.stage,
            workflow=spec.workflow,
        )
        retry_rule = self.retry_policy.resolve(spec.name)
        # Delegated and non-retried operations are deliberately single-call at
        # this layer, even if a broad policy rule happens to match their name.
        # Their inner owner may still perform its own attempts/fallbacks.
        effective_max_attempts = (
            retry_rule.max_attempts
            if spec.retry_owner is RetryOwner.RELIABILITY
            else 1
        )
        errors: list[ExecutionError] = []
        attempt_history: list[dict[str, Any]] = []

        for attempt_number in range(1, effective_max_attempts + 1):
            effective_deadline = self._effective_deadline(deadline)
            attempt = OperationAttempt(
                attempt=attempt_number,
                max_attempts=effective_max_attempts,
                timeout=timeout,
                deadline=effective_deadline,
            )
            span = self._start_attempt_span(
                spec,
                attempt,
                trace_context=trace_context,
                parent_span_id=parent_span_id,
                tool_call_id=tool_call_id,
                input_summary=input_summary,
            )
            reservation: BudgetReservation | None = None
            attempt_costs = self._attempt_budget_costs(spec, attempt_number)
            if self.budget_ledger is not None:
                try:
                    reservation = self.budget_ledger.reserve(
                        attempt_costs,
                        observational_dimensions=(
                            spec.budget_observational_dimensions
                        ),
                        operation=spec.name,
                        attempt=attempt_number,
                        trace_context=trace_context,
                        span_id=span.span_id if span is not None else None,
                        parent_span_id=(
                            span.parent_span_id if span is not None else parent_span_id
                        ),
                        stage=spec.stage,
                        tool_name=spec.tool_name,
                    )
                except BudgetExceededError as exc:
                    error = exc.error
                    errors.append(error)
                    attempt_history.append(
                        {
                            "attempt": attempt_number,
                            "status": "REJECTED",
                            "error_code": error.code.value,
                        }
                    )
                    self._fail_span(span, error)
                    return ExecutionResult(
                        status=ExecutionStatus.FAILED,
                        errors=tuple(errors),
                        metadata={
                            **self._metadata(
                                spec, attempt_number, timeout, attempt_history
                            ),
                            "retry_stop_reason": (
                                "execution budget exhausted: "
                                f"{error.details.get('dimension', 'UNKNOWN')}"
                            ),
                            "budget_snapshot": exc.snapshot.model_dump(mode="json"),
                        },
                    )
                except Exception as exc:
                    accounting_error = self._accounting_error(spec, exc)
                    errors.append(accounting_error)
                    attempt_history.append(
                        {
                            "attempt": attempt_number,
                            "status": "REJECTED",
                            "error_code": accounting_error.code.value,
                        }
                    )
                    self._fail_span(span, accounting_error)
                    return ExecutionResult(
                        status=ExecutionStatus.FAILED,
                        errors=tuple(errors),
                        metadata={
                            **self._metadata(
                                spec, attempt_number, timeout, attempt_history
                            ),
                            "retry_stop_reason": "budget accounting failed",
                        },
                    )

            operation_started = False

            async def tracked_operation(current_attempt: OperationAttempt) -> T:
                nonlocal operation_started
                operation_started = True
                return await operation(current_attempt)

            started_monotonic = self.clock.monotonic()
            try:
                value = await self._execute_attempt(
                    tracked_operation,
                    attempt,
                    deadline=effective_deadline,
                )
            except asyncio.CancelledError as exc:
                error = self.classifier.classify(
                    exc,
                    source=spec.tool_name or spec.workflow or "reliability",
                    operation=spec.name,
                )
                accounting_error = self._settle_failed_attempt(
                    spec,
                    attempt,
                    reservation,
                    operation_started=operation_started,
                    trace_context=trace_context,
                    span=span,
                    parent_span_id=parent_span_id,
                )
                await self._cleanup(cleanup, attempt, error)
                self._fail_span(span, error, cancelled=True)
                return ExecutionResult(
                    status=ExecutionStatus.CANCELLED,
                    errors=(error,) + ((accounting_error,) if accounting_error else ()),
                    metadata=self._metadata(spec, attempt_number, timeout, attempt_history),
                )
            except Exception as exc:
                elapsed_ms = max(0, round((self.clock.monotonic() - started_monotonic) * 1000))
                timeout_source = getattr(exc, "_reliability_timeout_source", None)
                error = self.classifier.classify(
                    exc,
                    source=spec.tool_name or spec.workflow or "reliability",
                    operation=spec.name,
                )
                accounting_error = self._settle_failed_attempt(
                    spec,
                    attempt,
                    reservation,
                    operation_started=operation_started,
                    trace_context=trace_context,
                    span=span,
                    parent_span_id=parent_span_id,
                )
                if timeout_source == DeadlineSource.EXECUTION_BUDGET.value:
                    if (
                        accounting_error is not None
                        and accounting_error.code is ErrorCode.BUDGET_EXCEEDED
                    ):
                        error = accounting_error
                        accounting_error = None
                    elif self.budget_ledger is not None:
                        budget_failure = self.budget_ledger.exceeded_error(
                            BudgetDimension.DURATION_MS,
                            requested=elapsed_ms,
                            operation=spec.name,
                            attempt=attempt_number,
                            phase="INFLIGHT",
                            reason="execution duration budget deadline reached",
                            trace_context=trace_context,
                            span_id=span.span_id if span is not None else None,
                            parent_span_id=(
                                span.parent_span_id
                                if span is not None
                                else parent_span_id
                            ),
                            stage=spec.stage,
                            tool_name=spec.tool_name,
                        )
                        error = budget_failure.error
                elif error.code is ErrorCode.OPERATION_TIMEOUT:
                    if timeout_source is None:
                        timeout_source = (
                            "SDK_TIMEOUT"
                            if timeout.rule.enforcement is TimeoutEnforcement.NATIVE
                            else effective_deadline.source.value
                            if effective_deadline is not None
                            else "ASYNCIO_TIMEOUT"
                        )
                    captured_timeout_ms = getattr(
                        exc, "_reliability_timeout_ms", None
                    )
                    error = self._timeout_error(
                        error,
                        spec=spec,
                        timeout=timeout,
                        timeout_source=timeout_source,
                        effective_timeout_ms=(
                            captured_timeout_ms
                            if captured_timeout_ms is not None
                            else timeout.rule.timeout_ms
                        ),
                        elapsed_ms=elapsed_ms,
                    )
                await self._cleanup(cleanup, attempt, error)
                errors.append(error)
                if accounting_error is not None:
                    errors.append(accounting_error)
                attempt_history.append(
                    {
                        "attempt": attempt_number,
                        "status": "FAILED",
                        "error_code": error.code.value,
                    }
                )
                self._fail_span(span, error)
                if (
                    error.code is ErrorCode.OPERATION_TIMEOUT
                    and timeout_source != DeadlineSource.EXECUTION_BUDGET.value
                ):
                    self._emit_timeout(
                        trace_context,
                        span,
                        spec,
                        attempt,
                        error,
                        elapsed_ms,
                    )
                if accounting_error is not None or error.code is ErrorCode.BUDGET_EXCEEDED:
                    return ExecutionResult(
                        status=ExecutionStatus.FAILED,
                        errors=tuple(errors),
                        metadata={
                            **self._metadata(
                                spec, attempt_number, timeout, attempt_history
                            ),
                            "retry_stop_reason": (
                                "budget accounting failed"
                                if accounting_error is not None
                                and accounting_error.code is not ErrorCode.BUDGET_EXCEEDED
                                else "execution budget exhausted"
                            ),
                        },
                    )
                retry_after_ms = parse_retry_after_ms(
                    error.details.get("retry_after"),
                    now=self.clock.now(),
                )
                budget_preview = self._preview_next_attempt(
                    spec,
                    attempt_number + 1,
                )
                decision = self.retry_policy.decide(
                    error,
                    RetryContext(
                        operation=spec.name,
                        attempt=attempt_number,
                        idempotent=spec.idempotent,
                        side_effect_level=spec.side_effect_level,
                        retry_owner=spec.retry_owner,
                        now_monotonic=self.clock.monotonic(),
                        deadline_monotonic=(
                            deadline.expires_at_monotonic if deadline else None
                        ),
                        retry_after_ms=retry_after_ms,
                        budget_allows_retry=(
                            budget_preview.allowed if budget_preview is not None else True
                        ),
                        budget_stop_dimension=(
                            budget_preview.stop_dimension
                            if budget_preview is not None
                            else None
                        ),
                        budget_duration_remaining_ms=(
                            budget_preview.duration_remaining_ms
                            if budget_preview is not None
                            else None
                        ),
                    ),
                    random_source=self.random_source,
                )
                if not decision.should_retry:
                    return ExecutionResult(
                        status=ExecutionStatus.FAILED,
                        errors=tuple(errors),
                        metadata={
                            **self._metadata(
                                spec, attempt_number, timeout, attempt_history
                            ),
                            "retry_stop_reason": decision.reason,
                        },
                    )
                self._emit_retry(
                    trace_context,
                    span,
                    spec,
                    attempt,
                    error,
                    decision.model_dump(mode="json"),
                )
                await self.sleeper.sleep(decision.delay_ms / 1000)
                continue

            token_usage: dict[str, Any] | None = None
            try:
                token_usage = (
                    token_usage_summarizer(value)
                    if token_usage_summarizer is not None
                    else None
                )
            except Exception as exc:
                error = self._accounting_error(spec, exc)
                settlement_error = self._settle_failed_attempt(
                    spec,
                    attempt,
                    reservation,
                    operation_started=True,
                    trace_context=trace_context,
                    span=span,
                    parent_span_id=parent_span_id,
                )
                errors.append(error)
                if settlement_error is not None:
                    errors.append(settlement_error)
                attempt_history.append(
                    {
                        "attempt": attempt_number,
                        "status": "PARTIAL",
                        "error_code": error.code.value,
                    }
                )
                self._fail_span(span, error)
                return ExecutionResult(
                    status=ExecutionStatus.PARTIAL,
                    value=value,
                    errors=tuple(errors),
                    metadata={
                        **self._metadata(
                            spec, attempt_number, timeout, attempt_history
                        ),
                        "retry_stop_reason": "token usage accounting failed postflight",
                    },
                )
            try:
                self._settle_successful_attempt(
                    spec,
                    attempt,
                    reservation,
                    token_usage=token_usage,
                    trace_context=trace_context,
                    span=span,
                    parent_span_id=parent_span_id,
                )
            except BudgetExceededError as exc:
                error = exc.error
                errors.append(error)
                attempt_history.append(
                    {
                        "attempt": attempt_number,
                        "status": "PARTIAL",
                        "error_code": error.code.value,
                    }
                )
                self._fail_span(span, error)
                return ExecutionResult(
                    status=ExecutionStatus.PARTIAL,
                    value=value,
                    errors=tuple(errors),
                    metadata={
                        **self._metadata(
                            spec, attempt_number, timeout, attempt_history
                        ),
                        "retry_stop_reason": "execution budget exhausted postflight",
                        "budget_snapshot": exc.snapshot.model_dump(mode="json"),
                    },
                )
            except Exception as exc:
                error = self._accounting_error(spec, exc)
                errors.append(error)
                attempt_history.append(
                    {
                        "attempt": attempt_number,
                        "status": "PARTIAL",
                        "error_code": error.code.value,
                    }
                )
                self._fail_span(span, error)
                return ExecutionResult(
                    status=ExecutionStatus.PARTIAL,
                    value=value,
                    errors=tuple(errors),
                    metadata={
                        **self._metadata(
                            spec, attempt_number, timeout, attempt_history
                        ),
                        "retry_stop_reason": "budget accounting failed postflight",
                    },
                )

            attempt_history.append({"attempt": attempt_number, "status": "SUCCESS"})
            if span is not None:
                summary = (
                    output_summarizer(value)
                    if output_summarizer is not None
                    else {"type": type(value).__name__}
                )
                span.succeed(output_summary=summary, token_usage=token_usage)
            return ExecutionResult(
                status=ExecutionStatus.SUCCESS,
                value=value,
                metadata=self._metadata(spec, attempt_number, timeout, attempt_history),
            )

        raise AssertionError("retry loop exited without a result")

    @staticmethod
    def _attempt_budget_costs(
        spec: OperationSpec,
        attempt_number: int,
    ) -> dict[BudgetDimension, int]:
        costs = dict(spec.budget_costs)
        costs[BudgetDimension.OPERATION_ATTEMPTS] = (
            costs.get(BudgetDimension.OPERATION_ATTEMPTS, 0) + 1
        )
        if attempt_number > 1:
            costs[BudgetDimension.RETRY_ATTEMPTS] = (
                costs.get(BudgetDimension.RETRY_ATTEMPTS, 0) + 1
            )
        return costs

    def _effective_deadline(
        self,
        caller_deadline: OperationDeadline | None,
    ) -> OperationDeadline | None:
        budget_expiry = (
            self.budget_ledger.duration_deadline_monotonic()
            if self.budget_ledger is not None
            else None
        )
        budget_deadline = (
            OperationDeadline(
                expires_at_monotonic=budget_expiry,
                source=DeadlineSource.EXECUTION_BUDGET,
            )
            if budget_expiry is not None
            else None
        )
        if caller_deadline is None:
            return budget_deadline
        if budget_deadline is None:
            return caller_deadline
        if budget_deadline.expires_at_monotonic < caller_deadline.expires_at_monotonic:
            return budget_deadline
        return caller_deadline

    def _preview_next_attempt(
        self,
        spec: OperationSpec,
        attempt_number: int,
    ) -> BudgetPreview | None:
        if self.budget_ledger is None:
            return None
        return self.budget_ledger.preview(
            self._attempt_budget_costs(spec, attempt_number),
            observational_dimensions=spec.budget_observational_dimensions,
        )

    def _settle_failed_attempt(
        self,
        spec: OperationSpec,
        attempt: OperationAttempt,
        reservation: BudgetReservation | None,
        *,
        operation_started: bool,
        trace_context: TraceContext | None,
        span: TraceSpan | None,
        parent_span_id: str | None,
    ) -> ExecutionError | None:
        if self.budget_ledger is None or reservation is None:
            return None
        try:
            if not operation_started:
                self.budget_ledger.release(reservation)
                return None
            # If a provider failure exposes no trustworthy token usage, strict
            # reservations are conservatively charged at their upper bound.
            # Observational dimensions remain unknown/unaccounted. This avoids
            # silently releasing a hard-limit reservation after a request was
            # actually sent while never inventing a precise API usage value.
            self.budget_ledger.commit(
                reservation,
                trace_context=trace_context,
                span_id=span.span_id if span is not None else None,
                parent_span_id=(
                    span.parent_span_id if span is not None else parent_span_id
                ),
                stage=spec.stage,
                tool_name=spec.tool_name,
            )
            return None
        except BudgetExceededError as exc:
            return exc.error
        except Exception as exc:
            return self._accounting_error(spec, exc)

    def _settle_successful_attempt(
        self,
        spec: OperationSpec,
        attempt: OperationAttempt,
        reservation: BudgetReservation | None,
        *,
        token_usage: dict[str, Any] | None,
        trace_context: TraceContext | None,
        span: TraceSpan | None,
        parent_span_id: str | None,
    ) -> None:
        if self.budget_ledger is None or reservation is None:
            return
        token_dimensions = self._token_dimensions()
        declared_tokens = (
            set(reservation.costs).union(reservation.observational_dimensions)
            & token_dimensions
        )
        actual_usage: dict[BudgetDimension, int] = {}
        if declared_tokens:
            if token_usage is None:
                raise RuntimeError(
                    "token budget dimensions require an actual token usage summarizer"
                )
            key_by_dimension = {
                BudgetDimension.PROMPT_TOKENS: "prompt_tokens",
                BudgetDimension.COMPLETION_TOKENS: "completion_tokens",
                BudgetDimension.TOTAL_TOKENS: "total_tokens",
            }
            for dimension in declared_tokens:
                key = key_by_dimension[dimension]
                if key not in token_usage:
                    raise RuntimeError(f"token usage is missing {key}")
                amount = int(token_usage[key])
                if amount < 0:
                    raise RuntimeError(f"token usage {key} cannot be negative")
                actual_usage[dimension] = amount
        self.budget_ledger.commit(
            reservation,
            actual_usage=actual_usage,
            trace_context=trace_context,
            span_id=span.span_id if span is not None else None,
            parent_span_id=span.parent_span_id if span is not None else parent_span_id,
            stage=spec.stage,
            tool_name=spec.tool_name,
        )

    @staticmethod
    def _token_dimensions() -> frozenset[BudgetDimension]:
        return frozenset(
            {
                BudgetDimension.PROMPT_TOKENS,
                BudgetDimension.COMPLETION_TOKENS,
                BudgetDimension.TOTAL_TOKENS,
            }
        )

    def _accounting_error(
        self,
        spec: OperationSpec,
        error: BaseException,
    ) -> ExecutionError:
        return self.classifier.classify(
            error,
            source="budget_ledger",
            operation=spec.name,
            details={"phase": "ACCOUNTING"},
        )

    async def _execute_attempt(
        self,
        operation: Operation[T],
        attempt: OperationAttempt,
        *,
        deadline: OperationDeadline | None,
    ) -> T:
        outer_timeout_ms: int | None = None
        outer_source: str | None = None
        rule = attempt.timeout.rule
        if rule.enforcement is TimeoutEnforcement.ASYNCIO_FALLBACK:
            outer_timeout_ms = rule.timeout_ms
            outer_source = "ASYNCIO_TIMEOUT"
        if deadline is not None:
            remaining_ms = max(
                0,
                round((deadline.expires_at_monotonic - self.clock.monotonic()) * 1000),
            )
            if outer_timeout_ms is None or remaining_ms < outer_timeout_ms:
                outer_timeout_ms = remaining_ms
                outer_source = deadline.source.value
        if outer_timeout_ms is not None:
            if outer_timeout_ms <= 0:
                error = TimeoutError("operation deadline expired before attempt")
                setattr(error, "_reliability_timeout_source", outer_source)
                setattr(error, "_reliability_timeout_ms", outer_timeout_ms)
                raise error
            try:
                async with asyncio.timeout(outer_timeout_ms / 1000):
                    return await operation(attempt)
            except TimeoutError as exc:
                setattr(exc, "_reliability_timeout_source", outer_source)
                setattr(exc, "_reliability_timeout_ms", outer_timeout_ms)
                raise
        return await operation(attempt)

    @staticmethod
    async def _cleanup(
        cleanup: Cleanup | None,
        attempt: OperationAttempt,
        error: ExecutionError,
    ) -> None:
        if cleanup is None:
            return
        result = cleanup(attempt, error)
        if inspect.isawaitable(result):
            await result

    def _start_attempt_span(
        self,
        spec: OperationSpec,
        attempt: OperationAttempt,
        *,
        trace_context: TraceContext | None,
        parent_span_id: str | None,
        tool_call_id: str | None,
        input_summary: dict[str, Any] | None,
    ) -> TraceSpan | None:
        if trace_context is None:
            return None
        return trace_context.start_span(
            TraceSpanKind.OPERATION,
            stage=spec.stage,
            step_id=f"attempt-{attempt.attempt}",
            parent_span_id=parent_span_id,
            tool_name=spec.tool_name,
            tool_call_id=tool_call_id,
            operation=spec.name,
            retry_count=attempt.attempt - 1,
            input_summary={
                **(input_summary or {}),
                "attempt": attempt.attempt,
                "max_attempts": attempt.max_attempts,
                "timeout_scope": attempt.timeout.scope.value,
                "timeout_ms": attempt.timeout.rule.timeout_ms,
            },
        )

    @staticmethod
    def _fail_span(
        span: TraceSpan | None,
        error: ExecutionError,
        *,
        cancelled: bool = False,
    ) -> None:
        if span is not None:
            span.fail(
                error,
                status=TraceStatus.CANCELLED if cancelled else TraceStatus.FAILED,
            )

    def _emit_timeout(
        self,
        trace_context: TraceContext | None,
        span: TraceSpan | None,
        spec: OperationSpec,
        attempt: OperationAttempt,
        error: ExecutionError,
        elapsed_ms: int,
    ) -> None:
        if trace_context is None or span is None:
            return
        now = self.clock.now()
        trace_context.emit(
            event_type=TraceEventType.TIMEOUT,
            status=TraceStatus.FAILED,
            stage=spec.stage,
            step_id=f"attempt-{attempt.attempt}",
            span_id=span.span_id,
            parent_span_id=span.parent_span_id,
            tool_name=spec.tool_name,
            operation=spec.name,
            started_at=now,
            ended_at=now,
            duration_ms=elapsed_ms,
            error_code=error.code,
            error_category=error.category,
            retryable=error.retryable,
            retry_count=attempt.attempt - 1,
            output_summary={
                "attempt": attempt.attempt,
                "timeout_ms": error.details.get("timeout_ms"),
                "timeout_source": error.details.get("timeout_source"),
            },
        )

    def _emit_retry(
        self,
        trace_context: TraceContext | None,
        span: TraceSpan | None,
        spec: OperationSpec,
        attempt: OperationAttempt,
        error: ExecutionError,
        decision: dict[str, Any],
    ) -> None:
        if trace_context is None or span is None:
            return
        trace_context.emit(
            event_type=TraceEventType.RETRY_SCHEDULED,
            status=TraceStatus.STARTED,
            stage=spec.stage,
            step_id=f"attempt-{attempt.attempt}",
            span_id=span.span_id,
            parent_span_id=span.parent_span_id,
            tool_name=spec.tool_name,
            operation=spec.name,
            error_code=error.code,
            error_category=error.category,
            retryable=error.retryable,
            retry_count=attempt.attempt,
            output_summary={
                "attempt": attempt.attempt,
                "next_attempt": decision["next_attempt"],
                "max_attempts": decision["max_attempts"],
                "delay_ms": decision["delay_ms"],
                "reason": decision["reason"],
            },
        )

    @staticmethod
    def _timeout_error(
        error: ExecutionError,
        *,
        spec: OperationSpec,
        timeout: TimeoutResolution,
        timeout_source: str,
        effective_timeout_ms: int | None,
        elapsed_ms: int,
    ) -> ExecutionError:
        details = dict(error.details)
        details.update(
            {
                "operation": spec.name,
                "timeout_ms": effective_timeout_ms,
                "elapsed_ms": elapsed_ms,
                "timeout_source": timeout_source,
                "timeout_scope": timeout.scope.value,
            }
        )
        return ExecutionError(
            code=error.code,
            category=error.category,
            message=error.message,
            retryable=error.retryable,
            source=error.source,
            operation=error.operation,
            details=details,
            cause_type=error.cause_type,
        )

    @staticmethod
    def _metadata(
        spec: OperationSpec,
        attempts: int,
        timeout: TimeoutResolution,
        attempt_history: list[dict[str, Any]],
    ) -> dict[str, Any]:
        return {
            "operation": spec.name,
            "attempts": attempts,
            "retry_owner": spec.retry_owner.value,
            "timeout_scope": timeout.scope.value,
            "timeout_enforcement": timeout.rule.enforcement.value,
            "attempt_history": attempt_history,
        }
