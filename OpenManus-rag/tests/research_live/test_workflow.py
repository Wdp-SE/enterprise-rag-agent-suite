from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from pathlib import Path

import pytest

from app.research.candidate_builder import CandidateBuilder
from app.research.candidate_validator import CandidateValidator
from app.research.evidence_extraction import CompositeEvidenceExtractor
from app.research.live_models import (
    AcquisitionMethod,
    AcquiredSource,
    ResearchErrorCode,
    ResearchPhase,
    ResearchSearchResult,
)
from app.research.output_adapters import (
    CandidatePackageAdapter,
    JsonResultAdapter,
    MarkdownReportAdapter,
)
from app.research.profile_loader import load_research_profile
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


class FakeSearch:
    def __init__(self, count: int = 4):
        self.count = count
        self.calls = 0

    async def search(self, profile, *, max_candidates):
        self.calls += 1
        return [
            ResearchSearchResult(
                query=profile.research_topic,
                title=f"Official source {index}",
                url=f"https://agency{index}.gov.cn/page",
                snippet="discovery only",
                engine="fake",
                position=index,
            )
            for index in range(1, min(self.count, max_candidates) + 1)
        ]


class FakeSourceAcquirer:
    def __init__(self, *, fail_positions: set[int] | None = None):
        self.fail_positions = fail_positions or set()
        self.calls = 0

    async def acquire(self, source, run_store):
        self.calls += 1
        if source.search_position in self.fail_positions:
            raise SourceAcquisitionError(
                ResearchErrorCode.DOWNLOAD_FAILED,
                "fixture download failed",
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


def workflow(tmp_path: Path, *, search_count: int = 4, fail_positions=None):
    validator = CandidateValidator()
    builder = CandidateBuilder(workspace_root=tmp_path, validator=validator, clock=lambda: NOW)
    adapters = [
        MarkdownReportAdapter(),
        JsonResultAdapter(),
        CandidatePackageAdapter(None, validator, candidate_builder=builder),
    ]
    return KnowledgeResearchWorkflow(
        workspace_root=tmp_path,
        search_provider=FakeSearch(search_count),
        source_selector=SourceSelector(POLICY),
        source_acquirer=FakeSourceAcquirer(fail_positions=fail_positions),
        evidence_extractor=CompositeEvidenceExtractor(),
        synthesizer=DeterministicResearchSynthesizer(),
        output_adapters=adapters,
        clock=lambda: NOW,
    )


@pytest.mark.asyncio
async def test_offline_workflow_runs_fixed_phases_without_rag(tmp_path: Path) -> None:
    outcome = await workflow(tmp_path).run(PROFILE)

    assert outcome.phases == [
        ResearchPhase.DISCOVER,
        ResearchPhase.SELECT,
        ResearchPhase.ACQUIRE,
        ResearchPhase.EXTRACT,
        ResearchPhase.BUILD_RESULT,
        ResearchPhase.OUTPUT,
        ResearchPhase.COMPLETE,
    ]
    assert outcome.metrics.search_count == 4
    assert outcome.metrics.selected_source_count == 3
    assert outcome.metrics.download_success == 3
    assert outcome.metrics.evidence_count == 3
    assert outcome.result.status.value == "COMPLETED"
    assert {output.adapter for output in outcome.outputs} == {
        "markdown_report",
        "json_result",
        "candidate_package",
    }
    assert all(output.status != "FAILED" for output in outcome.outputs)


@pytest.mark.asyncio
async def test_download_failure_continues_with_other_sources(tmp_path: Path) -> None:
    outcome = await workflow(tmp_path, fail_positions={2}).run(PROFILE)

    assert outcome.metrics.download_success == 2
    assert outcome.metrics.download_failure == 1
    assert outcome.result.status.value == "PARTIAL"
    assert any(failure.code.value == "DOWNLOAD_FAILED" for failure in outcome.failures)
    assert outcome.metrics.evidence_count == 2


@pytest.mark.asyncio
async def test_insufficient_evidence_still_writes_markdown_and_json(tmp_path: Path) -> None:
    outcome = await workflow(tmp_path, search_count=1).run(PROFILE)

    by_adapter = {output.adapter: output for output in outcome.outputs}
    assert outcome.result.status.value == "INSUFFICIENT_EVIDENCE"
    assert by_adapter["markdown_report"].status == "CREATED"
    assert by_adapter["json_result"].status == "CREATED"
    assert by_adapter["candidate_package"].status == "INSUFFICIENT_EVIDENCE"


def test_knowledge_research_agent_is_composition_not_manus_subclass() -> None:
    source = (PROJECT_ROOT / "app/agent/knowledge_research.py").read_text(encoding="utf-8")

    assert "class KnowledgeResearchAgent:" in source
    assert "class KnowledgeResearchAgent(Manus)" not in source
