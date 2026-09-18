"""Deterministic application runner for evidence-driven document drafting."""

from __future__ import annotations

import hashlib
import json
import os
import time
import uuid
from dataclasses import replace
from pathlib import Path
from urllib.parse import urlsplit

from app.reliability.budget import BudgetDimension, BudgetExceededError, BudgetLedger, ExecutionBudget
from app.reliability.progress import NoProgressDetector, ProgressSignal
from app.reliability.trace import TraceContext, TraceRecorder, TraceSpanKind

from .configuration import DocumentWorkflowConfig
from .drafting import DraftPolicy, FieldDraftingService
from .evidence import EvidenceCache
from .freshness import EvidenceFreshnessValidator
from .integrity import OutputIntegrityValidator
from .models import FieldDraftStatus, SectionDraft, TaskStatus, WorkflowStatus
from .planning import QueryPlanner, SectionTaskPlanner
from .policy import CapabilityId, require_capability
from .rag import HTTPRetrieveClient, RAGTool, RetrievalClient
from .scope import WorkflowScope
from .state import CheckpointInvalid, CheckpointStore, WorkflowState, now
from .sufficiency import EvidenceSufficiency, EvidenceSufficiencyService
from .template import TemplateParser, TemplateRenderer


class DocumentWorkflow:
    def __init__(
        self,
        rag_client: RetrievalClient,
        *,
        config: DocumentWorkflowConfig | None = None,
        scope: WorkflowScope | None = None,
        drafting_service: FieldDraftingService | None = None,
    ):
        config = (config or DocumentWorkflowConfig.from_env()).validate()
        if isinstance(rag_client, HTTPRetrieveClient):
            if config.rag_base_url is None:
                config = replace(config, rag_base_url=rag_client.base_url)
            elif config.rag_base_url.rstrip("/") != rag_client.base_url:
                raise ValueError("RAG client base URL differs from central configuration")
            rag_client.timeout = config.rag_timeout_seconds
            rag_client.retry_limit = config.rag_retry_limit
        self.config = config
        self.requested_scope = scope
        self.scope = scope or WorkflowScope()
        self.rag_tool = RAGTool(rag_client, config.rag_top_k, self.scope)
        self.drafting = drafting_service or FieldDraftingService(
            DraftPolicy(config.drafting_mode, config.data_classification)
        )
        self.sufficiency = EvidenceSufficiencyService()

    def run(self, template: str | Path, output: str | Path) -> dict:
        return self._execute(Path(template).resolve(), Path(output).resolve(), state=None)

    def resume(self, workflow_id: str, *, output: str | Path, template: str | Path | None = None) -> dict:
        output_path = Path(output).resolve()
        state = CheckpointStore(self.config.checkpoint_root or output_path / "checkpoints").load(workflow_id)
        saved_scope = WorkflowScope.from_dict(state.scope)
        if self.requested_scope is not None and self.requested_scope.fingerprint() != saved_scope.fingerprint():
            raise CheckpointInvalid("workflow scope changed during resume")
        if saved_scope.fingerprint() != state.scope_fingerprint:
            raise CheckpointInvalid("checkpoint scope fingerprint invalid")
        self.scope = saved_scope
        self.rag_tool.retrieval_scope = saved_scope
        source = Path(template or state.template_path).resolve()
        if source != Path(state.template_path).resolve() or output_path != Path(state.output_path).resolve():
            raise CheckpointInvalid("resume template or output path mismatch")
        return self._execute(source, output_path, state=state)

    def _execute(self, source: Path, target_dir: Path, *, state: WorkflowState | None) -> dict:
        started = time.monotonic()
        if self.config.output_root and not target_dir.is_relative_to(self.config.output_root.resolve()):
            raise ValueError("output path outside configured OUTPUT_ROOT")
        target_dir.mkdir(parents=True, exist_ok=True)
        original_hash = hashlib.sha256(source.read_bytes()).hexdigest()
        require_capability(CapabilityId.TEMPLATE_READ)
        schema = TemplateParser().parse(source)
        tasks = SectionTaskPlanner().plan(schema)
        sections = {item.section_id: item for item in schema.sections}
        cache = EvidenceCache(target_dir, target_dir / "evidence.json")
        checkpoint = CheckpointStore(self.config.checkpoint_root or target_dir / "checkpoints")
        freshness_events: list[dict] = []
        if state is None:
            if (target_dir / "draft.docx").exists():
                raise FileExistsError("draft.docx already exists; choose a new output directory")
            run_id = f"dw_{uuid.uuid4().hex}"
            state = WorkflowState(
                run_id, schema.template_id, original_hash, str(source), str(target_dir),
                self.config.fingerprint(), self.scope.to_dict(), self.scope.fingerprint(),
            )
            state.section_states = {task.section_id: self._task_state(task) for task in tasks}
            state.evidence_snapshot = cache.snapshot()
            checkpoint.save(state)
        else:
            run_id = state.workflow_id
            if state.template_hash != original_hash or state.template_id != schema.template_id or state.config_fingerprint != self.config.fingerprint():
                raise CheckpointInvalid("template hash or workflow configuration mismatch")
            if set(state.section_states) != {task.section_id for task in tasks}:
                raise CheckpointInvalid("checkpoint section list mismatch")
            cache.restore(state.evidence_snapshot)
            for task in tasks:
                self._restore_task(task, state.section_states[task.section_id])
            active_versions = self.rag_tool.client.active_versions()
            decisions, affected = cache.apply_freshness(
                EvidenceFreshnessValidator(active_versions.get),
                historical_version_ids=set(self.scope.version_ids),
            )
            freshness_events = [
                {
                    "evidence_id": item.evidence_id, "document_id": item.document_id,
                    "version_id": item.version_id, "active_version_id": item.active_version_id,
                    "freshness": item.freshness.value,
                }
                for item in decisions
            ]
            for task in tasks:
                if task.task_id in affected:
                    task.status = TaskStatus.PENDING
                    task.evidence_ids = []
                    task.missing_fields = []
                    task.stop_reason = "STALE_EVIDENCE_REFRESH"
                    state.section_drafts.pop(task.section_id, None)
                    state.section_reviews.pop(task.section_id, None)
                    state.section_states[task.section_id] = self._task_state(task)
                    cache.invalidate_task(task.task_id)
                    state.approved_path = None
        trace_root = self.config.trace_root or target_dir
        trace_context = TraceContext(run_id, "document_workflow", TraceRecorder(trace_root))
        ledger = BudgetLedger(ExecutionBudget(
            max_steps=max(1, self.config.max_workflow_steps - state.step_count),
            max_tool_calls=max(1, self.config.execution_budget - state.rag_call_count),
            max_duration_ms=self.config.workflow_timeout_seconds * 1000,
            max_total_tokens=0, max_llm_calls=0,
        ))
        drafts = {
            section_id: SectionDraft.from_dict(record)
            for section_id, record in state.section_drafts.items()
        }
        trace_sections: list[dict] = []
        errors: list[dict] = []
        query_planner = QueryPlanner()
        state.workflow_status = WorkflowStatus.RUNNING.value
        checkpoint.save(state)
        for task in tasks:
            if task.status is TaskStatus.COMPLETE and task.section_id in drafts:
                continue
            task.status = TaskStatus.RUNNING
            task.started_at = now()
            task.attempt_count += 1
            task.queries = []
            task.evidence_ids = []
            task.missing_fields = []
            task.error_code = None
            task.error_summary = None
            state.current_section_id = task.section_id
            state.section_states[task.section_id] = self._task_state(task)
            checkpoint.save(state)
            detector = NoProgressDetector(threshold=self.config.no_progress_threshold)
            field_drafts = []
            section_calls = 0
            for field in task.required_fields:
                existing = cache.for_field(task.task_id, field.field_id)
                decision = self.sufficiency.evaluate(field, existing)
                planned = query_planner.plan(sections[task.section_id], field, self.scope, existing)
                for planned_query in planned:
                    if decision.status is EvidenceSufficiency.SUFFICIENT:
                        break
                    if section_calls >= self.config.max_section_steps:
                        task.stop_reason = "MAX_SECTION_STEPS"
                        break
                    key = (task.task_id, field.field_id, planned_query.text)
                    if key in cache.query_attempted:
                        continue
                    try:
                        target_domain = urlsplit(self.rag_tool.client.base_url).hostname if isinstance(self.rag_tool.client, HTTPRetrieveClient) else None
                        require_capability(CapabilityId.RAG_QUERY, network=True, target_domain=target_domain)
                        reservation = ledger.reserve(
                            {BudgetDimension.STEPS: 1, BudgetDimension.TOOL_CALLS: 1},
                            operation="rag_retrieve", attempt=1,
                        )
                    except BudgetExceededError as exc:
                        task.stop_reason = exc.error.code.value
                        break
                    cache.query_attempted.add(key)
                    task.queries.append(planned_query.text)
                    section_calls += 1
                    state.step_count += 1
                    state.rag_call_count += 1
                    span = trace_context.start_span(
                        TraceSpanKind.OPERATION, stage="COLLECT_EVIDENCE", step_id=task.task_id,
                        tool_name="rag_retrieve", operation=planned_query.kind,
                        input_summary={"query_hash": hashlib.sha256(planned_query.text.encode()).hexdigest(), "scope_fingerprint": self.scope.fingerprint()},
                    )
                    try:
                        hits = self.rag_tool.retrieve_knowledge(planned_query.text)
                        before = len(cache.by_task[task.task_id])
                        for hit in hits:
                            cache.add(task.task_id, field.field_id, planned_query.text, hit)
                        growth = len(cache.by_task[task.task_id]) - before
                        span.succeed(output_summary={"hit_count": len(hits), "new_evidence_count": growth})
                        cache_snapshot = cache.snapshot()
                        state.evidence_snapshot = cache_snapshot
                        checkpoint.save(state)
                        no_progress = detector.observe(ProgressSignal(
                            sequence=section_calls, event_type="EVIDENCE_GROWTH", stage="COLLECT_EVIDENCE",
                            operation="rag_retrieve", evidence_count=len(cache.by_task[task.task_id]),
                            completed_unit_count=len(field_drafts), successful=True,
                        ))
                        if no_progress.no_progress:
                            task.stop_reason = "NO_EVIDENCE_GROWTH"
                    except Exception as exc:
                        errors.append({"task_id": task.task_id, "field_id": field.field_id, "error_type": type(exc).__name__})
                        span.__exit__(type(exc), exc, None)
                        task.error_code = type(exc).__name__
                        task.error_summary = "RAG retrieval failed"
                        cache.query_attempted.discard(key)
                        task.stop_reason = "RAG_ERROR"
                    finally:
                        ledger.commit(reservation)
                    decision = self.sufficiency.evaluate(field, cache.for_field(task.task_id, field.field_id))
                    if task.stop_reason in {"RAG_ERROR", "MAX_SECTION_STEPS"}:
                        break
                evidence = cache.for_field(task.task_id, field.field_id)
                decision = self.sufficiency.evaluate(field, evidence)
                field_drafts.append(self.drafting.draft(field, sections[task.section_id], evidence, decision))
            missing_ids = [
                item.field_id for item in field_drafts
                if item.status in {FieldDraftStatus.MISSING, FieldDraftStatus.INSUFFICIENT_EVIDENCE, FieldDraftStatus.INVALID}
            ]
            field_names = {item.field_id: item.field_name for item in task.required_fields}
            task.missing_fields = [field_names[item] for item in missing_ids]
            task.evidence_ids = sorted({evidence_id for item in field_drafts for evidence_id in item.evidence_ids})
            task.status = TaskStatus.PARTIAL if missing_ids else TaskStatus.COMPLETE
            task.stop_reason = task.stop_reason or ("INSUFFICIENT_EVIDENCE" if missing_ids else None)
            task.completed_at = now()
            draft = SectionDraft(task.section_id, task.section_title, field_drafts, task.status)
            drafts[task.section_id] = draft
            state.section_states[task.section_id] = self._task_state(task)
            state.section_drafts[task.section_id] = draft.to_dict()
            state.section_reviews.setdefault(task.section_id, {
                "section_id": task.section_id, "status": "PENDING", "reviewer": "",
                "reviewed_at": None, "comment": "", "draft_hash": None,
                "approved_content_hash": None, "edited_fields": {},
            })
            state.evidence_snapshot = cache.snapshot()
            state.current_section_id = None
            state.last_stop_reason = task.stop_reason
            checkpoint.save(state)
            trace_sections.append({
                "task_id": task.task_id, "section_id": task.section_id, "queries": list(task.queries),
                "rag_calls": section_calls, "evidence_ids": list(task.evidence_ids),
                "status": task.status.value, "stop_reason": task.stop_reason,
                "missing_fields": list(task.missing_fields),
            })
        ordered_drafts = [drafts[task.section_id] for task in tasks]
        state.workflow_status = WorkflowStatus.REVIEW_REQUIRED.value
        OutputIntegrityValidator().validate_draft(
            source=source, original_hash=original_hash, schema=schema,
            tasks=tasks, drafts=ordered_drafts, cache=cache,
        )
        draft_path = target_dir / ("draft.docx" if not (target_dir / "draft.docx").exists() else f"draft-resume-{uuid.uuid4().hex[:8]}.docx")
        temporary = target_dir / f".draft-{run_id}.tmp.docx"
        require_capability(CapabilityId.DRAFT_WRITE, write=True)
        try:
            TemplateRenderer().render(source, temporary, schema, ordered_drafts, cache.store.list())
            if hashlib.sha256(source.read_bytes()).hexdigest() != original_hash or draft_path.exists():
                raise RuntimeError("template changed or draft output already exists")
            os.replace(temporary, draft_path)
        finally:
            temporary.unlink(missing_ok=True)
        cache.save()
        state.draft_path = str(draft_path)
        state.evidence_snapshot = cache.snapshot()
        checkpoint.save(state)
        trace = {
            "workflow_id": run_id, "workflow_status": state.workflow_status,
            "scope": self.scope.to_dict(), "scope_fingerprint": self.scope.fingerprint(),
            "drafting_mode": self.config.drafting_mode.value,
            "sections": trace_sections, "freshness_events": freshness_events,
            "total_rag_calls": state.rag_call_count, "total_unique_evidence": len(cache.store),
            "errors": errors, "duration_ms": round((time.monotonic() - started) * 1000, 3),
            "requires_human_review": True,
        }
        (target_dir / "execution_trace.json").write_text(json.dumps(trace, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        return {"schema": schema, "tasks": tasks, "drafts": ordered_drafts, "trace": trace, "draft_path": draft_path, "state": state}

    @staticmethod
    def _task_state(task) -> dict:
        return {
            "status": task.status.value, "queries": list(task.queries),
            "evidence_ids": list(task.evidence_ids), "missing_fields": list(task.missing_fields),
            "started_at": task.started_at, "completed_at": task.completed_at,
            "attempt_count": task.attempt_count, "stop_reason": task.stop_reason,
            "error_code": task.error_code, "error_summary": task.error_summary,
        }

    @staticmethod
    def _restore_task(task, record: dict) -> None:
        task.status = TaskStatus(record["status"])
        for name in ("queries", "evidence_ids", "missing_fields"):
            setattr(task, name, list(record.get(name, [])))
        for name in ("started_at", "completed_at", "stop_reason", "error_code", "error_summary"):
            setattr(task, name, record.get(name))
        task.attempt_count = int(record.get("attempt_count", 0))
