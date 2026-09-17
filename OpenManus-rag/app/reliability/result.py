"""Generic execution results that coexist with OpenManus ToolResult."""

from __future__ import annotations

from enum import Enum
from typing import Any, Generic, TypeVar

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.reliability.errors import ErrorClassifier, ExecutionError, SensitiveDataSanitizer
from app.tool.base import ToolResult


T = TypeVar("T")
_METADATA_SANITIZER = SensitiveDataSanitizer(max_text_length=512)


class ExecutionStatus(str, Enum):
    SUCCESS = "SUCCESS"
    PARTIAL = "PARTIAL"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


class ExecutionResult(BaseModel, Generic[T]):
    model_config = ConfigDict(extra="forbid", arbitrary_types_allowed=True)

    status: ExecutionStatus
    value: T | None = None
    errors: tuple[ExecutionError, ...] = Field(default_factory=tuple)
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("metadata", mode="before")
    @classmethod
    def sanitize_metadata(cls, value: Any) -> dict[str, Any]:
        if value is None:
            return {}
        if not isinstance(value, dict):
            value = {"value": value}
        return _METADATA_SANITIZER.sanitize(value)

    @model_validator(mode="after")
    def validate_status_contract(self) -> "ExecutionResult[T]":
        if self.status is ExecutionStatus.SUCCESS and self.errors:
            raise ValueError("SUCCESS ExecutionResult cannot contain errors")
        if self.status in {ExecutionStatus.FAILED, ExecutionStatus.CANCELLED} and not self.errors:
            raise ValueError(f"{self.status.value} ExecutionResult requires an error")
        return self

    @property
    def primary_error(self) -> ExecutionError | None:
        return self.errors[0] if self.errors else None


def execution_result_from_tool_result(
    tool_result: ToolResult,
    *,
    source: str,
    operation: str,
    typed_error: ExecutionError | BaseException | None = None,
    classifier: ErrorClassifier | None = None,
) -> ExecutionResult[ToolResult]:
    """Adapt a legacy ToolResult without changing its contract or string behavior."""

    if typed_error is None and not tool_result.error:
        return ExecutionResult(
            status=ExecutionStatus.SUCCESS,
            value=tool_result,
            metadata={"has_image": bool(tool_result.base64_image)},
        )
    error_value: ExecutionError | BaseException | str
    error_value = typed_error if typed_error is not None else str(tool_result.error)
    execution_error = (classifier or ErrorClassifier()).classify(
        error_value,
        source=source,
        operation=operation,
    )
    return ExecutionResult(
        status=ExecutionStatus.FAILED,
        value=tool_result,
        errors=(execution_error,),
        metadata={"has_image": bool(tool_result.base64_image)},
    )
