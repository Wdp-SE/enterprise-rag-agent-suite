"""Deterministic, opt-in task execution policy contracts.

This module is deliberately peripheral to Agent Core.  It decides whether a
declared workflow capability may run and how an outer workflow may react to
structured reliability state.  It does not execute tools, fallbacks, or
replanning.
"""

from __future__ import annotations

import re
import tomllib
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.reliability.budget import BudgetSnapshot
from app.reliability.errors import ErrorCode, ExecutionError
from app.reliability.progress import NoProgressDecision, NoProgressReason
from app.reliability.result import ExecutionResult
from app.reliability.retry import RetryOwner, SideEffectLevel
from app.reliability.trace import TraceSanitizer


_PROFILE_ID_PATTERN = re.compile(r"^[a-z0-9][a-z0-9_-]{0,127}$")
_DOMAIN_LABEL_PATTERN = re.compile(r"^[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?$")
_WINDOWS_DRIVE_PATTERN = re.compile(r"^[A-Za-z]:")
_DECISION_SANITIZER = TraceSanitizer()


class PolicyAction(str, Enum):
    CONTINUE = "CONTINUE"
    STOP = "STOP"
    FALLBACK = "FALLBACK"
    REPLAN = "REPLAN"


class PolicyReason(str, Enum):
    POLICY_DISABLED = "POLICY_DISABLED"
    ALLOWED = "ALLOWED"
    UNKNOWN_CAPABILITY = "UNKNOWN_CAPABILITY"
    CAPABILITY_METADATA_MISSING = "CAPABILITY_METADATA_MISSING"
    TOOL_DENIED = "TOOL_DENIED"
    TOOL_NOT_ALLOWED = "TOOL_NOT_ALLOWED"
    SIDE_EFFECT_DENIED = "SIDE_EFFECT_DENIED"
    NETWORK_ACCESS_DENIED = "NETWORK_ACCESS_DENIED"
    DOMAIN_REQUIRED = "DOMAIN_REQUIRED"
    DOMAIN_NOT_ALLOWED = "DOMAIN_NOT_ALLOWED"
    OUTPUT_ROOT_REQUIRED = "OUTPUT_ROOT_REQUIRED"
    OUTPUT_ROOT_INVALID = "OUTPUT_ROOT_INVALID"
    OUTPUT_ROOT_NOT_ALLOWED = "OUTPUT_ROOT_NOT_ALLOWED"
    EXTERNAL_WRITE_DENIED = "EXTERNAL_WRITE_DENIED"
    BUDGET_EXHAUSTED = "BUDGET_EXHAUSTED"
    RETRY_PENDING = "RETRY_PENDING"
    UNRECOVERABLE_ERROR = "UNRECOVERABLE_ERROR"
    ERROR_FALLBACK = "ERROR_FALLBACK"
    ERROR_STOP = "ERROR_STOP"
    NO_PROGRESS_FALLBACK = "NO_PROGRESS_FALLBACK"
    NO_PROGRESS_REPLAN = "NO_PROGRESS_REPLAN"
    NO_PROGRESS_STOP = "NO_PROGRESS_STOP"
    INVALID_FALLBACK_TARGET = "INVALID_FALLBACK_TARGET"


class PolicyEvaluationPoint(str, Enum):
    PRE_OPERATION = "PRE_OPERATION"
    POST_OPERATION = "POST_OPERATION"
    WORKFLOW = "WORKFLOW"


class CapabilityId(str, Enum):
    """Stable workflow capability identifiers, independent of Python classes."""

    WEB_SEARCH = "web_search"
    HTTP_GET = "http_get"
    BROWSER_ACQUIRE = "browser_acquire"
    EVIDENCE_EXTRACT = "evidence_extract"
    LLM_SYNTHESIS = "llm_synthesis"
    WORKSPACE_WRITE = "workspace_write"
    CANDIDATE_PACKAGE = "candidate_package"
    PYTHON_EXECUTE = "python_execute"
    STR_REPLACE_EDITOR = "str_replace_editor"
    APPROVE_CANDIDATE = "approve_candidate"
    RAG_INGESTION = "rag_ingestion"
    FAISS_WRITE = "faiss_write"
    EXTERNAL_PUBLISH = "external_publish"
    RAG_QUERY = "rag_query"
    TEMPLATE_READ = "template_read"
    DRAFT_WRITE = "draft_write"


@dataclass(frozen=True)
class CapabilitySpec:
    side_effect_level: SideEffectLevel
    network_required: bool
    external_write: bool = False
    default_output_root: str | None = None


# Conservative metadata is used only to validate a declared fallback target.
# The current operation must still provide explicit PRE_OPERATION metadata.
CAPABILITY_SPECS: dict[CapabilityId, CapabilitySpec] = {
    CapabilityId.RAG_QUERY: CapabilitySpec(SideEffectLevel.READ_ONLY, True),
    CapabilityId.TEMPLATE_READ: CapabilitySpec(SideEffectLevel.READ_ONLY, False),
    CapabilityId.DRAFT_WRITE: CapabilitySpec(SideEffectLevel.IDEMPOTENT_WRITE, False),
    CapabilityId.WEB_SEARCH: CapabilitySpec(SideEffectLevel.READ_ONLY, True),
    CapabilityId.HTTP_GET: CapabilitySpec(SideEffectLevel.READ_ONLY, True),
    CapabilityId.BROWSER_ACQUIRE: CapabilitySpec(
        SideEffectLevel.IDEMPOTENT_WRITE, True, default_output_root="research_runs"
    ),
    CapabilityId.EVIDENCE_EXTRACT: CapabilitySpec(
        SideEffectLevel.IDEMPOTENT_WRITE, False, default_output_root="research_runs"
    ),
    CapabilityId.LLM_SYNTHESIS: CapabilitySpec(SideEffectLevel.READ_ONLY, True),
    CapabilityId.WORKSPACE_WRITE: CapabilitySpec(
        SideEffectLevel.IDEMPOTENT_WRITE, False
    ),
    CapabilityId.CANDIDATE_PACKAGE: CapabilitySpec(
        SideEffectLevel.IDEMPOTENT_WRITE,
        False,
        default_output_root="candidate_knowledge",
    ),
    CapabilityId.PYTHON_EXECUTE: CapabilitySpec(
        SideEffectLevel.NON_IDEMPOTENT, False
    ),
    CapabilityId.STR_REPLACE_EDITOR: CapabilitySpec(
        SideEffectLevel.IDEMPOTENT_WRITE, False
    ),
    CapabilityId.APPROVE_CANDIDATE: CapabilitySpec(
        SideEffectLevel.NON_IDEMPOTENT, True, external_write=True
    ),
    CapabilityId.RAG_INGESTION: CapabilitySpec(
        SideEffectLevel.NON_IDEMPOTENT, True, external_write=True
    ),
    CapabilityId.FAISS_WRITE: CapabilitySpec(
        SideEffectLevel.NON_IDEMPOTENT, False, external_write=True
    ),
    CapabilityId.EXTERNAL_PUBLISH: CapabilitySpec(
        SideEffectLevel.NON_IDEMPOTENT, True, external_write=True
    ),
}


def _normalize_domain_pattern(value: str) -> str:
    candidate = str(value).strip().casefold().rstrip(".")
    wildcard = candidate.startswith("*.")
    hostname = candidate[2:] if wildcard else candidate
    if (
        not hostname
        or candidate == "*"
        or "://" in candidate
        or any(character in candidate for character in "/\\?#:@")
        or "*" in hostname
    ):
        raise ValueError("domain rules must be exact hosts or explicit *.example.com patterns")
    try:
        hostname = hostname.encode("idna").decode("ascii")
    except UnicodeError as exc:
        raise ValueError("invalid domain rule") from exc
    labels = hostname.split(".")
    if len(labels) < 2 or any(not _DOMAIN_LABEL_PATTERN.fullmatch(label) for label in labels):
        raise ValueError("invalid domain rule")
    return f"*.{hostname}" if wildcard else hostname


def _normalize_target_domain(value: str) -> str | None:
    candidate = str(value).strip().casefold().rstrip(".")
    if (
        not candidate
        or "://" in candidate
        or any(character in candidate for character in "/\\?#:@*")
    ):
        return None
    try:
        candidate = candidate.encode("idna").decode("ascii")
    except UnicodeError:
        return None
    labels = candidate.split(".")
    if len(labels) < 2 or any(not _DOMAIN_LABEL_PATTERN.fullmatch(label) for label in labels):
        return None
    return candidate


def _domain_allowed(hostname: str, patterns: frozenset[str]) -> bool:
    for pattern in sorted(patterns):
        if pattern.startswith("*."):
            suffix = pattern[1:]
            if hostname.endswith(suffix) and hostname != pattern[2:]:
                return True
        elif hostname == pattern:
            return True
    return False


def _normalize_output_root(value: str) -> str:
    candidate = str(value).strip()
    if (
        not candidate
        or candidate.startswith(("/", "\\", "//", "\\\\"))
        or _WINDOWS_DRIVE_PATTERN.match(candidate)
    ):
        raise ValueError("output roots must be workspace-relative logical paths")
    candidate = candidate.replace("\\", "/").strip("/")
    parts = candidate.split("/")
    if any(part in {"", ".", ".."} for part in parts):
        raise ValueError("output roots cannot contain empty, dot, or parent segments")
    return "/".join(parts)


def _output_root_allowed(root: str, allowed_roots: frozenset[str]) -> bool:
    return any(root == allowed or root.startswith(f"{allowed}/") for allowed in sorted(allowed_roots))


class TaskPolicyProfile(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)

    profile_id: str = Field(pattern=_PROFILE_ID_PATTERN.pattern)
    enabled: bool = True
    allowed_tools: frozenset[CapabilityId] | None = None
    denied_tools: frozenset[CapabilityId] = Field(default_factory=frozenset)
    network_access: bool = False
    allowed_domains: frozenset[str] | None = None
    allowed_output_roots: frozenset[str] | None = None
    allow_external_writes: bool = False
    allowed_side_effect_levels: frozenset[SideEffectLevel] = Field(
        default_factory=lambda: frozenset({SideEffectLevel.READ_ONLY})
    )
    operation_fallbacks: dict[str, CapabilityId] = Field(default_factory=dict)
    tool_fallbacks: dict[CapabilityId, CapabilityId] = Field(default_factory=dict)
    error_fallbacks: dict[ErrorCode, CapabilityId] = Field(default_factory=dict)
    no_progress_actions: dict[NoProgressReason, PolicyAction] = Field(default_factory=dict)
    no_progress_fallbacks: dict[NoProgressReason, CapabilityId] = Field(default_factory=dict)
    timeout_profile: str | None = Field(default=None, max_length=128)
    retry_profile: str | None = Field(default=None, max_length=128)
    budget_profile: str | None = Field(default=None, max_length=128)

    @field_validator("allowed_domains", mode="before")
    @classmethod
    def normalize_domains(cls, value: Any) -> Any:
        if value is None:
            return None
        return frozenset(_normalize_domain_pattern(item) for item in value)

    @field_validator("allowed_output_roots", mode="before")
    @classmethod
    def normalize_output_roots(cls, value: Any) -> Any:
        if value is None:
            return None
        return frozenset(_normalize_output_root(item) for item in value)

    @field_validator("operation_fallbacks", mode="before")
    @classmethod
    def normalize_operation_fallbacks(cls, value: Any) -> dict[str, Any]:
        normalized: dict[str, Any] = {}
        for key, target in (value or {}).items():
            operation = str(key).strip()
            if not operation:
                raise ValueError("operation fallback keys cannot be blank")
            normalized[operation] = target
        return normalized

    @model_validator(mode="after")
    def validate_profile_contract(self) -> "TaskPolicyProfile":
        if self.allowed_tools is not None:
            overlap = self.allowed_tools.intersection(self.denied_tools)
            if overlap:
                names = ", ".join(sorted(item.value for item in overlap))
                raise ValueError(f"allowed_tools and denied_tools overlap: {names}")
        return self

    @classmethod
    def disabled(cls, profile_id: str = "disabled") -> "TaskPolicyProfile":
        return cls(profile_id=profile_id, enabled=False)

    @classmethod
    def from_toml(cls, path: str | Path) -> "TaskPolicyProfile":
        source = Path(path)
        with source.open("rb") as handle:
            payload = tomllib.load(handle)
        values = payload.get("policy", payload)
        if not isinstance(values, dict):
            raise ValueError("task policy TOML must contain a mapping")
        return cls.model_validate(values)


class PolicyRetryState(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    retry_pending: bool = False
    retry_exhausted: bool = False
    attempt: int | None = Field(default=None, ge=1)
    max_attempts: int | None = Field(default=None, ge=1)
    retry_owner: RetryOwner | None = None

    @model_validator(mode="after")
    def validate_retry_state(self) -> "PolicyRetryState":
        if self.retry_pending and self.retry_exhausted:
            raise ValueError("retry cannot be both pending and exhausted")
        if (
            self.attempt is not None
            and self.max_attempts is not None
            and self.attempt > self.max_attempts
        ):
            raise ValueError("attempt cannot exceed max_attempts")
        return self


class PolicyContext(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, arbitrary_types_allowed=True)

    task_type: str | None = Field(default=None, max_length=128)
    workflow: str | None = Field(default=None, max_length=128)
    stage: str | None = Field(default=None, max_length=128)
    evaluation_point: PolicyEvaluationPoint = PolicyEvaluationPoint.WORKFLOW
    execution_result: ExecutionResult[Any] | None = None
    primary_error: ExecutionError | None = None
    budget_snapshot: BudgetSnapshot | None = None
    no_progress_decision: NoProgressDecision | None = None
    operation: str | None = Field(default=None, max_length=128)
    tool_name: str | None = Field(default=None, max_length=128)
    side_effect_level: SideEffectLevel | str | None = None
    network_required: bool | None = None
    target_domain: str | None = Field(default=None, max_length=253)
    output_root: str | None = Field(default=None, max_length=512)
    external_write: bool | None = None
    retry_state: PolicyRetryState | None = None

    @field_validator("side_effect_level", mode="before")
    @classmethod
    def preserve_unknown_side_effect(cls, value: Any) -> Any:
        if value is None or isinstance(value, SideEffectLevel):
            return value
        candidate = str(value).strip()
        try:
            return SideEffectLevel(candidate)
        except ValueError:
            return candidate

    @model_validator(mode="after")
    def validate_error_sources(self) -> "PolicyContext":
        result_error = self.execution_result.primary_error if self.execution_result else None
        if self.primary_error is not None and result_error is not None and self.primary_error != result_error:
            raise ValueError("primary_error conflicts with execution_result.primary_error")
        return self

    @property
    def resolved_error(self) -> ExecutionError | None:
        if self.primary_error is not None:
            return self.primary_error
        return self.execution_result.primary_error if self.execution_result else None


class PolicyDecision(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    action: PolicyAction
    reason_code: PolicyReason
    message: str = Field(min_length=1, max_length=2300)
    allowed: bool
    fallback_target: CapabilityId | None = None
    replan_hint: str | None = Field(default=None, max_length=2300)
    policy_profile: str = Field(min_length=1, max_length=128)
    details: dict[str, Any] = Field(default_factory=dict)

    @field_validator("message", "replan_hint", mode="before")
    @classmethod
    def sanitize_text(cls, value: Any) -> Any:
        if value is None:
            return None
        return _DECISION_SANITIZER.sanitize_text(str(value))

    @field_validator("details", mode="before")
    @classmethod
    def sanitize_details(cls, value: Any) -> dict[str, Any]:
        if value is None:
            return {}
        if not isinstance(value, dict):
            value = {"value": value}
        return _DECISION_SANITIZER.sanitize(value)

    @model_validator(mode="after")
    def validate_decision_contract(self) -> "PolicyDecision":
        expected_allowed = self.action is PolicyAction.CONTINUE
        if self.allowed is not expected_allowed:
            raise ValueError("allowed must be true only for CONTINUE")
        if self.action is PolicyAction.FALLBACK and self.fallback_target is None:
            raise ValueError("FALLBACK requires fallback_target")
        if self.action is not PolicyAction.FALLBACK and self.fallback_target is not None:
            raise ValueError("fallback_target is only valid for FALLBACK")
        if self.action is PolicyAction.REPLAN and not self.replan_hint:
            raise ValueError("REPLAN requires replan_hint")
        if self.action is not PolicyAction.REPLAN and self.replan_hint is not None:
            raise ValueError("replan_hint is only valid for REPLAN")
        return self


_HARD_STOP_ERRORS = frozenset(
    {
        ErrorCode.AUTHENTICATION_FAILED,
        ErrorCode.INVALID_INPUT,
        ErrorCode.POLICY_BLOCKED,
        ErrorCode.CANCELLED,
        ErrorCode.INTERNAL_ERROR,
        ErrorCode.INSUFFICIENT_EVIDENCE,
        ErrorCode.RESOURCE_EXHAUSTED,
    }
)
_FALLBACK_ELIGIBLE_ERRORS = frozenset(
    {
        ErrorCode.ACCESS_DENIED,
        ErrorCode.TOOL_CAPABILITY_UNAVAILABLE,
        ErrorCode.UNSUPPORTED_CONTENT,
        ErrorCode.TRANSIENT_NETWORK,
        ErrorCode.OPERATION_TIMEOUT,
        ErrorCode.RATE_LIMITED,
        ErrorCode.EXTERNAL_SERVICE_FAILED,
        ErrorCode.RESPONSE_PARSE_FAILED,
    }
)


class TaskPolicy:
    """Pure deterministic policy evaluator."""

    def __init__(self, profile: TaskPolicyProfile):
        self.profile = profile

    @classmethod
    def disabled(cls) -> "TaskPolicy":
        return cls(TaskPolicyProfile.disabled())

    def evaluate(self, context: PolicyContext) -> PolicyDecision:
        if not self.profile.enabled:
            return self._continue(
                PolicyReason.POLICY_DISABLED,
                "Task policy is disabled; existing workflow behavior is preserved",
            )

        capability_denial = self._evaluate_current_capability(context)
        if capability_denial is not None:
            return capability_denial

        error = context.resolved_error
        exhausted = tuple(
            sorted(
                (context.budget_snapshot.exhausted_dimensions if context.budget_snapshot else []),
                key=lambda item: item.value,
            )
        )
        if (error is not None and error.code is ErrorCode.BUDGET_EXCEEDED) or exhausted:
            return self._stop(
                PolicyReason.BUDGET_EXHAUSTED,
                "Execution budget is exhausted; no further operation is allowed",
                details={"exhausted_dimensions": [item.value for item in exhausted]},
            )

        retry_state = context.retry_state
        if retry_state is not None and retry_state.retry_pending and not retry_state.retry_exhausted:
            return self._continue(
                PolicyReason.RETRY_PENDING,
                "RetryPolicy still owns the current operation decision",
                details={
                    "attempt": retry_state.attempt,
                    "max_attempts": retry_state.max_attempts,
                    "retry_owner": retry_state.retry_owner.value if retry_state.retry_owner else None,
                },
            )

        if error is not None and error.code in _HARD_STOP_ERRORS:
            return self._stop(
                PolicyReason.UNRECOVERABLE_ERROR,
                f"Unrecoverable execution error: {error.code.value}",
                details={"error_code": error.code.value},
            )

        no_progress = context.no_progress_decision
        if no_progress is not None and no_progress.no_progress and no_progress.reason is not None:
            return self._decide_no_progress(context, no_progress.reason)

        if error is not None:
            if error.code in _FALLBACK_ELIGIBLE_ERRORS:
                target = self._resolve_fallback(context, error_code=error.code)
                if target is not None:
                    return self._fallback_or_stop(
                        context,
                        target,
                        PolicyReason.ERROR_FALLBACK,
                        f"Fallback declared after {error.code.value}",
                        details={"error_code": error.code.value},
                    )
            return self._stop(
                PolicyReason.ERROR_STOP,
                f"No permitted continuation after {error.code.value}",
                details={"error_code": error.code.value},
            )

        return self._continue(PolicyReason.ALLOWED, "Task policy allows the operation")

    def _evaluate_current_capability(self, context: PolicyContext) -> PolicyDecision | None:
        has_capability_metadata = any(
            value is not None
            for value in (
                context.tool_name,
                context.side_effect_level,
                context.network_required,
                context.output_root,
                context.external_write,
            )
        )
        if context.evaluation_point is PolicyEvaluationPoint.PRE_OPERATION:
            missing = [
                name
                for name, value in (
                    ("operation", context.operation),
                    ("tool_name", context.tool_name),
                    ("side_effect_level", context.side_effect_level),
                    ("network_required", context.network_required),
                    ("external_write", context.external_write),
                )
                if value is None
            ]
            if missing:
                return self._stop(
                    PolicyReason.CAPABILITY_METADATA_MISSING,
                    "PRE_OPERATION capability metadata is incomplete",
                    details={"missing_fields": sorted(missing)},
                )
        elif not has_capability_metadata:
            return None

        capability = self._parse_capability(context.tool_name)
        if capability is None:
            return self._stop(
                PolicyReason.UNKNOWN_CAPABILITY,
                "The requested capability is not registered",
            )
        if capability in self.profile.denied_tools:
            return self._stop(PolicyReason.TOOL_DENIED, "The requested capability is explicitly denied")
        if self.profile.allowed_tools is not None and capability not in self.profile.allowed_tools:
            return self._stop(PolicyReason.TOOL_NOT_ALLOWED, "The requested capability is not allowlisted")

        side_effect = context.side_effect_level
        if side_effect is not None and not isinstance(side_effect, SideEffectLevel):
            return self._stop(
                PolicyReason.SIDE_EFFECT_DENIED,
                "Unknown side-effect level is denied",
            )
        if isinstance(side_effect, SideEffectLevel) and side_effect not in self.profile.allowed_side_effect_levels:
            return self._stop(
                PolicyReason.SIDE_EFFECT_DENIED,
                f"Side-effect level {side_effect.value} is not permitted",
            )

        if context.network_required is True:
            if not self.profile.network_access:
                return self._stop(PolicyReason.NETWORK_ACCESS_DENIED, "Network access is disabled by policy")
            domain_denial = self._validate_domain(context.target_domain)
            if domain_denial is not None:
                return domain_denial

        if context.output_root is not None:
            output_denial = self._validate_output_root(context.output_root)
            if output_denial is not None:
                return output_denial
        elif (
            context.evaluation_point is PolicyEvaluationPoint.PRE_OPERATION
            and side_effect is SideEffectLevel.IDEMPOTENT_WRITE
            and self.profile.allowed_output_roots is not None
            and context.external_write is False
        ):
            return self._stop(
                PolicyReason.OUTPUT_ROOT_REQUIRED,
                "A workspace output root is required for this write",
            )

        if context.external_write is True and not self.profile.allow_external_writes:
            return self._stop(PolicyReason.EXTERNAL_WRITE_DENIED, "External writes are disabled by policy")
        return None

    def _validate_domain(self, value: str | None) -> PolicyDecision | None:
        patterns = self.profile.allowed_domains
        if patterns is None:
            return None
        if value is None:
            return self._stop(PolicyReason.DOMAIN_REQUIRED, "A target domain is required by the allowlist")
        hostname = _normalize_target_domain(value)
        if hostname is None or not _domain_allowed(hostname, patterns):
            return self._stop(PolicyReason.DOMAIN_NOT_ALLOWED, "The target domain is not allowlisted")
        return None

    def _validate_output_root(self, value: str) -> PolicyDecision | None:
        try:
            normalized = _normalize_output_root(value)
        except ValueError:
            return self._stop(PolicyReason.OUTPUT_ROOT_INVALID, "The output root is not a safe logical path")
        roots = self.profile.allowed_output_roots
        if roots is not None and not _output_root_allowed(normalized, roots):
            return self._stop(PolicyReason.OUTPUT_ROOT_NOT_ALLOWED, "The output root is not allowlisted")
        return None

    def _decide_no_progress(
        self,
        context: PolicyContext,
        reason: NoProgressReason,
    ) -> PolicyDecision:
        action = self.profile.no_progress_actions.get(reason, PolicyAction.STOP)
        if action is PolicyAction.CONTINUE:
            return self._continue(
                PolicyReason.ALLOWED,
                f"Profile allows continuation after {reason.value}",
                details={"no_progress_reason": reason.value},
            )
        if action is PolicyAction.REPLAN:
            return PolicyDecision(
                action=PolicyAction.REPLAN,
                reason_code=PolicyReason.NO_PROGRESS_REPLAN,
                message=f"Workflow should replan after {reason.value}",
                allowed=False,
                replan_hint=f"Select a different operation plan after {reason.value}",
                policy_profile=self.profile.profile_id,
                details={"no_progress_reason": reason.value},
            )
        if action is PolicyAction.FALLBACK:
            target = self._resolve_fallback(context, no_progress_reason=reason)
            if target is not None:
                return self._fallback_or_stop(
                    context,
                    target,
                    PolicyReason.NO_PROGRESS_FALLBACK,
                    f"Fallback declared after {reason.value}",
                    details={"no_progress_reason": reason.value},
                )
        return self._stop(
            PolicyReason.NO_PROGRESS_STOP,
            f"Workflow should stop after {reason.value}",
            details={"no_progress_reason": reason.value},
        )

    def _resolve_fallback(
        self,
        context: PolicyContext,
        *,
        error_code: ErrorCode | None = None,
        no_progress_reason: NoProgressReason | None = None,
    ) -> CapabilityId | None:
        if context.operation and context.operation in self.profile.operation_fallbacks:
            return self.profile.operation_fallbacks[context.operation]
        capability = self._parse_capability(context.tool_name)
        if capability is not None and capability in self.profile.tool_fallbacks:
            return self.profile.tool_fallbacks[capability]
        if error_code is not None:
            return self.profile.error_fallbacks.get(error_code)
        if no_progress_reason is not None:
            return self.profile.no_progress_fallbacks.get(no_progress_reason)
        return None

    def _fallback_or_stop(
        self,
        context: PolicyContext,
        target: CapabilityId,
        reason: PolicyReason,
        message: str,
        *,
        details: dict[str, Any],
    ) -> PolicyDecision:
        invalid = self._fallback_invalid_reason(context, target)
        if invalid is not None:
            return self._stop(
                PolicyReason.INVALID_FALLBACK_TARGET,
                "Configured fallback target is not permitted",
                details={**details, "fallback_validation": invalid},
            )
        return PolicyDecision(
            action=PolicyAction.FALLBACK,
            reason_code=reason,
            message=message,
            allowed=False,
            fallback_target=target,
            policy_profile=self.profile.profile_id,
            details=details,
        )

    def _fallback_invalid_reason(
        self, context: PolicyContext, target: CapabilityId
    ) -> str | None:
        spec = CAPABILITY_SPECS.get(target)
        if spec is None:
            return "unknown_capability"
        if target in self.profile.denied_tools:
            return "denied_capability"
        if self.profile.allowed_tools is not None and target not in self.profile.allowed_tools:
            return "capability_not_allowlisted"
        if spec.side_effect_level not in self.profile.allowed_side_effect_levels:
            return "side_effect_not_allowed"
        if spec.external_write and not self.profile.allow_external_writes:
            return "external_write_not_allowed"
        if spec.network_required:
            if not self.profile.network_access:
                return "network_not_allowed"
            if self.profile.allowed_domains is not None:
                hostname = _normalize_target_domain(context.target_domain or "")
                if hostname is None or not _domain_allowed(hostname, self.profile.allowed_domains):
                    return "domain_not_allowed"
        output_root = spec.default_output_root or context.output_root
        if output_root is not None:
            try:
                normalized = _normalize_output_root(output_root)
            except ValueError:
                return "invalid_output_root"
            if (
                self.profile.allowed_output_roots is not None
                and not _output_root_allowed(normalized, self.profile.allowed_output_roots)
            ):
                return "output_root_not_allowed"
        elif (
            spec.side_effect_level is SideEffectLevel.IDEMPOTENT_WRITE
            and self.profile.allowed_output_roots is not None
        ):
            return "output_root_required"
        return None

    @staticmethod
    def _parse_capability(value: str | None) -> CapabilityId | None:
        if value is None:
            return None
        try:
            return CapabilityId(str(value).strip())
        except ValueError:
            return None

    def _continue(
        self,
        reason: PolicyReason,
        message: str,
        *,
        details: dict[str, Any] | None = None,
    ) -> PolicyDecision:
        return PolicyDecision(
            action=PolicyAction.CONTINUE,
            reason_code=reason,
            message=message,
            allowed=True,
            policy_profile=self.profile.profile_id,
            details=details or {},
        )

    def _stop(
        self,
        reason: PolicyReason,
        message: str,
        *,
        details: dict[str, Any] | None = None,
    ) -> PolicyDecision:
        return PolicyDecision(
            action=PolicyAction.STOP,
            reason_code=reason,
            message=message,
            allowed=False,
            policy_profile=self.profile.profile_id,
            details=details or {},
        )
