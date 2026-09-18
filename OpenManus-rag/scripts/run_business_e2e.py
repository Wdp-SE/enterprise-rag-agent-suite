"""Safe offline E2E for drafting, review, rejection and official finalization."""

from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.document_workflow import DocumentWorkflowFacade
from app.document_workflow.configuration import DocumentWorkflowConfig
from app.document_workflow.integrity import OutputIntegrityError
from app.document_workflow.rag import DemoRAGClient


TEMPLATE = ROOT / "project_delivery/document_workflow_business_refactor/demo/requirement_change_impact_template.docx"
OUTPUT = ROOT / "project_delivery/document_workflow_business_refactor/e2e"


def main() -> None:
    if OUTPUT.exists():
        shutil.rmtree(OUTPUT)
    client = DemoRAGClient()
    facade = DocumentWorkflowFacade(
        OUTPUT,
        config=DocumentWorkflowConfig(data_classification="synthetic"),
        rag_client=client,
    )
    record = facade.create_workflow(
        TEMPLATE,
        {"project_ids": ["DEMO-RD"], "active_only": True},
    )
    result = facade.run_workflow(record)
    sections = {item["section_title"]: item for item in result["sections"] if item["fields"]}
    multi_evidence = len(sections["1 变更概述"]["fields"][0]["evidence_ids"]) >= 2
    missing = sections["4 回退方案"]["fields"][0]["status"] == "MISSING"

    facade.review_section(
        result["workflow_id"], section_id=sections["1 变更概述"]["section_id"],
        action="APPROVED", reviewer="safe-e2e",
    )
    facade.review_section(
        result["workflow_id"], section_id=sections["2 影响分析"]["section_id"],
        action="APPROVED", reviewer="safe-e2e", comment="人工精炼",
        edited_fields={sections["2 影响分析"]["fields"][0]["field_id"]: "影响接口网关、连接池、容量测试和上线监控。"},
    )
    facade.review_section(
        result["workflow_id"], section_id=sections["3 验证结论"]["section_id"],
        action="APPROVED", reviewer="safe-e2e",
    )
    rejected = facade.review_section(
        result["workflow_id"], section_id=sections["4 回退方案"]["section_id"],
        action="REJECTED", reviewer="safe-e2e", comment="知识库缺少回退方案",
    )
    official_blocked = False
    try:
        facade.finalize_document(result["workflow_id"])
    except OutputIntegrityError:
        official_blocked = True
    facade.review_section(
        result["workflow_id"], section_id=sections["4 回退方案"]["section_id"],
        action="APPROVED", reviewer="safe-e2e", comment="评审人补充",
        edited_fields={sections["4 回退方案"]["fields"][0]["field_id"]: "异常时回退上一稳定版本，并恢复原限流参数。"},
    )
    approved = facade.finalize_document(result["workflow_id"])
    payload = {
        "data_policy": "synthetic/offline",
        "scope": result["scope"],
        "multi_evidence_draft": multi_evidence,
        "missing_fail_closed": missing,
        "section_reject": rejected["workflow_status"] == "REJECTED",
        "official_output_blocked_on_reject": official_blocked,
        "approved_output": approved["workflow_status"] == "APPROVED" and Path(approved["artifacts"]["approved"]).is_file(),
        "workflow_id": result["workflow_id"],
    }
    payload["safe_end_to_end"] = all(
        payload[key] for key in (
            "multi_evidence_draft", "missing_fail_closed", "section_reject",
            "official_output_blocked_on_reject", "approved_output",
        )
    )
    (OUTPUT / "e2e_result.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(payload, ensure_ascii=False))


if __name__ == "__main__":
    main()

