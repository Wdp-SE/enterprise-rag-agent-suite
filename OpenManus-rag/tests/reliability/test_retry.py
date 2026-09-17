from __future__ import annotations

from datetime import datetime, timedelta, timezone

from app.reliability.budget import BudgetDimension
from app.reliability.errors import ErrorCategory, ErrorCode, ExecutionError
from app.reliability.retry import (
    RetryContext,
    RetryOwner,
    RetryPolicy,
    RetryRule,
    SideEffectLevel,
    parse_retry_after_ms,
)


class FakeRandom:
    def __init__(self, value: float):
        self.value = value

    def random(self) -> float:
        return self.value


def error(code: ErrorCode, *, retryable: bool = True) -> ExecutionError:
    return ExecutionError(
        code=code,
        category=ErrorCategory.NETWORK,
        message="fixture",
        retryable=retryable,
        source="fixture",
        operation="op",
    )


def context(
    *,
    attempt: int = 1,
    owner: RetryOwner = RetryOwner.RELIABILITY,
    idempotent: bool = True,
    side_effect: SideEffectLevel = SideEffectLevel.READ_ONLY,
    now: float = 10.0,
    deadline: float | None = None,
    retry_after_ms: int | None = None,
    budget_allows_retry: bool = True,
    budget_stop_dimension: BudgetDimension | None = None,
    budget_duration_remaining_ms: int | None = None,
) -> RetryContext:
    return RetryContext(
        operation="op",
        attempt=attempt,
        idempotent=idempotent,
        side_effect_level=side_effect,
        retry_owner=owner,
        now_monotonic=now,
        deadline_monotonic=deadline,
        retry_after_ms=retry_after_ms,
        budget_allows_retry=budget_allows_retry,
        budget_stop_dimension=budget_stop_dimension,
        budget_duration_remaining_ms=budget_duration_remaining_ms,
    )


def policy(*, jitter: float = 0.0) -> RetryPolicy:
    return RetryPolicy(
        operation_rules={
            "op": RetryRule.transient_default(
                max_attempts=3,
                base_delay_ms=100,
                max_delay_ms=250,
                jitter_ratio=jitter,
            )
        }
    )


def decide(code: ErrorCode, **context_kwargs):
    return policy().decide(
        error(code),
        context(**context_kwargs),
        random_source=FakeRandom(0.5),
    )


def test_transient_timeout_rate_limit_and_service_failure_are_allowed() -> None:
    for code in (
        ErrorCode.TRANSIENT_NETWORK,
        ErrorCode.OPERATION_TIMEOUT,
        ErrorCode.RATE_LIMITED,
        ErrorCode.EXTERNAL_SERVICE_FAILED,
    ):
        assert decide(code).should_retry is True


def test_403_401_invalid_capability_unsupported_and_internal_do_not_retry() -> None:
    for code in (
        ErrorCode.ACCESS_DENIED,
        ErrorCode.AUTHENTICATION_FAILED,
        ErrorCode.INVALID_INPUT,
        ErrorCode.TOOL_CAPABILITY_UNAVAILABLE,
        ErrorCode.UNSUPPORTED_CONTENT,
        ErrorCode.INTERNAL_ERROR,
    ):
        decision = policy().decide(
            error(code, retryable=False),
            context(),
            random_source=FakeRandom(0.5),
        )
        assert decision.should_retry is False


def test_policy_allowlist_is_required_even_for_retryable_error() -> None:
    disallowed = error(ErrorCode.INTERNAL_ERROR, retryable=True)
    decision = policy().decide(
        disallowed, context(), random_source=FakeRandom(0.5)
    )
    assert decision.should_retry is False
    assert "does not allow" in decision.reason


def test_non_idempotent_operation_never_retries() -> None:
    decision = decide(
        ErrorCode.TRANSIENT_NETWORK,
        idempotent=False,
        side_effect=SideEffectLevel.NON_IDEMPOTENT,
    )
    assert decision.should_retry is False
    assert "not explicitly idempotent" in decision.reason


def test_delegated_owner_prevents_nested_retry() -> None:
    decision = decide(ErrorCode.TRANSIENT_NETWORK, owner=RetryOwner.DELEGATED)
    assert decision.should_retry is False
    assert "delegated" in decision.reason


def test_attempts_exhausted() -> None:
    decision = decide(ErrorCode.TRANSIENT_NETWORK, attempt=3)
    assert decision.should_retry is False
    assert decision.reason == "attempts exhausted"


def test_deadline_already_exhausted() -> None:
    decision = decide(ErrorCode.TRANSIENT_NETWORK, now=10.0, deadline=10.0)
    assert decision.should_retry is False
    assert decision.reason == "deadline exhausted"


def test_deadline_rejects_delay_that_would_cross_it() -> None:
    decision = decide(ErrorCode.TRANSIENT_NETWORK, now=10.0, deadline=10.05)
    assert decision.should_retry is False
    assert "before next attempt" in decision.reason


def test_execution_budget_can_stop_retry_without_mutable_ledger_dependency() -> None:
    decision = decide(
        ErrorCode.TRANSIENT_NETWORK,
        budget_allows_retry=False,
        budget_stop_dimension=BudgetDimension.RETRY_ATTEMPTS,
    )
    assert decision.should_retry is False
    assert decision.reason == "execution budget exhausted: RETRY_ATTEMPTS"


def test_execution_duration_budget_rejects_retry_delay() -> None:
    decision = decide(
        ErrorCode.TRANSIENT_NETWORK,
        budget_duration_remaining_ms=100,
    )
    assert decision.should_retry is False
    assert decision.reason == "execution budget exhausted: DURATION_MS"


def test_exponential_backoff_and_max_delay() -> None:
    first = decide(ErrorCode.TRANSIENT_NETWORK, attempt=1)
    second = decide(ErrorCode.TRANSIENT_NETWORK, attempt=2)
    assert first.delay_ms == 100
    assert second.delay_ms == 200
    capped_rule = RetryRule.transient_default(
        max_attempts=5,
        base_delay_ms=100,
        max_delay_ms=250,
        jitter_ratio=0,
    )
    capped_policy = RetryPolicy(operation_rules={"op": capped_rule})
    capped = capped_policy.decide(
        error(ErrorCode.TRANSIENT_NETWORK),
        context(attempt=3),
        random_source=FakeRandom(0.5),
    )
    assert capped.delay_ms == 250


def test_jitter_is_deterministic_with_injected_source() -> None:
    jitter_policy = policy(jitter=0.2)
    low = jitter_policy.decide(
        error(ErrorCode.TRANSIENT_NETWORK),
        context(),
        random_source=FakeRandom(0.0),
    )
    high = jitter_policy.decide(
        error(ErrorCode.TRANSIENT_NETWORK),
        context(),
        random_source=FakeRandom(1.0),
    )
    assert low.delay_ms == 80
    assert high.delay_ms == 120


def test_retry_after_precedes_backoff_and_is_capped() -> None:
    normal = policy().decide(
        error(ErrorCode.RATE_LIMITED),
        context(retry_after_ms=175),
        random_source=FakeRandom(0.5),
    )
    capped = policy().decide(
        error(ErrorCode.RATE_LIMITED),
        context(retry_after_ms=10_000),
        random_source=FakeRandom(0.5),
    )
    assert normal.delay_ms == 175
    assert capped.delay_ms == 250


def test_retry_after_parses_seconds_and_http_date() -> None:
    now = datetime(2026, 8, 29, 0, 0, tzinfo=timezone.utc)
    assert parse_retry_after_ms("2", now=now) == 2_000
    assert (
        parse_retry_after_ms(
            (now + timedelta(seconds=3)).strftime("%a, %d %b %Y %H:%M:%S GMT"),
            now=now,
        )
        == 3_000
    )


def test_invalid_or_negative_retry_after_is_ignored() -> None:
    assert parse_retry_after_ms("not-a-delay") is None
    assert parse_retry_after_ms("-1") is None
