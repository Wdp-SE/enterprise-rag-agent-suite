"""Optional reliability contracts; importing this package instruments nothing."""

from __future__ import annotations

from importlib import import_module
from typing import Any


_EXPORTS = {
    "ErrorCategory": ("app.reliability.errors", "ErrorCategory"),
    "ErrorClassifier": ("app.reliability.errors", "ErrorClassifier"),
    "ErrorCode": ("app.reliability.errors", "ErrorCode"),
    "ExecutionError": ("app.reliability.errors", "ExecutionError"),
    "ExecutionErrorRaised": ("app.reliability.errors", "ExecutionErrorRaised"),
    "ExecutionResult": ("app.reliability.result", "ExecutionResult"),
    "ExecutionStatus": ("app.reliability.result", "ExecutionStatus"),
    "execution_result_from_tool_result": (
        "app.reliability.result",
        "execution_result_from_tool_result",
    ),
    "Clock": ("app.reliability.trace", "Clock"),
    "NoopTraceRecorder": ("app.reliability.trace", "NoopTraceRecorder"),
    "SystemClock": ("app.reliability.trace", "SystemClock"),
    "TraceContext": ("app.reliability.trace", "TraceContext"),
    "TraceEvent": ("app.reliability.trace", "TraceEvent"),
    "TraceEventType": ("app.reliability.trace", "TraceEventType"),
    "TraceRecorder": ("app.reliability.trace", "TraceRecorder"),
    "TraceRecorderError": ("app.reliability.trace", "TraceRecorderError"),
    "TraceSanitizer": ("app.reliability.trace", "TraceSanitizer"),
    "TraceSpanKind": ("app.reliability.trace", "TraceSpanKind"),
    "TraceStatus": ("app.reliability.trace", "TraceStatus"),
    "TimeoutEnforcement": ("app.reliability.timeout", "TimeoutEnforcement"),
    "TimeoutPolicy": ("app.reliability.timeout", "TimeoutPolicy"),
    "TimeoutResolution": ("app.reliability.timeout", "TimeoutResolution"),
    "TimeoutResolver": ("app.reliability.timeout", "TimeoutResolver"),
    "TimeoutRule": ("app.reliability.timeout", "TimeoutRule"),
    "AsyncioSleeper": ("app.reliability.retry", "AsyncioSleeper"),
    "RetryContext": ("app.reliability.retry", "RetryContext"),
    "RetryDecision": ("app.reliability.retry", "RetryDecision"),
    "RetryOwner": ("app.reliability.retry", "RetryOwner"),
    "RetryPolicy": ("app.reliability.retry", "RetryPolicy"),
    "RetryRule": ("app.reliability.retry", "RetryRule"),
    "SideEffectLevel": ("app.reliability.retry", "SideEffectLevel"),
    "BudgetAccountingError": ("app.reliability.budget", "BudgetAccountingError"),
    "BudgetDimension": ("app.reliability.budget", "BudgetDimension"),
    "BudgetExceededError": ("app.reliability.budget", "BudgetExceededError"),
    "BudgetLedger": ("app.reliability.budget", "BudgetLedger"),
    "BudgetPreview": ("app.reliability.budget", "BudgetPreview"),
    "BudgetReservation": ("app.reliability.budget", "BudgetReservation"),
    "BudgetReservationStatus": (
        "app.reliability.budget",
        "BudgetReservationStatus",
    ),
    "BudgetSnapshot": ("app.reliability.budget", "BudgetSnapshot"),
    "ExecutionBudget": ("app.reliability.budget", "ExecutionBudget"),
    "NoProgressDecision": ("app.reliability.progress", "NoProgressDecision"),
    "NoProgressDetector": ("app.reliability.progress", "NoProgressDetector"),
    "NoProgressEvidence": ("app.reliability.progress", "NoProgressEvidence"),
    "NoProgressReason": ("app.reliability.progress", "NoProgressReason"),
    "ProgressSignal": ("app.reliability.progress", "ProgressSignal"),
    "TraceProgressAdapter": (
        "app.reliability.progress",
        "TraceProgressAdapter",
    ),
    "safe_identity_hash": ("app.reliability.progress", "safe_identity_hash"),
    "DeadlineSource": ("app.reliability.executor", "DeadlineSource"),
    "OperationAttempt": ("app.reliability.executor", "OperationAttempt"),
    "OperationDeadline": ("app.reliability.executor", "OperationDeadline"),
    "OperationSpec": ("app.reliability.executor", "OperationSpec"),
    "ReliableOperationExecutor": (
        "app.reliability.executor",
        "ReliableOperationExecutor",
    ),
    "CapabilityId": ("app.reliability.policy", "CapabilityId"),
    "PolicyAction": ("app.reliability.policy", "PolicyAction"),
    "PolicyContext": ("app.reliability.policy", "PolicyContext"),
    "PolicyDecision": ("app.reliability.policy", "PolicyDecision"),
    "PolicyEvaluationPoint": (
        "app.reliability.policy",
        "PolicyEvaluationPoint",
    ),
    "PolicyReason": ("app.reliability.policy", "PolicyReason"),
    "PolicyRetryState": ("app.reliability.policy", "PolicyRetryState"),
    "TaskPolicy": ("app.reliability.policy", "TaskPolicy"),
    "TaskPolicyProfile": ("app.reliability.policy", "TaskPolicyProfile"),
    "ReliableWorkflowController": (
        "app.reliability.workflow_control",
        "ReliableWorkflowController",
    ),
}

__all__ = list(_EXPORTS)


def __getattr__(name: str) -> Any:
    try:
        module_name, attribute = _EXPORTS[name]
    except KeyError as exc:
        raise AttributeError(name) from exc
    value = getattr(import_module(module_name), attribute)
    globals()[name] = value
    return value
