from __future__ import annotations

import hashlib
import json

from evaluation.real_world_retrieval.quality_v2.expanded_corpus_diagnostic import (
    run_diagnostic, verify_frozen_question_inputs,
)


def test_diagnostic_records_expanded_corpus_separately_from_frozen_v2_results():
    result = run_diagnostic()

    assert result["purpose"] == "regression_diagnostic_only_not_new_holdout_or_policy_selection"
    assert result["old_corpus_manifest_sha256"] != result["expanded_corpus_manifest_sha256"]
    assert result["source_count"] > 52
    assert len(result["splits"]["dev"]["cases"]) == 20
    assert len(result["splits"]["holdout"]["cases"]) == 20
    assert result["splits"]["dev"]["summary"]["answerable_count"] > 0


def test_diagnostic_refuses_modified_frozen_questions(tmp_path):
    files = {
        "queries.jsonl": '{"query_id":"q1"}\n',
        "ground_truth.jsonl": '{"query_id":"q1"}\n',
        "frozen_split.json": '{"dev":["q1"],"holdout":[]}',
    }
    for filename, content in files.items():
        (tmp_path / filename).write_text(content, encoding="utf-8")
    lock = {"sha256": {
        filename: hashlib.sha256((tmp_path / filename).read_bytes()).hexdigest()
        for filename in files
    }}
    (tmp_path / "selection_lock.json").write_text(json.dumps(lock), encoding="utf-8")
    verify_frozen_question_inputs(tmp_path)
    (tmp_path / "queries.jsonl").write_text('{"query_id":"changed"}\n', encoding="utf-8")

    try:
        verify_frozen_question_inputs(tmp_path)
    except ValueError as exc:
        assert "queries.jsonl" in str(exc)
    else:
        raise AssertionError("modified frozen questions must be rejected")
