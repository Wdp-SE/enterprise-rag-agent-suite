"""Stable UI/CLI facade for the document workflow product."""

from __future__ import annotations

import hashlib
import json
import shutil
import uuid
import zipfile
from dataclasses import asdict, replace
from pathlib import Path

from .configuration import DocumentWorkflowConfig
from .evidence import EvidenceCache
from .integrity import OutputIntegrityValidator
from .models import SectionDraft, WorkflowStatus
from .planning import SectionTaskPlanner
from .policy import CapabilityId, require_capability
from .rag import DemoRAGClient, HTTPRetrieveClient, RetrievalClient
from .repository import WorkflowRepository
from .review import ReviewService, SectionReviewStatus
from .scope import WorkflowScope
from .state import CheckpointStore
from .template import TemplateParser, TemplateRenderer
from .workflow import DocumentWorkflow


class DocumentWorkflowFacade:
    def __init__(
        self,
        runtime_root: str | Path,
        *,
        config: DocumentWorkflowConfig | None = None,
        rag_client: RetrievalClient | None = None,
        rag_base_url: str | None = None,
        request_timeout_seconds: float | None = None,
        data_classification: str | None = None,
    ):
        self.runtime_root = Path(runtime_root).resolve()
        self.uploads_root = self.runtime_root / "uploads"
        self.outputs_root = self.runtime_root / "outputs"
        self.uploads_root.mkdir(parents=True, exist_ok=True)
        self.outputs_root.mkdir(parents=True, exist_ok=True)
        base_config = config or DocumentWorkflowConfig.from_env()
        overrides = {}
        if rag_base_url is not None:
            overrides["rag_base_url"] = rag_base_url
        if request_timeout_seconds is not None:
            overrides["rag_timeout_seconds"] = request_timeout_seconds
        if data_classification is not None:
            overrides["data_classification"] = data_classification
        self.config = replace(base_config, **overrides).validate()
        self.rag_client = rag_client
        self.repository = WorkflowRepository(self.runtime_root)

    @staticmethod
    def _validate_docx(path: Path) -> None:
        if path.suffix.lower() != ".docx" or not path.is_file() or not zipfile.is_zipfile(path):
            raise ValueError("仅支持有效的结构化 Word (.docx) 模板")

    def create_workflow(self, template: str | Path, scope: dict | WorkflowScope, *, display_name: str | None = None) -> dict:
        source = Path(template).resolve()
        self._validate_docx(source)
        workflow_scope = scope if isinstance(scope, WorkflowScope) else WorkflowScope.from_dict(scope)
        run_id = f"ui_{uuid.uuid4().hex}"
        upload_dir = self.uploads_root / run_id
        output_dir = self.outputs_root / run_id
        upload_dir.mkdir()
        output_dir.mkdir()
        target = upload_dir / "template.docx"
        shutil.copy2(source, target)
        return self._template_record(run_id, target, output_dir, workflow_scope, display_name or source.name)

    def create_workflow_from_bytes(self, filename: str, content: bytes, scope: dict | WorkflowScope) -> dict:
        if Path(filename).suffix.lower() != ".docx":
            raise ValueError("仅支持 .docx 文件")
        workflow_scope = scope if isinstance(scope, WorkflowScope) else WorkflowScope.from_dict(scope)
        run_id = f"ui_{uuid.uuid4().hex}"
        upload_dir = self.uploads_root / run_id
        output_dir = self.outputs_root / run_id
        upload_dir.mkdir()
        output_dir.mkdir()
        target = upload_dir / "template.docx"
        target.write_bytes(content)
        try:
            self._validate_docx(target)
            return self._template_record(run_id, target, output_dir, workflow_scope, Path(filename).name)
        except Exception:
            shutil.rmtree(upload_dir, ignore_errors=True)
            shutil.rmtree(output_dir, ignore_errors=True)
            raise

    def _template_record(self, run_id: str, path: Path, output: Path, scope: WorkflowScope, display_name: str) -> dict:
        schema = TemplateParser().parse(path)
        tasks = SectionTaskPlanner().plan(schema)
        return {
            "run_id": run_id, "path": str(path), "output_dir": str(output),
            "filename": display_name, "size": path.stat().st_size,
            "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            "scope": scope.to_dict(), "scope_fingerprint": scope.fingerprint(),
            "summary": {
                "template_id": schema.template_id, "template_name": schema.template_name,
                "section_count": len(schema.sections), "table_count": len(schema.tables),
                "field_count": len(schema.fields), "sections": [asdict(item) for item in schema.sections],
                "tasks": [
                    {"task_id": task.task_id, "section_id": task.section_id, "section_title": task.section_title,
                     "status": task.status.value, "required_fields": [asdict(field) for field in task.required_fields]}
                    for task in tasks
                ],
            },
        }

    def _client(self, use_demo_rag: bool = False) -> RetrievalClient:
        if use_demo_rag:
            return DemoRAGClient()
        if self.rag_client is not None:
            return self.rag_client
        if not self.config.rag_base_url:
            raise ValueError("RAG_BASE_URL is required")
        return HTTPRetrieveClient(self.config.rag_base_url, self.config.rag_timeout_seconds, self.config.rag_retry_limit)

    def run_workflow(self, record: dict, *, use_demo_rag: bool = False) -> dict:
        scope = WorkflowScope.from_dict(record["scope"])
        if scope.fingerprint() != record["scope_fingerprint"]:
            raise ValueError("workflow scope fingerprint invalid")
        source, output = Path(record["path"]).resolve(), Path(record["output_dir"]).resolve()
        if not source.is_relative_to(self.uploads_root) or not output.is_relative_to(self.outputs_root):
            raise ValueError("workflow paths outside runtime root")
        config = replace(self.config, output_root=self.outputs_root, checkpoint_root=output / "checkpoints", trace_root=output).validate()
        raw = DocumentWorkflow(self._client(use_demo_rag), config=config, scope=scope).run(source, output)
        return self._serialize(raw["state"], execution_trace=raw.get("trace"))

    def resume_workflow(self, workflow_id: str, *, use_demo_rag: bool = False) -> dict:
        state = self.repository.get(workflow_id)
        scope = WorkflowScope.from_dict(state.scope)
        config = replace(
            self.config, output_root=self.outputs_root,
            checkpoint_root=Path(state.output_path) / "checkpoints", trace_root=Path(state.output_path),
        ).validate()
        raw = DocumentWorkflow(self._client(use_demo_rag), config=config, scope=scope).resume(
            workflow_id, output=state.output_path, template=state.template_path,
        )
        return self._serialize(raw["state"], execution_trace=raw.get("trace"))

    def list_workflows(self) -> list[dict]:
        return self.repository.list_workflows()

    def get_workflow(self, workflow_id: str) -> dict:
        return self._serialize(self.repository.get(workflow_id))

    def review_section(
        self,
        workflow_id: str,
        *,
        section_id: str,
        action: str,
        reviewer: str,
        comment: str = "",
        edited_fields: dict[str, str] | None = None,
    ) -> dict:
        require_capability(CapabilityId.REVIEW_WRITE, write=True)
        state = self.repository.get(workflow_id)
        if state.workflow_status == WorkflowStatus.APPROVED.value:
            raise ValueError("approved workflow is immutable")
        status = SectionReviewStatus(action.upper())
        ReviewService().review_section(
            state, section_id=section_id, status=status, reviewer=reviewer,
            comment=comment, edited_fields=edited_fields,
        )
        self.repository.save(state)
        return self._serialize(state)

    def finalize_document(self, workflow_id: str) -> dict:
        require_capability(CapabilityId.FINALIZE, write=True)
        state = self.repository.get(workflow_id)
        source = Path(state.template_path)
        schema = TemplateParser().parse(source)
        tasks = SectionTaskPlanner().plan(schema)
        drafts = [SectionDraft.from_dict(state.section_drafts[task.section_id]) for task in tasks]
        cache = EvidenceCache(Path(state.output_path), Path(state.output_path) / "evidence.json")
        cache.restore(state.evidence_snapshot)
        OutputIntegrityValidator().validate_final(state=state, schema=schema, tasks=tasks, drafts=drafts, cache=cache)
        target = Path(state.output_path) / "approved.docx"
        if target.exists():
            raise FileExistsError("approved.docx already exists")
        TemplateRenderer().render(source, target, schema, drafts, cache.store.list())
        state.workflow_status = WorkflowStatus.APPROVED.value
        state.approved_path = str(target)
        self.repository.save(state)
        return self._serialize(state)

    def _serialize(self, state, *, execution_trace: dict | None = None) -> dict:
        if execution_trace is None:
            trace_path = Path(state.output_path) / "execution_trace.json"
            try:
                loaded_trace = json.loads(trace_path.read_text(encoding="utf-8"))
                execution_trace = loaded_trace if isinstance(loaded_trace, dict) else {}
            except (OSError, ValueError, TypeError):
                execution_trace = {}
        schema = TemplateParser().parse(state.template_path)
        fields = {item.field_id: item for item in schema.fields}
        evidence_records = state.evidence_snapshot.get("evidence", [])
        evidence_by_id = {item["evidence_id"]: item for item in evidence_records}
        sections = []
        for section in schema.sections:
            record = state.section_drafts.get(section.section_id)
            if record is None:
                task_state = state.section_states.get(section.section_id, {})
                sections.append({"section_id": section.section_id, "section_title": section.title, "status": task_state.get("status", "PENDING"), "fields": [], "queries": task_state.get("queries", []), "evidence_ids": [], "evidence": [], "review": state.section_reviews.get(section.section_id, {"status": "PENDING"})})
                continue
            draft = SectionDraft.from_dict(record)
            section_evidence_ids = draft.evidence_ids
            sections.append({
                "section_id": section.section_id, "section_title": section.title, "status": draft.status.value,
                "queries": state.section_states[section.section_id].get("queries", []),
                "fields": [
                    {**item.to_dict(), "field_name": fields[item.field_id].field_name}
                    for item in draft.fields
                ],
                "evidence_ids": section_evidence_ids,
                "evidence": [evidence_by_id[item] for item in section_evidence_ids if item in evidence_by_id],
                "review": state.section_reviews.get(section.section_id, {"status": "PENDING"}),
                "stop_reason": state.section_states[section.section_id].get("stop_reason"),
            })
        output = Path(state.output_path)
        artifacts = {
            "draft": state.draft_path,
            "evidence": str(output / "evidence.json") if (output / "evidence.json").is_file() else None,
            "trace": str(output / "execution_trace.json") if (output / "execution_trace.json").is_file() else None,
            "approved": state.approved_path,
        }
        return {
            "workflow_id": state.workflow_id, "workflow_status": state.workflow_status,
            "requires_human_review": True, "scope": state.scope,
            "scope_fingerprint": state.scope_fingerprint,
            "template": {"template_id": schema.template_id, "template_name": Path(state.template_path).name, "section_count": len(schema.sections), "sections": [asdict(item) for item in schema.sections]},
            "sections": sections, "total_rag_calls": state.rag_call_count,
            "unique_evidence_count": len(evidence_records),
            "missing_field_count": sum(item["status"] in {"MISSING", "INSUFFICIENT_EVIDENCE", "INVALID"} for section in sections for item in section["fields"]),
            "all_sections_approved": ReviewService.all_approved(state),
            "last_stop_reason": state.last_stop_reason,
            "refresh_summary": execution_trace.get("refresh_summary"), "artifacts": artifacts,
        }

    def artifact_bytes(self, path: str | Path) -> bytes:
        candidate = Path(path).resolve()
        if not candidate.is_relative_to(self.runtime_root) or not candidate.is_file():
            raise ValueError("artifact path outside runtime root")
        return candidate.read_bytes()
