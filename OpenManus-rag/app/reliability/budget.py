"""Authoritative, in-memory execution budget accounting.

The ledger is intentionally independent from Agent Core and from persisted
Trace. Trace is a best-effort projection of committed ledger state; it is not
the enforcement authority.
"""

from __future__ import annotations

import threading
from enum import Enum
from typing import Any, Mapping

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.reliability.errors import (
    ErrorCategory,
    ErrorCode,
    ExecutionError,
    ExecutionErrorRaised,
)
from app.reliability.trace import (
    Clock,
    SystemClock,
    TraceContext,
    TraceEventType,
    TraceStatus,
)


class BudgetDimension(str, Enum):
    OPERATION_ATTEMPTS = "OPERATION_ATTEMPTS"
    STEPS = "STEPS"
    TOOL_CALLS = "TOOL_CALLS"
    SEARCH_CALLS = "SEARCH_CALLS"
    BROWSER_ACTIONS = "BROWSER_ACTIONS"
    DOWNLOADS = "DOWNLOADS"
    LLM_CALLS = "LLM_CALLS"
    RETRY_ATTEMPTS = "RETRY_ATTEMPTS"
    DURATION_MS = "DURATION_MS"
    PROMPT_TOKENS = "PROMPT_TOKENS"
    COMPLETION_TOKENS = "COMPLETION_TOKENS"
    TOTAL_TOKENS = "TOTAL_TOKENS"


_FIELD_BY_DIMENSION: dict[BudgetDimension, str] = {
    dimension: f"max_{dimension.value.casefold()}" for dimension in BudgetDimension
}


class ExecutionBudget(BaseModel):
    """Optional hard limits; ``None`` means unlimited and ``0`` means denied."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    max_operation_attempts: int | None = Field(default=None, ge=0)
    max_steps: int | None = Field(default=None, ge=0)
    max_tool_calls: int | None = Field(default=None, ge=0)
    max_search_calls: int | None = Field(default=None, ge=0)
    max_browser_actions: int | None = Field(default=None, ge=0)
    max_downloads: int | None = Field(default=None, ge=0)
    max_llm_calls: int | None = Field(default=None, ge=0)
    max_retry_attempts: int | None = Field(default=None, ge=0)
    max_duration_ms: int | None = Field(default=None, ge=0)
    max_prompt_tokens: int | None = Field(default=None, ge=0)
    max_completion_tokens: int | None = Field(default=None, ge=0)
    max_total_tokens: int | None = Field(default=None, ge=0)

    @classmethod
    def disabled(cls) -> "ExecutionBudget":
        return cls()

    def limit_for(self, dimension: BudgetDimension) -> int | None:
        return getattr(self, _FIELD_BY_DIMENSION[dimension])

    def limits(self) -> dict[BudgetDimension, int | None]:
        return {dimension: self.limit_for(dimension) for dimension in BudgetDimension}


class BudgetReservationStatus(str, Enum):
    RESERVED = "RESERVED"
    COMMITTED = "COMMITTED"
    RELEASED = "RELEASED"


class BudgetReservation(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    reservation_id: str = Field(pattern=r"^budget_reservation_[0-9]{6}$")
    costs: dict[BudgetDimension, int] = Field(default_factory=dict)
    observational_dimensions: frozenset[BudgetDimension] = Field(default_factory=frozenset)
    status: BudgetReservationStatus
    operation: str = Field(min_length=1, max_length=128)
    attempt: int = Field(ge=1)

    @field_validator("costs")
    @classmethod
    def validate_costs(
        cls, value: dict[BudgetDimension, int]
    ) -> dict[BudgetDimension, int]:
        if any(amount <= 0 for amount in value.values()):
            raise ValueError("reservation costs must be positive")
        return dict(value)

    @model_validator(mode="after")
    def validate_dimension_modes(self) -> "BudgetReservation":
        overlap = set(self.costs).intersection(self.observational_dimensions)
        if overlap:
            raise ValueError("a dimension cannot be both reserved and observational")
        if not self.costs and not self.observational_dimensions:
            raise ValueError("reservation must contain a cost or observational dimension")
        return self


class BudgetSnapshot(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    limits: dict[BudgetDimension, int | None]
    committed: dict[BudgetDimension, int]
    reserved: dict[BudgetDimension, int]
    remaining: dict[BudgetDimension, int | None]
    elapsed_duration_ms: int = Field(ge=0)
    reservation_count: int = Field(ge=0)
    exhausted_dimensions: list[BudgetDimension] = Field(default_factory=list)


class BudgetPreview(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    allowed: bool
    stop_dimension: BudgetDimension | None = None
    reason: str = ""
    duration_remaining_ms: int | None = Field(default=None, ge=0)


class BudgetAccountingError(RuntimeError):
    """The caller supplied usage that cannot be reconciled with a reservation."""


class BudgetExceededError(ExecutionErrorRaised):
    """Typed enforcement error carrying a sanitized ExecutionError."""

    def __init__(self, error: ExecutionError, snapshot: BudgetSnapshot):
        super().__init__(error)
        self.snapshot = snapshot


class BudgetLedger:
    """Atomic reserve/commit/release accounting for one execution task."""

    def __init__(
        self,
        budget: ExecutionBudget | None = None,
        *,
        clock: Clock | None = None,
    ) -> None:
        self.budget = budget or ExecutionBudget.disabled()
        self.clock = clock or SystemClock()
        self.started_at_monotonic = self.clock.monotonic()
        self._committed = {dimension: 0 for dimension in BudgetDimension}
        self._reserved = {dimension: 0 for dimension in BudgetDimension}
        self._reservations: dict[str, BudgetReservation] = {}
        self._reservation_sequence = 0
        self._lock = threading.RLock()

    @property
    def enabled(self) -> bool:
        return any(limit is not None for limit in self.budget.limits().values())

    def duration_deadline_monotonic(self) -> float | None:
        """Return the task-wide duration deadline, if one is configured."""

        if self.budget.max_duration_ms is None:
            return None
        return self.started_at_monotonic + (self.budget.max_duration_ms / 1000)

    def duration_remaining_ms(self) -> int | None:
        """Return a non-negative duration remainder from the monotonic clock."""

        deadline = self.duration_deadline_monotonic()
        if deadline is None:
            return None
        return max(0, round((deadline - self.clock.monotonic()) * 1000))

    def exceeded_error(
        self,
        dimension: BudgetDimension,
        *,
        requested: int,
        operation: str,
        attempt: int,
        phase: str,
        reason: str,
        trace_context: TraceContext | None = None,
        span_id: str | None = None,
        parent_span_id: str | None = None,
        stage: str | None = None,
        tool_name: str | None = None,
        **extra: Any,
    ) -> BudgetExceededError:
        """Build and best-effort project an explicit enforcement failure."""

        error = self._budget_error(
            dimension,
            requested=requested,
            operation=operation,
            attempt=attempt,
            phase=phase,
            reason=reason,
            **extra,
        )
        self._emit_exceeded(
            trace_context,
            span_id=span_id,
            parent_span_id=parent_span_id,
            stage=stage,
            tool_name=tool_name,
            operation=operation,
            attempt=attempt,
            error=error,
        )
        return BudgetExceededError(error, self.snapshot())

    def _elapsed_duration_ms(self) -> int:
        return max(
            0,
            round((self.clock.monotonic() - self.started_at_monotonic) * 1000),
        )

    def _refresh_duration(self) -> int:
        elapsed = self._elapsed_duration_ms()
        self._committed[BudgetDimension.DURATION_MS] = elapsed
        return elapsed

    def _remaining(self, dimension: BudgetDimension) -> int | None:
        limit = self.budget.limit_for(dimension)
        if limit is None:
            return None
        return max(0, limit - self._committed[dimension] - self._reserved[dimension])

    def snapshot(self) -> BudgetSnapshot:
        with self._lock:
            elapsed = self._refresh_duration()
            limits = self.budget.limits()
            remaining = {
                dimension: self._remaining(dimension)
                for dimension in BudgetDimension
            }
            exhausted = sorted(
                (
                    dimension
                    for dimension, limit in limits.items()
                    if limit is not None
                    and self._committed[dimension] + self._reserved[dimension] >= limit
                ),
                key=lambda value: value.value,
            )
            return BudgetSnapshot(
                limits=limits,
                committed=dict(self._committed),
                reserved=dict(self._reserved),
                remaining=remaining,
                elapsed_duration_ms=elapsed,
                reservation_count=len(self._reservations),
                exhausted_dimensions=exhausted,
            )

    @staticmethod
    def _normalize_costs(
        costs: Mapping[BudgetDimension, int] | None,
    ) -> dict[BudgetDimension, int]:
        normalized: dict[BudgetDimension, int] = {}
        for raw_dimension, raw_amount in (costs or {}).items():
            dimension = BudgetDimension(raw_dimension)
            amount = int(raw_amount)
            if amount <= 0:
                raise ValueError("budget costs must be positive")
            normalized[dimension] = normalized.get(dimension, 0) + amount
        return normalized

    @staticmethod
    def _normalize_observational(
        dimensions: set[BudgetDimension] | frozenset[BudgetDimension] | None,
    ) -> frozenset[BudgetDimension]:
        return frozenset(BudgetDimension(value) for value in (dimensions or ()))

    def preview(
        self,
        costs: Mapping[BudgetDimension, int] | None,
        *,
        observational_dimensions: set[BudgetDimension]
        | frozenset[BudgetDimension]
        | None = None,
    ) -> BudgetPreview:
        normalized = self._normalize_costs(costs)
        observational = self._normalize_observational(observational_dimensions)
        if set(normalized).intersection(observational):
            raise ValueError("a dimension cannot be both reserved and observational")
        with self._lock:
            elapsed = self._refresh_duration()
            duration_limit = self.budget.max_duration_ms
            duration_remaining = (
                None if duration_limit is None else max(0, duration_limit - elapsed)
            )
            if duration_limit is not None and elapsed >= duration_limit:
                return BudgetPreview(
                    allowed=False,
                    stop_dimension=BudgetDimension.DURATION_MS,
                    reason="execution duration budget exhausted",
                    duration_remaining_ms=duration_remaining,
                )
            for dimension in sorted(observational, key=lambda value: value.value):
                if self.budget.limit_for(dimension) is not None:
                    return BudgetPreview(
                        allowed=False,
                        stop_dimension=dimension,
                        reason="strict budget requires a reliable reservation upper bound",
                        duration_remaining_ms=duration_remaining,
                    )
            for dimension in sorted(normalized, key=lambda value: value.value):
                limit = self.budget.limit_for(dimension)
                if limit is None:
                    continue
                if (
                    self._committed[dimension]
                    + self._reserved[dimension]
                    + normalized[dimension]
                    > limit
                ):
                    return BudgetPreview(
                        allowed=False,
                        stop_dimension=dimension,
                        reason="budget limit would be exceeded",
                        duration_remaining_ms=duration_remaining,
                    )
            return BudgetPreview(
                allowed=True,
                duration_remaining_ms=duration_remaining,
            )

    def reserve(
        self,
        costs: Mapping[BudgetDimension, int] | None,
        *,
        operation: str,
        attempt: int,
        observational_dimensions: set[BudgetDimension]
        | frozenset[BudgetDimension]
        | None = None,
        trace_context: TraceContext | None = None,
        span_id: str | None = None,
        parent_span_id: str | None = None,
        stage: str | None = None,
        tool_name: str | None = None,
    ) -> BudgetReservation:
        normalized = self._normalize_costs(costs)
        observational = self._normalize_observational(observational_dimensions)
        preview = self.preview(
            normalized,
            observational_dimensions=observational,
        )
        if not preview.allowed:
            dimension = preview.stop_dimension or BudgetDimension.OPERATION_ATTEMPTS
            error = self._budget_error(
                dimension,
                requested=normalized.get(dimension, 0),
                operation=operation,
                attempt=attempt,
                phase="PREFLIGHT",
                reason=preview.reason,
            )
            self._emit_exceeded(
                trace_context,
                span_id=span_id,
                parent_span_id=parent_span_id,
                stage=stage,
                tool_name=tool_name,
                operation=operation,
                attempt=attempt,
                error=error,
            )
            raise BudgetExceededError(error, self.snapshot())
        with self._lock:
            # Preview is intentionally not authoritative. Recheck all state
            # while holding the mutation lock so a prior preview cannot race.
            second_preview = self.preview(
                normalized,
                observational_dimensions=observational,
            )
            if not second_preview.allowed:
                dimension = (
                    second_preview.stop_dimension
                    or BudgetDimension.OPERATION_ATTEMPTS
                )
                error = self._budget_error(
                    dimension,
                    requested=normalized.get(dimension, 0),
                    operation=operation,
                    attempt=attempt,
                    phase="PREFLIGHT",
                    reason=second_preview.reason,
                )
                self._emit_exceeded(
                    trace_context,
                    span_id=span_id,
                    parent_span_id=parent_span_id,
                    stage=stage,
                    tool_name=tool_name,
                    operation=operation,
                    attempt=attempt,
                    error=error,
                )
                raise BudgetExceededError(error, self.snapshot())
            self._reservation_sequence += 1
            reservation = BudgetReservation(
                reservation_id=(
                    f"budget_reservation_{self._reservation_sequence:06d}"
                ),
                costs=normalized,
                observational_dimensions=observational,
                status=BudgetReservationStatus.RESERVED,
                operation=operation,
                attempt=attempt,
            )
            for dimension, amount in normalized.items():
                self._reserved[dimension] += amount
            self._reservations[reservation.reservation_id] = reservation
            return reservation

    def commit(
        self,
        reservation: BudgetReservation | str,
        *,
        actual_usage: Mapping[BudgetDimension, int] | None = None,
        trace_context: TraceContext | None = None,
        span_id: str | None = None,
        parent_span_id: str | None = None,
        stage: str | None = None,
        tool_name: str | None = None,
    ) -> BudgetReservation:
        reservation_id = (
            reservation.reservation_id
            if isinstance(reservation, BudgetReservation)
            else str(reservation)
        )
        actual: dict[BudgetDimension, int] = {}
        for raw_dimension, raw_amount in (actual_usage or {}).items():
            dimension = BudgetDimension(raw_dimension)
            amount = int(raw_amount)
            if amount < 0:
                raise ValueError("actual budget usage cannot be negative")
            actual[dimension] = amount

        with self._lock:
            current = self._require_reserved(reservation_id, action="commit")
            duration_before = self._committed[BudgetDimension.DURATION_MS]
            unknown = set(actual) - set(current.costs) - set(
                current.observational_dimensions
            )
            if unknown:
                names = ", ".join(sorted(value.value for value in unknown))
                raise BudgetAccountingError(
                    f"actual usage contains unreserved dimensions: {names}"
                )
            committed_delta = dict(current.costs)
            committed_delta.update(actual)
            overruns = sorted(
                (
                    dimension
                    for dimension, amount in actual.items()
                    if dimension in current.costs
                    and amount > current.costs[dimension]
                ),
                key=lambda value: value.value,
            )
            for dimension, amount in current.costs.items():
                self._reserved[dimension] -= amount
            for dimension, amount in committed_delta.items():
                self._committed[dimension] += amount
            updated = current.model_copy(
                update={"status": BudgetReservationStatus.COMMITTED}
            )
            self._reservations[reservation_id] = updated
            elapsed = self._refresh_duration()
            duration_delta = max(0, elapsed - duration_before)
            duration_overrun = (
                self.budget.max_duration_ms is not None
                and elapsed > self.budget.max_duration_ms
            )

        for dimension, amount in sorted(
            committed_delta.items(), key=lambda item: item[0].value
        ):
            self._emit_consumed(
                trace_context,
                span_id=span_id,
                parent_span_id=parent_span_id,
                stage=stage,
                tool_name=tool_name,
                operation=current.operation,
                attempt=current.attempt,
                dimension=dimension,
                delta=amount,
            )
        if (
            duration_delta
            and BudgetDimension.DURATION_MS not in committed_delta
        ):
            self._emit_consumed(
                trace_context,
                span_id=span_id,
                parent_span_id=parent_span_id,
                stage=stage,
                tool_name=tool_name,
                operation=current.operation,
                attempt=current.attempt,
                dimension=BudgetDimension.DURATION_MS,
                delta=duration_delta,
            )

        exceeded_dimension = (
            overruns[0]
            if overruns
            else BudgetDimension.DURATION_MS
            if duration_overrun
            else None
        )
        if exceeded_dimension is not None:
            requested = committed_delta.get(exceeded_dimension, elapsed)
            reason = (
                "actual usage exceeded its reliable reservation upper bound"
                if overruns
                else "execution duration budget exhausted during operation"
            )
            error = self._budget_error(
                exceeded_dimension,
                requested=requested,
                operation=current.operation,
                attempt=current.attempt,
                phase="POSTFLIGHT",
                reason=reason,
                actual_usage=requested,
                reservation=current.costs.get(exceeded_dimension, 0),
            )
            self._emit_exceeded(
                trace_context,
                span_id=span_id,
                parent_span_id=parent_span_id,
                stage=stage,
                tool_name=tool_name,
                operation=current.operation,
                attempt=current.attempt,
                error=error,
            )
            raise BudgetExceededError(error, self.snapshot())
        return updated

    def release(self, reservation: BudgetReservation | str) -> BudgetReservation:
        reservation_id = (
            reservation.reservation_id
            if isinstance(reservation, BudgetReservation)
            else str(reservation)
        )
        with self._lock:
            current = self._require_reserved(reservation_id, action="release")
            for dimension, amount in current.costs.items():
                self._reserved[dimension] -= amount
            updated = current.model_copy(
                update={"status": BudgetReservationStatus.RELEASED}
            )
            self._reservations[reservation_id] = updated
            return updated

    def get_reservation(self, reservation_id: str) -> BudgetReservation:
        with self._lock:
            try:
                return self._reservations[reservation_id]
            except KeyError as exc:
                raise BudgetAccountingError("unknown budget reservation") from exc

    def _require_reserved(
        self,
        reservation_id: str,
        *,
        action: str,
    ) -> BudgetReservation:
        try:
            current = self._reservations[reservation_id]
        except KeyError as exc:
            raise BudgetAccountingError("unknown budget reservation") from exc
        if current.status is not BudgetReservationStatus.RESERVED:
            raise BudgetAccountingError(
                f"cannot {action} reservation in {current.status.value} state"
            )
        return current

    def _budget_error(
        self,
        dimension: BudgetDimension,
        *,
        requested: int,
        operation: str,
        attempt: int,
        phase: str,
        reason: str,
        **extra: Any,
    ) -> ExecutionError:
        snapshot = self.snapshot()
        return ExecutionError(
            code=ErrorCode.BUDGET_EXCEEDED,
            category=ErrorCategory.RESOURCE,
            message=f"Execution budget exceeded for {dimension.value}: {reason}",
            retryable=False,
            source="budget_ledger",
            operation=operation,
            details={
                "dimension": dimension.value,
                "requested": requested,
                "committed": snapshot.committed[dimension],
                "reserved": snapshot.reserved[dimension],
                "remaining": snapshot.remaining[dimension],
                "limit": snapshot.limits[dimension],
                "attempt": attempt,
                "phase": phase,
                "reason": reason,
                **extra,
            },
            cause_type="BudgetExceededError",
        )

    def _emit_consumed(
        self,
        trace_context: TraceContext | None,
        *,
        span_id: str | None,
        parent_span_id: str | None,
        stage: str | None,
        tool_name: str | None,
        operation: str,
        attempt: int,
        dimension: BudgetDimension,
        delta: int,
    ) -> None:
        if trace_context is None or span_id is None:
            return
        snapshot = self.snapshot()
        try:
            trace_context.emit(
                event_type=TraceEventType.BUDGET_CONSUMED,
                status=TraceStatus.SUCCESS,
                stage=stage,
                step_id=f"attempt-{attempt}",
                span_id=span_id,
                parent_span_id=parent_span_id,
                tool_name=tool_name,
                operation=operation,
                output_summary={
                    "dimension": dimension.value,
                    "delta": delta,
                    "used": snapshot.committed[dimension],
                    "reserved": snapshot.reserved[dimension],
                    "remaining": snapshot.remaining[dimension],
                    "limit": snapshot.limits[dimension],
                    "attempt": attempt,
                },
            )
        except Exception:
            # Persisted trace is a projection. A recorder failure must never
            # roll back or invalidate authoritative in-memory accounting.
            return

    def _emit_exceeded(
        self,
        trace_context: TraceContext | None,
        *,
        span_id: str | None,
        parent_span_id: str | None,
        stage: str | None,
        tool_name: str | None,
        operation: str,
        attempt: int,
        error: ExecutionError,
    ) -> None:
        if trace_context is None or span_id is None:
            return
        try:
            trace_context.emit(
                event_type=TraceEventType.BUDGET_EXCEEDED,
                status=TraceStatus.FAILED,
                stage=stage,
                step_id=f"attempt-{attempt}",
                span_id=span_id,
                parent_span_id=parent_span_id,
                tool_name=tool_name,
                operation=operation,
                error_code=error.code,
                error_category=error.category,
                retryable=False,
                retry_count=max(0, attempt - 1),
                output_summary={
                    "dimension": error.details.get("dimension"),
                    "delta": error.details.get("requested"),
                    "used": error.details.get("committed"),
                    "reserved": error.details.get("reserved"),
                    "remaining": error.details.get("remaining"),
                    "limit": error.details.get("limit"),
                    "attempt": attempt,
                    "phase": error.details.get("phase"),
                },
            )
        except Exception:
            return


__all__ = [
    "BudgetAccountingError",
    "BudgetDimension",
    "BudgetExceededError",
    "BudgetLedger",
    "BudgetPreview",
    "BudgetReservation",
    "BudgetReservationStatus",
    "BudgetSnapshot",
    "ExecutionBudget",
]
