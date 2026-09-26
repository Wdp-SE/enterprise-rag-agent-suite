"""Observer-only progress signals and deterministic no-progress detection."""

from __future__ import annotations

import hashlib
import json
import re
from enum import Enum
from typing import Any, Iterable

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.reliability.errors import ErrorCode
from app.reliability.trace import (
    TraceContext,
    TraceEvent,
    TraceEventType,
    TraceSanitizer,
    TraceStatus,
)


_SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")


def safe_identity_hash(value: Any, *, sanitizer: TraceSanitizer | None = None) -> str:
    """Hash a sanitized canonical representation at the structured-input boundary."""

    sanitized = (sanitizer or TraceSanitizer()).sanitize(value)
    canonical = json.dumps(
        sanitized,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


class ProgressSignal(BaseModel):
    """A content-free observation suitable for progress analysis."""

    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)

    sequence: int = Field(ge=1)
    event_type: str = Field(min_length=1, max_length=128)
    stage: str | None = Field(default=None, max_length=128)
    operation: str | None = Field(default=None, max_length=128)
    tool_name: str | None = Field(default=None, max_length=128)
    normalized_arguments_hash: str | None = None
    target_resource_hash: str | None = None
    error_code: ErrorCode | None = None
    output_hash: str | None = None
    artifact_count: int | None = Field(default=None, ge=0)
    evidence_count: int | None = Field(default=None, ge=0)
    completed_unit_count: int | None = Field(default=None, ge=0)
    successful: bool | None = None
    span_id: str | None = None
    parent_span_id: str | None = None

    @field_validator(
        "normalized_arguments_hash",
        "target_resource_hash",
        "output_hash",
    )
    @classmethod
    def validate_sha256(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.casefold()
        if not _SHA256_PATTERN.fullmatch(normalized):
            raise ValueError("identity fields must be lowercase SHA256 hashes")
        return normalized

    @classmethod
    def from_raw_input(
        cls,
        *,
        sequence: int,
        event_type: str,
        raw_arguments: Any | None = None,
        target_resource: Any | None = None,
        **fields: Any,
    ) -> "ProgressSignal":
        """Compute identities before raw input is discarded or trace-summarized."""

        return cls(
            sequence=sequence,
            event_type=event_type,
            normalized_arguments_hash=(
                safe_identity_hash(raw_arguments)
                if raw_arguments is not None
                else None
            ),
            target_resource_hash=(
                safe_identity_hash(target_resource)
                if target_resource is not None
                else None
            ),
            **fields,
        )


class TraceProgressAdapter:
    """Project structured Trace events without reverse-hashing sanitized summaries."""

    _COUNT_FIELDS = ("artifact_count", "evidence_count", "completed_unit_count")
    _HASH_FIELDS = (
        "normalized_arguments_hash",
        "target_resource_hash",
        "output_hash",
    )

    @classmethod
    def from_event(cls, event: TraceEvent) -> ProgressSignal:
        # Identity hashes are accepted only when an input-boundary adapter
        # explicitly supplied them. Other summary content is never re-hashed.
        combined = {**event.input_summary, **event.output_summary}
        hashes: dict[str, str | None] = {}
        for name in cls._HASH_FIELDS:
            candidate = combined.get(name)
            hashes[name] = (
                str(candidate).casefold()
                if candidate is not None
                and _SHA256_PATTERN.fullmatch(str(candidate).casefold())
                else None
            )
        counts: dict[str, int | None] = {}
        for name in cls._COUNT_FIELDS:
            candidate = combined.get(name)
            counts[name] = (
                int(candidate)
                if isinstance(candidate, int) and not isinstance(candidate, bool)
                and candidate >= 0
                else None
            )
        return ProgressSignal(
            sequence=event.sequence,
            event_type=event.event_type.value,
            stage=event.stage,
            operation=event.operation,
            tool_name=event.tool_name,
            error_code=event.error_code,
            successful=event.status is TraceStatus.SUCCESS,
            span_id=event.span_id,
            parent_span_id=event.parent_span_id,
            **hashes,
            **counts,
        )

    @classmethod
    def from_events(cls, events: Iterable[TraceEvent]) -> list[ProgressSignal]:
        return [cls.from_event(event) for event in events]


class NoProgressReason(str, Enum):
    SAME_ERROR_REPEAT = "SAME_ERROR_REPEAT"
    SAME_RESOURCE_REPEAT = "SAME_RESOURCE_REPEAT"
    SAME_OPERATION_REPEAT = "SAME_OPERATION_REPEAT"
    STAGE_REENTRY_WITHOUT_PROGRESS = "STAGE_REENTRY_WITHOUT_PROGRESS"
    NO_ARTIFACT_GROWTH = "NO_ARTIFACT_GROWTH"


class NoProgressEvidence(BaseModel):
    """Content-free evidence explaining one detector decision."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    sequence: int = Field(ge=1)
    operation: str | None = None
    normalized_arguments_hash: str | None = None
    target_resource_hash: str | None = None
    error_code: ErrorCode | None = None
    artifact_count: int | None = Field(default=None, ge=0)
    evidence_count: int | None = Field(default=None, ge=0)
    completed_unit_count: int | None = Field(default=None, ge=0)


class NoProgressDecision(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    sequence: int = Field(ge=1)
    no_progress: bool
    reason: NoProgressReason | None = None
    streak_count: int = Field(default=0, ge=0)
    rule_identity: str | None = None
    latched: bool = False
    should_emit: bool = False
    progress_observed: bool = False
    window_size: int = Field(default=0, ge=0)
    repeat_count: int = Field(default=0, ge=0)
    first_sequence: int | None = Field(default=None, ge=1)
    last_sequence: int | None = Field(default=None, ge=1)
    evidence: tuple[NoProgressEvidence, ...] = ()

    @property
    def is_no_progress(self) -> bool:
        return self.no_progress

    @property
    def reason_code(self) -> NoProgressReason | None:
        return self.reason


class NoProgressDetector:
    """Stateful observer; it reports but never stops, retries, or replans work."""

    _PRIORITY = (
        NoProgressReason.SAME_ERROR_REPEAT,
        NoProgressReason.SAME_RESOURCE_REPEAT,
        NoProgressReason.SAME_OPERATION_REPEAT,
        NoProgressReason.STAGE_REENTRY_WITHOUT_PROGRESS,
        NoProgressReason.NO_ARTIFACT_GROWTH,
    )

    def __init__(self, *, threshold: int = 3) -> None:
        if threshold < 2:
            raise ValueError("no-progress threshold must be at least 2")
        self.threshold = threshold
        self._window: list[ProgressSignal] = []
        self._max_counts = {
            "artifact_count": -1,
            "evidence_count": -1,
            "completed_unit_count": -1,
        }
        self._seen_success_outputs: set[str] = set()
        self._latched_identity: str | None = None

    @property
    def latched(self) -> bool:
        return self._latched_identity is not None

    def observe(
        self,
        signal: ProgressSignal,
        *,
        trace_context: TraceContext | None = None,
    ) -> NoProgressDecision:
        progress = self._is_progress(signal)
        if progress:
            self._window.clear()
            self._latched_identity = None
            return NoProgressDecision(
                sequence=signal.sequence,
                no_progress=False,
                progress_observed=True,
            )

        self._window.append(signal)

        candidates = self._candidates()
        selected = next(
            (
                candidates[reason]
                for reason in self._PRIORITY
                if reason in candidates
            ),
            None,
        )
        if selected is None:
            return NoProgressDecision(
                sequence=signal.sequence,
                no_progress=False,
                latched=self.latched,
            )

        reason, streak_count, key = selected
        identity = safe_identity_hash({"reason": reason.value, "key": key})
        should_emit = identity != self._latched_identity
        self._latched_identity = identity
        relevant_signals = self._window[-min(streak_count, len(self._window)) :]
        evidence = tuple(
            NoProgressEvidence(
                sequence=item.sequence,
                operation=item.operation,
                normalized_arguments_hash=item.normalized_arguments_hash,
                target_resource_hash=item.target_resource_hash,
                error_code=item.error_code,
                artifact_count=item.artifact_count,
                evidence_count=item.evidence_count,
                completed_unit_count=item.completed_unit_count,
            )
            for item in relevant_signals
        )
        decision = NoProgressDecision(
            sequence=signal.sequence,
            no_progress=True,
            reason=reason,
            streak_count=streak_count,
            rule_identity=identity,
            latched=True,
            should_emit=should_emit,
            window_size=len(self._window),
            repeat_count=streak_count,
            first_sequence=(evidence[0].sequence if evidence else None),
            last_sequence=(evidence[-1].sequence if evidence else None),
            evidence=evidence,
        )
        if should_emit:
            self._emit(trace_context, signal, decision)
        return decision

    def _is_progress(self, signal: ProgressSignal) -> bool:
        grew = False
        for name in self._max_counts:
            value = getattr(signal, name)
            if value is not None:
                if value > self._max_counts[name]:
                    # A first zero establishes a baseline; it is not growth.
                    if self._max_counts[name] >= 0 or value > 0:
                        grew = True
                    self._max_counts[name] = max(self._max_counts[name], value)
        new_success_output = bool(
            signal.successful
            and signal.output_hash
            and signal.output_hash not in self._seen_success_outputs
        )
        if signal.successful and signal.output_hash:
            self._seen_success_outputs.add(signal.output_hash)
        return grew or new_success_output

    def _candidates(
        self,
    ) -> dict[NoProgressReason, tuple[NoProgressReason, int, Any]]:
        candidates: dict[
            NoProgressReason, tuple[NoProgressReason, int, Any]
        ] = {}
        if not self._window:
            return candidates
        latest = self._window[-1]

        error_count = self._suffix_count("error_code", latest.error_code)
        if latest.error_code is not None and error_count >= self.threshold:
            candidates[NoProgressReason.SAME_ERROR_REPEAT] = (
                NoProgressReason.SAME_ERROR_REPEAT,
                error_count,
                latest.error_code.value,
            )

        resource_count = self._suffix_count(
            "target_resource_hash", latest.target_resource_hash
        )
        if latest.target_resource_hash is not None and resource_count >= self.threshold:
            candidates[NoProgressReason.SAME_RESOURCE_REPEAT] = (
                NoProgressReason.SAME_RESOURCE_REPEAT,
                resource_count,
                latest.target_resource_hash,
            )

        operation_key = (
            latest.stage,
            latest.operation,
            latest.tool_name,
            latest.normalized_arguments_hash,
        )
        operation_count = 0
        if latest.operation is not None:
            for signal in reversed(self._window):
                key = (
                    signal.stage,
                    signal.operation,
                    signal.tool_name,
                    signal.normalized_arguments_hash,
                )
                if key != operation_key:
                    break
                operation_count += 1
        if operation_count >= self.threshold:
            candidates[NoProgressReason.SAME_OPERATION_REPEAT] = (
                NoProgressReason.SAME_OPERATION_REPEAT,
                operation_count,
                operation_key,
            )

        if latest.stage is not None:
            entries = 0
            prior_stage: str | None = None
            for signal in self._window:
                if signal.stage == latest.stage and prior_stage != latest.stage:
                    entries += 1
                prior_stage = signal.stage
            if entries >= self.threshold:
                candidates[NoProgressReason.STAGE_REENTRY_WITHOUT_PROGRESS] = (
                    NoProgressReason.STAGE_REENTRY_WITHOUT_PROGRESS,
                    entries,
                    latest.stage,
                )

        if len(self._window) >= self.threshold:
            candidates[NoProgressReason.NO_ARTIFACT_GROWTH] = (
                NoProgressReason.NO_ARTIFACT_GROWTH,
                len(self._window),
                "no-count-or-output-growth",
            )
        return candidates

    def _suffix_count(self, field: str, expected: Any) -> int:
        if expected is None:
            return 0
        count = 0
        for signal in reversed(self._window):
            if getattr(signal, field) != expected:
                break
            count += 1
        return count

    @staticmethod
    def _emit(
        trace_context: TraceContext | None,
        signal: ProgressSignal,
        decision: NoProgressDecision,
    ) -> None:
        if trace_context is None or signal.span_id is None:
            return
        try:
            trace_context.emit(
                event_type=TraceEventType.NO_PROGRESS,
                status=TraceStatus.FAILED,
                stage=signal.stage,
                span_id=signal.span_id,
                parent_span_id=signal.parent_span_id,
                tool_name=signal.tool_name,
                operation=signal.operation,
                error_code=ErrorCode.NO_PROGRESS,
                output_summary={
                    "reason": decision.reason.value if decision.reason else None,
                    "streak_count": decision.streak_count,
                    "window_size": decision.window_size,
                    "repeat_count": decision.repeat_count,
                    "first_sequence": decision.first_sequence,
                    "last_sequence": decision.last_sequence,
                    "rule_identity": decision.rule_identity,
                    "observer_only": True,
                },
            )
        except Exception:
            # Detection is observer-only; trace health cannot alter workflow.
            return


__all__ = [
    "NoProgressDecision",
    "NoProgressDetector",
    "NoProgressEvidence",
    "NoProgressReason",
    "ProgressSignal",
    "TraceProgressAdapter",
    "safe_identity_hash",
]
