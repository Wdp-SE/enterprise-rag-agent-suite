from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest

from app.reliability.budget import BudgetDimension, BudgetLedger, ExecutionBudget
from app.reliability.executor import ReliableOperationExecutor
from app.reliability.progress import NoProgressDetector, NoProgressReason
from app.reliability.trace import TraceEvent, TraceEventType, TraceRecorder
from app.research.evidence_extraction import CompositeEvidenceExtractor
from app.research.live_models import (
    AcquisitionMethod,
    AcquiredSource,
    ResearchErrorCode,
    ResearchSearchResult,
    SelectedSource,
)
from app.research.profile_loader import load_research_profile
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
POLICY = SourcePolicy.from_toml(
    PROJECT_ROOT / "config/research_policies/default.toml"
)
NOW = datetime(2026, 8, 29, 9, 0, 0, 123456, timezone.utc)


class FakeSearch:
    def __init__(self, count: int = 3) -> None:
        self.count = count
        self.calls = 0

    async def search(self, profile, *, max_candidates):
        self.calls += 1
        return [
            ResearchSearchResult(
                query=profile.research_topic,
                title=f"Official source {position}",
                url=f"https://agency{position}.gov.cn/requirements",
                snippet="discovery metadata only",
                engine="fake",
                position=position,
            )
            for position in range(1, min(self.count, max_candidates) + 1)
        ]


class FakeAcquirer:
    def __init__(self, *, always_fail: bool = False) -> None:
        self.always_fail = always_fail
        self.calls = 0

    async def acquire(self, source, run_store):
        self.calls += 1
        if self.always_fail:
            raise SourceAcquisitionError(
                ResearchErrorCode.DOWNLOAD_FAILED,
                "connection reset by fixture",
                source_url=source.url,
            )
        content = (
            "<!doctype html><html><body><article>"
            f"<h1>Requirements {source.search_position}</h1>"
            f"<p>Complete public fact {source.search_position} with sufficient context.</p>"
            "</article></body></html>"
        ).encode()
        archived = run_store.archive_staged(
            run_store.stage_bytes(content, extension=".html")
        )
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


class DuplicateSelector:
    def __init__(self, policy: SourcePolicy) -> None:
        self.delegate = SourceSelector(policy)

    def select(self, results, profile, *, max_sources):
        selected = self.delegate.select(results, profile, max_sources=1)[0]
        return [selected, selected, selected]

    def refine_acquired(self, source):
        return self.delegate.refine_acquired(source)


class BudgetedFakeSynthesizer:
    def __init__(self) -> None:
        self.delegate = DeterministicResearchSynthesizer()

    def reliability_budget_contract(self, profile, evidence):
        return (
            {
                BudgetDimension.LLM_CALLS: 1,
                BudgetDimension.PROMPT_TOKENS: 100,
                BudgetDimension.COMPLETION_TOKENS: 50,
                BudgetDimension.TOTAL_TOKENS: 150,
            },
            frozenset(),
        )

    async def synthesize(self, profile, evidence):
        return await self.delegate.synthesize(profile, evidence)


def make_workflow(
    workspace: Path,
    *,
    search=None,
    selector=None,
    acquirer=None,
    synthesizer=None,
    executor=None,
    detector=None,
    recorder=None,
) -> KnowledgeResearchWorkflow:
    return KnowledgeResearchWorkflow(
        workspace_root=workspace,
        search_provider=search or FakeSearch(),
        source_selector=selector or SourceSelector(POLICY),
        source_acquirer=acquirer or FakeAcquirer(),
        evidence_extractor=CompositeEvidenceExtractor(),
        synthesizer=synthesizer or DeterministicResearchSynthesizer(),
        output_adapters=[],
        result_builder=ResearchResultBuilder(clock=lambda: NOW),
        clock=lambda: NOW,
        duration_clock=lambda: 0.0,
        operation_executor=executor,
        progress_detector=detector,
        trace_recorder=recorder,
    )


def read_events(recorder: TraceRecorder, run_id: str) -> list[TraceEvent]:
    return [
        TraceEvent.model_validate_json(line)
        for line in recorder.path_for(run_id).read_text(encoding="utf-8").splitlines()
    ]


@pytest.mark.asyncio
async def test_normal_research_progress_never_reports_no_progress(
    tmp_path: Path,
) -> None:
    detector = NoProgressDetector(threshold=3)
    workflow = make_workflow(tmp_path, detector=detector)
    outcome = await workflow.run(PROFILE)
    assert outcome.metrics.download_success == 3
    assert outcome.metrics.evidence_count == 3
    assert workflow.last_progress_decisions
    assert not any(item.no_progress for item in workflow.last_progress_decisions)


@pytest.mark.asyncio
async def test_observer_mode_does_not_change_research_business_output(
    tmp_path: Path,
) -> None:
    without = await make_workflow(tmp_path / "without").run(PROFILE)
    observed_workflow = make_workflow(
        tmp_path / "observed", detector=NoProgressDetector(threshold=3)
    )
    with_observer = await observed_workflow.run(PROFILE)
    assert with_observer.result == without.result
    assert with_observer.metrics == without.metrics
    assert with_observer.failures == without.failures
    assert with_observer.outputs == without.outputs


@pytest.mark.asyncio
async def test_repeated_url_and_error_prefers_same_error_and_emits_once(
    tmp_path: Path,
) -> None:
    recorder = TraceRecorder(tmp_path / "trace")
    detector = NoProgressDetector(threshold=3)
    acquirer = FakeAcquirer(always_fail=True)
    workflow = make_workflow(
        tmp_path,
        search=FakeSearch(count=1),
        selector=DuplicateSelector(POLICY),
        acquirer=acquirer,
        detector=detector,
        recorder=recorder,
    )
    outcome = await workflow.run(PROFILE)
    emitted = [item for item in workflow.last_progress_decisions if item.should_emit]
    events = read_events(recorder, outcome.result.run_id)
    no_progress_events = [
        event for event in events if event.event_type is TraceEventType.NO_PROGRESS
    ]
    assert acquirer.calls == 3
    assert emitted[0].reason is NoProgressReason.SAME_ERROR_REPEAT
    assert len(no_progress_events) == 1


@pytest.mark.asyncio
async def test_research_outer_search_and_download_budgets_are_accounted(
    tmp_path: Path,
) -> None:
    ledger = BudgetLedger(
        ExecutionBudget(max_search_calls=1, max_downloads=2)
    )
    executor = ReliableOperationExecutor(budget_ledger=ledger)
    acquirer = FakeAcquirer()
    workflow = make_workflow(
        tmp_path,
        acquirer=acquirer,
        executor=executor,
        detector=NoProgressDetector(threshold=3),
    )
    outcome = await workflow.run(PROFILE)
    snapshot = ledger.snapshot()
    assert snapshot.committed[BudgetDimension.SEARCH_CALLS] == 1
    assert snapshot.committed[BudgetDimension.DOWNLOADS] == 2
    assert acquirer.calls == 2
    assert outcome.metrics.download_success == 2
    assert outcome.metrics.download_failure == 1
    assert not any(item.no_progress for item in workflow.last_progress_decisions)


@pytest.mark.asyncio
async def test_research_synthesis_contract_commits_llm_call_and_actual_tokens(
    tmp_path: Path,
) -> None:
    ledger = BudgetLedger(
        ExecutionBudget(
            max_llm_calls=1,
            max_prompt_tokens=100,
            max_completion_tokens=50,
            max_total_tokens=150,
        )
    )
    workflow = make_workflow(
        tmp_path,
        synthesizer=BudgetedFakeSynthesizer(),
        executor=ReliableOperationExecutor(budget_ledger=ledger),
    )
    outcome = await workflow.run(PROFILE)
    snapshot = ledger.snapshot()
    assert outcome.result.key_findings
    assert snapshot.committed[BudgetDimension.LLM_CALLS] == 1
    assert snapshot.committed[BudgetDimension.PROMPT_TOKENS] == 0
    assert snapshot.committed[BudgetDimension.COMPLETION_TOKENS] == 0
    assert snapshot.committed[BudgetDimension.TOTAL_TOKENS] == 0

