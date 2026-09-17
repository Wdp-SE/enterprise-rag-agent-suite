from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.reliability.timeout import (
    TimeoutEnforcement,
    TimeoutPolicy,
    TimeoutResolver,
    TimeoutRule,
    TimeoutScope,
)


def rule(milliseconds: int) -> TimeoutRule:
    return TimeoutRule(
        timeout_ms=milliseconds,
        enforcement=TimeoutEnforcement.ASYNCIO_FALLBACK,
    )


def policy() -> TimeoutPolicy:
    return TimeoutPolicy(
        operation_rules={"research.http_get": rule(1_000)},
        tool_rules={"web_search": rule(2_000)},
        stage_rules={"ACQUIRE": rule(3_000)},
        workflow_rules={"knowledge_research": rule(4_000)},
        default_rule=rule(5_000),
    )


def test_exact_operation_timeout_has_highest_precedence() -> None:
    resolution = TimeoutResolver(policy()).resolve(
        operation="research.http_get",
        tool_name="web_search",
        stage="ACQUIRE",
        workflow="knowledge_research",
    )
    assert resolution.scope is TimeoutScope.EXACT_OPERATION
    assert resolution.rule.timeout_ms == 1_000


def test_tool_timeout_precedes_stage_and_workflow() -> None:
    resolution = TimeoutResolver(policy()).resolve(
        operation="other",
        tool_name="web_search",
        stage="ACQUIRE",
        workflow="knowledge_research",
    )
    assert resolution.scope is TimeoutScope.TOOL
    assert resolution.rule.timeout_ms == 2_000


def test_stage_timeout_precedes_workflow() -> None:
    resolution = TimeoutResolver(policy()).resolve(
        operation="other",
        stage="ACQUIRE",
        workflow="knowledge_research",
    )
    assert resolution.scope is TimeoutScope.STAGE
    assert resolution.rule.timeout_ms == 3_000


def test_workflow_timeout_precedes_default() -> None:
    resolution = TimeoutResolver(policy()).resolve(
        operation="other",
        workflow="knowledge_research",
    )
    assert resolution.scope is TimeoutScope.WORKFLOW
    assert resolution.rule.timeout_ms == 4_000


def test_default_timeout_is_final_fallback() -> None:
    resolution = TimeoutResolver(policy()).resolve(operation="other")
    assert resolution.scope is TimeoutScope.DEFAULT
    assert resolution.rule.timeout_ms == 5_000


def test_disabled_policy_resolves_to_disabled() -> None:
    resolution = TimeoutResolver(TimeoutPolicy.disabled()).resolve(operation="raw")
    assert resolution.scope is TimeoutScope.DISABLED
    assert resolution.enabled is False


def test_native_rule_carries_distinct_http_phase_timeouts() -> None:
    native = TimeoutRule(
        timeout_ms=15_000,
        enforcement=TimeoutEnforcement.NATIVE,
        connect_ms=3_000,
        read_ms=12_000,
        write_ms=5_000,
        pool_ms=2_000,
    )
    assert native.connect_ms == 3_000
    assert native.read_ms == 12_000
    assert len({native.connect_ms, native.read_ms, native.write_ms, native.pool_ms}) > 1


def test_disabled_rule_rejects_timeout_values() -> None:
    with pytest.raises(ValidationError, match="disabled timeout rule"):
        TimeoutRule(timeout_ms=1_000)


def test_asyncio_rule_rejects_native_phase_values() -> None:
    with pytest.raises(ValidationError, match="require NATIVE"):
        TimeoutRule(
            timeout_ms=1_000,
            enforcement=TimeoutEnforcement.ASYNCIO_FALLBACK,
            connect_ms=100,
        )


def test_enabled_rule_requires_timeout_ms() -> None:
    with pytest.raises(ValidationError, match="requires timeout_ms"):
        TimeoutRule(enforcement=TimeoutEnforcement.NATIVE)


def test_rule_keys_cannot_be_blank() -> None:
    with pytest.raises(ValidationError, match="cannot be blank"):
        TimeoutPolicy(operation_rules={" ": rule(1_000)})
