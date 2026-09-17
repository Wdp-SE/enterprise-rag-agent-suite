from __future__ import annotations

import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

from app.research.evidence_store import EvidenceStore
from app.research.live_models import (
    ResearchResult,
    ResearchSource,
    ResearchStatus,
    TokenUsage,
)
from app.research.models import Evidence, SourceLevel
from app.research.llm_synthesis_smoke import synthesize_existing_run
from app.research.profile_loader import load_research_profile
from app.research.research_synthesis import LLMResearchSynthesizer
from app.research.run_store import ResearchRunStore, create_run_id


PROJECT_ROOT = Path(__file__).resolve().parents[2]
PROFILE = load_research_profile(
    PROJECT_ROOT / "config/research_profiles/special_equipment_validation.toml"
)
NOW = datetime(2026, 8, 28, tzinfo=timezone.utc)


def test_run_research_help_is_an_independent_cli_smoke() -> None:
    completed = subprocess.run(
        [sys.executable, "run_research.py", "--help"],
        cwd=PROJECT_ROOT,
        text=True,
        capture_output=True,
        check=False,
    )

    assert completed.returncode == 0, completed.stderr
    assert "Knowledge Research Workflow" in completed.stdout
    assert "--llm-preflight-run" in completed.stdout
    assert "--llm-synthesis-run" in completed.stdout


class OneCallClient:
    model = "fixture-model"

    def __init__(self, evidence_id: str, content: str):
        self.evidence_id = evidence_id
        self.content = content
        self.calls = 0

    def count_tokens(self, prompt: str) -> int:
        return 100

    async def complete(self, prompt: str):
        self.calls += 1
        return json.dumps(
            {
                "findings": [
                    {"statement": self.content, "evidence_ids": [self.evidence_id]}
                ],
                "limitations": [],
                "unresolved_questions": [],
            }
        ), TokenUsage(
            model=self.model,
            prompt_tokens=100,
            completion_tokens=20,
            total_tokens=120,
            latency_seconds=0.2,
        )


@pytest.mark.asyncio
async def test_llm_smoke_reuses_existing_evidence_without_research(tmp_path: Path) -> None:
    run_id = create_run_id(PROFILE, NOW)
    run_store = ResearchRunStore(tmp_path, run_id)
    run_store.initialize()
    raw = run_store.context.raw_sources_root / ("a" * 64 + ".html")
    raw.write_text("<html><body>source</body></html>", encoding="utf-8")
    item = Evidence(
        title="Source",
        content="特种设备使用单位应当建立安全管理制度。",
        organization="example.gov.cn",
        source_url="https://example.gov.cn/source",
        source_type="webpage",
        retrieved_at=NOW,
        local_file=raw.relative_to(tmp_path).as_posix(),
        section="Requirements",
        source_level=SourceLevel.TIER1,
    )
    store = EvidenceStore(tmp_path, run_store.relative_to_workspace(run_store.context.evidence_path))
    store.add(item)
    store.save()
    prior = ResearchResult(
        run_id=run_id,
        profile_id=PROFILE.profile_id,
        research_topic=PROFILE.research_topic,
        status=ResearchStatus.COMPLETED,
        evidence_ids=[item.evidence_id],
        sources=[
            ResearchSource(
                source_id="S01",
                title=item.title,
                organization=item.organization,
                url=item.source_url,
                source_type=item.source_type,
                source_level=item.source_level,
                local_file=item.local_file,
                raw_file_hash="a" * 64,
                retrieved_at=NOW,
                evidence_ids=[item.evidence_id],
            )
        ],
        generated_at=NOW,
    )
    run_store.write_json("outputs/structured_result.json", prior.model_dump(mode="json"))
    run_store.write_text("outputs/research_report.md", "deterministic report\n")
    client = OneCallClient(item.evidence_id, item.content)

    result, result_path, usage_path = await synthesize_existing_run(
        workspace_root=tmp_path,
        run_id=run_id,
        profile=PROFILE,
        synthesizer=LLMResearchSynthesizer(client),
    )

    assert client.calls == 1
    assert result.key_findings[0].evidence_ids == [item.evidence_id]
    assert (tmp_path / result_path).is_file()
    assert json.loads((tmp_path / usage_path).read_text(encoding="utf-8"))["total_tokens"] == 120
    assert (run_store.context.outputs_root / "research_report_llm.md").is_file()
    assert (run_store.context.outputs_root / "structured_result_llm.json").is_file()
    assert (run_store.context.outputs_root / "evidence_selection_report.json").is_file()
    assert (run_store.context.outputs_root / "research_report.md").read_text(
        encoding="utf-8"
    ) == "deterministic report\n"
