from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from app.reliability.errors import ErrorCode
from app.reliability.trace import (
    NoopTraceRecorder,
    TraceEvent,
    TraceEventType,
    TraceRecorder,
    TraceStatus,
)
from app.research.evidence_extraction import CompositeEvidenceExtractor
from app.research.live_models import (
    AcquisitionMethod,
    AcquiredSource,
    OutputArtifact,
    ResearchErrorCode,
    ResearchFailure,
    ResearchPhase,
)
from app.research.profile_loader import load_research_profile
from app.research.reliability import research_failure_to_execution_error
from app.research.research_result import ResearchResultBuilder
from app.research.research_synthesis import DeterministicResearchSynthesizer
from app.research.source_acquisition import SourceAcquisitionError
from app.research.source_policy import SourcePolicy
from app.research.source_selection import SourceSelector
from app.research.workflow import KnowledgeResearchWorkflow


PROJECT_ROOT = Path(__file__).resolve().parents[2]
PROFILE = load_research_profile(
    PROJECT_ROOT / "config/research_profiles/special_equipment_validation.toml"
)
POLICY = SourcePolicy.from_toml(PROJECT_ROOT / "config/research_policies/default.toml")
NOW = datetime(2026, 8, 28, 8, 0, 0, 123456, timezone.utc)


class FakeTraceClock:
    def __init__(self) -> None:
        self.elapsed = 0.0

    def now(self) -> datetime:
        return NOW

    def monotonic(self) -> float:
        self.elapsed += 0.01
        return self.elapsed


class FakeSearch:
    async def search(self, profile, *, max_candidates):
        from app.research.live_models import ResearchSearchResult

        return [
            ResearchSearchResult(
                query=profile.research_topic,
                title=f"Official source {position}",
                url=f"https://agency{position}.gov.cn/page?token=must-not-leak",
                snippet="discovery only",
                engine="fake",
                position=position,
            )
            for position in range(1, min(3, max_candidates) + 1)
        ]


class FakeAcquirer:
    def __init__(self, *, fail_position: int | None = None):
        self.fail_position = fail_position

    async def acquire(self, source, run_store):
        if source.search_position == self.fail_position:
            raise SourceAcquisitionError(
                ResearchErrorCode.DOWNLOAD_FAILED,
                "HTTP 403 forbidden Authorization: Bearer source-secret",
                source_url=source.url,
            )
        data = (
            "<!doctype html><html><head><title>Fixture</title></head><body><article>"
            f"<h1>Requirements {source.search_position}</h1>"
            f"<p>Complete public fact for source {source.search_position} with review context.</p>"
            "</article></body></html>"
        ).encode("utf-8")
        staged = run_store.stage_bytes(data, extension=".html")
        archived = run_store.archive_staged(staged)
        return AcquiredSource(
            search_result_id=source.search_result_id,
            title=source.title,
            organization=source.organization,
            source_url=source.url,
            final_url=source.url,
            source_type="webpage",
            source_level=source.source_level,
            media_type="text/html",
            acquisition_method=AcquisitionMethod.HTTP,
            retrieved_at=NOW,
            local_file=archived.local_file,
            raw_file_hash=archived.raw_file_hash,
            reused=archived.reused,
        )


class FakeOutputAdapter:
    name = "fixture_json"

    async def write(self, *, result, evidence_store, run_store, profile):
        path = run_store.write_json("outputs/fixture.json", result.model_dump(mode="json"))
        return OutputArtifact(adapter=self.name, status="CREATED", path=path)


class FailingSynthesizer:
    async def synthesize(self, profile, evidence):
        raise RuntimeError("fixture synthesis exploded")


class FailingTraceRecorder(TraceRecorder):
    def _append_line(self, target: Path, line: str) -> None:
        raise OSError("trace storage fixture failure")


def make_workflow(
    workspace: Path,
    *,
    trace_recorder=None,
    fail_position: int | None = None,
    synthesizer=None,
) -> KnowledgeResearchWorkflow:
    return KnowledgeResearchWorkflow(
        workspace_root=workspace,
        search_provider=FakeSearch(),
        source_selector=SourceSelector(POLICY),
        source_acquirer=FakeAcquirer(fail_position=fail_position),
        evidence_extractor=CompositeEvidenceExtractor(),
        synthesizer=synthesizer or DeterministicResearchSynthesizer(),
        output_adapters=[FakeOutputAdapter()],
        result_builder=ResearchResultBuilder(clock=lambda: NOW),
        clock=lambda: NOW,
        duration_clock=lambda: 0.0,
        trace_recorder=trace_recorder,
        trace_clock=FakeTraceClock(),
    )


def read_trace(recorder: TraceRecorder, run_id: str) -> list[TraceEvent]:
    return [
        TraceEvent.model_validate_json(line)
        for line in recorder.path_for(run_id).read_text(encoding="utf-8").splitlines()
    ]


@pytest.mark.asyncio
async def test_research_success_traces_six_fixed_stages_and_operations(tmp_path: Path) -> None:
    recorder = TraceRecorder(tmp_path)
    outcome = await make_workflow(tmp_path, trace_recorder=recorder).run(PROFILE)
    events = read_trace(recorder, outcome.result.run_id)

    assert events[0].event_type is TraceEventType.RUN_STARTED
    assert events[-1].event_type is TraceEventType.RUN_SUCCEEDED
    assert events[-1].status is TraceStatus.SUCCESS
    assert [event.stage for event in events if event.event_type is TraceEventType.STAGE_STARTED] == [
        phase.value
        for phase in (
            ResearchPhase.DISCOVER,
            ResearchPhase.SELECT,
            ResearchPhase.ACQUIRE,
            ResearchPhase.EXTRACT,
            ResearchPhase.BUILD_RESULT,
            ResearchPhase.OUTPUT,
        )
    ]
    assert len([event for event in events if event.event_type is TraceEventType.STAGE_SUCCEEDED]) == 6
    assert any(event.operation == "search.query" for event in events)
    assert any(event.operation == "output.write" for event in events)


@pytest.mark.asyncio
async def test_tolerated_source_failure_is_operation_failure_and_partial_run(
    tmp_path: Path,
) -> None:
    recorder = TraceRecorder(tmp_path)
    outcome = await make_workflow(
        tmp_path,
        trace_recorder=recorder,
        fail_position=2,
    ).run(PROFILE)
    events = read_trace(recorder, outcome.result.run_id)
    failures = [event for event in events if event.event_type is TraceEventType.OPERATION_FAILED]

    assert outcome.result.status.value == "PARTIAL"
    assert any(event.error_code is ErrorCode.ACCESS_DENIED for event in failures)
    assert events[-1].event_type is TraceEventType.RUN_SUCCEEDED
    assert events[-1].status is TraceStatus.PARTIAL
    raw = recorder.path_for(outcome.result.run_id).read_text(encoding="utf-8")
    assert "source-secret" not in raw
    assert "must-not-leak" not in raw


@pytest.mark.asyncio
async def test_unhandled_workflow_exception_records_stage_operation_and_run_failure(
    tmp_path: Path,
) -> None:
    recorder = TraceRecorder(tmp_path)
    workflow = make_workflow(
        tmp_path,
        trace_recorder=recorder,
        synthesizer=FailingSynthesizer(),
    )
    with pytest.raises(RuntimeError, match="synthesis exploded"):
        await workflow.run(PROFILE)

    run_id = next((tmp_path / "traces").glob("*.jsonl")).stem
    events = read_trace(recorder, run_id)
    assert events[-1].event_type is TraceEventType.RUN_FAILED
    assert events[-1].error_code is ErrorCode.INTERNAL_ERROR
    assert any(event.event_type is TraceEventType.STAGE_FAILED for event in events)
    assert any(event.event_type is TraceEventType.OPERATION_FAILED for event in events)


def test_research_failure_mapping_preserves_contract_and_maps_known_codes() -> None:
    unsupported = ResearchFailure(
        code=ResearchErrorCode.UNSUPPORTED_SCAN_PDF,
        message="PDF has no directly extractable text",
        phase=ResearchPhase.EXTRACT,
        source_url="https://example.test/scan.pdf?token=hidden",
    )
    mapped = research_failure_to_execution_error(unsupported)
    assert unsupported.code is ResearchErrorCode.UNSUPPORTED_SCAN_PDF
    assert mapped.code is ErrorCode.UNSUPPORTED_CONTENT
    assert mapped.details["research_error_code"] == "UNSUPPORTED_SCAN_PDF"
    assert "hidden" not in json.dumps(mapped.model_dump(mode="json"))


@pytest.mark.asyncio
async def test_best_effort_trace_failure_does_not_change_business_outcome(tmp_path: Path) -> None:
    expected = await make_workflow(
        tmp_path / "expected",
        trace_recorder=NoopTraceRecorder(),
    ).run(PROFILE)
    recorder = FailingTraceRecorder(tmp_path / "actual", best_effort=True)
    actual = await make_workflow(
        tmp_path / "actual",
        trace_recorder=recorder,
    ).run(PROFILE)

    assert actual.model_dump(mode="json") == expected.model_dump(mode="json")
    assert recorder.healthy is False
    assert recorder.errors


@pytest.mark.asyncio
async def test_default_noop_and_explicit_noop_outputs_are_identical(tmp_path: Path) -> None:
    implicit = await make_workflow(tmp_path / "implicit").run(PROFILE)
    explicit = await make_workflow(
        tmp_path / "explicit",
        trace_recorder=NoopTraceRecorder(),
    ).run(PROFILE)
    assert implicit.model_dump(mode="json") == explicit.model_dump(mode="json")
    assert not (tmp_path / "implicit" / "traces").exists()
    assert not (tmp_path / "explicit" / "traces").exists()
