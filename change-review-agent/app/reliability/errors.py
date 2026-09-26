"""Stable, sanitized error contracts for optional reliability integrations."""

from __future__ import annotations

import asyncio
import hashlib
import json
import re
import ssl
from enum import Enum
from typing import Any, Mapping
from urllib.parse import urlsplit

import httpx
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator


class ErrorCategory(str, Enum):
    NETWORK = "NETWORK"
    TIMEOUT = "TIMEOUT"
    THROTTLING = "THROTTLING"
    SECURITY = "SECURITY"
    INPUT = "INPUT"
    CAPABILITY = "CAPABILITY"
    DATA = "DATA"
    SERVICE = "SERVICE"
    POLICY = "POLICY"
    RESOURCE = "RESOURCE"
    PROGRESS = "PROGRESS"
    CANCELLATION = "CANCELLATION"
    INTERNAL = "INTERNAL"


class ErrorCode(str, Enum):
    TRANSIENT_NETWORK = "TRANSIENT_NETWORK"
    OPERATION_TIMEOUT = "OPERATION_TIMEOUT"
    RATE_LIMITED = "RATE_LIMITED"
    AUTHENTICATION_FAILED = "AUTHENTICATION_FAILED"
    ACCESS_DENIED = "ACCESS_DENIED"
    INVALID_INPUT = "INVALID_INPUT"
    TOOL_CAPABILITY_UNAVAILABLE = "TOOL_CAPABILITY_UNAVAILABLE"
    RESPONSE_PARSE_FAILED = "RESPONSE_PARSE_FAILED"
    UNSUPPORTED_CONTENT = "UNSUPPORTED_CONTENT"
    INSUFFICIENT_EVIDENCE = "INSUFFICIENT_EVIDENCE"
    EXTERNAL_SERVICE_FAILED = "EXTERNAL_SERVICE_FAILED"
    POLICY_BLOCKED = "POLICY_BLOCKED"
    RESOURCE_EXHAUSTED = "RESOURCE_EXHAUSTED"
    BUDGET_EXCEEDED = "BUDGET_EXCEEDED"
    NO_PROGRESS = "NO_PROGRESS"
    CANCELLED = "CANCELLED"
    INTERNAL_ERROR = "INTERNAL_ERROR"


_SENSITIVE_KEYS = {
    "apikey",
    "token",
    "accesstoken",
    "authorization",
    "cookie",
    "password",
    "secret",
}
_BULK_CONTENT_KEYS = {
    "body",
    "content",
    "evidence",
    "evidencelist",
    "html",
    "messages",
    "output",
    "pagecontent",
    "prompt",
    "prompttext",
    "rawcontent",
    "rawresponse",
    "requestbody",
    "response",
    "responsebody",
    "tooloutput",
    "webpage",
}
_URL_RE = re.compile(r"https?://[^\s<>\"']+", re.IGNORECASE)
_SECRET_ASSIGNMENT_RE = re.compile(
    r"(?i)(\b(?:api[_\s-]?key|access[_\s-]?token|authorization|cookie|password|secret|token)"
    r"\b\s*[:=]\s*)(?:bearer\s+)?([^\s,;]+)"
)
_BEARER_RE = re.compile(r"(?i)\bbearer\s+[A-Za-z0-9._~+\-/]+=*")
_OPENAI_KEY_RE = re.compile(r"\bsk-[A-Za-z0-9_-]{8,}\b")


def _normalized_key(value: object) -> str:
    return re.sub(r"[^a-z0-9]", "", str(value).casefold())


class SensitiveDataSanitizer:
    """Recursively redact credentials and summarize content-bearing values."""

    def __init__(self, *, max_text_length: int = 2048, max_collection_items: int = 50):
        if max_text_length < 32:
            raise ValueError("max_text_length must be at least 32")
        if max_collection_items < 1:
            raise ValueError("max_collection_items must be positive")
        self.max_text_length = max_text_length
        self.max_collection_items = max_collection_items

    @staticmethod
    def summarize_url(value: str) -> dict[str, str]:
        try:
            parsed = urlsplit(value.strip())
            scheme = parsed.scheme.casefold()
            hostname = parsed.hostname
            port = parsed.port
        except ValueError:
            parsed = None
            scheme = ""
            hostname = None
            port = None
        if parsed is None or scheme not in {"http", "https"} or not hostname:
            return {"type": "invalid_url", "sha256": hashlib.sha256(value.encode()).hexdigest()}
        host = hostname.casefold()
        if port:
            host = f"{host}:{port}"
        path = parsed.path or "/"
        return {
            "type": "url",
            "scheme": scheme,
            "host": host,
            "path_hash": hashlib.sha256(path.encode("utf-8")).hexdigest(),
        }

    @staticmethod
    def summarize_value(value: Any) -> dict[str, Any]:
        if isinstance(value, bytes):
            payload = value
            length = len(value)
            value_type = "bytes"
        elif isinstance(value, str):
            payload = value.encode("utf-8")
            length = len(value)
            value_type = "str"
        else:
            try:
                serialized = json.dumps(
                    value,
                    ensure_ascii=False,
                    sort_keys=True,
                    separators=(",", ":"),
                    default=str,
                )
            except (TypeError, ValueError):
                serialized = type(value).__name__
            payload = serialized.encode("utf-8")
            length = len(value) if hasattr(value, "__len__") else 1
            value_type = type(value).__name__
        return {
            "type": value_type,
            "count" if not isinstance(value, (str, bytes)) else "length": length,
            "sha256": hashlib.sha256(payload).hexdigest(),
        }

    def sanitize_text(self, value: str) -> str:
        def redact_url(match: re.Match[str]) -> str:
            raw = match.group(0)
            trailing = ""
            while raw and raw[-1] in ".,);]":
                trailing = raw[-1] + trailing
                raw = raw[:-1]
            try:
                parsed = urlsplit(raw)
                hostname = parsed.hostname
                port = parsed.port
            except ValueError:
                return "[REDACTED_URL]" + trailing
            if not hostname:
                return "[REDACTED_URL]" + trailing
            host = hostname.casefold()
            if port:
                host = f"{host}:{port}"
            safe = f"{parsed.scheme.casefold()}://{host}{parsed.path or '/'}"
            if parsed.query or parsed.fragment:
                safe += "?[REDACTED_QUERY]"
            return safe + trailing

        sanitized = _URL_RE.sub(redact_url, value)
        sanitized = _SECRET_ASSIGNMENT_RE.sub(r"\1[REDACTED]", sanitized)
        sanitized = _BEARER_RE.sub("Bearer [REDACTED]", sanitized)
        sanitized = _OPENAI_KEY_RE.sub("[REDACTED]", sanitized)
        if len(sanitized) > self.max_text_length:
            digest = hashlib.sha256(sanitized.encode("utf-8")).hexdigest()
            return f"{sanitized[: self.max_text_length]}… [truncated sha256={digest}]"
        return sanitized

    def sanitize(self, value: Any, *, key: object | None = None) -> Any:
        normalized = _normalized_key(key) if key is not None else ""
        if normalized in _SENSITIVE_KEYS or normalized.endswith(
            ("apikey", "password", "secret", "token")
        ):
            return "[REDACTED]"
        if normalized in {"url", "sourceurl", "finalurl"} and isinstance(value, str):
            return self.summarize_url(value)
        if normalized in _BULK_CONTENT_KEYS:
            return self.summarize_value(value)
        if isinstance(value, BaseModel):
            return self.sanitize(value.model_dump(mode="json"), key=key)
        if isinstance(value, Mapping):
            return {
                str(item_key): self.sanitize(item_value, key=item_key)
                for item_key, item_value in value.items()
            }
        if isinstance(value, (list, tuple, set, frozenset)):
            items = list(value)
            sanitized = [
                self.sanitize(item) for item in items[: self.max_collection_items]
            ]
            if len(items) > self.max_collection_items:
                sanitized.append({"truncated_items": len(items) - self.max_collection_items})
            return sanitized
        if isinstance(value, bytes):
            return self.summarize_value(value)
        if isinstance(value, str):
            return self.sanitize_text(value)
        if value is None or isinstance(value, (bool, int, float)):
            return value
        return self.sanitize_text(str(value))


_ERROR_SANITIZER = SensitiveDataSanitizer()


class ExecutionError(BaseModel):
    """A machine-readable failure; retryable is advisory only in Phase 1A."""

    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)

    code: ErrorCode
    category: ErrorCategory
    message: str = Field(min_length=1, max_length=2300)
    retryable: bool = False
    source: str = Field(min_length=1, max_length=128)
    operation: str = Field(min_length=1, max_length=128)
    details: dict[str, Any] = Field(default_factory=dict)
    cause_type: str | None = Field(default=None, max_length=256)

    @field_validator("message", "source", "operation", "cause_type", mode="before")
    @classmethod
    def sanitize_text_fields(cls, value: Any) -> Any:
        if value is None:
            return None
        return _ERROR_SANITIZER.sanitize_text(str(value))

    @field_validator("details", mode="before")
    @classmethod
    def sanitize_details(cls, value: Any) -> dict[str, Any]:
        if value is None:
            return {}
        if not isinstance(value, Mapping):
            value = {"value": value}
        return _ERROR_SANITIZER.sanitize(value)


class ExecutionErrorRaised(RuntimeError):
    """Carry a classified error through an existing exception-based boundary."""

    def __init__(self, error: ExecutionError):
        super().__init__(error.message)
        self.error = error


class ErrorClassifier:
    """Deterministically classify known project, protocol, and Python failures."""

    _TRANSIENT_PATTERNS = (
        "connection reset",
        "connection aborted",
        "connection refused",
        "tls eof",
        "ssl eof",
        "unexpected eof",
        "temporarily unavailable",
        "remote protocol error",
    )

    def classify(
        self,
        error: ExecutionError | BaseException | str,
        *,
        source: str,
        operation: str,
        details: Mapping[str, Any] | None = None,
    ) -> ExecutionError:
        if isinstance(error, ExecutionError):
            return error
        if isinstance(error, ExecutionErrorRaised):
            return error.error

        message = str(error).strip() or type(error).__name__
        cause_type = type(error).__name__ if isinstance(error, BaseException) else "StringError"
        merged_details = dict(details or {})

        if isinstance(error, httpx.HTTPStatusError):
            status_code = error.response.status_code
            merged_details["status_code"] = status_code
            retry_after = error.response.headers.get("retry-after")
            if retry_after is not None:
                merged_details["retry_after"] = retry_after
            if status_code == 401:
                return self._make(ErrorCode.AUTHENTICATION_FAILED, ErrorCategory.SECURITY, message, False, source, operation, merged_details, cause_type)
            if status_code == 403:
                return self._make(ErrorCode.ACCESS_DENIED, ErrorCategory.SECURITY, message, False, source, operation, merged_details, cause_type)
            if status_code == 429:
                return self._make(ErrorCode.RATE_LIMITED, ErrorCategory.THROTTLING, message, True, source, operation, merged_details, cause_type)
            if status_code == 408:
                return self._make(ErrorCode.OPERATION_TIMEOUT, ErrorCategory.TIMEOUT, message, True, source, operation, merged_details, cause_type)
            if status_code == 400:
                return self._make(ErrorCode.INVALID_INPUT, ErrorCategory.INPUT, message, False, source, operation, merged_details, cause_type)
            return self._make(ErrorCode.EXTERNAL_SERVICE_FAILED, ErrorCategory.SERVICE, message, status_code >= 500, source, operation, merged_details, cause_type)

        if isinstance(error, (asyncio.TimeoutError, TimeoutError, httpx.TimeoutException)):
            return self._make(ErrorCode.OPERATION_TIMEOUT, ErrorCategory.TIMEOUT, message, True, source, operation, merged_details, cause_type)
        if isinstance(error, asyncio.CancelledError):
            return self._make(ErrorCode.CANCELLED, ErrorCategory.CANCELLATION, message, False, source, operation, merged_details, cause_type)
        if isinstance(error, (httpx.NetworkError, httpx.ProtocolError, ConnectionError, ssl.SSLError)):
            return self._make(ErrorCode.TRANSIENT_NETWORK, ErrorCategory.NETWORK, message, True, source, operation, merged_details, cause_type)
        if isinstance(error, (json.JSONDecodeError, UnicodeDecodeError)):
            return self._make(ErrorCode.RESPONSE_PARSE_FAILED, ErrorCategory.DATA, message, False, source, operation, merged_details, cause_type)
        if isinstance(error, (ValidationError, TypeError, ValueError)):
            return self._make(ErrorCode.INVALID_INPUT, ErrorCategory.INPUT, message, False, source, operation, merged_details, cause_type)

        # Existing adapters commonly wrap SDK/protocol failures in their own
        # domain exception. Directly recognized exceptions above always win
        # (notably asyncio.TimeoutError, whose internal cause is cancellation).
        # For an otherwise unknown wrapper, retain its public message while
        # deriving status/Retry-After/retryability from its explicit cause.
        cause = error.__cause__ if isinstance(error, BaseException) else None
        if isinstance(cause, BaseException) and cause is not error:
            classified_cause = self.classify(
                cause,
                source=source,
                operation=operation,
                details=merged_details,
            )
            if classified_cause.code is not ErrorCode.INTERNAL_ERROR:
                return self._make(
                    classified_cause.code,
                    classified_cause.category,
                    message,
                    classified_cause.retryable,
                    source,
                    operation,
                    classified_cause.details,
                    cause_type,
                )

        lowered = message.casefold()
        if "no public full-document" in lowered or "capability unavailable" in lowered or "unknown tool" in lowered:
            return self._make(ErrorCode.TOOL_CAPABILITY_UNAVAILABLE, ErrorCategory.CAPABILITY, message, False, source, operation, merged_details, cause_type)
        if "429" in lowered or "rate limit" in lowered or "too many requests" in lowered:
            return self._make(ErrorCode.RATE_LIMITED, ErrorCategory.THROTTLING, message, True, source, operation, merged_details, cause_type)
        if "403" in lowered or "forbidden" in lowered or "access denied" in lowered:
            return self._make(ErrorCode.ACCESS_DENIED, ErrorCategory.SECURITY, message, False, source, operation, merged_details, cause_type)
        if "401" in lowered or "authentication failed" in lowered or "unauthorized" in lowered:
            return self._make(ErrorCode.AUTHENTICATION_FAILED, ErrorCategory.SECURITY, message, False, source, operation, merged_details, cause_type)
        if "timed out" in lowered or "timeout" in lowered:
            return self._make(ErrorCode.OPERATION_TIMEOUT, ErrorCategory.TIMEOUT, message, True, source, operation, merged_details, cause_type)
        if any(pattern in lowered for pattern in self._TRANSIENT_PATTERNS):
            return self._make(ErrorCode.TRANSIENT_NETWORK, ErrorCategory.NETWORK, message, True, source, operation, merged_details, cause_type)
        if "unsupported" in lowered:
            return self._make(ErrorCode.UNSUPPORTED_CONTENT, ErrorCategory.DATA, message, False, source, operation, merged_details, cause_type)
        if "parse" in lowered or "invalid response" in lowered or "schema" in lowered:
            return self._make(ErrorCode.RESPONSE_PARSE_FAILED, ErrorCategory.DATA, message, False, source, operation, merged_details, cause_type)
        if "invalid" in lowered or "must be" in lowered or "validation" in lowered:
            return self._make(ErrorCode.INVALID_INPUT, ErrorCategory.INPUT, message, False, source, operation, merged_details, cause_type)
        return self._make(ErrorCode.INTERNAL_ERROR, ErrorCategory.INTERNAL, message, False, source, operation, merged_details, cause_type)

    @staticmethod
    def _make(
        code: ErrorCode,
        category: ErrorCategory,
        message: str,
        retryable: bool,
        source: str,
        operation: str,
        details: Mapping[str, Any],
        cause_type: str,
    ) -> ExecutionError:
        return ExecutionError(
            code=code,
            category=category,
            message=message,
            retryable=retryable,
            source=source,
            operation=operation,
            details=dict(details),
            cause_type=cause_type,
        )
