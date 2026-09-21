from __future__ import annotations

from components.business_messages import (
    INVALID_EVIDENCE_MESSAGE,
    INVALID_STRUCTURE_MESSAGE,
    NO_EVIDENCE_MESSAGE,
    STALE_EVIDENCE_MESSAGE,
    business_failure_message,
)
from components.evidence_view import render_query_sources
from components.scope_view import build_scope_view


CATALOG = [
    {
        "document_id": "REQ",
        "title": "需求规格说明书",
        "project_id": "P-001",
        "project_name": "研发平台升级",
        "document_type": "REQUIREMENT",
        "active_version": {"version_id": "REQ@2", "version_label": "V2.0", "status": "ACTIVE"},
        "versions": [
            {"version_id": "REQ@1", "version_label": "V1.0", "status": "SUPERSEDED"},
            {"version_id": "REQ@2", "version_label": "V2.0", "status": "ACTIVE"},
        ],
    }
]


def test_scope_view_uses_the_exact_active_and_historical_scope():
    active_scope = {"project_ids": ["P-001"], "document_ids": ["REQ"], "active_only": True}
    active = build_scope_view(active_scope, CATALOG)
    assert active["project"] == "研发平台升级"
    assert active["document_type"] == "需求文档"
    assert active["documents"] == "《需求规格说明书》"
    assert active["versions"] == "当前有效版本"
    assert active["historical"] is False
    assert active["technical_scope"] == active_scope

    historical_scope = {"project_ids": ["P-001"], "version_ids": ["REQ@1"], "active_only": False}
    historical = build_scope_view(historical_scope, CATALOG)
    assert historical["documents"] == "《需求规格说明书》"
    assert "V1.0（历史版本）" in historical["versions"]
    assert historical["historical"] is True
    assert historical["technical_scope"] == historical_scope


def test_query_citation_uses_real_trace_provenance_and_hides_ids_by_default(monkeypatch):
    from components import evidence_view

    rendered = []
    technical = []

    class Context:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

    monkeypatch.setattr(evidence_view.st, "markdown", lambda value, **kwargs: rendered.append(str(value)))
    monkeypatch.setattr(evidence_view.st, "json", lambda value, **kwargs: technical.append(value))
    monkeypatch.setattr(evidence_view.st, "expander", lambda *args, **kwargs: Context())

    render_query_sources(
        [{"document_id": "REQ", "page_number": 126}],
        {"REQ": "需求规格说明书"},
        trace=[{
            "document_id": "REQ",
            "page_number": 126,
            "version_id": "REQ@2",
            "version_label": "V2.0",
            "section_id": "sec-43",
            "section_path": ["4.3 IPv4 分片处理"],
            "chunk_id": "REQ@2:chunk:43",
        }],
    )

    combined = "\n".join(rendered)
    assert "《需求规格说明书》" in combined
    assert "版本：V2.0" in combined
    assert "章节：4.3 IPv4 分片处理" in combined
    assert "页码：第 126 页" in combined
    assert "REQ@2" not in combined and "chunk:43" not in combined
    assert technical[0]["version_id"] == "REQ@2"
    assert technical[0]["chunk_id"] == "REQ@2:chunk:43"


def test_business_failure_messages_cover_existing_fail_closed_states():
    assert business_failure_message("NO_EVIDENCE") == NO_EVIDENCE_MESSAGE
    assert business_failure_message("EVIDENCE_FRESHNESS_INVALID") == STALE_EVIDENCE_MESSAGE
    assert business_failure_message("EVIDENCE_MEMBERSHIP_INVALID") == INVALID_EVIDENCE_MESSAGE
    assert business_failure_message("STRUCTURED_OUTPUT_INVALID") == INVALID_STRUCTURE_MESSAGE
    assert business_failure_message(
        "ALL_REQUIRED_SECTIONS_MUST_BE_APPROVED", pending_review_count=3
    ) == "还有 3 个必要章节尚未审核通过，暂不能生成正式文档。"
