from __future__ import annotations

from fastapi.testclient import TestClient

from src.engineering_change import (
    ChangeType,
    DiscoverySource,
    EngineeringImpactService,
    EngineeringItem,
    EngineeringItemRetriever,
    EngineeringItemType,
    EngineeringRetrievalScope,
    TraceLink,
    TraceProvenance,
    TraceStatus,
    compare_engineering_items,
    content_hash,
)
from src.rd_v2_api import create_app
from tests.test_rd_v3_runtime_api import _runtime


def item(
    identifier: str,
    *,
    version: str = "v1",
    content: str | None = None,
    document: str = "requirements",
    item_type: EngineeringItemType = EngineeringItemType.REQUIREMENT,
) -> EngineeringItem:
    text = content or f"{identifier} 默认内容"
    fields = {
        "organization_id": "demo_company_a",
        "project_id": "PAYMENT",
        "document_id": document,
        "version_id": version,
        "section_id": f"{document}-section",
        "external_identifier": identifier,
    }
    return EngineeringItem(
        item_id=EngineeringItem.stable_id(fields),
        item_type=item_type,
        organization_id=fields["organization_id"],
        project_id=fields["project_id"],
        document_id=document,
        version_id=version,
        section_id=fields["section_id"],
        external_identifier=identifier,
        title=identifier,
        content=text,
        content_hash=content_hash(text),
    )


def test_item_diff_identifies_all_change_types_by_external_identifier() -> None:
    old = [
        item("REQ-023", content="REQ-023 并发 500"),
        item("REQ-024", content="REQ-024 保持"),
        item("REQ-099", content="REQ-099 删除"),
    ]
    new = [
        item("REQ-023", version="v2", content="REQ-023 并发 1000"),
        item("REQ-024", version="v2", content="REQ-024 保持"),
        item("REQ-025", version="v2", content="REQ-025 新增异步状态"),
    ]

    changes = compare_engineering_items(old, new)

    assert {change.external_identifier: change.change_type for change in changes} == {
        "REQ-023": ChangeType.MODIFIED,
        "REQ-024": ChangeType.UNCHANGED,
        "REQ-025": ChangeType.ADDED,
        "REQ-099": ChangeType.REMOVED,
    }
    modified = next(change for change in changes if change.external_identifier == "REQ-023")
    assert modified.old_content == "REQ-023 并发 500"
    assert modified.new_content == "REQ-023 并发 1000"
    assert modified.old_version_id == "v1"
    assert modified.new_version_id == "v2"
    assert modified.old_content_hash != modified.new_content_hash


def test_exact_identifier_retrieval_applies_scope_before_exact_then_dense() -> None:
    exact_wrong_project = item("REQ-023", document="other")
    exact_wrong_project.project_id = "OTHER"
    exact = item("REQ-023", version="v2")
    semantic = item(
        "DES-014", version="design-v1", document="design",
        item_type=EngineeringItemType.DESIGN,
    )
    out_of_scope_dense = item(
        "API-008", version="api-v1", document="api", item_type=EngineeringItemType.API,
    )
    out_of_scope_dense.project_id = "OTHER"

    hits = EngineeringItemRetriever().retrieve(
        "REQ-023 有哪些影响？",
        [exact_wrong_project, exact, semantic, out_of_scope_dense],
        EngineeringRetrievalScope(organization_ids=["demo_company_a"], project_ids=["PAYMENT"]),
        dense_item_ids=[semantic.item_id, out_of_scope_dense.item_id],
        top_k=5,
    )

    assert [hit.item.item_id for hit in hits] == [exact.item_id, semantic.item_id]
    assert [hit.discovery_source for hit in hits] == [
        DiscoverySource.EXACT_IDENTIFIER,
        DiscoverySource.RETRIEVAL_SUGGESTION,
    ]


def test_confirmed_trace_and_suggested_dense_impact_remain_distinct() -> None:
    requirement = item("REQ-023", version="requirements-v2")
    design = item("DES-014", document="design", item_type=EngineeringItemType.DESIGN)
    runbook = item("OPS-006", document="runbook", item_type=EngineeringItemType.RUNBOOK)
    trace = TraceLink.create(
        source_item_id=requirement.item_id,
        target_item_id=design.item_id,
        provenance=TraceProvenance.EXPLICIT,
        status=TraceStatus.CONFIRMED,
        metadata={"evidence_ids": ["ev_explicit"]},
    )

    impacts = EngineeringImpactService().discover(
        changed_item_id=requirement.item_id,
        items=[requirement, design, runbook],
        trace_links=[trace],
        dense_item_ids=[design.item_id, runbook.item_id],
        evidence_by_item={runbook.item_id: ["ev_semantic"]},
    )

    assert [(impact.impacted_item_id, impact.discovery_source, impact.review_status) for impact in impacts] == [
        (design.item_id, DiscoverySource.EXPLICIT_TRACE, TraceStatus.CONFIRMED),
        (runbook.item_id, DiscoverySource.RETRIEVAL_SUGGESTION, TraceStatus.SUGGESTED),
    ]
    assert impacts[0].trace_link_id == trace.trace_link_id
    assert impacts[1].trace_link_id is None
    assert impacts[1].evidence_ids == ["ev_semantic"]


def test_v4_engineering_http_contracts_keep_existing_fastapi_boundary(tmp_path) -> None:
    old = item("REQ-023", content="REQ-023 并发 500")
    new = item("REQ-023", version="v2", content="REQ-023 并发 1000")
    design = item("DES-014", document="design", item_type=EngineeringItemType.DESIGN)
    trace = TraceLink.create(
        source_item_id=new.item_id,
        target_item_id=design.item_id,
        provenance=TraceProvenance.EXPLICIT,
        status=TraceStatus.CONFIRMED,
    )

    with TestClient(create_app(_runtime(tmp_path))) as client:
        diff = client.post("/engineering/items/diff", json={
            "old_items": [old.model_dump(mode="json")],
            "new_items": [new.model_dump(mode="json")],
        })
        assert diff.status_code == 200
        assert diff.json()["changes"][0]["change_type"] == "MODIFIED"

        retrieve = client.post("/engineering/items/retrieve", json={
            "query": "REQ-023",
            "items": [new.model_dump(mode="json"), design.model_dump(mode="json")],
            "scope": {"organization_ids": ["demo_company_a"], "project_ids": ["PAYMENT"]},
            "dense_item_ids": [design.item_id],
            "top_k": 5,
        })
        assert retrieve.status_code == 200
        assert [row["discovery_source"] for row in retrieve.json()["results"]] == [
            "EXACT_IDENTIFIER", "RETRIEVAL_SUGGESTION"
        ]

        impact = client.post("/engineering/impacts/discover", json={
            "changed_item_id": new.item_id,
            "items": [new.model_dump(mode="json"), design.model_dump(mode="json")],
            "trace_links": [trace.model_dump(mode="json")],
            "dense_item_ids": [design.item_id],
            "evidence_by_item": {},
        })
        assert impact.status_code == 200
        assert impact.json()["impacts"][0]["discovery_source"] == "EXPLICIT_TRACE"
        assert impact.json()["impacts"][0]["review_status"] == "CONFIRMED"

