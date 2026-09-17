from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from pathlib import Path

import pytest

from app.reliability.policy import (
    CapabilityId,
    PolicyAction,
    TaskPolicy,
    TaskPolicyProfile,
)
from app.reliability.retry import SideEffectLevel
from app.reliability.trace import TraceEvent, TraceEventType, TraceRecorder
from app.reliability.workflow_control import ReliableWorkflowController
from app.research.evidence_extraction import CompositeEvidenceExtractor
from app.research.live_models import AcquisitionMethod, AcquiredSource, ResearchSearchResult
from app.research.profile_loader import load_research_profile
from app.research.research_result import ResearchResultBuilder
from app.research.research_synthesis import DeterministicResearchSynthesizer
from app.research.source_policy import SourcePolicy
from app.research.source_selection import SourceSelector
from app.research.workflow import KnowledgeResearchWorkflow


PROJECT_ROOT = Path(__file__).resolve().parents[2]
PROFILE = load_research_profile(
    PROJECT_ROOT / "config/research_profiles/special_equipment_validation.toml"
)
SOURCE_POLICY = SourcePolicy.from_toml(
    PROJECT_ROOT / "config/research_policies/default.toml"
)
NOW = datetime(2026, 8, 29, 12, 0, 0, 123456, timezone.utc)


class FakeSearch:
    async def search(self, profile, *, max_candidates):
        return [
            ResearchSearchResult(
                query=profile.research_topic,
                title=f"Official source {position}",
                url=f"https://agency{position}.gov.cn/requirements",
                snippet="discovery metadata only",
                engine="fake",
                position=position,
            )
            for position in range(1, min(2, max_candidates) + 1)
        ]


class FakeAcquirer:
    async def acquire(self, source, run_store):
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


def controller(*, network_access: bool = True, enabled: bool = True):
    return ReliableWorkflowController(
        TaskPolicy(
            TaskPolicyProfile(
                profile_id="research_observer",
                enabled=enabled,
                allowed_tools=frozenset(
                    {
                        CapabilityId.WEB_SEARCH,
                        CapabilityId.HTTP_GET,
                        CapabilityId.BROWSER_ACQUIRE,
                        CapabilityId.EVIDENCE_EXTRACT,
                        CapabilityId.LLM_SYNTHESIS,
                        CapabilityId.WORKSPACE_WRITE,
                        CapabilityId.CANDIDATE_PACKAGE,
                    }
                ),
                network_access=network_access,
                allowed_output_roots=frozenset(
                    {"research_runs", "candidate_knowledge"}
                ),
                allowed_side_effect_levels=frozenset(
                    {SideEffectLevel.READ_ONLY, SideEffectLevel.IDEMPOTENT_WRITE}
                ),
            )
        )
    )


def make_workflow(
    workspace: Path,
    *,
    workflow_controller=None,
    recorder=None,
) -> KnowledgeResearchWorkflow:
    return KnowledgeResearchWorkflow(
        workspace_root=workspace,
        search_provider=FakeSearch(),
        source_selector=SourceSelector(SOURCE_POLICY),
        source_acquirer=FakeAcquirer(),
        evidence_extractor=CompositeEvidenceExtractor(),
        synthesizer=DeterministicResearchSynthesizer(),
        output_adapters=[],
        result_builder=ResearchResultBuilder(clock=lambda: NOW),
        clock=lambda: NOW,
        duration_clock=lambda: 0.0,
        trace_recorder=recorder,
        workflow_controller=workflow_controller,
    )


def result_hash(outcome) -> str:
    return hashlib.sha256(outcome.result.model_dump_json().encode("utf-8")).hexdigest()


def read_events(recorder: TraceRecorder, run_id: str) -> list[TraceEvent]:
    return [
        TraceEvent.model_validate_json(line)
        for line in recorder.path_for(run_id).read_text(encoding="utf-8").splitlines()
    ]


@pytest.mark.asyncio
async def test_research_policy_observer_does_not_change_business_output(
    tmp_path: Path,
) -> None:
    baseline = await make_workflow(tmp_path / "baseline").run(PROFILE)
    observed_workflow = make_workflow(
        tmp_path / "observed", workflow_controller=controller()
    )
    observed = await observed_workflow.run(PROFILE)
    assert result_hash(observed) == result_hash(baseline)
    assert observed.metrics == baseline.metrics
    assert observed.failures == baseline.failures
    assert observed.outputs == baseline.outputs
    assert observed_workflow.last_policy_decisions


@pytest.mark.asyncio
async def test_research_policy_observer_never_enforces_stop(tmp_path: Path) -> None:
    workflow = make_workflow(
        tmp_path,
        workflow_controller=controller(network_access=False),
    )
    outcome = await workflow.run(PROFILE)
    assert outcome.result.key_findings
    assert any(
        decision.action is PolicyAction.STOP
        for decision in workflow.last_policy_decisions
    )


@pytest.mark.asyncio
async def test_disabled_research_policy_preserves_output(tmp_path: Path) -> None:
    baseline = await make_workflow(tmp_path / "baseline").run(PROFILE)
    workflow = make_workflow(
        tmp_path / "disabled", workflow_controller=controller(enabled=False)
    )
    observed = await workflow.run(PROFILE)
    assert result_hash(observed) == result_hash(baseline)
    assert all(item.allowed for item in workflow.last_policy_decisions)


@pytest.mark.asyncio
async def test_research_observer_projects_policy_trace(tmp_path: Path) -> None:
    recorder = TraceRecorder(tmp_path / "trace")
    workflow = make_workflow(
        tmp_path / "workspace",
        workflow_controller=controller(),
        recorder=recorder,
    )
    outcome = await workflow.run(PROFILE)
    events = read_events(recorder, outcome.result.run_id)
    policy_events = [
        event for event in events if event.event_type is TraceEventType.POLICY_DECISION
    ]
    assert len(policy_events) == len(workflow.last_policy_decisions)
    assert all(event.tool_name in {item.value for item in CapabilityId} for event in policy_events)


@pytest.mark.asyncio
async def test_controller_none_preserves_empty_policy_diagnostics(tmp_path: Path) -> None:
    workflow = make_workflow(tmp_path)
    await workflow.run(PROFILE)
    assert workflow.last_policy_decisions == ()
