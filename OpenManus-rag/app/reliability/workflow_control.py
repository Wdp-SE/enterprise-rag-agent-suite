"""Peripheral projection from TaskPolicy decisions to workflow control signals."""

from __future__ import annotations

from app.reliability.policy import (
    PolicyAction,
    PolicyContext,
    PolicyDecision,
    TaskPolicy,
)
from app.reliability.trace import (
    TraceContext,
    TraceEventType,
    TraceSanitizer,
    TraceStatus,
)


class ReliableWorkflowController:
    """Evaluate policy and emit best-effort Trace events.

    The returned decision is the only control contract.  This class never
    executes a tool, fallback, or replan action.
    """

    def __init__(self, policy: TaskPolicy):
        self.policy = policy
        self._sanitizer = TraceSanitizer()

    def decide(
        self,
        context: PolicyContext,
        *,
        trace_context: TraceContext | None = None,
        span_id: str | None = None,
        parent_span_id: str | None = None,
    ) -> PolicyDecision:
        decision = self.policy.evaluate(context)
        if trace_context is not None:
            self._record_decision(
                decision,
                context,
                trace_context,
                span_id=span_id,
                parent_span_id=parent_span_id,
            )
        return decision

    evaluate = decide

    def _record_decision(
        self,
        decision: PolicyDecision,
        context: PolicyContext,
        trace_context: TraceContext,
        *,
        span_id: str | None,
        parent_span_id: str | None,
    ) -> None:
        # Enforcement state is already decided.  Trace persistence is strictly
        # best effort and must never alter or suppress the decision.
        try:
            event_span_id = span_id or trace_context.allocate_span_id(
                context.operation or "policy.evaluate"
            )
            error = context.resolved_error
            exhausted = sorted(
                (
                    item.value
                    for item in (
                        context.budget_snapshot.exhausted_dimensions
                        if context.budget_snapshot
                        else []
                    )
                )
            )
            no_progress_reason = (
                context.no_progress_decision.reason.value
                if context.no_progress_decision
                and context.no_progress_decision.reason is not None
                else None
            )
            summary = self._sanitizer.sanitize(
                {
                    "action": decision.action.value,
                    "reason_code": decision.reason_code.value,
                    "policy_profile": decision.policy_profile,
                    "allowed": decision.allowed,
                    "fallback_target": (
                        decision.fallback_target.value
                        if decision.fallback_target is not None
                        else None
                    ),
                    "has_replan_hint": decision.replan_hint is not None,
                    "budget_exhausted_dimensions": exhausted,
                    "no_progress_reason": no_progress_reason,
                }
            )
            status = {
                PolicyAction.CONTINUE: TraceStatus.SUCCESS,
                PolicyAction.STOP: TraceStatus.FAILED,
                PolicyAction.FALLBACK: TraceStatus.PARTIAL,
                PolicyAction.REPLAN: TraceStatus.PARTIAL,
            }[decision.action]
            event_fields = {
                "status": status,
                "stage": context.stage,
                "span_id": event_span_id,
                "parent_span_id": parent_span_id,
                "tool_name": context.tool_name,
                "operation": context.operation or "policy.evaluate",
                "error_code": error.code if error else None,
                "error_category": error.category if error else None,
                "retryable": error.retryable if error else None,
                "output_summary": summary,
            }
            trace_context.emit(
                event_type=TraceEventType.POLICY_DECISION,
                **event_fields,
            )
            if not decision.allowed:
                trace_context.emit(
                    event_type=TraceEventType.POLICY_DENIED,
                    **event_fields,
                )
        except Exception:
            return

