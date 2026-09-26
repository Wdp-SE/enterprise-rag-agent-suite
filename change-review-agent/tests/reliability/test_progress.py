from __future__ import annotations

from pathlib import Path

from app.reliability.errors import ErrorCode
from app.reliability.progress import (
    NoProgressDetector,
    NoProgressReason,
    ProgressSignal,
    TraceProgressAdapter,
    safe_identity_hash,
)
from app.reliability.trace import (
    TraceContext,
    TraceEvent,
    TraceEventType,
    TraceRecorder,
    TraceSpanKind,
)


def signal(sequence: int, **fields) -> ProgressSignal:
    return ProgressSignal(
        sequence=sequence,
        event_type="OPERATION_FAILED",
        operation=fields.pop("operation", "fixture.operation"),
        stage=fields.pop("stage", "ACQUIRE"),
        **fields,
    )


def observe_all(detector: NoProgressDetector, signals: list[ProgressSignal]):
    return [detector.observe(item) for item in signals]


def read_events(recorder: TraceRecorder, run_id: str) -> list[TraceEvent]:
    return [
        TraceEvent.model_validate_json(line)
        for line in recorder.path_for(run_id).read_text(encoding="utf-8").splitlines()
    ]


def test_identity_hash_is_canonical_for_mapping_order() -> None:
    left = safe_identity_hash({"query": "alpha", "page": 1})
    right = safe_identity_hash({"page": 1, "query": "alpha"})
    assert left == right


def test_arguments_hash_is_created_from_raw_structured_input_without_retaining_it() -> None:
    item = ProgressSignal.from_raw_input(
        sequence=1,
        event_type="CALL",
        raw_arguments={"query": "safety rules", "api_key": "super-secret"},
        target_resource="https://example.test/private/path?token=secret",
    )
    payload = item.model_dump_json()
    assert item.normalized_arguments_hash is not None
    assert item.target_resource_hash is not None
    assert "safety rules" not in payload
    assert "super-secret" not in payload
    assert "example.test" not in payload


def test_different_structured_arguments_produce_different_hashes() -> None:
    assert safe_identity_hash({"page": 1}) != safe_identity_hash({"page": 2})


def test_trace_adapter_preserves_explicit_boundary_hashes(tmp_path: Path) -> None:
    recorder = TraceRecorder(tmp_path)
    context = TraceContext("progress_adapter", "fixture", recorder)
    expected = safe_identity_hash({"query": "fixture"})
    span = context.start_span(
        TraceSpanKind.OPERATION,
        operation="fixture.operation",
        input_summary={"normalized_arguments_hash": expected},
    )
    event = read_events(recorder, "progress_adapter")[0]
    adapted = TraceProgressAdapter.from_event(event)
    assert adapted.normalized_arguments_hash == expected
    assert adapted.span_id == span.span_id


def test_trace_adapter_does_not_reverse_hash_sanitized_input_summary(
    tmp_path: Path,
) -> None:
    recorder = TraceRecorder(tmp_path)
    context = TraceContext("no_reverse_hash", "fixture", recorder)
    context.start_span(
        TraceSpanKind.OPERATION,
        operation="fixture.operation",
        input_summary={"query_preview": "already sanitized"},
    )
    adapted = TraceProgressAdapter.from_event(
        read_events(recorder, "no_reverse_hash")[0]
    )
    assert adapted.normalized_arguments_hash is None
    assert adapted.target_resource_hash is None


def test_trace_adapter_carries_progress_counts(tmp_path: Path) -> None:
    recorder = TraceRecorder(tmp_path)
    context = TraceContext("progress_counts", "fixture", recorder)
    span = context.start_span(TraceSpanKind.OPERATION, operation="extract")
    span.succeed(
        output_summary={
            "artifact_count": 2,
            "evidence_count": 5,
            "completed_unit_count": 1,
        }
    )
    event = read_events(recorder, "progress_counts")[-1]
    adapted = TraceProgressAdapter.from_event(event)
    assert adapted.successful is True
    assert adapted.artifact_count == 2
    assert adapted.evidence_count == 5
    assert adapted.completed_unit_count == 1


def test_same_error_has_highest_priority() -> None:
    detector = NoProgressDetector(threshold=3)
    resource = safe_identity_hash("https://example.test/a")
    decisions = observe_all(
        detector,
        [
            signal(
                index,
                error_code=ErrorCode.TRANSIENT_NETWORK,
                target_resource_hash=resource,
            )
            for index in range(1, 4)
        ],
    )
    assert decisions[-1].reason is NoProgressReason.SAME_ERROR_REPEAT
    assert decisions[-1].is_no_progress is True
    assert decisions[-1].reason_code is NoProgressReason.SAME_ERROR_REPEAT
    assert decisions[-1].window_size == 3
    assert decisions[-1].repeat_count == 3
    assert decisions[-1].first_sequence == 1
    assert decisions[-1].last_sequence == 3
    assert [item.sequence for item in decisions[-1].evidence] == [1, 2, 3]


def test_same_resource_repeat_is_detected() -> None:
    detector = NoProgressDetector(threshold=3)
    resource = safe_identity_hash("resource-a")
    decisions = observe_all(
        detector,
        [
            signal(index, operation=f"operation-{index}", target_resource_hash=resource)
            for index in range(1, 4)
        ],
    )
    assert decisions[-1].reason is NoProgressReason.SAME_RESOURCE_REPEAT


def test_same_operation_repeat_is_detected() -> None:
    detector = NoProgressDetector(threshold=3)
    decisions = observe_all(detector, [signal(index) for index in range(1, 4)])
    assert decisions[-1].reason is NoProgressReason.SAME_OPERATION_REPEAT


def test_stage_reentry_without_progress_uses_stable_priority() -> None:
    detector = NoProgressDetector(threshold=3)
    decisions = observe_all(
        detector,
        [
            signal(1, stage="A", operation="one"),
            signal(2, stage="B", operation="two"),
            signal(3, stage="A", operation="three"),
            signal(4, stage="B", operation="four"),
            signal(5, stage="A", operation="five"),
        ],
    )
    assert decisions[-1].reason is NoProgressReason.STAGE_REENTRY_WITHOUT_PROGRESS


def test_different_operations_without_growth_trigger_no_artifact_growth() -> None:
    detector = NoProgressDetector(threshold=3)
    decisions = observe_all(
        detector,
        [signal(index, operation=f"operation-{index}") for index in range(1, 4)],
    )
    assert decisions[-1].reason is NoProgressReason.NO_ARTIFACT_GROWTH


def test_artifact_growth_resets_existing_latch() -> None:
    detector = NoProgressDetector(threshold=3)
    observe_all(detector, [signal(index, artifact_count=0) for index in range(1, 4)])
    assert detector.latched is True
    decision = detector.observe(signal(4, artifact_count=1, successful=True))
    assert decision.progress_observed is True
    assert detector.latched is False


def test_evidence_growth_resets_streak() -> None:
    detector = NoProgressDetector(threshold=3)
    observe_all(detector, [signal(index, evidence_count=2) for index in range(1, 4)])
    decision = detector.observe(signal(4, evidence_count=3, successful=True))
    assert decision.no_progress is False
    assert decision.progress_observed is True


def test_completed_unit_growth_resets_streak() -> None:
    detector = NoProgressDetector(threshold=3)
    observe_all(
        detector, [signal(index, completed_unit_count=1) for index in range(1, 4)]
    )
    decision = detector.observe(
        signal(4, completed_unit_count=2, successful=True)
    )
    assert decision.progress_observed is True


def test_new_successful_output_hash_is_progress() -> None:
    detector = NoProgressDetector(threshold=3)
    output_hash = safe_identity_hash({"artifact": "new"})
    decision = detector.observe(
        signal(1, successful=True, output_hash=output_hash)
    )
    assert decision.progress_observed is True


def test_repeated_successful_output_does_not_keep_resetting() -> None:
    detector = NoProgressDetector(threshold=3)
    output_hash = safe_identity_hash({"artifact": "same"})
    decisions = observe_all(
        detector,
        [
            signal(index, successful=True, output_hash=output_hash)
            for index in range(1, 5)
        ],
    )
    assert decisions[-1].no_progress is True


def test_same_no_progress_streak_emits_only_once() -> None:
    detector = NoProgressDetector(threshold=3)
    decisions = observe_all(
        detector,
        [
            signal(index, error_code=ErrorCode.TRANSIENT_NETWORK)
            for index in range(1, 6)
        ],
    )
    assert [decision.should_emit for decision in decisions] == [
        False,
        False,
        True,
        False,
        False,
    ]


def test_progress_allows_a_new_latched_streak() -> None:
    detector = NoProgressDetector(threshold=3)
    first = observe_all(
        detector,
        [signal(index, error_code=ErrorCode.TRANSIENT_NETWORK) for index in range(1, 4)],
    )[-1]
    detector.observe(signal(4, artifact_count=1, successful=True))
    second = observe_all(
        detector,
        [signal(index, error_code=ErrorCode.TRANSIENT_NETWORK, artifact_count=1) for index in range(5, 8)],
    )[-1]
    assert first.should_emit is True
    assert second.should_emit is True
    assert first.rule_identity == second.rule_identity


def test_rule_identity_change_can_establish_new_streak() -> None:
    detector = NoProgressDetector(threshold=3)
    first = observe_all(
        detector,
        [signal(index, error_code=ErrorCode.TRANSIENT_NETWORK) for index in range(1, 4)],
    )[-1]
    second = observe_all(
        detector,
        [signal(index, error_code=ErrorCode.RATE_LIMITED) for index in range(4, 7)],
    )[-1]
    assert first.should_emit is True
    assert second.should_emit is True
    assert first.rule_identity != second.rule_identity


def test_optional_signal_fields_may_be_absent() -> None:
    item = ProgressSignal(sequence=1, event_type="RUN_STARTED")
    assert item.operation is None
    assert item.successful is None


def test_no_progress_trace_is_emitted_once_per_latch(tmp_path: Path) -> None:
    recorder = TraceRecorder(tmp_path)
    context = TraceContext("no_progress_trace", "fixture", recorder)
    span = context.start_span(TraceSpanKind.OPERATION, operation="fixture.operation")
    detector = NoProgressDetector(threshold=3)
    for index in range(1, 6):
        detector.observe(
            signal(
                index,
                error_code=ErrorCode.TRANSIENT_NETWORK,
                span_id=span.span_id,
                parent_span_id=span.parent_span_id,
            ),
            trace_context=context,
        )
    events = read_events(recorder, "no_progress_trace")
    no_progress = [
        event for event in events if event.event_type is TraceEventType.NO_PROGRESS
    ]
    assert len(no_progress) == 1
    assert no_progress[0].output_summary["reason"] == "SAME_ERROR_REPEAT"


def test_trace_failure_does_not_change_observer_decision() -> None:
    class BrokenTrace:
        def emit(self, **kwargs):
            raise OSError("trace unavailable")

    detector = NoProgressDetector(threshold=3)
    decisions = []
    for index in range(1, 4):
        decisions.append(
            detector.observe(
                signal(
                    index,
                    error_code=ErrorCode.TRANSIENT_NETWORK,
                    span_id="span_00000000000000000000",
                ),
                trace_context=BrokenTrace(),
            )
        )
    assert decisions[-1].no_progress is True
    assert decisions[-1].should_emit is True
