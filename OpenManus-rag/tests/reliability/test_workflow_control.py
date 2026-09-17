from __future__ import annotations

from pathlib import Path

from app.reliability.errors import ErrorCategory, ErrorCode, ExecutionError
from app.reliability.policy import (
    CapabilityId,
    PolicyAction,
    PolicyContext,
    PolicyEvaluationPoint,
    TaskPolicy,
    TaskPolicyProfile,
)
from app.reliability.progress import NoProgressDecision, NoProgressReason
from app.reliability.retry import SideEffectLevel
from app.reliability.trace import TraceContext, TraceEvent, TraceEventType, TraceRecorder
from app.reliability.workflow_control import ReliableWorkflowController


def policy() -> TaskPolicy:
    return TaskPolicy(
        TaskPolicyProfile(
            profile_id="fake_workflow",
            allowed_tools=frozenset(
                {
                    CapabilityId.HTTP_GET,
                    CapabilityId.BROWSER_ACQUIRE,
                    CapabilityId.WEB_SEARCH,
                }
            ),
            network_access=True,
            allowed_output_roots=frozenset({"research_runs"}),
            allowed_side_effect_levels=frozenset(
                {SideEffectLevel.READ_ONLY, SideEffectLevel.IDEMPOTENT_WRITE}
            ),
            error_fallbacks={
                ErrorCode.ACCESS_DENIED: CapabilityId.BROWSER_ACQUIRE,
            },
            no_progress_actions={
                NoProgressReason.SAME_OPERATION_REPEAT: PolicyAction.REPLAN,
            },
        )
    )


def execution_error(code: ErrorCode) -> ExecutionError:
    return ExecutionError(
        code=code,
        category=ErrorCategory.SECURITY,
        message="fixture failure",
        retryable=False,
        source="fixture",
        operation="research.http_get",
    )


def read_events(recorder: TraceRecorder, run_id: str) -> list[TraceEvent]:
    return [
        TraceEvent.model_validate_json(line)
        for line in recorder.path_for(run_id).read_text(encoding="utf-8").splitlines()
    ]


class FakeWorkflow:
    def __init__(self, controller: ReliableWorkflowController):
        self.controller = controller
        self.events: list[str] = []

    def run(self, context: PolicyContext) -> dict[str, str | None]:
        decision = self.controller.decide(context)
        if decision.action is PolicyAction.CONTINUE:
            self.events.append("next_fake_step")
            return {"status": "CONTINUED", "target": None}
        if decision.action is PolicyAction.STOP:
            self.events.append("fake_workflow_terminated")
            return {"status": "STOPPED", "target": None}
        if decision.action is PolicyAction.FALLBACK:
            target = decision.fallback_target.value
            self.events.append(f"fallback:{target}")
            return {"status": "FALLBACK_EXECUTED", "target": target}
        self.events.append("replan_requested")
        return {"status": "REPLAN_REQUESTED", "target": decision.replan_hint}


def test_fake_workflow_continue_advances() -> None:
    workflow = FakeWorkflow(ReliableWorkflowController(policy()))
    result = workflow.run(PolicyContext())
    assert result == {"status": "CONTINUED", "target": None}
    assert workflow.events == ["next_fake_step"]


def test_fake_workflow_stop_terminates() -> None:
    workflow = FakeWorkflow(ReliableWorkflowController(policy()))
    result = workflow.run(
        PolicyContext(primary_error=execution_error(ErrorCode.AUTHENTICATION_FAILED))
    )
    assert result["status"] == "STOPPED"
    assert workflow.events == ["fake_workflow_terminated"]


def test_fake_workflow_executes_registered_fallback() -> None:
    workflow = FakeWorkflow(ReliableWorkflowController(policy()))
    result = workflow.run(
        PolicyContext(
            evaluation_point=PolicyEvaluationPoint.POST_OPERATION,
            operation="research.http_get",
            tool_name=CapabilityId.HTTP_GET.value,
            target_domain="agency.example.com",
            primary_error=execution_error(ErrorCode.ACCESS_DENIED),
        )
    )
    assert result == {
        "status": "FALLBACK_EXECUTED",
        "target": CapabilityId.BROWSER_ACQUIRE.value,
    }


def test_fake_workflow_returns_structured_replan_request() -> None:
    workflow = FakeWorkflow(ReliableWorkflowController(policy()))
    result = workflow.run(
        PolicyContext(
            no_progress_decision=NoProgressDecision(
                sequence=3,
                no_progress=True,
                reason=NoProgressReason.SAME_OPERATION_REPEAT,
                streak_count=3,
            )
        )
    )
    assert result["status"] == "REPLAN_REQUESTED"
    assert result["target"]


def test_controller_emits_policy_decision_for_allowed_operation(tmp_path: Path) -> None:
    recorder = TraceRecorder(tmp_path)
    trace = TraceContext("policy_allowed", "fake_workflow", recorder)
    decision = ReliableWorkflowController(policy()).decide(
        PolicyContext(stage="DISCOVER", operation="fake.next"),
        trace_context=trace,
    )
    events = read_events(recorder, "policy_allowed")
    assert decision.allowed is True
    assert [item.event_type for item in events] == [TraceEventType.POLICY_DECISION]
    assert events[0].output_summary["action"] == PolicyAction.CONTINUE.value


def test_controller_emits_policy_decision_and_denied_for_stop(tmp_path: Path) -> None:
    recorder = TraceRecorder(tmp_path)
    trace = TraceContext("policy_denied", "fake_workflow", recorder)
    decision = ReliableWorkflowController(policy()).decide(
        PolicyContext(
            stage="DISCOVER",
            operation="research.http_get",
            primary_error=execution_error(ErrorCode.AUTHENTICATION_FAILED),
        ),
        trace_context=trace,
    )
    events = read_events(recorder, "policy_denied")
    assert decision.action is PolicyAction.STOP
    assert [item.event_type for item in events] == [
        TraceEventType.POLICY_DECISION,
        TraceEventType.POLICY_DENIED,
    ]


def test_fallback_and_replan_trace_are_partial_and_denied(tmp_path: Path) -> None:
    recorder = TraceRecorder(tmp_path)
    trace = TraceContext("policy_partial", "fake_workflow", recorder)
    controller = ReliableWorkflowController(policy())
    controller.decide(
        PolicyContext(
            operation="research.http_get",
            tool_name=CapabilityId.HTTP_GET.value,
            target_domain="agency.example.com",
            primary_error=execution_error(ErrorCode.ACCESS_DENIED),
        ),
        trace_context=trace,
    )
    events = read_events(recorder, "policy_partial")
    assert len(events) == 2
    assert all(item.status.value == "PARTIAL" for item in events)


class FailingTraceRecorder:
    best_effort = False

    @property
    def healthy(self) -> bool:
        return False

    @property
    def errors(self) -> tuple:
        return ()

    @property
    def last_error(self):
        return RuntimeError("trace unavailable")

    def record(self, **event_fields):
        raise RuntimeError("trace unavailable")


def test_trace_failure_does_not_change_policy_enforcement() -> None:
    trace = TraceContext("trace_failure", "fake_workflow", FailingTraceRecorder())
    decision = ReliableWorkflowController(policy()).decide(
        PolicyContext(primary_error=execution_error(ErrorCode.AUTHENTICATION_FAILED)),
        trace_context=trace,
    )
    assert decision.action is PolicyAction.STOP
    assert decision.allowed is False


def test_trace_projection_contains_only_safe_policy_summary(tmp_path: Path) -> None:
    recorder = TraceRecorder(tmp_path)
    trace = TraceContext("policy_safe_trace", "fake_workflow", recorder)
    ReliableWorkflowController(policy()).decide(
        PolicyContext(
            operation="research.http_get",
            primary_error=ExecutionError(
                code=ErrorCode.AUTHENTICATION_FAILED,
                category=ErrorCategory.SECURITY,
                message="Authorization=Bearer super-secret",
                retryable=False,
                source="fixture",
                operation="research.http_get",
                details={"prompt": "private prompt", "api_key": "sk-private"},
            ),
        ),
        trace_context=trace,
    )
    raw = recorder.path_for("policy_safe_trace").read_text(encoding="utf-8")
    assert "super-secret" not in raw
    assert "private prompt" not in raw
    assert "sk-private" not in raw


def test_controller_evaluate_alias_returns_same_decision() -> None:
    controller = ReliableWorkflowController(policy())
    context = PolicyContext()
    assert controller.evaluate(context) == controller.decide(context)
