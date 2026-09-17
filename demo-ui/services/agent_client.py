"""Thin Python adapter over the frozen Document Workflow Agent V2."""

from __future__ import annotations

import hashlib
import json
import shutil
import sys
import uuid
import zipfile
from dataclasses import asdict
from pathlib import Path
from typing import Any

from config import AGENT_ROOT, SAFE_TEMPLATE, DemoConfig
from services.rag_client import ServiceError


class AgentClient:
    def __init__(self, config: DemoConfig):
        self.config = config
        if str(AGENT_ROOT) not in sys.path:
            sys.path.insert(0, str(AGENT_ROOT))

    def status(self) -> dict[str, Any]:
        try:
            from app.document_workflow.template import TemplateParser  # noqa: F401
            from app.document_workflow.workflow import DocumentWorkflow  # noqa: F401
            ready = SAFE_TEMPLATE.is_file()
            return {"ready": ready, "label": "Ready" if ready else "Safe template missing"}
        except Exception as exc:
            return {"ready": False, "label": "Unavailable", "detail": type(exc).__name__}

    @staticmethod
    def _validate_docx(path: Path) -> None:
        if path.suffix.lower() != ".docx" or not path.is_file() or not zipfile.is_zipfile(path):
            raise ValueError("仅支持有效的结构化 Word (.docx) 模板")

    def _new_paths(self) -> tuple[str, Path, Path]:
        run_id = f"ui_{uuid.uuid4().hex}"
        upload_dir = self.config.runtime_root / "uploads" / run_id
        output_dir = self.config.runtime_root / "outputs" / run_id
        upload_dir.mkdir(parents=True)
        output_dir.mkdir(parents=True)
        return run_id, upload_dir, output_dir

    def load_demo_template(self) -> dict[str, Any]:
        run_id, upload_dir, output_dir = self._new_paths()
        target = upload_dir / "template.docx"
        shutil.copy2(SAFE_TEMPLATE, target)
        return self._template_record(run_id, target, output_dir)

    def save_upload(self, filename: str, content: bytes) -> dict[str, Any]:
        if Path(filename).suffix.lower() != ".docx":
            raise ValueError("仅支持 .docx 文件")
        run_id, upload_dir, output_dir = self._new_paths()
        target = upload_dir / "template.docx"
        target.write_bytes(content)
        try:
            self._validate_docx(target)
            return self._template_record(run_id, target, output_dir, display_name=Path(filename).name)
        except Exception:
            shutil.rmtree(upload_dir, ignore_errors=True)
            shutil.rmtree(output_dir, ignore_errors=True)
            raise

    def _template_record(self, run_id: str, path: Path, output_dir: Path,
                         display_name: str | None = None) -> dict[str, Any]:
        self._validate_docx(path)
        summary = self.parse_template(path)
        return {
            "run_id": run_id, "path": str(path), "output_dir": str(output_dir),
            "filename": display_name or path.name, "size": path.stat().st_size,
            "sha256": hashlib.sha256(path.read_bytes()).hexdigest(), "summary": summary,
        }

    def parse_template(self, path: str | Path) -> dict[str, Any]:
        from app.document_workflow.planning import SectionTaskPlanner
        from app.document_workflow.template import TemplateParser

        source = Path(path)
        self._validate_docx(source)
        try:
            schema = TemplateParser().parse(source)
            tasks = SectionTaskPlanner().plan(schema)
        except Exception as exc:
            raise ValueError("DOCX 不是当前 Parser 支持的结构化模板") from exc
        return {
            "template_id": schema.template_id, "template_name": schema.template_name,
            "section_count": len(schema.sections), "table_count": len(schema.tables),
            "field_count": len(schema.fields),
            "sections": [asdict(section) for section in schema.sections],
            "tasks": [{"task_id": task.task_id, "section_id": task.section_id,
                       "section_title": task.section_title, "status": task.status.value,
                       "required_fields": [field.field_name for field in task.required_fields]}
                      for task in tasks],
        }

    def run_workflow(self, template_record: dict[str, Any], *, use_demo_rag: bool = False) -> dict[str, Any]:
        from app.document_workflow.configuration import DocumentWorkflowConfig
        from app.document_workflow.rag import DemoRAGClient, HTTPRetrieveClient
        from app.document_workflow.workflow import DocumentWorkflow

        source = Path(template_record["path"])
        output = Path(template_record["output_dir"])
        self._validate_docx(source)
        if output.joinpath("draft.docx").exists():
            raise ValueError("此模板已经执行过；请重新加载模板后再运行")
        client = (DemoRAGClient() if use_demo_rag else HTTPRetrieveClient(
            self.config.rag_base_url, timeout=self.config.request_timeout_seconds, retry_limit=1
        ))
        workflow_config = DocumentWorkflowConfig(
            rag_base_url=None if use_demo_rag else self.config.rag_base_url,
            rag_timeout_seconds=self.config.request_timeout_seconds,
            rag_retry_limit=1,
            output_root=self.config.runtime_root / "outputs",
            checkpoint_root=output / "checkpoints",
            trace_root=output,
        ).validate()
        try:
            raw = DocumentWorkflow(client, config=workflow_config).run(source, output)
        except Exception as exc:
            raise ServiceError("Document Workflow 执行失败。", type(exc).__name__, "AGENT_FAILED") from exc
        return self._serialize_result(raw, output)

    @staticmethod
    def _serialize_result(raw: dict[str, Any], output: Path) -> dict[str, Any]:
        tasks = raw["tasks"]
        drafts = {draft.section_id: draft for draft in raw["drafts"]}
        trace_sections = {item["section_id"]: item for item in raw["trace"]["sections"]}
        evidence_records = raw["state"].evidence_snapshot.get("evidence", [])
        evidence_by_id = {item["evidence_id"]: item for item in evidence_records}
        sections = []
        for task in tasks:
            draft = drafts[task.section_id]
            item_trace = trace_sections.get(task.section_id, {})
            sections.append({
                "task_id": task.task_id, "section_id": task.section_id,
                "section_title": task.section_title, "status": task.status.value,
                "queries": list(task.queries), "query_count": len(task.queries),
                "rag_calls": int(item_trace.get("rag_calls", 0)),
                "evidence_ids": list(task.evidence_ids),
                "evidence": [evidence_by_id[eid] for eid in task.evidence_ids if eid in evidence_by_id],
                "missing_fields": list(task.missing_fields),
                "stop_reason": task.stop_reason,
                "draft_preview": draft.content,
            })
        workflow_id = raw["state"].workflow_id
        jsonl = output / "traces" / f"{workflow_id}.jsonl"
        timeline = []
        if jsonl.is_file():
            for line in jsonl.read_text(encoding="utf-8").splitlines():
                try:
                    event = json.loads(line)
                except json.JSONDecodeError:
                    continue
                timeline.append({key: event.get(key) for key in (
                    "timestamp", "event_type", "status", "stage", "step_id", "operation", "duration_ms"
                )})
        artifacts = {
            "draft": str(raw["draft_path"]),
            "evidence": str(output / "evidence.json"),
            "trace": str(output / "execution_trace.json"),
        }
        for label, path in artifacts.items():
            if not Path(path).is_file():
                raise ServiceError(f"Workflow 缺少 {label} 输出。", label, "OUTPUT_MISSING")
        return {
            "workflow_id": workflow_id, "workflow_status": raw["state"].workflow_status,
            "requires_human_review": raw["state"].requires_human_review,
            "template": {"template_id": raw["schema"].template_id,
                         "template_name": raw["schema"].template_name,
                         "section_count": len(raw["schema"].sections),
                         "sections": [asdict(item) for item in raw["schema"].sections]},
            "sections": sections, "timeline": timeline, "trace": raw["trace"],
            "total_rag_calls": raw["trace"]["total_rag_calls"],
            "unique_evidence_count": raw["trace"]["total_unique_evidence"],
            "missing_field_count": sum(len(item["missing_fields"]) for item in sections),
            "artifacts": artifacts,
        }

    @staticmethod
    def artifact_bytes(path: str | Path) -> bytes:
        artifact = Path(path)
        if not artifact.is_file():
            raise FileNotFoundError("下载文件不存在")
        return artifact.read_bytes()

