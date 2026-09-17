"""Deterministic retry decisions; this module never executes an operation."""

from __future__ import annotations

import asyncio
import random
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from enum import Enum
from typing import Protocol

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.reliability.budget import BudgetDimension
from app.reliability.errors import ErrorCode, ExecutionError


class SideEffectLevel(str, Enum):
    READ_ONLY = "READ_ONLY"
    IDEMPOTENT_WRITE = "IDEMPOTENT_WRITE"
    NON_IDEMPOTENT = "NON_IDEMPOTENT"


class RetryOwner(str, Enum):
    RELIABILITY = "RELIABILITY"
    DELEGATED = "DELEGATED"
    NONE = "NONE"


DEFAULT_RETRYABLE_CODES = frozenset(
    {
        ErrorCode.TRANSIENT_NETWORK,
        ErrorCode.OPERATION_TIMEOUT,
        ErrorCode.RATE_LIMITED,
        ErrorCode.EXTERNAL_SERVICE_FAILED,
    }
)


class RetryRule(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    max_attempts: int = Field(default=1, ge=1, le=20)
    allowed_error_codes: frozenset[ErrorCode] = Field(default_factory=frozenset)
    base_delay_ms: int = Field(default=0, ge=0)
    max_delay_ms: int = Field(default=0, ge=0)
    jitter_ratio: float = Field(default=0.0, ge=0.0, le=1.0)

    @model_validator(mode="after")
    def validate_delay_range(self) -> "RetryRule":
        if self.base_delay_ms > self.max_delay_ms:
            raise ValueError("base_delay_ms cannot exceed max_delay_ms")
        return self

    @classmethod
    def disabled(cls) -> "RetryRule":
        return cls()

    @classmethod
    def transient_default(
        cls,
        *,
        max_attempts: int = 3,
        base_delay_ms: int = 500,
        max_delay_ms: int = 10_000,
        jitter_ratio: float = 0.1,
    ) -> "RetryRule":
        return cls(
            max_attempts=max_attempts,
            allowed_error_codes=DEFAULT_RETRYABLE_CODES,
            base_delay_ms=base_delay_ms,
            max_delay_ms=max_delay_ms,
            jitter_ratio=jitter_ratio,
        )


class RetryPolicy(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    operation_rules: dict[str, RetryRule] = Field(default_factory=dict)
    default_rule: RetryRule = Field(default_factory=RetryRule.disabled)

    @field_validator("operation_rules", mode="before")
    @classmethod
    def validate_rule_keys(cls, value):
        value = value or {}
        if any(not str(key).strip() for key in value):
            raise ValueError("retry rule keys cannot be blank")
        return {str(key).strip(): rule for key, rule in value.items()}

    @classmethod
    def disabled(cls) -> "RetryPolicy":
        return cls()

    def resolve(self, operation: str) -> RetryRule:
        return self.operation_rules.get(operation, self.default_rule)

    def decide(
        self,
        error: ExecutionError,
        context: "RetryContext",
        *,
        random_source: "RandomSource",
    ) -> "RetryDecision":
        rule = self.resolve(context.operation)
        next_attempt = context.attempt + 1

        def stop(reason: str) -> RetryDecision:
            return RetryDecision(
                should_retry=False,
                reason=reason,
                delay_ms=0,
                next_attempt=next_attempt,
                max_attempts=rule.max_attempts,
            )

        if context.retry_owner is RetryOwner.DELEGATED:
            return stop("retry ownership is delegated to the underlying operation")
        if context.retry_owner is not RetryOwner.RELIABILITY:
            return stop("operation has no reliability retry owner")
        if not error.retryable:
            return stop("error classification is not retryable")
        if not context.idempotent or context.side_effect_level is SideEffectLevel.NON_IDEMPOTENT:
            return stop("operation is not explicitly idempotent")
        if error.code not in rule.allowed_error_codes:
            return stop("retry policy does not allow this error code")
        if context.attempt >= rule.max_attempts:
            return stop("attempts exhausted")
        if context.deadline_monotonic is not None and context.now_monotonic >= context.deadline_monotonic:
            return stop("deadline exhausted")
        if not context.budget_allows_retry:
            dimension = (
                context.budget_stop_dimension.value
                if context.budget_stop_dimension is not None
                else "UNKNOWN"
            )
            return stop(f"execution budget exhausted: {dimension}")

        delay_ms = self._delay_ms(error, context, rule, random_source)
        if (
            context.deadline_monotonic is not None
            and context.now_monotonic + (delay_ms / 1000) >= context.deadline_monotonic
        ):
            return stop("deadline exhausted before next attempt")
        if (
            context.budget_duration_remaining_ms is not None
            and delay_ms >= context.budget_duration_remaining_ms
        ):
            return stop("execution budget exhausted: DURATION_MS")
        return RetryDecision(
            should_retry=True,
            reason="retryable idempotent operation within attempts and deadline",
            delay_ms=delay_ms,
            next_attempt=next_attempt,
            max_attempts=rule.max_attempts,
        )

    @staticmethod
    def _delay_ms(
        error: ExecutionError,
        context: "RetryContext",
        rule: RetryRule,
        random_source: "RandomSource",
    ) -> int:
        retry_after_ms = context.retry_after_ms
        if error.code is ErrorCode.RATE_LIMITED and retry_after_ms is not None:
            return min(max(0, retry_after_ms), rule.max_delay_ms)
        exponential = rule.base_delay_ms * (2 ** max(0, context.attempt - 1))
        capped = min(exponential, rule.max_delay_ms)
        if not capped or not rule.jitter_ratio:
            return capped
        offset = ((random_source.random() * 2.0) - 1.0) * rule.jitter_ratio
        return min(rule.max_delay_ms, max(0, round(capped * (1.0 + offset))))


class RetryContext(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    operation: str
    attempt: int = Field(ge=1)
    idempotent: bool
    side_effect_level: SideEffectLevel
    retry_owner: RetryOwner
    now_monotonic: float
    deadline_monotonic: float | None = None
    retry_after_ms: int | None = Field(default=None, ge=0)
    budget_allows_retry: bool = True
    budget_stop_dimension: BudgetDimension | None = None
    budget_duration_remaining_ms: int | None = Field(default=None, ge=0)


class RetryDecision(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    should_retry: bool
    reason: str
    delay_ms: int = Field(ge=0)
    next_attempt: int = Field(ge=2)
    max_attempts: int = Field(ge=1)


class RandomSource(Protocol):
    def random(self) -> float: ...


class SystemRandomSource:
    def __init__(self) -> None:
        self._random = random.SystemRandom()

    def random(self) -> float:
        return self._random.random()


class Sleeper(Protocol):
    async def sleep(self, seconds: float) -> None: ...


class AsyncioSleeper:
    async def sleep(self, seconds: float) -> None:
        await asyncio.sleep(seconds)


def parse_retry_after_ms(value: object, *, now: datetime | None = None) -> int | None:
    """Parse Retry-After seconds or HTTP-date; invalid/negative values are ignored."""

    if value is None:
        return None
    text = str(value).strip()
    try:
        seconds = float(text)
    except ValueError:
        try:
            parsed = parsedate_to_datetime(text)
            if parsed.tzinfo is None or parsed.utcoffset() is None:
                parsed = parsed.replace(tzinfo=timezone.utc)
            current = now or datetime.now(timezone.utc)
            seconds = (parsed - current).total_seconds()
        except (TypeError, ValueError, OverflowError):
            return None
    if seconds < 0:
        return None
    return round(seconds * 1000)
