from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest
from pydantic import ValidationError

from app.research.live_models import (
    ResearchFinding,
    ResearchResult,
    ResearchSearchResult,
    ResearchStatus,
)
from app.research.profile_loader import load_research_profile
from app.research.run_store import ResearchRunStore, ResearchRunStoreError, create_run_id


PROJECT_ROOT = Path(__file__).resolve().parents[2]
PROFILE_PATH = PROJECT_ROOT / "config/research_profiles/special_equipment_validation.toml"


def test_search_result_preserves_structure_and_has_stable_id() -> None:
    first = ResearchSearchResult(
        query="topic",
        title="Official page",
        url="HTTPS://EXAMPLE.GOV.CN/a/?b=2&a=1#fragment",
        snippet="structured snippet",
        engine="Bing",
        position=1,
    )
    second = ResearchSearchResult(
        query="different query",
        title="Changed display title",
        url="https://example.gov.cn/a?a=1&b=2",
        snippet="other snippet",
        engine="bing",
        position=2,
    )

    assert first.url == "https://example.gov.cn/a?a=1&b=2"
    assert first.search_result_id == second.search_result_id
    assert first.snippet == "structured snippet"


def test_research_result_rejects_unknown_evidence_id() -> None:
    with pytest.raises(ValidationError, match="unknown Evidence"):
        ResearchResult(
            run_id="kr_20260828T010203123456Z_1234abcd",
            profile_id="profile",
            research_topic="topic",
            status=ResearchStatus.COMPLETED,
            summary="summary",
            evidence_ids=["ev_11111111111111111111"],
            key_findings=[
                ResearchFinding(
                    statement="unsupported",
                    evidence_ids=["ev_22222222222222222222"],
                )
            ],
            generated_at=datetime.now(timezone.utc),
        )


def test_insufficient_result_rejects_findings() -> None:
    with pytest.raises(ValidationError, match="insufficient Evidence"):
        ResearchResult(
            run_id="kr_20260828T010203123456Z_1234abcd",
            profile_id="profile",
            research_topic="topic",
            status=ResearchStatus.INSUFFICIENT_EVIDENCE,
            evidence_ids=["ev_11111111111111111111"],
            key_findings=[
                ResearchFinding(
                    statement="not allowed",
                    evidence_ids=["ev_11111111111111111111"],
                )
            ],
            generated_at=datetime.now(timezone.utc),
        )


def test_run_store_is_scoped_and_writes_atomically(tmp_path: Path) -> None:
    profile = load_research_profile(PROFILE_PATH)
    run_id = create_run_id(profile, datetime(2026, 8, 28, 1, 2, 3, 123456, timezone.utc))
    store = ResearchRunStore(tmp_path, run_id)
    context = store.initialize()

    staged = store.stage_bytes(b"<!doctype html><html><body>source</body></html>", extension=".html")
    archived = store.archive_staged(staged)
    manifest = store.write_json("outputs/manifest.json", {"run_id": run_id})

    assert context.run_id == run_id
    assert (tmp_path / archived.local_file).read_bytes().startswith(b"<!doctype html>")
    assert (tmp_path / manifest).is_file()
    assert not list((tmp_path / manifest).parent.glob("*.tmp"))


def test_run_store_refuses_reusing_an_existing_run(tmp_path: Path) -> None:
    profile = load_research_profile(PROFILE_PATH)
    run_id = create_run_id(profile, datetime(2026, 8, 28, tzinfo=timezone.utc))
    ResearchRunStore(tmp_path, run_id).initialize()

    with pytest.raises(ResearchRunStoreError, match="already exists"):
        ResearchRunStore(tmp_path, run_id).initialize()

