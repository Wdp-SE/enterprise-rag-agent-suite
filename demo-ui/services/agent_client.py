"""UI adapter that depends only on the stable DocumentWorkflowFacade."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

from config import AGENT_ROOT, SAFE_TEMPLATE, DemoConfig
from services.rag_client import ServiceError


class AgentClient:
    def __init__(self, config: DemoConfig):
        self.config = config
        if str(AGENT_ROOT) not in sys.path:
            sys.path.insert(0, str(AGENT_ROOT))
        from app.document_workflow import DocumentWorkflowFacade

        self.facade = DocumentWorkflowFacade(
            config.runtime_root,
            rag_base_url=config.rag_base_url,
            request_timeout_seconds=config.request_timeout_seconds,
            data_classification=config.demo_data_classification,
        )

    def status(self) -> dict[str, Any]:
        ready = SAFE_TEMPLATE.is_file()
        return {"ready": ready, "label": "Ready" if ready else "Flagship template missing"}

    def load_demo_template(self, scope: dict | None = None) -> dict[str, Any]:
        return self.facade.create_workflow(SAFE_TEMPLATE, scope or {"active_only": True}, display_name="需求变更影响分析模板.docx")

    def save_upload(self, filename: str, content: bytes, scope: dict | None = None) -> dict[str, Any]:
        return self.facade.create_workflow_from_bytes(filename, content, scope or {"active_only": True})

    def run_workflow(self, template_record: dict[str, Any], *, use_demo_rag: bool = False) -> dict[str, Any]:
        try:
            return self.facade.run_workflow(template_record, use_demo_rag=use_demo_rag)
        except Exception as exc:
            raise ServiceError("文档工作流执行失败。", str(exc), "AGENT_FAILED") from exc

    def list_workflows(self) -> list[dict[str, Any]]:
        return self.facade.list_workflows()

    def get_workflow(self, workflow_id: str) -> dict[str, Any]:
        return self.facade.get_workflow(workflow_id)

    def resume_workflow(self, workflow_id: str) -> dict[str, Any]:
        try:
            return self.facade.resume_workflow(workflow_id)
        except Exception as exc:
            raise ServiceError("恢复工作流失败。", str(exc), "RESUME_FAILED") from exc

    def review_section(
        self,
        workflow_id: str,
        *,
        section_id: str,
        action: str,
        reviewer: str,
        comment: str,
        edited_fields: dict[str, str],
    ) -> dict[str, Any]:
        try:
            return self.facade.review_section(
                workflow_id, section_id=section_id, action=action,
                reviewer=reviewer, comment=comment, edited_fields=edited_fields,
            )
        except Exception as exc:
            raise ServiceError("章节审核失败。", str(exc), "REVIEW_FAILED") from exc

    def finalize_document(self, workflow_id: str) -> dict[str, Any]:
        try:
            return self.facade.finalize_document(workflow_id)
        except Exception as exc:
            raise ServiceError("正式文档生成失败。", str(exc), "FINALIZE_FAILED") from exc

    def artifact_bytes(self, path: str | Path) -> bytes:
        return self.facade.artifact_bytes(path)
