from __future__ import annotations


def test_cross_document_metric_requires_both_sources():
    from evaluation.real_world_retrieval.quality_v2.run_quality_v2 import complete_source_recall

    assert complete_source_recall(["source-a"], {"source-a", "source-b"}) is False
    assert complete_source_recall(["source-a", "source-b"], {"source-a", "source-b"}) is True


def test_source_ranking_metrics_count_each_document_only_once():
    from evaluation.real_world_retrieval.quality_v2.run_quality_v2 import source_ranking_metrics

    metrics = source_ranking_metrics(["source-a", "source-a", "source-b"], {"source-a", "source-b"})

    assert metrics["recall_at_5"] is True
    assert metrics["reciprocal_rank"] == 1.0
    assert metrics["ndcg_at_5"] == 1.0
    assert metrics["complete_source_recall"] is True


def test_split_is_deterministic_and_balanced_by_category():
    from evaluation.real_world_retrieval.quality_v2.run_quality_v2 import assign_split

    counts = {
        "cross_document": 8,
        "version_scope": 8,
        "zh": 6,
        "en": 6,
        "mixed": 4,
        "hard_ambiguous": 4,
        "no_answer": 4,
    }
    queries = [
        {"query_id": f"{category}-{index:02d}", "category": category}
        for category, count in counts.items()
        for index in range(count)
    ]

    split = assign_split(queries)

    assert split == assign_split(queries)
    assert len(split["dev"]) == len(split["holdout"]) == 20
    assert set(split["dev"]).isdisjoint(split["holdout"])
    for category, count in counts.items():
        dev = [query_id for query_id in split["dev"] if query_id.startswith(category + "-")]
        holdout = [query_id for query_id in split["holdout"] if query_id.startswith(category + "-")]
        assert len(dev) == len(holdout) == count // 2


def test_locked_inputs_reject_any_query_or_corpus_change(tmp_path):
    import hashlib
    import json

    from evaluation.real_world_retrieval.quality_v2.run_quality_v2 import load_locked_inputs

    files = {
        "queries.jsonl": '{"query_id":"q1"}\n',
        "ground_truth.jsonl": '{"query_id":"q1","required_source_ids":[]}\n',
        "frozen_split.json": json.dumps({"dev": ["q1"], "holdout": []}),
        "corpus_manifest.json": json.dumps({"sources": []}),
    }
    for name, content in files.items():
        (tmp_path / name).write_text(content, encoding="utf-8")
    lock = {
        "sha256": {
            name: hashlib.sha256((tmp_path / name).read_bytes()).hexdigest()
            for name in files
        }
    }
    (tmp_path / "selection_lock.json").write_text(json.dumps(lock), encoding="utf-8")

    loaded = load_locked_inputs(tmp_path, corpus_manifest_path=tmp_path / "corpus_manifest.json")
    assert loaded["split"] == {"dev": ["q1"], "holdout": []}
    (tmp_path / "queries.jsonl").write_text('{"query_id":"q2"}\n', encoding="utf-8")
    try:
        load_locked_inputs(tmp_path, corpus_manifest_path=tmp_path / "corpus_manifest.json")
    except ValueError as exc:
        assert "hash" in str(exc).casefold()
    else:
        raise AssertionError("changed evaluation inputs must be rejected")


def test_holdout_output_cannot_be_overwritten(tmp_path):
    from evaluation.real_world_retrieval.quality_v2.run_quality_v2 import ensure_holdout_is_unrun

    output = tmp_path / "holdout__bm25.json"
    ensure_holdout_is_unrun(output)
    output.write_text("{}", encoding="utf-8")
    try:
        ensure_holdout_is_unrun(output)
    except FileExistsError:
        pass
    else:
        raise AssertionError("locked HOLDOUT output must not be overwritten")


def test_ground_truth_markers_must_exist_in_the_pinned_source_chunks():
    from evaluation.real_world_retrieval.quality_v2.run_quality_v2 import validate_ground_truth_markers

    truth = [{
        "query_id": "q1", "answerable": True,
        "required_source_ids": ["3.4.3|en|guide/api/healthcheck"],
        "expected_markers": {"3.4.3|en|guide/api/healthcheck": ["API-Server"]},
    }]
    chunks = [{
        "version": "3.4.3", "language": "en", "document_key": "guide/api/healthcheck",
        "document_title": "Health Check", "heading_path": ["API-Server"], "content": "Returns status.",
    }]
    validate_ground_truth_markers(truth, chunks)
    truth[0]["expected_markers"]["3.4.3|en|guide/api/healthcheck"] = ["Worker-Server"]
    try:
        validate_ground_truth_markers(truth, chunks)
    except ValueError as exc:
        assert "marker" in str(exc).casefold()
    else:
        raise AssertionError("unsupported evidence marker must be rejected")


def test_holdout_requires_the_candidate_code_that_won_dev(tmp_path):
    import json

    from evaluation.real_world_retrieval.quality_v2.run_quality_v2 import ensure_candidate_matches_dev

    dev_result = tmp_path / "dev__bm25_fields.json"
    dev_result.write_text(json.dumps({"policy": "bm25_fields", "candidate_sha256": "abc"}), encoding="utf-8")
    ensure_candidate_matches_dev(dev_result, "bm25_fields", "abc")
    try:
        ensure_candidate_matches_dev(dev_result, "bm25_fields", "changed")
    except ValueError as exc:
        assert "changed" in str(exc).casefold()
    else:
        raise AssertionError("HOLDOUT must reject code changed since DEV selection")
