from __future__ import annotations

import numpy as np
import pytest

from evaluation.autoware_accuracy_v7.quality_first_retrieval import (
    dense_rank,
    reciprocal_rank_fusion,
    retrieval_metrics,
    validate_case_set,
)


def _hit(chunk_id: str, document_id: str, version: str = "docs-main", language: str = "zh") -> dict:
    return {
        "chunk_id": chunk_id,
        "document_id": document_id,
        "version": version,
        "language": language,
    }


def test_dense_rank_applies_version_and_language_filters_before_ranking() -> None:
    hits = [
        _hit("zh", "doc-zh"),
        _hit("en", "doc-en", language="en"),
        _hit("old", "doc-old", version="1.9.0"),
    ]
    vectors = np.asarray([[0.70, np.sqrt(1 - 0.70**2)], [1.00, 0.00], [np.sqrt(1 - 0.01**2), 0.01]], dtype=np.float32)

    ranked = dense_rank(
        np.asarray([1.0, 0.0], dtype=np.float32),
        hits,
        vectors,
        version="docs-main",
        language="zh",
        top_k=10,
    )

    assert [row["chunk_id"] for row in ranked] == ["zh"]
    assert ranked[0]["dense_score"] == pytest.approx(0.70)


def test_dense_rank_rejects_misaligned_or_non_normalized_vectors() -> None:
    hits = [_hit("a", "doc-a")]
    with pytest.raises(ValueError, match="vector rows"):
        dense_rank(np.asarray([1.0, 0.0]), hits, np.zeros((0, 2)), version="docs-main", language="zh", top_k=1)
    with pytest.raises(ValueError, match="normalized"):
        dense_rank(np.asarray([2.0, 0.0]), hits, np.asarray([[1.0, 0.0]]), version="docs-main", language="zh", top_k=1)


def test_rrf_deduplicates_chunks_and_preserves_rank_fusion_provenance() -> None:
    lexical = [_hit("a", "doc-a"), _hit("b", "doc-b")]
    semantic = [_hit("b", "doc-b"), _hit("c", "doc-c")]

    ranked = reciprocal_rank_fusion([lexical, semantic], top_k=3, rrf_k=10)

    assert [row["chunk_id"] for row in ranked] == ["b", "a", "c"]
    assert ranked[0]["retrieval_sources"] == ["lexical", "semantic"]
    assert ranked[0]["rrf_score"] == pytest.approx(1 / 11 + 1 / 12)


def test_retrieval_metrics_separate_recall_completeness_and_wrong_version() -> None:
    cases = [
        {"case_id": "multi", "required_sources": ["doc-a", "doc-b"], "version": "docs-main"},
        {"case_id": "single", "required_sources": ["doc-c"], "version": "docs-main"},
    ]
    results = {
        "multi": [_hit("a", "doc-a"), _hit("old", "doc-x", version="1.9.0")],
        "single": [_hit("c", "doc-c")],
    }

    metrics = retrieval_metrics(cases, results, ks=(1, 2))

    assert metrics["required_source_recall_at_1"] == pytest.approx(2 / 3)
    assert metrics["complete_required_sources_at_1"] == pytest.approx(1 / 2)
    assert metrics["complete_required_sources_at_2"] == pytest.approx(1 / 2)
    assert metrics["wrong_version_count"] == 1
    assert metrics["mrr_at_2"] == pytest.approx(1.0)


def test_validate_case_set_enforces_scope_split_and_old_eval_independence() -> None:
    cases = [
        {
            "case_id": "dev-a", "split": "dev", "family_id": "family-a",
            "query": "中文查询 A", "version": "docs-main", "language": "zh",
            "required_sources": ["docs-main:zh:doc-a"], "answerable": True,
        },
        {
            "case_id": "hold-b", "split": "holdout", "family_id": "family-b",
            "query": "中文查询 B", "version": "docs-main", "language": "zh",
            "required_sources": [], "answerable": False,
        },
    ]
    summary = validate_case_set(
        cases,
        known_sources={"docs-main:zh:doc-a"},
        old_queries={"旧查询"},
        old_sources={"docs-main:zh:old"},
    )
    assert summary["split_counts"] == {"dev": 1, "holdout": 1}
    assert summary["source_reuse_from_prior_evals"] == 0


@pytest.mark.parametrize(
    "mutate, message",
    [
        (lambda rows: rows[1].update(family_id="family-a"), "leak"),
        (lambda rows: rows[0].update(language="en"), "Chinese docs-main"),
        (lambda rows: rows[0].update(required_sources=["docs-main:zh:old"]), "reused"),
        (lambda rows: rows[0].update(answerable=False), "answerable"),
    ],
)
def test_validate_case_set_rejects_leakage_or_bad_labels(mutate, message: str) -> None:
    import copy

    cases = [
        {
            "case_id": "dev-a", "split": "dev", "family_id": "family-a",
            "query": "中文查询 A", "version": "docs-main", "language": "zh",
            "required_sources": ["docs-main:zh:doc-a"], "answerable": True,
        },
        {
            "case_id": "hold-b", "split": "holdout", "family_id": "family-b",
            "query": "中文查询 B", "version": "docs-main", "language": "zh",
            "required_sources": [], "answerable": False,
        },
    ]
    changed = copy.deepcopy(cases)
    mutate(changed)
    with pytest.raises(ValueError, match=message):
        validate_case_set(
            changed,
            known_sources={"docs-main:zh:doc-a", "docs-main:zh:old"},
            old_queries={"旧查询"},
            old_sources={"docs-main:zh:old"},
        )
