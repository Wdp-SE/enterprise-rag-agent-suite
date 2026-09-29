"""Tests for deterministic query facets and reciprocal-rank fusion."""

from __future__ import annotations

import importlib.util
from pathlib import Path


MODULE = Path(__file__).resolve().parents[1] / "src" / "retrieval_fusion.py"


def _module():
    spec = importlib.util.spec_from_file_location("retrieval_fusion", MODULE)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_single_fact_query_is_preserved_exactly():
    module = _module()
    query = "3.4.3 的 missed_fire_policy 默认值是什么？"
    assert module.split_query_facets(query) == [query]


def test_explicit_multi_clause_query_splits_and_caps_at_four():
    module = _module()
    query = "参数优先级是什么；失败恢复如何配置；下游节点参数如何传递"
    assert module.split_query_facets(query) == [
        "参数优先级是什么", "失败恢复如何配置", "下游节点参数如何传递",
    ]
    assert len(module.split_query_facets("；".join([f"问题{i}" for i in range(8)]))) == 4


def test_oversized_query_is_rejected_and_whitespace_facets_are_removed():
    module = _module()
    assert module.split_query_facets("甲；；乙") == ["甲", "乙"]
    try:
        module.split_query_facets("字" * 4001)
    except ValueError as exc:
        assert "4000" in str(exc)
    else:
        raise AssertionError("oversized query must be rejected")


def test_rrf_deduplicates_hits_and_keeps_facet_trace():
    module = _module()
    first = {"chunk_id": "3.4.3:zh:a:1", "version": "3.4.3", "retrieval_score": 9.0}
    second = {"chunk_id": "3.4.3:zh:b:1", "version": "3.4.3", "retrieval_score": 4.0}

    result = module.fuse_ranked_hits([[first, second], [second, first]], top_k=5)

    by_id = {hit["chunk_id"]: hit for hit in result}
    assert len(result) == 2
    assert by_id[first["chunk_id"]]["retrieved_by"] == [0, 1]
    assert by_id[second["chunk_id"]]["retrieved_by"] == [0, 1]
    assert by_id[first["chunk_id"]]["rrf_score"] == by_id[second["chunk_id"]]["rrf_score"]
    assert [hit["chunk_id"] for hit in result] == sorted(by_id)
    assert by_id[first["chunk_id"]]["retrieval_score"] == 9.0


def test_single_ranking_preserves_original_order_and_rows():
    module = _module()
    rows = [{"chunk_id": "b"}, {"chunk_id": "a"}]
    assert module.fuse_ranked_hits([rows], top_k=1) == rows[:1]
    assert module.fuse_ranked_hits([], top_k=5) == []
