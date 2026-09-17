from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError

from app.reliability.budget import BudgetLedger, ExecutionBudget
from app.reliability.errors import ErrorCategory, ErrorCode, ExecutionError
from app.reliability.policy import (
    CapabilityId,
    PolicyAction,
    PolicyContext,
    PolicyDecision,
    PolicyEvaluationPoint,
    PolicyReason,
    PolicyRetryState,
    TaskPolicy,
    TaskPolicyProfile,
)
from app.reliability.progress import NoProgressDecision, NoProgressReason
from app.reliability.retry import RetryOwner, SideEffectLevel


PROJECT_ROOT = Path(__file__).resolve().parents[2]


def profile(**overrides) -> TaskPolicyProfile:
    values = {
        "profile_id": "fixture_safe",
        "allowed_tools": frozenset(
            {
                CapabilityId.WEB_SEARCH,
                CapabilityId.HTTP_GET,
                CapabilityId.BROWSER_ACQUIRE,
                CapabilityId.WORKSPACE_WRITE,
                CapabilityId.CANDIDATE_PACKAGE,
            }
        ),
        "network_access": True,
        "allowed_output_roots": frozenset({"research_runs", "candidate_knowledge"}),
        "allowed_side_effect_levels": frozenset(
            {SideEffectLevel.READ_ONLY, SideEffectLevel.IDEMPOTENT_WRITE}
        ),
    }
    values.update(overrides)
    return TaskPolicyProfile(**values)


def pre_context(**overrides) -> PolicyContext:
    values = {
        "evaluation_point": PolicyEvaluationPoint.PRE_OPERATION,
        "operation": "research.search",
        "tool_name": CapabilityId.WEB_SEARCH.value,
        "side_effect_level": SideEffectLevel.READ_ONLY,
        "network_required": True,
        "target_domain": "search.example.com",
        "external_write": False,
    }
    values.update(overrides)
    return PolicyContext(**values)


def error(code: ErrorCode, *, retryable: bool = False) -> ExecutionError:
    return ExecutionError(
        code=code,
        category=ErrorCategory.INTERNAL,
        message=f"fixture {code.value}",
        retryable=retryable,
        source="fixture",
        operation="research.http_get",
    )


def no_progress(reason: NoProgressReason) -> NoProgressDecision:
    return NoProgressDecision(
        sequence=3,
        no_progress=True,
        reason=reason,
        streak_count=3,
        repeat_count=3,
    )


def fallback_profile(**overrides) -> TaskPolicyProfile:
    values = {
        "operation_fallbacks": {"research.http_get": CapabilityId.BROWSER_ACQUIRE},
        "error_fallbacks": {
            ErrorCode.ACCESS_DENIED: CapabilityId.BROWSER_ACQUIRE,
            ErrorCode.TOOL_CAPABILITY_UNAVAILABLE: CapabilityId.BROWSER_ACQUIRE,
            ErrorCode.TRANSIENT_NETWORK: CapabilityId.BROWSER_ACQUIRE,
        },
        "no_progress_actions": {
            NoProgressReason.SAME_ERROR_REPEAT: PolicyAction.FALLBACK,
            NoProgressReason.SAME_RESOURCE_REPEAT: PolicyAction.FALLBACK,
            NoProgressReason.SAME_OPERATION_REPEAT: PolicyAction.REPLAN,
            NoProgressReason.NO_ARTIFACT_GROWTH: PolicyAction.REPLAN,
        },
        "no_progress_fallbacks": {
            NoProgressReason.SAME_ERROR_REPEAT: CapabilityId.BROWSER_ACQUIRE,
            NoProgressReason.SAME_RESOURCE_REPEAT: CapabilityId.BROWSER_ACQUIRE,
        },
    }
    values.update(overrides)
    return profile(**values)


def post_http_context(**overrides) -> PolicyContext:
    values = {
        "evaluation_point": PolicyEvaluationPoint.POST_OPERATION,
        "operation": "research.http_get",
        "tool_name": CapabilityId.HTTP_GET.value,
        "target_domain": "agency.example.com",
    }
    values.update(overrides)
    return PolicyContext(**values)


def test_safe_profile_loads_from_toml() -> None:
    loaded = TaskPolicyProfile.from_toml(
        PROJECT_ROOT / "config/reliability_policies/knowledge_research_safe.toml"
    )
    assert loaded.profile_id == "knowledge_research_safe"
    assert CapabilityId.WEB_SEARCH in loaded.allowed_tools
    assert CapabilityId.APPROVE_CANDIDATE in loaded.denied_tools
    assert SideEffectLevel.NON_IDEMPOTENT not in loaded.allowed_side_effect_levels


def test_normal_pre_operation_is_allowed() -> None:
    decision = TaskPolicy(profile()).evaluate(pre_context())
    assert decision.action is PolicyAction.CONTINUE
    assert decision.allowed is True


def test_budget_error_stops() -> None:
    decision = TaskPolicy(profile()).evaluate(
        post_http_context(primary_error=error(ErrorCode.BUDGET_EXCEEDED))
    )
    assert decision.action is PolicyAction.STOP
    assert decision.reason_code is PolicyReason.BUDGET_EXHAUSTED


def test_exhausted_budget_snapshot_stops() -> None:
    snapshot = BudgetLedger(ExecutionBudget(max_steps=0)).snapshot()
    decision = TaskPolicy(profile()).evaluate(post_http_context(budget_snapshot=snapshot))
    assert decision.reason_code is PolicyReason.BUDGET_EXHAUSTED


@pytest.mark.parametrize(
    "code",
    [
        ErrorCode.AUTHENTICATION_FAILED,
        ErrorCode.INVALID_INPUT,
        ErrorCode.POLICY_BLOCKED,
        ErrorCode.CANCELLED,
        ErrorCode.INTERNAL_ERROR,
        ErrorCode.INSUFFICIENT_EVIDENCE,
        ErrorCode.RESOURCE_EXHAUSTED,
    ],
)
def test_unrecoverable_errors_stop(code: ErrorCode) -> None:
    decision = TaskPolicy(fallback_profile()).evaluate(
        post_http_context(primary_error=error(code))
    )
    assert decision.action is PolicyAction.STOP
    assert decision.reason_code is PolicyReason.UNRECOVERABLE_ERROR


def test_access_denied_with_configured_fallback() -> None:
    decision = TaskPolicy(fallback_profile()).evaluate(
        post_http_context(primary_error=error(ErrorCode.ACCESS_DENIED))
    )
    assert decision.action is PolicyAction.FALLBACK
    assert decision.fallback_target is CapabilityId.BROWSER_ACQUIRE


def test_capability_unavailable_with_fallback() -> None:
    decision = TaskPolicy(fallback_profile()).evaluate(
        post_http_context(primary_error=error(ErrorCode.TOOL_CAPABILITY_UNAVAILABLE))
    )
    assert decision.action is PolicyAction.FALLBACK


def test_capability_unavailable_without_fallback_stops() -> None:
    decision = TaskPolicy(profile()).evaluate(
        post_http_context(primary_error=error(ErrorCode.TOOL_CAPABILITY_UNAVAILABLE))
    )
    assert decision.action is PolicyAction.STOP
    assert decision.reason_code is PolicyReason.ERROR_STOP


def test_retry_pending_defers_to_retry_policy() -> None:
    state = PolicyRetryState(
        retry_pending=True,
        attempt=1,
        max_attempts=3,
        retry_owner=RetryOwner.RELIABILITY,
    )
    decision = TaskPolicy(profile()).evaluate(
        post_http_context(
            primary_error=error(ErrorCode.TRANSIENT_NETWORK, retryable=True),
            retry_state=state,
        )
    )
    assert decision.action is PolicyAction.CONTINUE
    assert decision.reason_code is PolicyReason.RETRY_PENDING


def test_retry_exhausted_enters_fallback_policy() -> None:
    state = PolicyRetryState(
        retry_exhausted=True,
        attempt=3,
        max_attempts=3,
        retry_owner=RetryOwner.RELIABILITY,
    )
    decision = TaskPolicy(fallback_profile()).evaluate(
        post_http_context(
            primary_error=error(ErrorCode.TRANSIENT_NETWORK, retryable=True),
            retry_state=state,
        )
    )
    assert decision.action is PolicyAction.FALLBACK


def test_same_error_repeat_uses_profile_fallback() -> None:
    decision = TaskPolicy(fallback_profile()).evaluate(
        post_http_context(no_progress_decision=no_progress(NoProgressReason.SAME_ERROR_REPEAT))
    )
    assert decision.action is PolicyAction.FALLBACK


def test_same_resource_repeat_uses_profile_fallback() -> None:
    decision = TaskPolicy(fallback_profile()).evaluate(
        post_http_context(no_progress_decision=no_progress(NoProgressReason.SAME_RESOURCE_REPEAT))
    )
    assert decision.action is PolicyAction.FALLBACK


@pytest.mark.parametrize(
    "reason",
    [NoProgressReason.SAME_OPERATION_REPEAT, NoProgressReason.NO_ARTIFACT_GROWTH],
)
def test_no_progress_replan_is_structured(reason: NoProgressReason) -> None:
    decision = TaskPolicy(fallback_profile()).evaluate(
        post_http_context(no_progress_decision=no_progress(reason))
    )
    assert decision.action is PolicyAction.REPLAN
    assert decision.replan_hint


def test_unconfigured_no_progress_stops() -> None:
    decision = TaskPolicy(profile()).evaluate(
        post_http_context(
            no_progress_decision=no_progress(NoProgressReason.STAGE_REENTRY_WITHOUT_PROGRESS)
        )
    )
    assert decision.action is PolicyAction.STOP


def test_read_only_is_allowed() -> None:
    assert TaskPolicy(profile()).evaluate(pre_context()).allowed is True


def test_idempotent_write_requires_explicit_permission() -> None:
    restricted = profile(allowed_side_effect_levels=frozenset({SideEffectLevel.READ_ONLY}))
    decision = TaskPolicy(restricted).evaluate(
        pre_context(
            tool_name=CapabilityId.WORKSPACE_WRITE.value,
            side_effect_level=SideEffectLevel.IDEMPOTENT_WRITE,
            network_required=False,
            output_root="research_runs/run-1",
        )
    )
    assert decision.reason_code is PolicyReason.SIDE_EFFECT_DENIED


def test_non_idempotent_is_denied_by_default() -> None:
    unrestricted_tools = profile(allowed_tools=None)
    decision = TaskPolicy(unrestricted_tools).evaluate(
        pre_context(
            tool_name=CapabilityId.PYTHON_EXECUTE.value,
            side_effect_level=SideEffectLevel.NON_IDEMPOTENT,
            network_required=False,
        )
    )
    assert decision.reason_code is PolicyReason.SIDE_EFFECT_DENIED


def test_allowed_tools_none_disables_allowlist() -> None:
    decision = TaskPolicy(profile(allowed_tools=None)).evaluate(pre_context())
    assert decision.allowed is True


def test_empty_allowed_tools_denies_every_capability() -> None:
    decision = TaskPolicy(profile(allowed_tools=frozenset())).evaluate(pre_context())
    assert decision.reason_code is PolicyReason.TOOL_NOT_ALLOWED


def test_explicit_denied_tool_has_priority() -> None:
    decision = TaskPolicy(
        profile(allowed_tools=None, denied_tools=frozenset({CapabilityId.PYTHON_EXECUTE}))
    ).evaluate(
        pre_context(
            tool_name=CapabilityId.PYTHON_EXECUTE.value,
            side_effect_level=SideEffectLevel.NON_IDEMPOTENT,
            network_required=False,
        )
    )
    assert decision.reason_code is PolicyReason.TOOL_DENIED


def test_unknown_capability_fails_closed() -> None:
    decision = TaskPolicy(profile(allowed_tools=None)).evaluate(
        pre_context(tool_name="unknown_mcp_tool")
    )
    assert decision.action is PolicyAction.STOP
    assert decision.reason_code is PolicyReason.UNKNOWN_CAPABILITY


def test_unknown_side_effect_level_fails_closed() -> None:
    decision = TaskPolicy(profile()).evaluate(pre_context(side_effect_level="MAYBE_WRITE"))
    assert decision.action is PolicyAction.STOP
    assert decision.reason_code is PolicyReason.SIDE_EFFECT_DENIED


def test_pre_operation_missing_metadata_fails_closed() -> None:
    decision = TaskPolicy(profile()).evaluate(
        PolicyContext(
            evaluation_point=PolicyEvaluationPoint.PRE_OPERATION,
            operation="research.search",
            tool_name=CapabilityId.WEB_SEARCH.value,
        )
    )
    assert decision.reason_code is PolicyReason.CAPABILITY_METADATA_MISSING
    assert "side_effect_level" in decision.details["missing_fields"]


def test_network_disabled_denies_network_operation() -> None:
    decision = TaskPolicy(profile(network_access=False)).evaluate(pre_context())
    assert decision.reason_code is PolicyReason.NETWORK_ACCESS_DENIED


def test_exact_domain_allowlist() -> None:
    policy = TaskPolicy(profile(allowed_domains=frozenset({"search.example.com"})))
    assert policy.evaluate(pre_context()).allowed is True


def test_subdomain_wildcard_does_not_match_apex() -> None:
    policy = TaskPolicy(profile(allowed_domains=frozenset({"*.example.com"})))
    assert policy.evaluate(pre_context()).allowed is True
    denied = policy.evaluate(pre_context(target_domain="example.com"))
    assert denied.reason_code is PolicyReason.DOMAIN_NOT_ALLOWED


def test_domain_allowlist_requires_target() -> None:
    policy = TaskPolicy(profile(allowed_domains=frozenset({"example.com"})))
    decision = policy.evaluate(pre_context(target_domain=None))
    assert decision.reason_code is PolicyReason.DOMAIN_REQUIRED


def test_domain_allowlist_rejects_other_domain() -> None:
    policy = TaskPolicy(profile(allowed_domains=frozenset({"example.com"})))
    decision = policy.evaluate(pre_context(target_domain="evil.example.net"))
    assert decision.reason_code is PolicyReason.DOMAIN_NOT_ALLOWED


def test_unbounded_domain_wildcard_is_invalid_profile() -> None:
    with pytest.raises(ValidationError, match="domain rules"):
        profile(allowed_domains=frozenset({"*"}))


def test_allowed_output_root_and_descendant() -> None:
    decision = TaskPolicy(profile()).evaluate(
        pre_context(
            tool_name=CapabilityId.WORKSPACE_WRITE.value,
            side_effect_level=SideEffectLevel.IDEMPOTENT_WRITE,
            network_required=False,
            output_root="research_runs/run-1/outputs",
        )
    )
    assert decision.allowed is True


@pytest.mark.parametrize("root", ["../escape", "/absolute", r"C:\escape", r"\\server\share"])
def test_unsafe_output_root_is_denied(root: str) -> None:
    decision = TaskPolicy(profile()).evaluate(
        pre_context(
            tool_name=CapabilityId.WORKSPACE_WRITE.value,
            side_effect_level=SideEffectLevel.IDEMPOTENT_WRITE,
            network_required=False,
            output_root=root,
        )
    )
    assert decision.reason_code is PolicyReason.OUTPUT_ROOT_INVALID


def test_output_root_outside_allowlist_is_denied() -> None:
    decision = TaskPolicy(profile()).evaluate(
        pre_context(
            tool_name=CapabilityId.WORKSPACE_WRITE.value,
            side_effect_level=SideEffectLevel.IDEMPOTENT_WRITE,
            network_required=False,
            output_root="other/place",
        )
    )
    assert decision.reason_code is PolicyReason.OUTPUT_ROOT_NOT_ALLOWED


def test_local_write_requires_output_root_under_active_allowlist() -> None:
    decision = TaskPolicy(profile()).evaluate(
        pre_context(
            tool_name=CapabilityId.WORKSPACE_WRITE.value,
            side_effect_level=SideEffectLevel.IDEMPOTENT_WRITE,
            network_required=False,
        )
    )
    assert decision.reason_code is PolicyReason.OUTPUT_ROOT_REQUIRED


def test_external_write_is_denied() -> None:
    decision = TaskPolicy(profile(allowed_tools=None)).evaluate(
        pre_context(
            tool_name=CapabilityId.EXTERNAL_PUBLISH.value,
            side_effect_level=SideEffectLevel.NON_IDEMPOTENT,
            network_required=True,
            external_write=True,
        )
    )
    assert decision.allowed is False


def test_fallback_target_not_allowlisted_degrades_to_stop() -> None:
    restricted = fallback_profile(allowed_tools=frozenset({CapabilityId.HTTP_GET}))
    decision = TaskPolicy(restricted).evaluate(
        post_http_context(primary_error=error(ErrorCode.ACCESS_DENIED))
    )
    assert decision.action is PolicyAction.STOP
    assert decision.reason_code is PolicyReason.INVALID_FALLBACK_TARGET


def test_fallback_target_denied_degrades_to_stop() -> None:
    restricted = fallback_profile(
        allowed_tools=None,
        denied_tools=frozenset({CapabilityId.BROWSER_ACQUIRE}),
    )
    decision = TaskPolicy(restricted).evaluate(
        post_http_context(primary_error=error(ErrorCode.ACCESS_DENIED))
    )
    assert decision.reason_code is PolicyReason.INVALID_FALLBACK_TARGET


def test_fallback_target_side_effect_denied_degrades_to_stop() -> None:
    restricted = fallback_profile(
        allowed_side_effect_levels=frozenset({SideEffectLevel.READ_ONLY})
    )
    decision = TaskPolicy(restricted).evaluate(
        post_http_context(primary_error=error(ErrorCode.ACCESS_DENIED))
    )
    assert decision.reason_code is PolicyReason.INVALID_FALLBACK_TARGET
    assert decision.details["fallback_validation"] == "side_effect_not_allowed"


def test_fallback_target_network_denied_degrades_to_stop() -> None:
    decision = TaskPolicy(fallback_profile(network_access=False)).evaluate(
        post_http_context(primary_error=error(ErrorCode.ACCESS_DENIED))
    )
    assert decision.reason_code is PolicyReason.INVALID_FALLBACK_TARGET


def test_fallback_target_domain_must_be_allowed() -> None:
    restricted = fallback_profile(allowed_domains=frozenset({"trusted.example.com"}))
    decision = TaskPolicy(restricted).evaluate(
        post_http_context(
            target_domain="other.example.com",
            primary_error=error(ErrorCode.ACCESS_DENIED),
        )
    )
    assert decision.reason_code is PolicyReason.INVALID_FALLBACK_TARGET


def test_allowed_denied_overlap_is_rejected() -> None:
    with pytest.raises(ValidationError, match="overlap"):
        profile(denied_tools=frozenset({CapabilityId.WEB_SEARCH}))


def test_unknown_capability_in_profile_is_rejected() -> None:
    with pytest.raises(ValidationError):
        TaskPolicyProfile(profile_id="invalid", allowed_tools={"not_registered"})


def test_policy_decision_json_round_trip() -> None:
    decision = TaskPolicy(fallback_profile()).evaluate(
        post_http_context(primary_error=error(ErrorCode.ACCESS_DENIED))
    )
    restored = PolicyDecision.model_validate_json(decision.model_dump_json())
    assert restored == decision


def test_policy_decision_sanitizes_message_and_details() -> None:
    decision = PolicyDecision(
        action=PolicyAction.STOP,
        reason_code=PolicyReason.ERROR_STOP,
        message="Authorization=Bearer top-secret https://example.com/a?token=query-secret",
        allowed=False,
        policy_profile="fixture",
        details={
            "api_key": "sk-very-secret-key",
            "content": "private evidence payload",
            "url": "https://example.com/private?token=value",
        },
    )
    payload = decision.model_dump_json()
    assert "top-secret" not in payload
    assert "query-secret" not in payload
    assert "very-secret" not in payload
    assert "private evidence payload" not in payload


def test_disabled_policy_preserves_behavior_even_for_unknown_metadata() -> None:
    decision = TaskPolicy.disabled().evaluate(
        pre_context(tool_name="unknown", side_effect_level="UNKNOWN")
    )
    assert decision.action is PolicyAction.CONTINUE
    assert decision.reason_code is PolicyReason.POLICY_DISABLED


def test_capability_denial_has_priority_over_budget() -> None:
    snapshot = BudgetLedger(ExecutionBudget(max_steps=0)).snapshot()
    decision = TaskPolicy(profile()).evaluate(
        pre_context(tool_name="unknown", budget_snapshot=snapshot)
    )
    assert decision.reason_code is PolicyReason.UNKNOWN_CAPABILITY


def test_budget_has_priority_over_retry_pending() -> None:
    snapshot = BudgetLedger(ExecutionBudget(max_steps=0)).snapshot()
    decision = TaskPolicy(profile()).evaluate(
        post_http_context(
            budget_snapshot=snapshot,
            retry_state=PolicyRetryState(retry_pending=True, attempt=1, max_attempts=3),
        )
    )
    assert decision.reason_code is PolicyReason.BUDGET_EXHAUSTED


def test_mapping_insertion_order_does_not_change_decision() -> None:
    left = fallback_profile(
        operation_fallbacks={
            "z.operation": CapabilityId.WEB_SEARCH,
            "research.http_get": CapabilityId.BROWSER_ACQUIRE,
        }
    )
    right = fallback_profile(
        operation_fallbacks={
            "research.http_get": CapabilityId.BROWSER_ACQUIRE,
            "z.operation": CapabilityId.WEB_SEARCH,
        }
    )
    context = post_http_context(primary_error=error(ErrorCode.ACCESS_DENIED))
    assert TaskPolicy(left).evaluate(context) == TaskPolicy(right).evaluate(context)


def test_same_context_is_deterministic() -> None:
    policy = TaskPolicy(fallback_profile())
    context = post_http_context(
        no_progress_decision=no_progress(NoProgressReason.SAME_OPERATION_REPEAT)
    )
    assert policy.evaluate(context) == policy.evaluate(context)
