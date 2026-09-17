"""Configurable timeout resolution without changing existing operation defaults."""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class TimeoutEnforcement(str, Enum):
    NATIVE = "NATIVE"
    ASYNCIO_FALLBACK = "ASYNCIO_FALLBACK"
    DISABLED = "DISABLED"


class TimeoutScope(str, Enum):
    EXACT_OPERATION = "EXACT_OPERATION"
    TOOL = "TOOL"
    STAGE = "STAGE"
    WORKFLOW = "WORKFLOW"
    DEFAULT = "DEFAULT"
    DISABLED = "DISABLED"


class TimeoutRule(BaseModel):
    """One timeout rule; native phase values are optional SDK hints."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    timeout_ms: int | None = Field(default=None, gt=0)
    enforcement: TimeoutEnforcement = TimeoutEnforcement.DISABLED
    connect_ms: int | None = Field(default=None, gt=0)
    read_ms: int | None = Field(default=None, gt=0)
    write_ms: int | None = Field(default=None, gt=0)
    pool_ms: int | None = Field(default=None, gt=0)

    @model_validator(mode="after")
    def validate_enabled_rule(self) -> "TimeoutRule":
        phase_values = (self.connect_ms, self.read_ms, self.write_ms, self.pool_ms)
        if self.enforcement is TimeoutEnforcement.DISABLED:
            if self.timeout_ms is not None or any(value is not None for value in phase_values):
                raise ValueError("disabled timeout rule cannot define timeout values")
        elif self.timeout_ms is None:
            raise ValueError("enabled timeout rule requires timeout_ms")
        if self.enforcement is not TimeoutEnforcement.NATIVE and any(
            value is not None for value in phase_values
        ):
            raise ValueError("connect/read/write/pool values require NATIVE enforcement")
        return self

    @classmethod
    def disabled(cls) -> "TimeoutRule":
        return cls()


class TimeoutResolution(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    rule: TimeoutRule
    scope: TimeoutScope
    matched_key: str | None = None

    @property
    def enabled(self) -> bool:
        return self.rule.enforcement is not TimeoutEnforcement.DISABLED


class TimeoutPolicy(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    operation_rules: dict[str, TimeoutRule] = Field(default_factory=dict)
    tool_rules: dict[str, TimeoutRule] = Field(default_factory=dict)
    stage_rules: dict[str, TimeoutRule] = Field(default_factory=dict)
    workflow_rules: dict[str, TimeoutRule] = Field(default_factory=dict)
    default_rule: TimeoutRule = Field(default_factory=TimeoutRule.disabled)

    @field_validator(
        "operation_rules",
        "tool_rules",
        "stage_rules",
        "workflow_rules",
        mode="before",
    )
    @classmethod
    def validate_rule_keys(cls, value):
        value = value or {}
        if any(not str(key).strip() for key in value):
            raise ValueError("timeout rule keys cannot be blank")
        return {str(key).strip(): rule for key, rule in value.items()}

    @classmethod
    def disabled(cls) -> "TimeoutPolicy":
        return cls()


class TimeoutResolver:
    def __init__(self, policy: TimeoutPolicy):
        self.policy = policy

    def resolve(
        self,
        *,
        operation: str,
        tool_name: str | None = None,
        stage: str | None = None,
        workflow: str | None = None,
    ) -> TimeoutResolution:
        candidates = (
            (TimeoutScope.EXACT_OPERATION, operation, self.policy.operation_rules),
            (TimeoutScope.TOOL, tool_name, self.policy.tool_rules),
            (TimeoutScope.STAGE, stage, self.policy.stage_rules),
            (TimeoutScope.WORKFLOW, workflow, self.policy.workflow_rules),
        )
        for scope, key, rules in candidates:
            if key is not None and key in rules:
                return TimeoutResolution(rule=rules[key], scope=scope, matched_key=key)
        if self.policy.default_rule.enforcement is TimeoutEnforcement.DISABLED:
            return TimeoutResolution(
                rule=self.policy.default_rule,
                scope=TimeoutScope.DISABLED,
            )
        return TimeoutResolution(
            rule=self.policy.default_rule,
            scope=TimeoutScope.DEFAULT,
            matched_key="default",
        )
