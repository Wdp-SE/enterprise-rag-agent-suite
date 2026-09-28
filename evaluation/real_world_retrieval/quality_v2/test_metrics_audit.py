from __future__ import annotations

from evaluation.real_world_retrieval.quality_v2.metrics_audit import audit_case, summarize_cases


def test_audit_distinguishes_any_hit_from_fractional_and_complete_source_coverage():
    truth = {
        "answerable": True,
        "required_source_ids": ["v|zh|a", "v|zh|b"],
        "expected_markers": {"v|zh|a": ["priority"], "v|zh|b": ["retry"]},
    }
    case = {
        "query_id": "q1",
        "ranked_source_ids": ["v|zh|a", "v|zh|a", "v|zh|other"],
        "ranked_chunk_ids": ["a1", "a2", "o1"],
    }
    chunks = {
        "a1": {"version": "v", "language": "zh", "document_key": "a", "content": "priority"},
        "a2": {"version": "v", "language": "zh", "document_key": "a", "content": "other text"},
        "o1": {"version": "v", "language": "zh", "document_key": "other", "content": "retry"},
    }

    audited = audit_case(case, truth, chunks)

    assert audited["source_hit_at_5"] is True
    assert audited["source_recall_at_5"] == 0.5
    assert audited["complete_source_recall_at_5"] is False
    assert audited["evidence_marker_recall_at_5"] == 0.5
    assert audited["unsupported_marker_source_ids"] == ["v|zh|b"]


def test_audit_requires_marker_in_returned_chunk_and_handles_unanswerable_case():
    truth = {
        "answerable": True,
        "required_source_ids": ["v|en|a"],
        "expected_markers": {"v|en|a": ["health check"]},
    }
    case = {"query_id": "q1", "ranked_source_ids": ["v|en|a"], "ranked_chunk_ids": ["a1"]}
    chunks = {"a1": {"version": "v", "language": "en", "document_key": "a", "content": "unrelated section"}}

    audited = audit_case(case, truth, chunks)
    assert audited["source_recall_at_5"] == 1.0
    assert audited["evidence_marker_recall_at_5"] == 0.0

    no_answer = audit_case(
        {"query_id": "q2", "ranked_source_ids": ["v|en|a"], "ranked_chunk_ids": ["a1"]},
        {"answerable": False, "required_source_ids": [], "expected_markers": {}},
        chunks,
    )
    assert no_answer["source_recall_at_5"] is None
    assert no_answer["evidence_marker_recall_at_5"] is None
    assert summarize_cases([audited, no_answer])["answerable_count"] == 1


def test_audit_rejects_result_without_corresponding_chunk():
    case = {"query_id": "q1", "ranked_source_ids": ["v|en|a"], "ranked_chunk_ids": ["missing"]}
    truth = {
        "answerable": True,
        "required_source_ids": ["v|en|a"],
        "expected_markers": {"v|en|a": ["health check"]},
    }
    try:
        audit_case(case, truth, {})
    except ValueError as exc:
        assert "missing" in str(exc)
    else:
        raise AssertionError("a missing chunk must not silently count as unsupported evidence")
