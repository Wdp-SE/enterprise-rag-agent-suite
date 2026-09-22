from __future__ import annotations

import copy
import json

from components.prototype_final_view import (
    build_overview,
    build_trace_view,
    load_evaluation_report,
)


def sample_result() -> dict:
    return {
        "changes": [{"change_type": "MODIFIED"}],
        "evidence": {"ev-1": {"content": "1000 并发"}},
        "evidence_selection": {
            "retrieved_evidence_count": 8,
            "valid_evidence_count": 6,
            "deduplicated_evidence_count": 4,
            "selected_evidence_count": 3,
            "max_evidence_count": 3,
            "selected_evidence_ids": ["ev-1"],
        },
        "state": {
            "task_id": "cir-1",
            "status": "APPLY_READY",
            "rag_calls": 3,
            "failure_reason": None,
            "patches": [
                {"review_status": "APPROVED", "apply_status": "PENDING"},
                {"review_status": "REJECTED", "apply_status": "PENDING"},
            ],
            "impacts": [{"discovery_source": "EXPLICIT_TRACE"}],
            "quality_gate": {
                "status": "PASS",
                "reasons": [],
                "patch_apply_status": "PENDING",
            },
            "candidate_version_record": None,
            "trace": [
                {
                    "workflow_id": "cir-1",
                    "step": "CREATE_TASK",
                    "status": "COMPLETE",
                    "latency": 0.01,
                    "rag_calls": 3,
                    "llm_calls": 0,
                    "evidence_count": 1,
                    "failure_reason": None,
                },
                {
                    "workflow_id": "cir-1",
                    "step": "HUMAN_REVIEW",
                    "status": "APPROVED",
                    "latency": 0.02,
                    "rag_calls": 3,
                    "llm_calls": 0,
                    "evidence_count": 1,
                    "failure_reason": None,
                },
            ],
        },
    }


def test_overview_and_trace_are_pure_projections_of_real_state() -> None:
    result = sample_result()
    original = copy.deepcopy(result)
    catalog = [
        {
            "document_id": "requirements",
            "active_version": {"version_id": "requirements-v2"},
            "versions": [
                {"version_id": "requirements-v1", "status": "SUPERSEDED"},
                {"version_id": "requirements-v2", "status": "ACTIVE"},
            ],
        }
    ]

    overview = build_overview(catalog, result)
    trace = build_trace_view(result)

    assert result == original
    assert overview["document_count"] == 1
    assert overview["active_version_count"] == 1
    assert overview["historical_version_count"] == 1
    assert overview["approved_patch_count"] == 1
    assert overview["rejected_patch_count"] == 1
    assert trace["workflow_id"] == "cir-1"
    assert trace["rag_calls"] == 3
    assert trace["llm_calls"] == 0
    assert trace["evidence_count"] == 1
    assert trace["evidence_selection"]["selected_evidence_count"] == 3
    assert any(row["label"] == "人工审核" and row["status"] == "已批准" for row in trace["steps"])


def test_evaluation_loader_is_local_json_only(tmp_path) -> None:
    path = tmp_path / "evaluation.json"
    path.write_text(
        json.dumps(
            {
                "rag": {"case_count": 7, "p50_latency_ms": 42.0, "p95_latency_ms": 109.513},
                "agent": {"impact_recall": 1.0},
                "safety": {"unapproved_writes": 0},
                "baseline_comparison": {"evaluation_only": True},
            }
        ),
        encoding="utf-8",
    )

    loaded = load_evaluation_report(path)

    assert loaded["rag"]["case_count"] == 7
    assert loaded["baseline_comparison"]["evaluation_only"] is True
