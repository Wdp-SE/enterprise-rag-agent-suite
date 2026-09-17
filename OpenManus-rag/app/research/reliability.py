"""Optional reliability adapters for the staged research workflow."""

from __future__ import annotations

import hashlib
from typing import Any

from app.reliability.errors import (
    ErrorCategory,
    ErrorClassifier,
    ErrorCode,
    ExecutionError,
    SensitiveDataSanitizer,
)
from app.reliability.trace import TraceContext, TraceSpan, TraceSpanKind
from app.research.live_models import ResearchErrorCode, ResearchFailure, ResearchPhase
from app.research.models import ResearchProfile


_SANITIZER = SensitiveDataSanitizer(max_text_length=512)


_RESEARCH_ERROR_DEFAULTS: dict[ResearchErrorCode, tuple[ErrorCode, ErrorCategory, bool]] = {
    ResearchErrorCode.SEARCH_FAILED: (
        ErrorCode.EXTERNAL_SERVICE_FAILED,
        ErrorCategory.SERVICE,
        True,
    ),
    ResearchErrorCode.DOWNLOAD_FAILED: (
        ErrorCode.EXTERNAL_SERVICE_FAILED,
        ErrorCategory.SERVICE,
        True,
    ),
    ResearchErrorCode.UNSUPPORTED_SCAN_PDF: (
        ErrorCode.UNSUPPORTED_CONTENT,
        ErrorCategory.DATA,
        False,
    ),
    ResearchErrorCode.EMPTY_CONTENT: (
        ErrorCode.UNSUPPORTED_CONTENT,
        ErrorCategory.DATA,
        False,
    ),
    ResearchErrorCode.EVIDENCE_EXTRACTION_FAILED: (
        ErrorCode.RESPONSE_PARSE_FAILED,
        ErrorCategory.DATA,
        False,
    ),
    ResearchErrorCode.INSUFFICIENT_EVIDENCE: (
        ErrorCode.INSUFFICIENT_EVIDENCE,
        ErrorCategory.DATA,
        False,
    ),
}


def research_failure_to_execution_error(
    failure: ResearchFailure,
    *,
    source: str = "knowledge_research",
    operation: str | None = None,
    classifier: ErrorClassifier | None = None,
) -> ExecutionError:
    """Map, rather than replace, the established ResearchFailure contract."""

    operation_name = operation or failure.phase.value.casefold()
    details: dict[str, Any] = {
        "research_error_code": failure.code.value,
        "phase": failure.phase.value,
    }
    if failure.source_url:
        details["source_url"] = failure.source_url
    classified = (classifier or ErrorClassifier()).classify(
        failure.message,
        source=source,
        operation=operation_name,
        details=details,
    )
    if classified.code is not ErrorCode.INTERNAL_ERROR:
        return classified
    code, category, retryable = _RESEARCH_ERROR_DEFAULTS[failure.code]
    return ExecutionError(
        code=code,
        category=category,
        message=failure.message,
        retryable=retryable,
        source=source,
        operation=operation_name,
        details=details,
        cause_type="ResearchFailure",
    )


class ResearchTraceSession:
    """Name and summarize the fixed research phases without owning workflow behavior."""

    def __init__(self, context: TraceContext):
        self.context = context

    def run_span(self, profile: ResearchProfile) -> TraceSpan:
        topic = profile.research_topic
        return self.context.start_span(
            TraceSpanKind.RUN,
            operation="knowledge_research.run",
            input_summary={
                "profile_id": profile.profile_id,
                "research_topic": {
                    "type": "str",
                    "length": len(topic),
                    "sha256": hashlib.sha256(topic.encode("utf-8")).hexdigest(),
                },
                "research_question_count": len(profile.research_questions),
                "max_sources": profile.max_sources,
            },
        )

    def stage_span(self, phase: ResearchPhase, *, parent_span_id: str) -> TraceSpan:
        return self.context.start_span(
            TraceSpanKind.STAGE,
            stage=phase.value,
            operation=f"research.{phase.value.casefold()}",
            parent_span_id=parent_span_id,
        )

    def operation_span(
        self,
        phase: ResearchPhase,
        operation: str,
        *,
        parent_span_id: str,
        input_summary: dict[str, Any] | None = None,
        tool_name: str | None = None,
        tool_call_id: str | None = None,
    ) -> TraceSpan:
        return self.context.start_span(
            TraceSpanKind.OPERATION,
            stage=phase.value,
            operation=operation,
            parent_span_id=parent_span_id,
            input_summary=_SANITIZER.sanitize(input_summary or {}),
            tool_name=tool_name,
            tool_call_id=tool_call_id,
        )
