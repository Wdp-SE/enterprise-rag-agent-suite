"""Build RAG-owned EngineeringItem/TraceLink fixtures from synthetic DOCX files."""

from __future__ import annotations

import json
import sys
from pathlib import Path

RAG_ROOT = Path(__file__).resolve().parents[1]
if str(RAG_ROOT) not in sys.path:
    sys.path.insert(0, str(RAG_ROOT))

from src.engineering_change import (
    DocxEngineeringParser,
    EngineeringItemFactory,
    IdentifierExtractor,
    OrganizationProfile,
    TraceLink,
    TraceProvenance,
    TraceStatus,
)


WORKSPACE = RAG_ROOT.parent
DEMO_ROOT = WORKSPACE / "project_delivery" / "v4_change_impact_review" / "demo_data"
PROFILE_PATH = RAG_ROOT / "data" / "v4_change_impact" / "profiles" / "demo_company_a.json"


DOCUMENTS = {
    "requirements_v1.docx": ("requirements", "requirements-v1", "需求规格说明书"),
    "requirements_v2.docx": ("requirements", "requirements-v2", "需求规格说明书"),
    "system_design_v1.docx": ("system_design", "design-v1", "系统设计说明书"),
    "api_spec_v1.docx": ("api_spec", "api-v1", "接口规范"),
    "test_cases_v1.docx": ("test_cases", "test-v1", "测试用例"),
    "runbook_v1.docx": ("runbook", "runbook-v1", "运维手册"),
}


def main() -> None:
    profile = OrganizationProfile.model_validate_json(PROFILE_PATH.read_text(encoding="utf-8"))
    parser = DocxEngineeringParser()
    factory = EngineeringItemFactory(IdentifierExtractor())
    items = []
    documents = []
    for filename, (document_id, version_id, document_type) in DOCUMENTS.items():
        source = DEMO_ROOT / filename
        sections = parser.parse(source, profile)
        extracted = factory.build(
            sections=sections,
            profile=profile,
            project_id="PAYMENT",
            document_id=document_id,
            version_id=version_id,
            document_type=document_type,
        )
        # A document may mention identifiers owned by other document types. Keep
        # those cross references as trace inputs, but publish only the primary
        # engineering items owned by this document into the demo inventory.
        items.extend(
            item
            for item in extracted
            if item.item_type.value == item.metadata["default_document_item_type"]
        )
        documents.append({
            "filename": filename,
            "document_id": document_id,
            "version_id": version_id,
            "version_label": "V2.0" if version_id == "requirements-v2" else "V1.0",
            "document_type": document_type,
            "title": source.stem,
        })
    by_key = {(item.version_id, item.external_identifier): item for item in items}
    requirement = by_key[("requirements-v2", "REQ-023")]
    explicit_targets = [
        by_key[("design-v1", "DES-014")],
        by_key[("api-v1", "API-008")],
        by_key[("test-v1", "TC-102")],
    ]
    links = [
        TraceLink.create(
            source_item_id=requirement.item_id,
            target_item_id=target.item_id,
            provenance=TraceProvenance.EXPLICIT,
            status=TraceStatus.CONFIRMED,
            metadata={"source": "synthetic explicit identifier fixture"},
        )
        for target in explicit_targets
    ]
    payload = {
        "schema_version": "v4-engineering-inventory-v1",
        "classification": "FULLY_SYNTHETIC",
        "profile": profile.model_dump(mode="json"),
        "documents": documents,
        "items": [item.model_dump(mode="json") for item in items],
        "trace_links": [link.model_dump(mode="json") for link in links],
        "changed_external_identifier": "REQ-023",
        "patch_target_external_identifier": "DES-014",
    }
    (DEMO_ROOT / "engineering_inventory.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )


if __name__ == "__main__":
    main()
