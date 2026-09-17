from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from app.research.evidence_budget import (
    EvidenceBudgetPlanner,
    EvidenceSelectionStatus,
)
from app.research.evidence_store import EvidenceStore
from app.research.models import Evidence, SourceLevel
from app.research.profile_loader import load_research_profile


PROJECT_ROOT = Path(__file__).resolve().parents[2]
PROFILE = load_research_profile(
    PROJECT_ROOT / "config/research_profiles/special_equipment_validation.toml"
)
NOW = datetime(2026, 8, 28, tzinfo=timezone.utc)


def marker_counter(text: str) -> int:
    """Predictable test counter: fixed overhead plus explicit TOKEN markers."""

    return 10 + text.count("TOKEN")


def planner(
    *,
    context: int = 100,
    source_share: float = 0.70,
    single_share: float = 1.0,
) -> EvidenceBudgetPlanner:
    return EvidenceBudgetPlanner(
        max_context_budget=context,
        completion_reserve_tokens=10,
        safety_margin_tokens=10,
        max_source_share=source_share,
        max_single_evidence_share=single_share,
        token_counter=marker_counter,
    )


def evidence(
    marker: str,
    *,
    tokens: int = 5,
    url: str = "https://example.gov.cn/source-a",
    level: SourceLevel = SourceLevel.TIER1,
    source_type: str = "government_webpage",
    relevant: bool = True,
    exact_content: str | None = None,
) -> Evidence:
    content = exact_content or (
        ("特种设备使用单位安全管理要求 " if relevant else "周末天气与体育比赛 ")
        + marker
        + (" TOKEN" * tokens)
    )
    return Evidence(
        title="特种设备公开资料" if relevant else "无关资料",
        content=content,
        organization=url.split("/")[2],
        source_url=url,
        source_type=source_type,
        retrieved_at=NOW,
        local_file="research_runs/run/raw_sources/" + marker.casefold() + ".html",
        section=f"section-{marker}",
        source_level=level,
    )


def twenty_two_evidence() -> list[Evidence]:
    return [
        evidence(
            f"item-{index:02d}",
            url=f"https://example.gov.cn/source-{'a' if index % 2 else 'b'}",
        )
        for index in range(22)
    ]


def test_twenty_two_evidence_are_reduced_below_budget() -> None:
    selected, report = planner().plan(PROFILE, twenty_two_evidence())

    assert report.total_evidence_count == 22
    assert 0 < len(selected) < 22
    assert report.selected_estimated_tokens <= report.max_evidence_budget


def test_same_input_produces_stable_selection() -> None:
    items = twenty_two_evidence()

    first = planner().plan(PROFILE, items)[1]
    second = planner().plan(PROFILE, items)[1]

    assert first.selected_evidence_ids == second.selected_evidence_ids
    assert first.selection_reasons == second.selection_reasons


def test_shuffled_input_order_does_not_change_selection() -> None:
    items = twenty_two_evidence()

    forward = planner().plan(PROFILE, items)[1]
    reversed_result = planner().plan(PROFILE, list(reversed(items)))[1]

    assert forward.selected_evidence_ids == reversed_result.selected_evidence_ids


def test_selection_never_exceeds_evidence_token_budget() -> None:
    _, report = planner(context=80).plan(PROFILE, twenty_two_evidence())

    assert report.selected_estimated_tokens <= report.max_evidence_budget
    assert report.selected_prompt_estimated_tokens <= (
        report.max_context_budget
        - report.completion_reserve_tokens
        - report.safety_margin_tokens
    )


def test_high_relevance_evidence_is_preferred() -> None:
    relevant = evidence("relevant", tokens=30)
    unrelated = evidence(
        "unrelated",
        tokens=30,
        url="https://example.gov.cn/unrelated",
        relevant=False,
    )

    selected, report = planner(source_share=1.0).plan(
        PROFILE, [unrelated, relevant]
    )

    assert [item.evidence_id for item in selected] == [relevant.evidence_id]
    assert "low topic/question relevance" in report.selection_reasons[unrelated.evidence_id]


def test_higher_source_level_wins_when_relevance_is_equal() -> None:
    tier1 = evidence(
        "same-a",
        tokens=30,
        url="https://authority.example/source",
        level=SourceLevel.TIER1,
    )
    tier3 = evidence(
        "same-b",
        tokens=30,
        url="https://ordinary.example/source",
        level=SourceLevel.TIER3,
    )

    selected, _ = planner(source_share=1.0).plan(PROFILE, [tier3, tier1])

    assert [item.evidence_id for item in selected] == [tier1.evidence_id]


def test_different_relevant_sources_receive_representatives() -> None:
    source_a = [
        evidence(f"a-{index}", tokens=10, url="https://a.gov.cn/source")
        for index in range(4)
    ]
    source_b = evidence("b-0", tokens=10, url="https://b.gov.cn/source")

    _, report = planner().plan(PROFILE, source_a + [source_b])

    assert set(report.source_distribution) == {
        "https://a.gov.cn/source",
        "https://b.gov.cn/source",
    }


def test_duplicate_content_does_not_consume_budget_twice() -> None:
    duplicate_text = "特种设备使用单位安全管理要求 duplicate TOKEN TOKEN"
    tier1 = evidence(
        "duplicate-a",
        url="https://authority.gov.cn/a",
        level=SourceLevel.TIER1,
        exact_content=duplicate_text,
    )
    tier3 = evidence(
        "duplicate-b",
        url="https://ordinary.example/b",
        level=SourceLevel.TIER3,
        exact_content=duplicate_text,
    )

    selected, report = planner().plan(PROFILE, [tier3, tier1])

    assert [item.evidence_id for item in selected] == [tier1.evidence_id]
    assert "duplicate content" in report.selection_reasons[tier3.evidence_id]


def test_unrelated_evidence_is_excluded_before_budget_fill() -> None:
    related = evidence("related", tokens=5)
    unrelated = evidence("nav", tokens=1, relevant=False)

    selected, report = planner().plan(PROFILE, [unrelated, related])

    assert related.evidence_id in {item.evidence_id for item in selected}
    assert unrelated.evidence_id in report.excluded_evidence_ids


def test_low_score_navigation_fragment_is_excluded() -> None:
    navigation = evidence(
        "navigation",
        tokens=1,
        exact_content="繁体 手机版 网站首页 政务公开 政务服务 互动交流 走进侨乡 TOKEN",
    )
    related = evidence(
        "requirements",
        tokens=5,
        url="https://example.gov.cn/requirements",
    )

    selected, report = planner().plan(PROFILE, [navigation, related])

    assert related.evidence_id in {item.evidence_id for item in selected}
    assert navigation.evidence_id in report.excluded_evidence_ids
    assert "low topic/question relevance" in report.selection_reasons[navigation.evidence_id]


def test_oversized_single_evidence_cannot_fill_the_budget() -> None:
    oversized = evidence("oversized", tokens=30)
    concise = evidence(
        "concise",
        tokens=5,
        url="https://example.gov.cn/concise",
    )

    selected, report = planner(single_share=0.35).plan(
        PROFILE, [oversized, concise]
    )

    assert concise.evidence_id in {item.evidence_id for item in selected}
    assert oversized.evidence_id in report.excluded_evidence_ids
    assert "fair-share limit" in report.selection_reasons[oversized.evidence_id]


def test_empty_evidence_returns_insufficient_evidence() -> None:
    selected, report = planner().plan(PROFILE, [])

    assert selected == []
    assert report.status is EvidenceSelectionStatus.INSUFFICIENT_EVIDENCE
    assert report.selected_evidence_count == 0


def test_planner_does_not_modify_evidence_store(tmp_path: Path) -> None:
    store = EvidenceStore(tmp_path, "evidence/evidence.json")
    for item in twenty_two_evidence():
        store.add(item)
    store.save()
    before_bytes = store.store_path.read_bytes()
    before_ids = [item.evidence_id for item in store.list()]

    planner().plan(PROFILE, store.list())

    assert [item.evidence_id for item in store.list()] == before_ids
    assert store.store_path.read_bytes() == before_bytes


def test_selection_report_contains_a_reason_for_every_evidence() -> None:
    items = twenty_two_evidence()

    _, report = planner().plan(PROFILE, items)

    assert set(report.selection_reasons) == {item.evidence_id for item in items}
    assert report.total_estimated_tokens >= report.selected_estimated_tokens
    assert report.fixed_prompt_estimated_tokens > 0
    assert report.token_estimation_method == "project_model_token_counter"


def test_all_selected_ids_come_from_original_evidence() -> None:
    items = twenty_two_evidence()

    selected, report = planner().plan(PROFILE, items)

    original_ids = {item.evidence_id for item in items}
    assert set(report.selected_evidence_ids).issubset(original_ids)
    assert {item.evidence_id for item in selected} == set(report.selected_evidence_ids)


def test_preferred_source_type_breaks_an_equal_rank_tie() -> None:
    preferred = evidence(
        "same-a",
        tokens=30,
        url="https://preferred.example/source",
        source_type="government_webpage",
    )
    other = evidence(
        "same-b",
        tokens=30,
        url="https://other.example/source",
        source_type="blog",
    )

    selected, _ = planner(source_share=1.0).plan(PROFILE, [other, preferred])

    assert [item.evidence_id for item in selected] == [preferred.evidence_id]
