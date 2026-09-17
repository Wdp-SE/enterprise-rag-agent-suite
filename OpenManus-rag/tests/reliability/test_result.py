from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.reliability.errors import ErrorCategory, ErrorCode, ExecutionError
from app.reliability.result import (
    ExecutionResult,
    ExecutionStatus,
    execution_result_from_tool_result,
)
from app.tool.base import ToolResult


def fixture_error(code: ErrorCode = ErrorCode.INTERNAL_ERROR) -> ExecutionError:
    return ExecutionError(
        code=code,
        category=ErrorCategory.INTERNAL,
        message="fixture failure",
        retryable=False,
        source="fixture",
        operation="test",
    )


def test_success_requires_no_errors() -> None:
    result = ExecutionResult[str](status=ExecutionStatus.SUCCESS, value="ok")
    assert result.value == "ok"
    assert result.primary_error is None
    with pytest.raises(ValidationError, match="cannot contain errors"):
        ExecutionResult(status=ExecutionStatus.SUCCESS, errors=(fixture_error(),))


def test_failed_and_cancelled_require_an_error() -> None:
    with pytest.raises(ValidationError, match="requires an error"):
        ExecutionResult(status=ExecutionStatus.FAILED)
    with pytest.raises(ValidationError, match="requires an error"):
        ExecutionResult(status=ExecutionStatus.CANCELLED)


def test_partial_can_contain_value_and_errors() -> None:
    error = fixture_error()
    result = ExecutionResult[str](
        status=ExecutionStatus.PARTIAL,
        value="usable subset",
        errors=(error,),
    )
    assert result.value == "usable subset"
    assert result.primary_error is error


def test_cancelled_result_exposes_primary_error() -> None:
    error = fixture_error(ErrorCode.CANCELLED)
    result = ExecutionResult(status=ExecutionStatus.CANCELLED, errors=(error,))
    assert result.primary_error.code is ErrorCode.CANCELLED


def test_execution_metadata_is_sanitized() -> None:
    result = ExecutionResult(
        status=ExecutionStatus.SUCCESS,
        metadata={"api_key": "hidden", "content": "full content"},
    )
    assert result.metadata["api_key"] == "[REDACTED]"
    assert result.metadata["content"]["type"] == "str"


def test_tool_result_success_adapter_preserves_legacy_value() -> None:
    legacy = ToolResult(output="ok")
    result = execution_result_from_tool_result(
        legacy, source="fixture_tool", operation="execute"
    )
    assert result.status is ExecutionStatus.SUCCESS
    assert result.value is legacy
    assert str(result.value) == "ok"


def test_tool_result_failure_adapter_classifies_known_string() -> None:
    legacy = ToolResult(error="HTTP 403 forbidden")
    result = execution_result_from_tool_result(
        legacy, source="fixture_tool", operation="execute"
    )
    assert result.status is ExecutionStatus.FAILED
    assert result.primary_error.code is ErrorCode.ACCESS_DENIED
    assert str(legacy) == "Error: HTTP 403 forbidden"


def test_tool_result_unknown_error_falls_back_to_internal() -> None:
    result = execution_result_from_tool_result(
        ToolResult(error="something novel happened"),
        source="fixture_tool",
        operation="execute",
    )
    assert result.primary_error.code is ErrorCode.INTERNAL_ERROR


def test_tool_result_typed_error_override_is_preserved() -> None:
    typed = fixture_error(ErrorCode.POLICY_BLOCKED)
    result = execution_result_from_tool_result(
        ToolResult(error="legacy display text"),
        source="fixture_tool",
        operation="execute",
        typed_error=typed,
    )
    assert result.primary_error is typed
