from __future__ import annotations

import asyncio

import pytest

from app.reliability.budget import (
    BudgetDimension,
    BudgetLedger,
    BudgetReservationStatus,
    ExecutionBudget,
)
from app.reliability.errors import ErrorCode
from app.reliability.executor import OperationSpec, ReliableOperationExecutor
from app.reliability.result import ExecutionStatus
from app.reliability.retry import RetryOwner, RetryPolicy, RetryRule, SideEffectLevel


def operation_spec(
    *,
    costs: dict[BudgetDimension, int] | None = None,
    observational: frozenset[BudgetDimension] = frozenset(),
) -> OperationSpec:
    return OperationSpec(
        name="fixture.budgeted",
        idempotent=True,
        side_effect_level=SideEffectLevel.READ_ONLY,
        retry_owner=RetryOwner.RELIABILITY,
        tool_name="fixture_tool",
        stage="TEST",
        workflow="fixture",
        budget_costs=costs or {},
        budget_observational_dimensions=observational,
    )


def retry_policy(max_attempts: int = 3) -> RetryPolicy:
    return RetryPolicy(
        operation_rules={
            "fixture.budgeted": RetryRule.transient_default(
                max_attempts=max_attempts,
                base_delay_ms=0,
                max_delay_ms=0,
                jitter_ratio=0,
            )
        }
    )


@pytest.mark.asyncio
async def test_preflight_exhaustion_never_invokes_operation() -> None:
    ledger = BudgetLedger(ExecutionBudget(max_operation_attempts=0))
    runner = ReliableOperationExecutor(budget_ledger=ledger)
    calls = 0

    async def operation(attempt):
        nonlocal calls
        calls += 1
        return "unexpected"

    result = await runner.execute(operation_spec(), operation)
    assert result.status is ExecutionStatus.FAILED
    assert result.primary_error.code is ErrorCode.BUDGET_EXCEEDED
    assert calls == 0
    assert ledger.snapshot().reservation_count == 0


@pytest.mark.asyncio
async def test_success_commits_attempt_and_declared_call_cost() -> None:
    ledger = BudgetLedger(
        ExecutionBudget(max_operation_attempts=2, max_tool_calls=2)
    )
    runner = ReliableOperationExecutor(budget_ledger=ledger)
    result = await runner.execute(
        operation_spec(costs={BudgetDimension.TOOL_CALLS: 1}),
        lambda attempt: asyncio.sleep(0, result="ok"),
    )
    snapshot = ledger.snapshot()
    assert result.status is ExecutionStatus.SUCCESS
    assert snapshot.committed[BudgetDimension.OPERATION_ATTEMPTS] == 1
    assert snapshot.committed[BudgetDimension.TOOL_CALLS] == 1


@pytest.mark.asyncio
async def test_failed_external_call_still_commits_fixed_costs() -> None:
    ledger = BudgetLedger(
        ExecutionBudget(max_operation_attempts=1, max_downloads=1)
    )
    runner = ReliableOperationExecutor(budget_ledger=ledger)

    async def operation(attempt):
        raise ValueError("invalid fixture")

    result = await runner.execute(
        operation_spec(costs={BudgetDimension.DOWNLOADS: 1}), operation
    )
    snapshot = ledger.snapshot()
    assert result.status is ExecutionStatus.FAILED
    assert snapshot.committed[BudgetDimension.OPERATION_ATTEMPTS] == 1
    assert snapshot.committed[BudgetDimension.DOWNLOADS] == 1


@pytest.mark.asyncio
async def test_retry_attempt_counts_only_real_attempts_after_first() -> None:
    ledger = BudgetLedger(
        ExecutionBudget(max_operation_attempts=3, max_retry_attempts=2)
    )
    runner = ReliableOperationExecutor(
        budget_ledger=ledger,
        retry_policy=retry_policy(3),
    )

    async def operation(attempt):
        raise ConnectionResetError("connection reset")

    result = await runner.execute(operation_spec(), operation)
    snapshot = ledger.snapshot()
    assert result.status is ExecutionStatus.FAILED
    assert result.metadata["attempts"] == 3
    assert snapshot.committed[BudgetDimension.OPERATION_ATTEMPTS] == 3
    assert snapshot.committed[BudgetDimension.RETRY_ATTEMPTS] == 2


@pytest.mark.asyncio
async def test_retry_budget_stops_before_unfunded_attempt() -> None:
    ledger = BudgetLedger(
        ExecutionBudget(max_operation_attempts=5, max_retry_attempts=1)
    )
    runner = ReliableOperationExecutor(
        budget_ledger=ledger,
        retry_policy=retry_policy(3),
    )
    calls = 0

    async def operation(attempt):
        nonlocal calls
        calls += 1
        raise ConnectionResetError("connection reset")

    result = await runner.execute(operation_spec(), operation)
    assert calls == 2
    assert result.metadata["attempts"] == 2
    assert "RETRY_ATTEMPTS" in result.metadata["retry_stop_reason"]


@pytest.mark.asyncio
async def test_preview_success_does_not_replace_atomic_reserve() -> None:
    ledger = BudgetLedger(ExecutionBudget(max_operation_attempts=2))

    class RacingSleeper:
        async def sleep(self, seconds: float) -> None:
            competing = ledger.reserve(
                {BudgetDimension.OPERATION_ATTEMPTS: 1},
                operation="competing.operation",
                attempt=1,
            )
            ledger.commit(competing)

    runner = ReliableOperationExecutor(
        budget_ledger=ledger,
        retry_policy=retry_policy(2),
        sleeper=RacingSleeper(),
    )
    calls = 0

    async def operation(attempt):
        nonlocal calls
        calls += 1
        raise ConnectionResetError("connection reset")

    result = await runner.execute(operation_spec(), operation)
    assert calls == 1
    assert result.status is ExecutionStatus.FAILED
    assert result.errors[-1].code is ErrorCode.BUDGET_EXCEEDED


@pytest.mark.asyncio
async def test_reliable_token_reservation_commits_actual_usage() -> None:
    ledger = BudgetLedger(
        ExecutionBudget(
            max_prompt_tokens=100,
            max_completion_tokens=50,
            max_total_tokens=150,
        )
    )
    runner = ReliableOperationExecutor(budget_ledger=ledger)
    token_costs = {
        BudgetDimension.PROMPT_TOKENS: 100,
        BudgetDimension.COMPLETION_TOKENS: 50,
        BudgetDimension.TOTAL_TOKENS: 150,
        BudgetDimension.LLM_CALLS: 1,
    }
    result = await runner.execute(
        operation_spec(costs=token_costs),
        lambda attempt: asyncio.sleep(0, result={"usage": "fixture"}),
        token_usage_summarizer=lambda value: {
            "prompt_tokens": 60,
            "completion_tokens": 20,
            "total_tokens": 80,
        },
    )
    snapshot = ledger.snapshot()
    assert result.status is ExecutionStatus.SUCCESS
    assert snapshot.committed[BudgetDimension.TOTAL_TOKENS] == 80
    assert snapshot.committed[BudgetDimension.LLM_CALLS] == 1


@pytest.mark.asyncio
async def test_actual_token_overrun_returns_partial_and_preserves_value() -> None:
    ledger = BudgetLedger(ExecutionBudget(max_total_tokens=200))
    runner = ReliableOperationExecutor(budget_ledger=ledger)
    result = await runner.execute(
        operation_spec(costs={BudgetDimension.TOTAL_TOKENS: 100}),
        lambda attempt: asyncio.sleep(0, result="generated"),
        token_usage_summarizer=lambda value: {"total_tokens": 120},
    )
    assert result.status is ExecutionStatus.PARTIAL
    assert result.value == "generated"
    assert result.primary_error.code is ErrorCode.BUDGET_EXCEEDED
    assert ledger.snapshot().committed[BudgetDimension.TOTAL_TOKENS] == 120


@pytest.mark.asyncio
async def test_strict_token_limit_without_upper_bound_rejects_preflight() -> None:
    ledger = BudgetLedger(ExecutionBudget(max_total_tokens=100))
    runner = ReliableOperationExecutor(budget_ledger=ledger)
    calls = 0

    async def operation(attempt):
        nonlocal calls
        calls += 1
        return "unexpected"

    result = await runner.execute(
        operation_spec(
            observational=frozenset({BudgetDimension.TOTAL_TOKENS})
        ),
        operation,
    )
    assert calls == 0
    assert result.primary_error.code is ErrorCode.BUDGET_EXCEEDED
    assert result.primary_error.details["dimension"] == "TOTAL_TOKENS"


@pytest.mark.asyncio
async def test_observational_token_usage_is_recorded_without_hard_limit() -> None:
    ledger = BudgetLedger(ExecutionBudget(max_llm_calls=1))
    runner = ReliableOperationExecutor(budget_ledger=ledger)
    result = await runner.execute(
        operation_spec(
            costs={BudgetDimension.LLM_CALLS: 1},
            observational=frozenset({BudgetDimension.TOTAL_TOKENS}),
        ),
        lambda attempt: asyncio.sleep(0, result="ok"),
        token_usage_summarizer=lambda value: {"total_tokens": 17},
    )
    assert result.status is ExecutionStatus.SUCCESS
    assert ledger.snapshot().committed[BudgetDimension.TOTAL_TOKENS] == 17


@pytest.mark.asyncio
async def test_failed_llm_without_usage_conservatively_charges_reserved_upper_bound() -> None:
    ledger = BudgetLedger(
        ExecutionBudget(max_llm_calls=1, max_total_tokens=100)
    )
    runner = ReliableOperationExecutor(budget_ledger=ledger)

    async def operation(attempt):
        raise ConnectionResetError("provider disconnected after request")

    result = await runner.execute(
        operation_spec(
            costs={
                BudgetDimension.LLM_CALLS: 1,
                BudgetDimension.TOTAL_TOKENS: 80,
            }
        ),
        operation,
    )
    snapshot = ledger.snapshot()
    assert result.status is ExecutionStatus.FAILED
    assert snapshot.committed[BudgetDimension.LLM_CALLS] == 1
    assert snapshot.committed[BudgetDimension.TOTAL_TOKENS] == 80


@pytest.mark.asyncio
async def test_duration_budget_deadline_is_not_operation_timeout() -> None:
    ledger = BudgetLedger(ExecutionBudget(max_duration_ms=10))
    runner = ReliableOperationExecutor(budget_ledger=ledger)

    async def operation(attempt):
        await asyncio.sleep(0.05)
        return "late"

    result = await runner.execute(operation_spec(), operation)
    assert result.status is ExecutionStatus.FAILED
    assert result.primary_error.code is ErrorCode.BUDGET_EXCEEDED
    assert result.primary_error.details["dimension"] == "DURATION_MS"


class BrokenCommitLedger(BudgetLedger):
    def commit(self, *args, **kwargs):
        raise RuntimeError("ledger write failed")


@pytest.mark.asyncio
async def test_ledger_failure_does_not_replace_business_primary_error() -> None:
    ledger = BrokenCommitLedger(ExecutionBudget(max_operation_attempts=1))
    runner = ReliableOperationExecutor(budget_ledger=ledger)

    async def operation(attempt):
        raise ConnectionResetError("business network failure")

    result = await runner.execute(operation_spec(), operation)
    assert result.status is ExecutionStatus.FAILED
    assert result.primary_error.code is ErrorCode.TRANSIENT_NETWORK
    assert result.errors[1].code is ErrorCode.INTERNAL_ERROR


@pytest.mark.asyncio
async def test_success_plus_ledger_failure_is_partial_with_value() -> None:
    ledger = BrokenCommitLedger(ExecutionBudget(max_operation_attempts=1))
    runner = ReliableOperationExecutor(budget_ledger=ledger)
    result = await runner.execute(
        operation_spec(),
        lambda attempt: asyncio.sleep(0, result="already-produced"),
    )
    assert result.status is ExecutionStatus.PARTIAL
    assert result.value == "already-produced"
    assert result.primary_error.code is ErrorCode.INTERNAL_ERROR
    reservation = ledger.get_reservation("budget_reservation_000001")
    assert reservation.status is BudgetReservationStatus.RESERVED


@pytest.mark.asyncio
async def test_executor_without_ledger_retains_phase_1b_behavior() -> None:
    runner = ReliableOperationExecutor(retry_policy=retry_policy(2))
    calls = 0

    async def operation(attempt):
        nonlocal calls
        calls += 1
        if calls == 1:
            raise ConnectionResetError("connection reset")
        return "ok"

    result = await runner.execute(operation_spec(), operation)
    assert result.status is ExecutionStatus.SUCCESS
    assert result.value == "ok"
    assert result.metadata["attempts"] == 2
