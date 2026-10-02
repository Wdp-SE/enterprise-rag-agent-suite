from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.public_knowledge import PublicKnowledgeIndex
from src.public_retrieval_runtime import PublicRetrievalRuntime


AUTOWARE_CORPUS = Path(__file__).resolve().parents[1] / "public_corpus_autoware"


def _config(tmp_path: Path, **overrides) -> Path:
    payload = {
        "schema_version": 1,
        "default_policy": "bm25",
        "allowed_policies": [
            "bm25", "bm25_faceted_rrf", "bm25_figure_ocr",
            "bm25_faceted_figure_ocr", "hybrid",
        ],
        "max_facets": 4,
        "rrf_k": 60,
        "image_top_k": 20,
    }
    payload.update(overrides)
    path = tmp_path / "runtime.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def _sidecar(tmp_path: Path) -> Path:
    source = Path(__file__).resolve().parents[1] / "public_corpus" / "figure_evidence_reviewed.json"
    target = tmp_path / "figures.json"
    target.write_bytes(source.read_bytes())
    return target


def test_default_runtime_is_exactly_the_locked_bm25_baseline(tmp_path):
    index = PublicKnowledgeIndex()
    runtime = PublicRetrievalRuntime(index, config_path=_config(tmp_path), sidecar_path=_sidecar(tmp_path))

    question = "DolphinScheduler 参数优先级从高到低是什么？"
    assert runtime.search(question) == index.search(question)
    assert runtime.last_retrieval_call_count == 1


@pytest.mark.parametrize("overrides", [
    {"schema_version": 2},
    {"default_policy": "unknown"},
    {"default_policy": "hybrid", "allowed_policies": ["bm25"]},
    {"max_facets": 0},
])
def test_invalid_runtime_config_fails_closed(tmp_path, overrides):
    with pytest.raises(ValueError, match="runtime config"):
        PublicRetrievalRuntime(
            PublicKnowledgeIndex(), config_path=_config(tmp_path, **overrides), sidecar_path=_sidecar(tmp_path),
        )


def test_image_rows_obey_version_and_language_scope(tmp_path):
    runtime = PublicRetrievalRuntime(
        PublicKnowledgeIndex(), config_path=_config(tmp_path), sidecar_path=_sidecar(tmp_path),
    )

    current = runtime.search(
        "processExitValue=0", top_k=20, version="3.4.3", language="en", policy="bm25_figure_ocr",
    )
    historical = runtime.search(
        "processExitValue=0", top_k=20, version="3.4.2", language="en", policy="bm25_figure_ocr",
    )

    assert any(row.get("figure_id") == "db6baeb0b9b5364a" for row in current)
    assert not any(row.get("modality") == "image_ocr" for row in historical)
    assert all(row["version"] == "3.4.3" for row in current)


@pytest.mark.parametrize("field,value", [
    ("review_status", "pending"),
    ("sha256", "0" * 64),
])
def test_unapproved_or_hash_mismatched_ocr_is_not_searchable(tmp_path, field, value):
    sidecar = json.loads(_sidecar(tmp_path).read_text(encoding="utf-8"))
    figure = next(row for row in sidecar["chunks"] if row["figure_id"] == "db6baeb0b9b5364a")
    figure[field] = value
    sidecar_path = tmp_path / "tampered.json"
    sidecar_path.write_text(json.dumps(sidecar), encoding="utf-8")
    runtime = PublicRetrievalRuntime(
        PublicKnowledgeIndex(), config_path=_config(tmp_path), sidecar_path=sidecar_path,
    )

    hits = runtime.search(
        "processExitValue=0", top_k=20, version="3.4.3", language="en", policy="bm25_figure_ocr",
    )

    assert not any(row.get("figure_id") == "db6baeb0b9b5364a" for row in hits)


def test_faceted_rrf_deduplicates_and_records_contributing_facets(tmp_path):
    runtime = PublicRetrievalRuntime(
        PublicKnowledgeIndex(), config_path=_config(tmp_path), sidecar_path=_sidecar(tmp_path),
    )

    hits = runtime.search(
        "参数优先级；工作流启动参数", top_k=20,
        version="3.4.3", language="zh", policy="bm25_faceted_rrf",
    )

    ids = [row["chunk_id"] for row in hits]
    assert len(ids) == len(set(ids))
    assert any(len(row.get("retrieved_by", [])) > 1 for row in hits)
    assert runtime.last_retrieval_call_count == 2


def test_faceted_single_fact_preserves_baseline_order(tmp_path):
    index = PublicKnowledgeIndex()
    runtime = PublicRetrievalRuntime(index, config_path=_config(tmp_path), sidecar_path=_sidecar(tmp_path))
    query = "missed_fire_policy 默认值是什么"

    assert runtime.search(query, policy="bm25_faceted_rrf") == index.search(query)
    assert runtime.last_retrieval_call_count == 1


def test_autoware_public_runtime_is_chinese_only_and_has_no_english_ocr_corpus():
    index = PublicKnowledgeIndex(root=AUTOWARE_CORPUS)
    runtime = PublicRetrievalRuntime(
        index,
        config_path=AUTOWARE_CORPUS / "public_retrieval_runtime.json",
        sidecar_path=AUTOWARE_CORPUS / "figure_evidence_reviewed.json",
    )
    question = "Autoware ROS 节点如何声明和读取参数？"
    candidate = runtime.search(question, top_k=5, version="latest", language="zh")
    english = runtime.search("How are trajectory checker constraints configured?", top_k=5, version="latest", language="en")

    assert candidate and all(row["locale"] == "zh-CN" for row in candidate)
    assert not english
    assert runtime._images == []
    assert runtime.config["default_policy"] == "bm25"


def test_autoware_chinese_current_and_history_are_separate_version_scopes():
    index = PublicKnowledgeIndex(root=AUTOWARE_CORPUS)
    runtime = PublicRetrievalRuntime(
        index,
        config_path=AUTOWARE_CORPUS / "public_retrieval_runtime.json",
        sidecar_path=AUTOWARE_CORPUS / "figure_evidence_reviewed.json",
    )
    question = "Autoware ROS 节点如何声明和读取参数？"
    current = runtime.search(question, top_k=5, version="latest", language="zh")
    history = runtime.search(question, top_k=5, version="community-zh-2026-01", language="zh")

    assert current and all(row["version"] == "community-zh-2026-07" for row in current)
    assert history and all(row["version"] == "community-zh-2026-01" for row in history)
