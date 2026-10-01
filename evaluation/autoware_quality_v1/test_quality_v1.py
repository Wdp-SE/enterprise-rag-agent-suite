from __future__ import annotations

import pytest
from evaluation.autoware_quality_v1.analyze_failures import analyze_failures

from evaluation.autoware_quality_v1.run_benchmark import (
    CORPUS, _load_cases, evaluate_results, select_policy, validate_cases,
)


def _case(case_id="a", family="family-a", split="dev", sources=None, answerable=True):
    return {
        "case_id": case_id,
        "family_id": family,
        "split": split,
        "category": "single_fact" if answerable else "unanswerable_scope",
        "query": "Which component owns this behavior?",
        "query_language": "en",
        "version": "latest",
        "language": "all",
        "required_sources": list(sources or []),
        "required_answer_points": [],
        "expected_image_ids": [],
        "answerable": answerable,
        "expected_relation_state": "none",
        "expected_component_versions": {"documentation": "docs-main", "universe": "0.52.0"},
    }


def test_validator_locks_families_and_exact_sources_across_latest_components():
    cases = [
        _case("docs", sources=["docs-main:en:guide/start"]),
        _case("universe", family="family-b", split="holdout", sources=["0.52.0:en:planning/overview"]),
    ]

    validate_cases(cases, {
        "docs-main:en:guide/start": "docs-main",
        "0.52.0:en:planning/overview": "0.52.0",
    })


def test_frozen_quality_set_covers_all_required_business_categories():
    import json

    cases, lock = _load_cases()
    manifest = json.loads((CORPUS / "corpus_manifest.json").read_text(encoding="utf-8"))
    sources = {
        f"{row['version']}:{row['language']}:{row['document_key']}": row
        for row in manifest["sources"]
    }
    validate_cases(cases, sources)

    assert 80 <= len(cases) <= 120
    assert set(row["category"] for row in cases) == {
        "single_fact", "cross_source", "explicit_version", "zh_query_en_evidence",
        "en_query_zh_evidence", "translation_relation_state", "image_evidence", "unanswerable_scope",
    }
    assert lock["split_counts"]["dev"] + lock["split_counts"]["holdout"] == len(cases)
    assert any(row["version"] == "latest" and row["expected_component_versions"] == {
        "documentation": "docs-main", "universe": "0.52.0",
    } for row in cases)


def test_validator_rejects_family_leakage_and_unknown_source_ids():
    cases = [
        _case("docs", sources=["docs-main:en:guide/start"]),
        _case("docs-copy", family="family-a", split="holdout", sources=["docs-main:en:guide/start"]),
    ]

    with pytest.raises(ValueError, match="family.*split"):
        validate_cases(cases, {"docs-main:en:guide/start": "docs-main"})

    with pytest.raises(ValueError, match="unknown required source"):
        validate_cases([_case(sources=["missing:en:nope"])], {})


def test_metrics_separate_cross_source_completeness_from_recall_and_no_answer_hits():
    cases = [
        _case("cross", sources=["0.52.0:en:planning/a", "0.52.0:en:planning/b"]),
        _case("none", family="negative", split="holdout", answerable=False),
    ]
    hits = {
        "cross": [
            {"document_id": "0.52.0:en:planning/a", "version": "0.52.0", "retrieval_score": 3},
        ],
        "none": [
            {"document_id": "0.52.0:en:planning/noise", "version": "0.52.0", "retrieval_score": 1},
        ],
    }

    metrics = evaluate_results(cases, hits, {"cross": [2.0], "none": [1.0]})

    assert metrics["required_source_recall_at_5"] == 0.5
    assert metrics["complete_required_sources_at_5"] == 0.0
    assert metrics["no_answer_nonempty_candidate_rate"] == 1.0
    assert metrics["by_category"]["unanswerable_scope"]["query_count"] == 1


def test_duplicate_chunks_from_one_required_document_do_not_inflate_rank_metrics():
    case = _case(sources=["docs-main:en:guide/start"])
    hits = {
        "a": [
            {"document_id": "docs-main:en:guide/start", "version": "docs-main", "retrieval_score": 4},
            {"document_id": "docs-main:en:guide/start", "version": "docs-main", "retrieval_score": 3},
            {"document_id": "docs-main:en:guide/other", "version": "docs-main", "retrieval_score": 2},
        ],
    }

    metrics = evaluate_results([case], hits, {"a": [1.0]})

    assert metrics["mrr_at_5"] == 1.0
    assert metrics["ndcg_at_5"] == 1.0
    assert metrics["required_source_recall_at_5"] == 1.0


def test_policy_selection_requires_holdout_gain_and_every_safety_gate():
    baseline = {
        "required_source_recall_at_5": 0.8, "complete_required_sources_at_5": 0.7,
        "no_answer_nonempty_candidate_rate": 0.4, "version_mismatch_count": 0,
        "explicit_version_mismatch_count": 0,
        "image_evidence_hit_at_5": 0.5, "search_p95_ms": 10,
    }
    dev = {**baseline, "image_evidence_hit_at_5": 0.8}
    holdout_regression = {**baseline, "complete_required_sources_at_5": 0.6, "image_evidence_hit_at_5": 0.9}
    holdout_gain = {**baseline, "image_evidence_hit_at_5": 0.7}

    assert select_policy({"bm25": {"dev": baseline, "holdout": baseline},
                          "candidate": {"dev": dev, "holdout": holdout_regression}})["selected_policy"] == "bm25"
    assert select_policy({"bm25": {"dev": baseline, "holdout": baseline},
                          "candidate": {"dev": dev, "holdout": holdout_gain}})["selected_policy"] == "candidate"
    assert select_policy({"bm25": {"dev": baseline, "holdout": baseline},
                          "candidate": {"dev": dev, "holdout": {**holdout_gain, "version_mismatch_count": 1}}})["selected_policy"] == "bm25"


def test_failure_analysis_groups_language_version_relation_and_missing_sources():
    chinese_query = _case("zh-en", family="doc-a", sources=["docs-main:en:guide/start"])
    chinese_query.update(category="zh_query_en_evidence", query_language="zh", expected_relation_state="candidate")
    version_query = _case("version", family="doc-b", split="holdout", sources=["docs-main:en:guide/api"])
    version_query.update(category="explicit_version", expected_component_versions={"documentation": "docs-main"})
    relation_query = _case("relation", family="doc-c", sources=["docs-main:zh:guide/launch", "docs-main:en:guide/launch"])
    relation_query.update(category="translation_relation_state", expected_relation_state="candidate")
    report = {
        "splits": {
            "dev": {"bm25": {"cases": [
                {"case_id": "zh-en", "required_sources": ["docs-main:en:guide/start"],
                 "found_sources_at_5": [], "expected_image_ids": [], "found_image_ids_at_5": [],
                 "hit_document_ids_at_5": ["docs-main:zh:guide/other"], "version_mismatches_at_5": []},
                {"case_id": "relation", "required_sources": ["docs-main:zh:guide/launch", "docs-main:en:guide/launch"],
                 "found_sources_at_5": ["docs-main:zh:guide/launch"], "expected_image_ids": [],
                 "found_image_ids_at_5": [], "hit_document_ids_at_5": ["docs-main:zh:guide/launch"],
                 "version_mismatches_at_5": []},
            ], "no_answer_nonempty_candidates": "1/1"}},
            "holdout": {"bm25": {"cases": [
                {"case_id": "version", "required_sources": ["docs-main:en:guide/api"],
                 "found_sources_at_5": [], "expected_image_ids": [], "found_image_ids_at_5": [],
                 "hit_document_ids_at_5": ["1.9.0:en:guide/api"],
                 "version_mismatches_at_5": [{"document_id": "1.9.0:en:guide/api", "version": "1.9.0"}]},
            ], "no_answer_nonempty_candidates": "1/1"}},
        },
        "selection": {"selected_policy": "bm25"},
    }

    analysis = analyze_failures(report, [chinese_query, version_query, relation_query])

    assert analysis["failure_count"] == 3
    assert analysis["by_query_language"]["zh"]["case_ids"] == ["zh-en"]
    assert analysis["by_selected_component_version"]["documentation=docs-main"]["case_ids"] == ["version"]
    assert analysis["by_selected_component_version"]["documentation=docs-main,universe=0.52.0"]["case_ids"] == ["relation", "zh-en"]
    assert analysis["by_relation_state"]["candidate"]["case_ids"] == ["relation", "zh-en"]
    failures = {row["case_id"]: row for row in analysis["failures"]}
    assert failures["zh-en"]["missing_required_sources"] == ["docs-main:en:guide/start"]
    assert failures["version"]["version_mismatches_at_5"]
