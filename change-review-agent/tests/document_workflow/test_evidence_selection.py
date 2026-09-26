from __future__ import annotations

from datetime import datetime, timezone

import pytest

from app.document_workflow.configuration import DocumentWorkflowConfig
from app.document_workflow.evidence_models import Evidence
from app.document_workflow.evidence_selection import (
    EvidenceSelectionError,
    EvidenceSelectionPolicy,
    EvidenceSelector,
)
from app.document_workflow.scope import WorkflowScope


def item(
    name: str,
    *,
    project_id: str = "PAYMENT",
    document_id: str = "requirements",
    version_id: str = "requirements-v2",
    version_status: str = "ACTIVE",
    freshness: str = "FRESH",
) -> Evidence:
    return Evidence(
        title=name,
        content=f"{name}：系统最大并发为 1000。",
        organization="星海软件科技有限公司（虚构）",
        source_type="RAG",
        source_url=f"https://example.test/{name}",
        project_id=project_id,
        document_id=document_id,
        document_type="REQUIREMENT",
        version_id=version_id,
        version_label="V2.0",
        version_status=version_status,
        freshness=freshness,
        chunk_id=f"{name}:1",
        query="最大并发",
        section="性能要求",
        section_path=["需求规格", "性能要求"],
        page_number=1,
        retrieved_at=datetime.now(timezone.utc),
        similarity=0.9,
    )


def test_selection_filters_scope_and_freshness_deduplicates_and_keeps_required() -> None:
    primary = item("primary")
    critical = item("critical")
    candidates = [
        primary,
        primary.model_copy(deep=True),
        item("stale", version_id="requirements-v1", version_status="SUPERSEDED", freshness="STALE"),
        item("outside", project_id="OTHER"),
        critical,
    ]
    selector = EvidenceSelector(EvidenceSelectionPolicy(max_evidence_count=1))

    result = selector.select(
        candidates,
        WorkflowScope(project_ids=("PAYMENT",), active_only=True),
        required_evidence_ids=(critical.evidence_id,),
    )

    assert [row.evidence_id for row in result.selected] == [critical.evidence_id]
    assert result.stats.model_dump() == {
        "retrieved_evidence_count": 5,
        "valid_evidence_count": 3,
        "deduplicated_evidence_count": 2,
        "selected_evidence_count": 1,
    }


def test_selection_blocks_instead_of_dropping_required_evidence() -> None:
    first = item("first")
    second = item("second")
    selector = EvidenceSelector(EvidenceSelectionPolicy(max_evidence_count=1))

    with pytest.raises(EvidenceSelectionError, match="required Evidence exceeds max_evidence_count"):
        selector.select(
            [first, second],
            WorkflowScope(project_ids=("PAYMENT",), active_only=True),
            required_evidence_ids=(first.evidence_id, second.evidence_id),
        )


def test_max_evidence_count_is_configurable_and_part_of_fingerprint(monkeypatch) -> None:
    monkeypatch.setenv("DOCUMENT_WORKFLOW_MAX_EVIDENCE_COUNT", "7")
    configured = DocumentWorkflowConfig.from_env()

    assert configured.max_evidence_count == 7
    assert configured.fingerprint() != DocumentWorkflowConfig(max_evidence_count=5).fingerprint()

    with pytest.raises(ValueError, match="max_evidence_count"):
        DocumentWorkflowConfig(max_evidence_count=0).validate()
