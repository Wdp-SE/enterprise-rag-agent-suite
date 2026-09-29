"""Contract tests for the independent, retrieval-only V4 evaluation."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest


RUNNER = Path(__file__).with_name("run_quality_v4.py")


def _module():
    spec = importlib.util.spec_from_file_location("quality_v4_runner", RUNNER)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _case(query_id, *, category="single_source", family_id="family", version="3.4.3",
          language="zh", expected_markers=None, expected_image_markers=None,
          answerable=True, figure_id=None, image_refs=None):
    return {
        "query_id": query_id,
        "category": category,
        "family_id": family_id,
        "query": f"查找问题 {query_id}",
        "version_scope": version,
        "language": language,
        "answerable": answerable,
        "expected_markers": expected_markers or {},
        "expected_image_markers": expected_image_markers or {},
        "image_refs": image_refs or {},
        "figure_id": figure_id,
    }


def test_split_keeps_families_and_images_in_one_partition():
    module = _module()
    cases = [
        _case("q1", family_id="same-image-a", category="image_only", figure_id="fig-a"),
        _case("q2", family_id="same-image-a", category="image_only", figure_id="fig-a"),
        _case("q3", family_id="other-family", category="text_plus_image", figure_id="fig-a"),
        _case("q4", family_id="text-family", category="single_source"),
        _case("q5", family_id="text-family", category="single_source"),
        _case("q6", family_id="last-family", category="no_answer", answerable=False),
    ]

    split = module.split_cases(cases, seed="v4-test-seed")

    assert not (set(split["dev"]) & set(split["holdout"]))
    assert set(split["dev"]) | set(split["holdout"]) == {case["query_id"] for case in cases}
    assert {case["query_id"] for case in cases if case["figure_id"] == "fig-a"} <= set(split["dev"]) or {
        case["query_id"] for case in cases if case["figure_id"] == "fig-a"
    } <= set(split["holdout"])
    for family in {case["family_id"] for case in cases}:
        ids = {case["query_id"] for case in cases if case["family_id"] == family}
        assert ids <= set(split["dev"]) or ids <= set(split["holdout"])


def test_metrics_cover_sources_images_versions_and_retrieval_only_no_answer():
    module = _module()
    cases = [
        _case(
            "cross-v", category="cross_version", family_id="versions", version="all",
            expected_markers={
                "3.4.2|zh|guide/parameter/a": ["alpha"],
                "3.4.3|zh|guide/parameter/a": ["beta"],
            },
        ),
        _case(
            "image", category="image_only", family_id="image-a", figure_id="fig-a",
            expected_image_markers={"fig-a": ["screen value 7"]},
        ),
        _case("unknown", category="no_answer", family_id="unknown", answerable=False),
    ]
    ranked_hits = {
        "cross-v": [
            {"version": "3.4.2", "language": "zh", "document_key": "guide/parameter/a", "content": "alpha"},
            {"version": "3.4.3", "language": "zh", "document_key": "guide/parameter/a", "content": "beta"},
        ],
        "image": [
            {"version": "3.4.3", "language": "zh", "document_key": "guide/project/screen", "figure_id": "fig-a", "content": "screen value 7", "modality": "image_ocr"},
        ],
        "unknown": [],
    }

    metrics = module.compute_metrics(
        cases, ranked_hits,
        elapsed_ms={"cross-v": 3.0, "image": 5.0, "unknown": 2.0},
        retrieval_calls={"cross-v": 1, "image": 2, "unknown": 1},
    )

    assert metrics["overall"]["source_recall_at_20"] == 1.0
    assert metrics["overall"]["cross_version_complete_at_5"] == 1.0
    assert metrics["overall"]["image_hit_at_5"] == 1.0
    assert metrics["overall"]["version_mismatch_count"] == 0
    assert metrics["overall"]["no_answer_nonempty_candidate_rate"] == 0.0
    assert metrics["overall"]["answerable_zero_result_rate"] == 0.0
    assert metrics["overall"]["retrieval_call_count"] == 4
    assert metrics["overall"]["warm_p95_ms"] == 5.0
    assert "answer_accuracy" not in metrics["overall"]
    assert "hallucination_rate" not in metrics["overall"]


def test_validation_rejects_missing_sources_and_unapproved_image_evidence(tmp_path):
    module = _module()
    source_path = tmp_path / "guide.md"
    source_path.write_text("visible value 7", encoding="utf-8")
    source = {
        "version": "3.4.3", "language": "zh", "document_key": "guide/a",
        "source_type": "official_documentation", "repository": "apache/dolphinscheduler",
        "local_path": "guide.md",
    }
    index = type("Index", (), {
        "manifest": {"sources": [source]},
        "chunks": [{"version": "3.4.3", "language": "zh", "document_key": "guide/a", "content": "visible value 7"}],
        "root": tmp_path,
    })()
    valid = _case(
        "q", category="image_only", family_id="image", figure_id="fig-a",
        expected_image_markers={"fig-a": ["screen value 7"]},
        image_refs={"fig-a": {"sha256": "a" * 64, "page_or_region": "visible value"}},
    )

    with pytest.raises(ValueError, match="approved image"):
        module.validate_cases([valid], index, {"chunks": []})

    missing = _case("missing", expected_markers={"3.4.3|zh|guide/missing": ["missing"]})
    with pytest.raises(ValueError, match="missing pinned source"):
        module.validate_cases([missing], index, {"chunks": []})

    malformed = _case("bad-single", category="single_source", answerable=False)
    with pytest.raises(ValueError, match="single-source"):
        module.validate_cases([malformed], index, {"chunks": []})


def test_image_cases_bind_reviewed_hash_and_named_region():
    module = _module()
    figure = {
        "figure_id": "fig-a", "version": "3.4.3", "language": "zh",
        "review_status": "approved", "sha256": "a" * 64,
        "content": "screen value 7", "document_key": "guide/a", "modality": "image_ocr",
    }
    case = _case(
        "image", category="image_only", figure_id="fig-a",
        expected_image_markers={"fig-a": ["screen value 7"]},
    )
    index = type("Index", (), {"manifest": {"sources": []}, "chunks": [], "root": Path(".")})()
    with pytest.raises(ValueError, match="image hash and region"):
        module.validate_cases([case], index, {"chunks": [figure]})

    case["image_refs"] = {"fig-a": {"sha256": "b" * 64, "page_or_region": "visible value"}}
    with pytest.raises(ValueError, match="image provenance mismatch"):
        module.validate_cases([case], index, {"chunks": [figure]})

    case["image_refs"]["fig-a"]["sha256"] = "a" * 64
    module.validate_cases([case], index, {"chunks": [figure]})


def test_frozen_v4_dataset_has_declared_coverage_and_no_related_case_leakage():
    module = _module()
    cases = module.read_cases()
    assert len(cases) == module.TARGET_CASE_COUNT == 104
    assert {name: sum(case["category"] == name for case in cases) for name in {
        "single_source", "cross_document", "cross_version", "image_only", "text_plus_image", "no_answer",
    }} == {
        "single_source": 16, "cross_document": 16, "cross_version": 16,
        "image_only": 24, "text_plus_image": 16, "no_answer": 16,
    }
    from src.public_knowledge import PublicKnowledgeIndex

    index = PublicKnowledgeIndex()
    sidecar = json.loads(module.SIDECAR.read_text(encoding="utf-8"))
    module.validate_cases(cases, index, sidecar)
    split = module.split_cases(cases, seed="quality-v4-family-figure-2026-09-29")
    owner = {qid: partition for partition, ids in split.items() for qid in ids}
    for key in ("family_id",):
        for value in {case[key] for case in cases}:
            partitions = {owner[case["query_id"]] for case in cases if case[key] == value}
            assert len(partitions) == 1
    for figure_id in {figure for case in cases for figure in case.get("expected_image_markers", {})}:
        partitions = {
            owner[case["query_id"]] for case in cases
            if figure_id in case.get("expected_image_markers", {})
        }
        assert len(partitions) == 1


def test_holdout_requires_matching_selection_and_is_one_shot(tmp_path):
    module = _module()
    hashes = {"cases.jsonl": "a" * 64}
    execution = tmp_path / "holdout_execution.json"

    with pytest.raises(ValueError, match="selection lock"):
        module.assert_holdout_allowed(None, hashes, execution)
    selection = {"policy": "bm25", "candidate_fingerprint": {"runtime.py": "b" * 64}, "input_sha256": hashes}
    assert module.assert_holdout_allowed(selection, hashes, execution)
    execution.write_text("{}", encoding="utf-8")
    with pytest.raises(FileExistsError, match="already executed"):
        module.assert_holdout_allowed(selection, hashes, execution)
    changed = {"cases.jsonl": "c" * 64}
    with pytest.raises(ValueError, match="input hash"):
        module.assert_holdout_allowed(selection, changed, tmp_path / "new-marker.json")


def test_runtime_activation_default_is_separate_from_scored_candidate_parameters():
    module = _module()
    bm25 = {"schema_version": 1, "default_policy": "bm25", "allowed_policies": ["bm25"], "max_facets": 4}
    image = {**bm25, "default_policy": "bm25_figure_ocr"}
    changed_candidate = {**bm25, "max_facets": 3}

    assert module.runtime_config_fingerprint(bm25) == module.runtime_config_fingerprint(image)
    assert module.runtime_config_fingerprint(bm25) != module.runtime_config_fingerprint(changed_candidate)
