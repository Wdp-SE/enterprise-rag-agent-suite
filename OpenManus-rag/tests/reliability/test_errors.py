from __future__ import annotations

import asyncio
import json
import ssl

import httpx

from app.reliability.errors import (
    ErrorCategory,
    ErrorClassifier,
    ErrorCode,
    ExecutionError,
)
from app.sandbox.core.exceptions import SandboxTimeoutError


def classify(error):
    return ErrorClassifier().classify(error, source="fixture", operation="test")


def http_status_error(status_code: int, message: str = "request failed") -> httpx.HTTPStatusError:
    request = httpx.Request("GET", "https://example.test/path?token=do-not-store")
    response = httpx.Response(status_code, request=request)
    return httpx.HTTPStatusError(message, request=request, response=response)


def test_existing_execution_error_is_preserved() -> None:
    expected = ExecutionError(
        code=ErrorCode.POLICY_BLOCKED,
        category=ErrorCategory.POLICY,
        message="blocked",
        retryable=False,
        source="policy",
        operation="authorize",
    )
    assert classify(expected) is expected


def test_http_403_is_access_denied_and_not_retryable() -> None:
    error = classify(http_status_error(403))
    assert (error.code, error.category, error.retryable) == (
        ErrorCode.ACCESS_DENIED,
        ErrorCategory.SECURITY,
        False,
    )
    assert error.details["status_code"] == 403


def test_http_429_is_rate_limited() -> None:
    error = classify(http_status_error(429))
    assert error.code is ErrorCode.RATE_LIMITED
    assert error.retryable is True


def test_domain_wrapper_preserves_http_status_and_retry_after() -> None:
    request = httpx.Request("GET", "https://example.test")
    response = httpx.Response(
        429,
        request=request,
        headers={"retry-after": "2"},
    )
    protocol_error = httpx.HTTPStatusError(
        "rate limited",
        request=request,
        response=response,
    )
    try:
        raise RuntimeError("adapter acquisition failed") from protocol_error
    except RuntimeError as wrapper:
        error = classify(wrapper)
    assert error.code is ErrorCode.RATE_LIMITED
    assert error.retryable is True
    assert error.details == {"status_code": 429, "retry_after": "2"}


def test_http_401_is_authentication_failure() -> None:
    error = classify(http_status_error(401))
    assert error.code is ErrorCode.AUTHENTICATION_FAILED
    assert error.retryable is False


def test_tls_eof_and_connection_reset_are_transient() -> None:
    assert classify(ssl.SSLError("TLS EOF occurred")).code is ErrorCode.TRANSIENT_NETWORK
    reset = classify(ConnectionResetError("connection reset by peer"))
    assert reset.code is ErrorCode.TRANSIENT_NETWORK
    assert reset.retryable is True


def test_asyncio_and_sandbox_timeout_share_timeout_code() -> None:
    first = classify(asyncio.TimeoutError("operation timed out"))
    second = classify(SandboxTimeoutError("sandbox timed out"))
    assert first.code is second.code is ErrorCode.OPERATION_TIMEOUT
    assert first.retryable is second.retryable is True


def test_browser_missing_public_reader_is_capability_error() -> None:
    error = classify(
        "BrowserUseTool has no public full-document interface; private page access is forbidden"
    )
    assert error.code is ErrorCode.TOOL_CAPABILITY_UNAVAILABLE
    assert error.retryable is False


def test_invalid_argument_is_not_retryable() -> None:
    error = classify(ValueError("max_candidates must be between 1 and 8"))
    assert error.code is ErrorCode.INVALID_INPUT
    assert error.retryable is False


def test_response_parse_failure_is_structured() -> None:
    try:
        json.loads("{")
    except json.JSONDecodeError as exc:
        error = classify(exc)
    assert error.code is ErrorCode.RESPONSE_PARSE_FAILED
    assert error.retryable is False


def test_unknown_exception_falls_back_to_internal_error() -> None:
    error = classify(RuntimeError("unrecognized fixture failure"))
    assert error.code is ErrorCode.INTERNAL_ERROR
    assert error.retryable is False


def test_execution_error_message_and_details_are_recursively_sanitized() -> None:
    error = ExecutionError(
        code=ErrorCode.INTERNAL_ERROR,
        category=ErrorCategory.INTERNAL,
        message=(
            "Authorization: Bearer auth-value Cookie: sid=cookie-value "
            "API Key=api-value "
            "https://url-user:url-pass@example.test/path?access_token=query-value"
        ),
        retryable=False,
        source="fixture",
        operation="sanitize",
        details={
            "password": "password-value",
            "nested": [{"secret": "secret-value", "api_token": "nested-token"}],
            "response_body": "a complete response body that must not be stored",
        },
    )
    serialized = json.dumps(error.model_dump(mode="json"), ensure_ascii=False)
    for secret in (
        "auth-value",
        "cookie-value",
        "api-value",
        "query-value",
        "url-user",
        "url-pass",
        "password-value",
        "secret-value",
        "nested-token",
        "a complete response body",
    ):
        assert secret not in serialized
    assert "[REDACTED]" in serialized
    assert error.details["response_body"]["type"] == "str"


def test_source_url_detail_keeps_no_query_string() -> None:
    error = ErrorClassifier().classify(
        "HTTP 403 forbidden",
        source="http",
        operation="get",
        details={"source_url": "https://example.test/path?token=hidden&x=1"},
    )
    assert error.details["source_url"] == {
        "type": "url",
        "scheme": "https",
        "host": "example.test",
        "path_hash": error.details["source_url"]["path_hash"],
    }
    assert "hidden" not in json.dumps(error.details)
