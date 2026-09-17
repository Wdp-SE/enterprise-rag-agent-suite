"""Fixed high-level document workflow with bounded RAG collection."""

from __future__ import annotations

import hashlib
import json
import os
import re
import time
import uuid
from dataclasses import replace
from pathlib import Path
from urllib.parse import urlsplit

from app.reliability.budget import BudgetDimension, BudgetExceededError, BudgetLedger, ExecutionBudget
from app.reliability.policy import CapabilityId
from app.reliability.progress import NoProgressDetector, ProgressSignal
from app.reliability.trace import TraceContext, TraceRecorder, TraceSpanKind

from .evidence import EvidenceCache
from .models import SectionDraft, TaskStatus, WorkflowStatus
from .configuration import DocumentWorkflowConfig
from .integrity import OutputIntegrityValidator
from .planning import QueryPlanner, SectionTaskPlanner
from .policy import require_capability
from .rag import HTTPRAGClient, HTTPRetrieveClient, RAGTool
from .template import TemplateParser, TemplateRenderer
from .state import CheckpointInvalid, CheckpointStore, WorkflowState, now


MISSING = "[MISSING: 当前知识库中未发现明确资料]"


class DocumentWorkflow:
    def __init__(self, rag_client, *, config: DocumentWorkflowConfig | None = None,
                 max_steps: int | None = None, max_tool_calls: int | None = None,
                 timeout_seconds: int | None = None, no_progress_threshold: int | None = None):
        config = config or DocumentWorkflowConfig.from_env()
        if isinstance(rag_client, HTTPRetrieveClient):
            if config.rag_base_url is None:
                config = replace(config, rag_base_url=rag_client.base_url)
            elif config.rag_base_url.rstrip("/") != rag_client.base_url:
                raise ValueError("RAG client base URL differs from central configuration")
            rag_client.timeout = config.rag_timeout_seconds
            rag_client.retry_limit = config.rag_retry_limit
        overrides = {}
        if max_steps is not None:
            overrides["max_workflow_steps"] = max_steps
        if max_tool_calls is not None:
            overrides["execution_budget"] = max_tool_calls
        if timeout_seconds is not None:
            overrides["workflow_timeout_seconds"] = timeout_seconds
        if no_progress_threshold is not None:
            overrides["no_progress_threshold"] = no_progress_threshold
        self.config = replace(config, **overrides).validate()
        self.rag_tool = RAGTool(rag_client, default_top_k=self.config.rag_top_k)
        self.max_steps = self.config.max_workflow_steps
        self.max_tool_calls = self.config.execution_budget
        self.timeout_seconds = self.config.workflow_timeout_seconds
        self.no_progress_threshold = self.config.no_progress_threshold

    def run(self, template: str | Path, output: str | Path) -> dict:
        return self._execute(template, output)

    def resume(self, workflow_id: str, *, output: str | Path,
               template: str | Path | None = None) -> dict:
        root = self.config.checkpoint_root or Path(output).resolve() / "checkpoints"
        state = CheckpointStore(root).load(workflow_id)
        if state.workflow_status == WorkflowStatus.COMPLETE.value:
            raise CheckpointInvalid("completed workflow cannot be finalized again")
        source = Path(template or state.template_path).resolve()
        if source != Path(state.template_path).resolve() or Path(output).resolve() != Path(state.output_path).resolve():
            raise CheckpointInvalid("resume template or output path mismatch")
        return self._execute(source, output, state=state)

    def _execute(self, template: str | Path, output: str | Path,
                 *, state: WorkflowState | None = None) -> dict:
        started = time.monotonic()
        source, target_dir = Path(template).resolve(), Path(output).resolve()
        if self.config.output_root and not target_dir.is_relative_to(self.config.output_root.resolve()):
            raise ValueError("output path outside configured OUTPUT_ROOT")
        target_dir.mkdir(parents=True, exist_ok=True)
        original_hash = hashlib.sha256(source.read_bytes()).hexdigest()
        require_capability(CapabilityId.TEMPLATE_READ)
        schema = TemplateParser().parse(source)
        tasks = SectionTaskPlanner().plan(schema)
        cache = EvidenceCache(target_dir, target_dir / "evidence_store.json")
        checkpoint = CheckpointStore(self.config.checkpoint_root or target_dir / "checkpoints")
        if state is None:
            if (target_dir / "draft.docx").exists():
                raise FileExistsError("draft.docx already exists; choose a new output directory")
            run_id = f"dw_{uuid.uuid4().hex}"
            state = WorkflowState(run_id, schema.template_id, original_hash,
                                  str(source), str(target_dir), self.config.fingerprint())
            state.section_states = {task.section_id: self._task_state(task) for task in tasks}
            state.evidence_snapshot = cache.snapshot()
            checkpoint.save(state)
        else:
            if (state.template_hash != original_hash or state.template_id != schema.template_id
                    or state.config_fingerprint != self.config.fingerprint()):
                raise CheckpointInvalid("template hash or workflow configuration mismatch")
            if set(state.section_states) != {task.section_id for task in tasks}:
                raise CheckpointInvalid("checkpoint section list mismatch")
            try:
                cache.restore(state.evidence_snapshot)
                for task in tasks:
                    record = state.section_states[task.section_id]
                    task.status = TaskStatus(record["status"])
                    task.queries = list(record.get("queries", []))
                    task.evidence_ids = list(record.get("evidence_ids", []))
                    task.missing_fields = list(record.get("missing_fields", []))
                    task.started_at = record.get("started_at")
                    task.completed_at = record.get("completed_at")
                    task.attempt_count = int(record.get("attempt_count", 0))
                    task.stop_reason = record.get("stop_reason")
                    task.error_code = record.get("error_code")
                    task.error_summary = record.get("error_summary")
                    if task.status == TaskStatus.COMPLETE:
                        draft_record = state.section_drafts[task.section_id]
                        draft = self._draft_from_record(draft_record)
                        cited = set(re.findall(r"\[Evidence: ([^\]]+)\]", draft.content))
                        if (draft.status != TaskStatus.COMPLETE
                                or draft.requires_human_review is not True
                                or set(draft.field_values) != {field.field_id for field in task.required_fields}
                                or cited != set(draft.evidence_ids)
                                or not cache.membership(task.task_id, draft.evidence_ids)):
                            raise CheckpointInvalid("completed draft evidence invalid")
                    else:
                        cache.query_attempted = {pair for pair in cache.query_attempted if pair[0] != task.task_id}
            except (KeyError, TypeError, ValueError) as exc:
                raise CheckpointInvalid("checkpoint task or evidence reference invalid") from exc
            run_id = state.workflow_id
        trace_root = self.config.trace_root or target_dir
        trace_context = TraceContext(run_id, "document_workflow", TraceRecorder(trace_root))
        if state.step_count >= self.max_steps or state.rag_call_count >= self.max_tool_calls:
            raise CheckpointInvalid("workflow execution budget exhausted")
        ledger = BudgetLedger(ExecutionBudget(
            max_steps=self.max_steps - state.step_count,
            max_tool_calls=self.max_tool_calls - state.rag_call_count,
            max_duration_ms=self.timeout_seconds * 1000,
            max_total_tokens=self.config.token_budget, max_llm_calls=0,
        ))
        drafts: list[SectionDraft] = [self._draft_from_record(state.section_drafts[task.section_id])
                                      for task in tasks if task.status == TaskStatus.COMPLETE]
        sections_trace: list[dict] = [self._trace_from_task(task) for task in tasks
                                      if task.status == TaskStatus.COMPLETE]
        errors: list[dict] = []
        query_planner = QueryPlanner()
        state.workflow_status = WorkflowStatus.RUNNING.value
        checkpoint.save(state)
        for task in tasks:
            if task.status == TaskStatus.COMPLETE:
                continue
            task.status = TaskStatus.RUNNING
            task.started_at = now()
            task.attempt_count += 1
            task.queries = []
            task.missing_fields = []
            task.evidence_ids = []
            task.error_code = None
            task.error_summary = None
            state.current_section_id = task.section_id
            state.section_states[task.section_id] = self._task_state(task)
            state.evidence_snapshot = cache.snapshot()
            checkpoint.save(state)
            detector = NoProgressDetector(threshold=self.no_progress_threshold)
            rag_calls = 0
            new_count = 0
            reused_count = 0
            retrieval_result_count = 0
            stop_reason = None
            no_progress = False
            for field in task.required_fields:
                if cache.covers(task.task_id, field.field_name):
                    continue
                for round_number in range(4):
                    if rag_calls >= self.config.max_section_steps:
                        stop_reason = "MAX_SECTION_STEPS"
                        break
                    if cache.covers(task.task_id, field.field_name):
                        break
                    query = query_planner.query(field.field_name, round_number)
                    if (task.task_id, query) in cache.query_attempted:
                        continue
                    try:
                        require_capability(
                            CapabilityId.RAG_QUERY, network=isinstance(self.rag_tool.client, (HTTPRAGClient, HTTPRetrieveClient)),
                            target_domain=urlsplit(self.rag_tool.client.base_url).hostname
                            if isinstance(self.rag_tool.client, (HTTPRAGClient, HTTPRetrieveClient)) else None,
                        )
                        reservation = ledger.reserve(
                            {BudgetDimension.STEPS: 1, BudgetDimension.TOOL_CALLS: 1},
                            operation="rag_query", attempt=1,
                        )
                    except BudgetExceededError as exc:
                        stop_reason = exc.error.code.value
                        break
                    task.queries.append(query)
                    cache.query_attempted.add((task.task_id, query))
                    rag_calls += 1
                    state.step_count += 1
                    state.rag_call_count += 1
                    state.section_states[task.section_id] = self._task_state(task)
                    state.evidence_snapshot = cache.snapshot()
                    checkpoint.save(state)
                    span = trace_context.start_span(
                        TraceSpanKind.OPERATION, stage="COLLECT_EVIDENCE",
                        step_id=task.task_id, tool_name="rag_query", operation="retrieve_knowledge",
                        input_summary={"query_hash": hashlib.sha256(query.encode()).hexdigest()},
                    )
                    try:
                        hits = self.rag_tool.retrieve_knowledge(query)
                        retrieval_result_count += len(hits)
                        call_new_count = 0
                        for hit in hits:
                            added = cache.add(task.task_id, query, hit)
                            call_new_count += int(added)
                            reused_count += int(not added)
                        new_count += call_new_count
                        span.succeed(output_summary={
                            "hit_count": len(hits), "new_evidence_count": call_new_count,
                            "evidence_ids": [hit.evidence_id for hit in hits],
                        })
                        state.evidence_snapshot = cache.snapshot()
                        checkpoint.save(state)
                    except Exception as exc:
                        errors.append({"task_id": task.task_id, "error_type": type(exc).__name__})
                        span.__exit__(type(exc), exc, None)
                        stop_reason = "RAG_ERROR"
                        task.error_code = type(exc).__name__
                        task.error_summary = "RAG retrieval failed"
                        cache.query_attempted.discard((task.task_id, query))
                        ledger.commit(reservation)
                        break
                    ledger.commit(reservation)
                    decision = detector.observe(ProgressSignal(
                        sequence=rag_calls, event_type="EVIDENCE_GROWTH",
                        stage="COLLECT_EVIDENCE", operation="rag_query",
                        evidence_count=len(cache.by_task[task.task_id]),
                        completed_unit_count=sum(
                            cache.covers(task.task_id, item.field_name)
                            for item in task.required_fields
                        ), successful=True,
                    ))
                    if decision.no_progress:
                        no_progress = True
                        stop_reason = "NO_EVIDENCE_GROWTH"
                        break
                if stop_reason:
                    break
            field_values: dict[str, str] = {}
            used_ids: set[str] = set()
            for field in task.required_fields:
                matching = [item for item in cache.for_task(task.task_id)
                            if field.field_name in item.content]
                if matching:
                    item = matching[0]
                    assert item.evidence_id is not None
                    field_values[field.field_id] = f"{item.content} [Evidence: {item.evidence_id}]"
                    used_ids.add(item.evidence_id)
                else:
                    field_values[field.field_id] = MISSING
                    task.missing_fields.append(field.field_name)
            task.evidence_ids = sorted(used_ids)
            if not cache.membership(task.task_id, task.evidence_ids):
                raise ValueError("draft cites evidence outside the current task cache")
            task.status = (
                TaskStatus.NO_PROGRESS if task.missing_fields and no_progress else
                TaskStatus.PARTIAL if task.missing_fields else TaskStatus.COMPLETE
            )
            task.stop_reason = stop_reason or ("INSUFFICIENT_EVIDENCE" if task.missing_fields else None)
            task.completed_at = now()
            drafts.append(SectionDraft(
                task.section_id, task.section_title, field_values, task.evidence_ids,
                task.missing_fields, task.status,
            ))
            sections_trace.append({
                "task_id": task.task_id, "section_id": task.section_id,
                "queries": [{"query_hash": hashlib.sha256(q.encode()).hexdigest()}
                            for q in task.queries],
                "query_hashes": [hashlib.sha256(q.encode()).hexdigest() for q in task.queries],
                "rag_calls": rag_calls, "evidence_count": len(cache.by_task[task.task_id]),
                "retrieval_result_count": retrieval_result_count,
                "new_evidence_count": new_count, "reused_evidence_count": reused_count,
                "evidence_ids": sorted(cache.by_task[task.task_id]),
                "status": task.status.value, "stop_reason": stop_reason,
                "missing_fields": self._trace_field_names(task.missing_fields),
            })
            state.section_states[task.section_id] = self._task_state(task)
            state.section_drafts[task.section_id] = self._draft_record(drafts[-1])
            state.evidence_snapshot = cache.snapshot()
            state.current_section_id = None
            checkpoint.save(state)
        state.workflow_status = (WorkflowStatus.COMPLETE.value if all(task.status == TaskStatus.COMPLETE for task in tasks)
                                 else WorkflowStatus.PARTIAL.value)
        draft_path = target_dir / ("draft.docx" if not (target_dir / "draft.docx").exists()
                                   else f"draft-resume-{uuid.uuid4().hex[:8]}.docx")
        try:
            OutputIntegrityValidator().validate(
                source=source, target=draft_path, original_hash=original_hash,
                schema=schema, tasks=tasks, drafts=drafts, cache=cache,
                workflow_status=state.workflow_status,
            )
            require_capability(CapabilityId.DRAFT_WRITE, write=True)
            temporary_draft = target_dir / f".draft-{run_id}.tmp.docx"
            try:
                TemplateRenderer().render(source, temporary_draft, schema, drafts)
                if hashlib.sha256(source.read_bytes()).hexdigest() != original_hash:
                    raise RuntimeError("original template changed during workflow")
                if draft_path.exists():
                    raise FileExistsError("draft output already exists")
                os.replace(temporary_draft, draft_path)
            finally:
                temporary_draft.unlink(missing_ok=True)
        except Exception:
            state.workflow_status = WorkflowStatus.FAILED.value
            checkpoint.save(state)
            raise
        cache.save()
        evidence_payload = {
            "workflow_id": run_id, "template_id": schema.template_id,
            "requires_human_review": True,
            "evidence": [
                {"evidence_id": item.evidence_id, "document_id": item.document_number,
                 "chunk_id": item.chunk_id, "page_number": item.page_number,
                 "section_id": item.section, "section_path": item.section_path,
                 "query_hash": hashlib.sha256((item.query or "").encode()).hexdigest(),
                 **({"content": item.content} if self.config.persist_full_evidence_text else {}),
                 "content_hash": item.content_hash,
                 "source_type": item.source_type,
                 "task_ids": sorted(task_id for task_id, ids in cache.by_task.items()
                                    if item.evidence_id in ids),
                 "query_hashes": sorted({hashlib.sha256(query.encode()).hexdigest()
                                        for (_, query), ids in cache.by_query.items()
                                        if item.evidence_id in ids})}
                for item in cache.store.list()
            ],
        }
        evidence_file = target_dir / ("evidence.json" if not (target_dir / "evidence.json").exists()
                                      else f"evidence-resume-{uuid.uuid4().hex[:8]}.json")
        evidence_file.write_text(
            json.dumps(evidence_payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        trace = {
            "workflow_id": run_id, "template_id": schema.template_id,
            "requires_human_review": True, "sections": sections_trace,
            "rag_adapter": type(self.rag_tool.client).__name__,
            "retrieval_endpoint": "/retrieve" if isinstance(self.rag_tool.client, HTTPRetrieveClient) else None,
            "total_steps": ledger.snapshot().committed[BudgetDimension.STEPS],
            "total_rag_calls": self.rag_tool.calls,
            "total_unique_evidence": len(cache.store), "token_usage": None,
            "duration_seconds": round(time.monotonic() - started, 3), "errors": errors,
            "original_template_hash": original_hash,
            "workflow_status": state.workflow_status,
            "checkpoint_schema_version": "document-workflow-checkpoint-v1",
        }
        trace_file = target_dir / ("execution_trace.json" if not (target_dir / "execution_trace.json").exists()
                                   else f"execution_trace_resume_{uuid.uuid4().hex[:8]}.json")
        trace_file.write_text(
            json.dumps(trace, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        checkpoint.save(state)
        return {"schema": schema, "tasks": tasks, "drafts": drafts,
                "trace": trace, "draft_path": draft_path, "evidence": evidence_payload,
                "state": state}

    @staticmethod
    def _task_state(task) -> dict:
        return {
            "task_id": task.task_id, "section_id": task.section_id, "status": task.status.value,
            "started_at": task.started_at, "completed_at": task.completed_at,
            "attempt_count": task.attempt_count, "queries": list(task.queries),
            "evidence_ids": list(task.evidence_ids), "missing_fields": list(task.missing_fields),
            "stop_reason": task.stop_reason, "error_code": task.error_code,
            "error_summary": task.error_summary,
        }

    @staticmethod
    def _draft_record(draft: SectionDraft) -> dict:
        return {"section_id": draft.section_id, "title": draft.title,
                "field_values": dict(draft.field_values), "evidence_ids": list(draft.evidence_ids),
                "missing_fields": list(draft.missing_fields), "status": draft.status.value,
                "requires_human_review": draft.requires_human_review}

    @staticmethod
    def _draft_from_record(record: dict) -> SectionDraft:
        return SectionDraft(record["section_id"], record["title"], record["field_values"],
                            record["evidence_ids"], record["missing_fields"],
                            TaskStatus(record["status"]), record["requires_human_review"])

    @staticmethod
    def _trace_from_task(task) -> dict:
        return {"task_id": task.task_id, "section_id": task.section_id,
                "query_hashes": [hashlib.sha256(q.encode()).hexdigest() for q in task.queries],
                "rag_calls": 0, "evidence_count": len(task.evidence_ids),
                "evidence_ids": list(task.evidence_ids), "status": task.status.value,
                "stop_reason": task.stop_reason,
                "missing_fields": DocumentWorkflow._trace_field_names(task.missing_fields),
                "resumed_from_checkpoint": True}

    @staticmethod
    def _trace_field_names(names: list[str]) -> list[str]:
        sensitive = re.compile(r"(?i)(?:api[_-]?key|token|secret|password|authorization)")
        return [f"field_sha256:{hashlib.sha256(name.encode()).hexdigest()}" if sensitive.search(name)
                else name for name in names]
