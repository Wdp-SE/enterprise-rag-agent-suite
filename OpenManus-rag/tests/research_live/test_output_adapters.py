from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from app.research.candidate_builder import CandidateBuilder
from app.research.candidate_validator import CandidateValidator
from app.research.evidence_store import EvidenceStore
from app.research.live_models import ResearchFinding, ResearchResult, ResearchSource, ResearchStatus
from app.research.models import Evidence, SourceLevel
from app.research.output_adapters import (
    CandidatePackageAdapter,
    JsonResultAdapter,
    MarkdownReportAdapter,
)
from app.research.profile_loader import load_research_profile
from app.research.run_store import ResearchRunStore, create_run_id
from app.tool.knowledge_draft import KnowledgeDraftTool


PROJECT_ROOT = Path(__file__).resolve().parents[2]
PROFILE = load_research_profile(
    PROJECT_ROOT / "config/research_profiles/special_equipment_validation.toml"
)
NOW = datetime(2026, 8, 28, tzinfo=timezone.utc)


def prepare(tmp_path: Path):
    run_id = create_run_id(PROFILE, NOW)
    run_store = ResearchRunStore(tmp_path, run_id)
    run_store.initialize()
    evidence: list[Evidence] = []
    sources: list[ResearchSource] = []
    for source_index, raw_hash in enumerate(("a" * 64, "b" * 64), start=1):
        path = tmp_path / f"research_runs/{run_id}/raw_sources/{raw_hash}.html"
        path.write_text(
            f"<html><body>original source {source_index}</body></html>", encoding="utf-8"
        )
        source_evidence = []
        for chunk_index in range(1, 3):
            item = Evidence(
                title=f"Source {source_index}",
                content=f"Evidence fact {source_index}-{chunk_index}.",
                organization=f"agency{source_index}.gov.cn",
                source_url=f"https://agency{source_index}.gov.cn/source",
                source_type="webpage",
                retrieved_at=NOW,
                local_file=path.relative_to(tmp_path).as_posix(),
                section="Requirements",
                source_level=SourceLevel.TIER1,
            )
            evidence.append(item)
            source_evidence.append(item.evidence_id)
        sources.append(
            ResearchSource(
                source_id=f"S{source_index:02d}",
                title=f"Source {source_index}",
                organization=f"agency{source_index}.gov.cn",
                url=f"https://agency{source_index}.gov.cn/source",
                source_type="webpage",
                source_level=SourceLevel.TIER1,
                local_file=path.relative_to(tmp_path).as_posix(),
                raw_file_hash=raw_hash,
                retrieved_at=NOW,
                evidence_ids=source_evidence,
            )
        )
    result = ResearchResult(
        run_id=run_id,
        profile_id=PROFILE.profile_id,
        research_topic=PROFILE.research_topic,
        status=ResearchStatus.COMPLETED,
        summary="Evidence-only result.",
        key_findings=[
            ResearchFinding(statement=item.content, evidence_ids=[item.evidence_id])
            for item in evidence
        ],
        evidence_ids=[item.evidence_id for item in evidence],
        sources=sources,
        generated_at=NOW,
    )
    store = EvidenceStore(tmp_path, f"research_runs/{run_id}/evidence/evidence.json")
    for item in evidence:
        store.add(item)
    store.save()
    return run_store, store, result, evidence


@pytest.mark.asyncio
async def test_markdown_and_json_outputs_do_not_depend_on_rag(tmp_path: Path) -> None:
    run_store, evidence_store, result, _ = prepare(tmp_path)

    markdown = await MarkdownReportAdapter().write(
        result=result, evidence_store=evidence_store, run_store=run_store, profile=PROFILE
    )
    structured = await JsonResultAdapter().write(
        result=result, evidence_store=evidence_store, run_store=run_store, profile=PROFILE
    )

    report = (tmp_path / markdown.path).read_text(encoding="utf-8")
    payload = json.loads((tmp_path / structured.path).read_text(encoding="utf-8"))
    assert "本报告基于公开资料生成" in report
    assert "[source:S01]" in report
    assert payload["run_id"] == result.run_id
    assert len(payload["evidence_ids"]) == 4


@pytest.mark.asyncio
async def test_candidate_uses_only_selected_evidence_subset(tmp_path: Path) -> None:
    run_store, evidence_store, result, all_evidence = prepare(tmp_path)
    validator = CandidateValidator()
    builder = CandidateBuilder(workspace_root=tmp_path, validator=validator, clock=lambda: NOW)
    tool = KnowledgeDraftTool(
        profile=PROFILE,
        evidence_store=evidence_store,
        candidate_builder=builder,
    )
    adapter = CandidatePackageAdapter(tool, validator)

    artifact = await adapter.write(
        result=result,
        evidence_store=evidence_store,
        run_store=run_store,
        profile=PROFILE,
    )

    selected_ids = set(artifact.details["evidence_ids"])
    package = tmp_path / artifact.path
    package_sources = json.loads((package / "sources.json").read_text(encoding="utf-8"))
    document = (package / "document.md").read_text(encoding="utf-8")
    assert len(result.evidence_ids) == 4
    assert len(selected_ids) == 2
    assert {source["evidence_id"] for source in package_sources} == selected_ids
    for item in all_evidence:
        if item.evidence_id in selected_ids:
            assert item.content in document
        else:
            assert item.content not in document
    assert all(f"[source:{source['source_id']}]" in document for source in package_sources)

