"""Explicit staged orchestration for one bounded knowledge-research run."""

from __future__ import annotations

import hashlib
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from time import monotonic
from typing import Callable
from urllib.parse import urlsplit

from app.reliability.budget import BudgetDimension
from app.reliability.errors import (
    ErrorCategory,
    ErrorClassifier,
    ErrorCode,
    ExecutionError,
    ExecutionErrorRaised,
)
from app.reliability.executor import OperationSpec, ReliableOperationExecutor
from app.reliability.progress import (
    NoProgressDecision,
    NoProgressDetector,
    ProgressSignal,
    safe_identity_hash,
)
from app.reliability.policy import (
    CapabilityId,
    PolicyContext,
    PolicyDecision,
    PolicyEvaluationPoint,
    PolicyRetryState,
)
from app.reliability.result import ExecutionStatus
from app.reliability.retry import RetryOwner, SideEffectLevel
from app.reliability.trace import (
    Clock,
    NoopTraceRecorder,
    SystemClock,
    TraceContext,
    TraceRecorderProtocol,
    TraceStatus,
)
from app.reliability.workflow_control import ReliableWorkflowController
from app.research.evidence_extraction import EvidenceExtractionError
from app.research.evidence_store import EvidenceStore
from app.research.live_models import (
    OutputArtifact,
    ResearchErrorCode,
    ResearchFailure,
    ResearchPhase,
    ResearchRunMetrics,
    ResearchRunOutcome,
    ResearchStatus,
)
from app.research.models import ResearchProfile
from app.research.output_adapters import OutputAdapterError
from app.research.reliability import (
    ResearchTraceSession,
    research_failure_to_execution_error,
)
from app.research.research_result import ResearchResultBuilder
from app.research.run_store import ResearchRunStore, create_run_id
from app.research.search_adapter import SearchAdapterError
from app.research.source_acquisition import SourceAcquisitionError


class KnowledgeResearchWorkflow:
    """Run DISCOVER→SELECT→ACQUIRE→EXTRACT→BUILD_RESULT→OUTPUT."""

    def __init__(
        self,
        *,
        workspace_root: str | Path,
        search_provider,
        source_selector,
        source_acquirer,
        evidence_extractor,
        synthesizer,
        output_adapters: list,
        result_builder: ResearchResultBuilder | None = None,
        max_search_candidates: int = 8,
        max_selected_sources: int = 3,
        clock: Callable[[], datetime] | None = None,
        duration_clock: Callable[[], float] | None = None,
        trace_recorder: TraceRecorderProtocol | None = None,
        trace_clock: Clock | None = None,
        error_classifier: ErrorClassifier | None = None,
        operation_executor: ReliableOperationExecutor | None = None,
        progress_detector: NoProgressDetector | None = None,
        workflow_controller: ReliableWorkflowController | None = None,
    ):
        if not 1 <= max_search_candidates <= 8:
            raise ValueError("max_search_candidates must be between 1 and 8")
        if not 1 <= max_selected_sources <= 3:
            raise ValueError("max_selected_sources must be between 1 and 3")
        self.workspace_root = Path(workspace_root).resolve()
        self.search_provider = search_provider
        self.source_selector = source_selector
        self.source_acquirer = source_acquirer
        self.evidence_extractor = evidence_extractor
        self.synthesizer = synthesizer
        self.output_adapters = output_adapters
        self.result_builder = result_builder or ResearchResultBuilder()
        self.max_search_candidates = max_search_candidates
        self.max_selected_sources = max_selected_sources
        self.clock = clock or (lambda: datetime.now(timezone.utc))
        self.duration_clock = duration_clock or monotonic
        self.trace_recorder = trace_recorder or NoopTraceRecorder()
        self.trace_clock = trace_clock or SystemClock()
        self.error_classifier = error_classifier or ErrorClassifier()
        # Explicit opt-in: None preserves the Phase 1A and original workflow
        # execution path byte-for-byte at the business-contract level.
        self.operation_executor = operation_executor
        # Observer-only opt-in. Decisions are diagnostics and never alter the
        # ResearchResult, outputs, retry behavior, or control flow.
        self.progress_detector = progress_detector
        # Observer-only opt-in. Policy decisions are recorded, but never alter
        # ResearchResult, retries, stage order, output, or workflow control.
        self.workflow_controller = workflow_controller
        self.last_progress_decisions: tuple[NoProgressDecision, ...] = ()
        self.last_policy_decisions: tuple[PolicyDecision, ...] = ()

    async def run(self, profile: ResearchProfile) -> ResearchRunOutcome:
        started = self.duration_clock()
        run_id = create_run_id(profile, self.clock())
        trace_context = TraceContext(
            run_id=run_id,
            workflow="knowledge_research",
            recorder=self.trace_recorder,
            clock=self.trace_clock,
        )
        research_trace = ResearchTraceSession(trace_context)
        run_span = research_trace.run_span(profile)
        run_store = ResearchRunStore(self.workspace_root, run_id)
        phases: list[ResearchPhase] = []
        failures: list[ResearchFailure] = []
        progress_sequence = 0
        progress_decisions: list[NoProgressDecision] = []
        policy_decisions: list[PolicyDecision] = []

        def observe_progress(
            *,
            event_type: str,
            stage: ResearchPhase,
            operation: str,
            raw_arguments=None,
            target_resource=None,
            error_code: ErrorCode | None = None,
            output_identity=None,
            artifact_count: int | None = None,
            evidence_count: int | None = None,
            completed_unit_count: int | None = None,
            successful: bool | None = None,
            span_id: str | None = None,
            parent_span_id: str | None = None,
            tool_name: str | None = None,
            execution_error: ExecutionError | None = None,
        ) -> None:
            nonlocal progress_sequence
            if self.progress_detector is None and self.workflow_controller is None:
                return
            progress_sequence += 1
            signal = ProgressSignal.from_raw_input(
                sequence=progress_sequence,
                event_type=event_type,
                stage=stage.value,
                operation=operation,
                tool_name=tool_name,
                raw_arguments=raw_arguments,
                target_resource=target_resource,
                error_code=error_code,
                output_hash=(
                    safe_identity_hash(output_identity)
                    if output_identity is not None
                    else None
                ),
                artifact_count=artifact_count,
                evidence_count=evidence_count,
                completed_unit_count=completed_unit_count,
                successful=successful,
                span_id=span_id,
                parent_span_id=parent_span_id,
            )
            progress_decision = None
            if self.progress_detector is not None:
                progress_decision = self.progress_detector.observe(
                    signal, trace_context=trace_context
                )
                progress_decisions.append(progress_decision)
            if self.workflow_controller is not None:
                capability_by_operation = {
                    "research.search": CapabilityId.WEB_SEARCH,
                    "research.source_acquire": CapabilityId.HTTP_GET,
                    "research.evidence_extract": CapabilityId.EVIDENCE_EXTRACT,
                    "research.llm_synthesis": CapabilityId.LLM_SYNTHESIS,
                }
                side_effect_by_operation = {
                    "research.search": SideEffectLevel.READ_ONLY,
                    "research.source_acquire": SideEffectLevel.IDEMPOTENT_WRITE,
                    "research.evidence_extract": SideEffectLevel.IDEMPOTENT_WRITE,
                    "research.llm_synthesis": SideEffectLevel.READ_ONLY,
                }
                network_operations = {
                    "research.search",
                    "research.source_acquire",
                    "research.llm_synthesis",
                }
                output_root = (
                    f"research_runs/{run_id}"
                    if side_effect_by_operation.get(operation)
                    is SideEffectLevel.IDEMPOTENT_WRITE
                    else None
                )
                target_domain = None
                if operation in network_operations and isinstance(target_resource, str):
                    try:
                        target_domain = urlsplit(target_resource).hostname
                    except ValueError:
                        target_domain = None
                budget_snapshot = None
                if (
                    self.operation_executor is not None
                    and self.operation_executor.budget_ledger is not None
                ):
                    budget_snapshot = self.operation_executor.budget_ledger.snapshot()
                policy_decisions.append(
                    self.workflow_controller.decide(
                        PolicyContext(
                            task_type="knowledge_research",
                            workflow="knowledge_research",
                            stage=stage.value,
                            evaluation_point=PolicyEvaluationPoint.POST_OPERATION,
                            primary_error=execution_error,
                            budget_snapshot=budget_snapshot,
                            no_progress_decision=progress_decision,
                            operation=operation,
                            tool_name=capability_by_operation.get(operation).value,
                            side_effect_level=side_effect_by_operation.get(operation),
                            network_required=operation in network_operations,
                            target_domain=target_domain,
                            output_root=output_root,
                            external_write=False,
                            retry_state=(
                                PolicyRetryState(retry_exhausted=True)
                                if execution_error is not None
                                else None
                            ),
                        ),
                        trace_context=trace_context,
                        span_id=span_id,
                        parent_span_id=parent_span_id,
                    )
                )
        try:
            run_store.initialize()

            phases.append(ResearchPhase.DISCOVER)
            with research_trace.stage_span(
                ResearchPhase.DISCOVER,
                parent_span_id=run_span.span_id,
            ) as stage_span:
                failure_count = len(failures)
                search_error_code: ErrorCode | None = None
                search_policy_error: ExecutionError | None = None
                if self.operation_executor is None:
                    with research_trace.operation_span(
                        ResearchPhase.DISCOVER,
                        "search.query",
                        parent_span_id=stage_span.span_id,
                        tool_name=type(self.search_provider).__name__,
                        input_summary={
                            "profile_id": profile.profile_id,
                            "max_candidates": self.max_search_candidates,
                        },
                    ) as operation_span:
                        try:
                            search_results = await self.search_provider.search(
                                profile, max_candidates=self.max_search_candidates
                            )
                            if not search_results:
                                failure = ResearchFailure(
                                    code=ResearchErrorCode.SEARCH_FAILED,
                                    message="Search returned no structured candidates",
                                    phase=ResearchPhase.DISCOVER,
                                )
                                failures.append(failure)
                                mapped_error = research_failure_to_execution_error(
                                    failure,
                                    operation="search.query",
                                    classifier=self.error_classifier,
                                )
                                search_error_code = mapped_error.code
                                search_policy_error = mapped_error
                                operation_span.fail(mapped_error)
                            else:
                                operation_span.succeed(
                                    output_summary={
                                        "search_result_count": len(search_results)
                                    }
                                )
                        except SearchAdapterError as exc:
                            search_results = []
                            failure = ResearchFailure(
                                code=ResearchErrorCode.SEARCH_FAILED,
                                message=str(exc),
                                phase=ResearchPhase.DISCOVER,
                            )
                            failures.append(failure)
                            mapped_error = research_failure_to_execution_error(
                                failure,
                                operation="search.query",
                                classifier=self.error_classifier,
                            )
                            search_error_code = mapped_error.code
                            search_policy_error = mapped_error
                            operation_span.fail(mapped_error)
                else:
                    async def search_once(_attempt):
                        results = await self.search_provider.search(
                            profile, max_candidates=self.max_search_candidates
                        )
                        if not results:
                            raise SearchAdapterError(
                                "Search returned no structured candidates"
                            )
                        return results

                    search_execution = await self.operation_executor.execute(
                        OperationSpec(
                            name="research.search",
                            idempotent=True,
                            side_effect_level=SideEffectLevel.READ_ONLY,
                            # WebSearch retains its existing engine retries and
                            # fallback loop; this outer layer never multiplies them.
                            retry_owner=RetryOwner.DELEGATED,
                            tool_name=type(self.search_provider).__name__,
                            stage=ResearchPhase.DISCOVER.value,
                            workflow="knowledge_research",
                            budget_costs={BudgetDimension.SEARCH_CALLS: 1},
                        ),
                        search_once,
                        trace_context=trace_context,
                        parent_span_id=stage_span.span_id,
                        input_summary={
                            "profile_id": profile.profile_id,
                            "max_candidates": self.max_search_candidates,
                        },
                        output_summarizer=lambda value: {
                            "search_result_count": len(value)
                        },
                    )
                    if search_execution.status is ExecutionStatus.SUCCESS:
                        search_results = search_execution.value or []
                    else:
                        search_results = []
                        primary_error = search_execution.primary_error
                        search_error_code = (
                            primary_error.code if primary_error is not None else None
                        )
                        search_policy_error = primary_error
                        failure = ResearchFailure(
                            code=ResearchErrorCode.SEARCH_FAILED,
                            message=(
                                primary_error.message
                                if primary_error is not None
                                else "Search failed without a classified error"
                            ),
                            phase=ResearchPhase.DISCOVER,
                        )
                        failures.append(failure)
                observe_progress(
                    event_type=(
                        "OPERATION_SUCCEEDED"
                        if search_results
                        else "OPERATION_FAILED"
                    ),
                    stage=ResearchPhase.DISCOVER,
                    operation="research.search",
                    tool_name=type(self.search_provider).__name__,
                    raw_arguments={
                        "profile_id": profile.profile_id,
                        "research_topic": profile.research_topic,
                        "max_candidates": self.max_search_candidates,
                    },
                    error_code=search_error_code,
                    output_identity=(
                        sorted(item.search_result_id for item in search_results)
                        if search_results
                        else None
                    ),
                    completed_unit_count=1 if search_results else 0,
                    successful=bool(search_results),
                    span_id=stage_span.span_id,
                    parent_span_id=stage_span.parent_span_id,
                    execution_error=search_policy_error,
                )
                stage_span.succeed(
                    status=(
                        TraceStatus.PARTIAL
                        if len(failures) > failure_count
                        else TraceStatus.SUCCESS
                    ),
                    output_summary={"search_result_count": len(search_results)},
                )

            phases.append(ResearchPhase.SELECT)
            with research_trace.stage_span(
                ResearchPhase.SELECT,
                parent_span_id=run_span.span_id,
            ) as stage_span:
                with research_trace.operation_span(
                    ResearchPhase.SELECT,
                    "source_policy.select",
                    parent_span_id=stage_span.span_id,
                    tool_name=type(self.source_selector).__name__,
                    input_summary={
                        "search_result_count": len(search_results),
                        "max_sources": self.max_selected_sources,
                    },
                ) as operation_span:
                    selected_sources = self.source_selector.select(
                        search_results,
                        profile,
                        max_sources=self.max_selected_sources,
                    )
                    operation_span.succeed(
                        output_summary={
                            "selected_source_count": len(selected_sources),
                            "source_levels": [
                                source.source_level.value for source in selected_sources
                            ],
                        }
                    )
                stage_span.succeed(
                    output_summary={"selected_source_count": len(selected_sources)}
                )

            phases.append(ResearchPhase.ACQUIRE)
            acquired_sources = []
            with research_trace.stage_span(
                ResearchPhase.ACQUIRE,
                parent_span_id=run_span.span_id,
            ) as stage_span:
                failure_count = len(failures)
                for source in selected_sources:
                    acquired_before = len(acquired_sources)
                    acquisition_error_code: ErrorCode | None = None
                    acquisition_policy_error: ExecutionError | None = None
                    if self.operation_executor is None:
                        with research_trace.operation_span(
                            ResearchPhase.ACQUIRE,
                            "source.acquire",
                            parent_span_id=stage_span.span_id,
                            tool_name=type(self.source_acquirer).__name__,
                            tool_call_id=source.search_result_id,
                            input_summary={
                                "search_result_id": source.search_result_id,
                                "url": source.url,
                                "source_level": source.source_level.value,
                            },
                        ) as operation_span:
                            try:
                                acquired = await self.source_acquirer.acquire(
                                    source, run_store
                                )
                                acquired = self.source_selector.refine_acquired(acquired)
                                acquired_sources.append(acquired)
                                operation_span.succeed(
                                    output_summary={
                                        "artifact_path": acquired.local_file,
                                        "media_type": acquired.media_type,
                                        "raw_file_hash": acquired.raw_file_hash,
                                        "reused": acquired.reused,
                                    }
                                )
                            except SourceAcquisitionError as exc:
                                failure = ResearchFailure(
                                    code=exc.code,
                                    message=str(exc),
                                    phase=ResearchPhase.ACQUIRE,
                                    source_url=exc.source_url,
                                )
                                failures.append(failure)
                                mapped_error = research_failure_to_execution_error(
                                    failure,
                                    operation="source.acquire",
                                    classifier=self.error_classifier,
                                )
                                acquisition_error_code = mapped_error.code
                                acquisition_policy_error = mapped_error
                                operation_span.fail(mapped_error)
                    else:
                        operation_name = getattr(
                            self.source_acquirer,
                            "reliability_operation_name",
                            "research.source_acquire",
                        )

                        async def acquire_once(attempt):
                            try:
                                attempt_method = getattr(
                                    self.source_acquirer,
                                    "acquire_attempt",
                                    None,
                                )
                                acquired_value = (
                                    await attempt_method(source, run_store, attempt)
                                    if callable(attempt_method)
                                    else await self.source_acquirer.acquire(source, run_store)
                                )
                                return self.source_selector.refine_acquired(
                                    acquired_value
                                )
                            except SourceAcquisitionError as exc:
                                failure = ResearchFailure(
                                    code=exc.code,
                                    message=str(exc),
                                    phase=ResearchPhase.ACQUIRE,
                                    source_url=exc.source_url,
                                )
                                mapped = research_failure_to_execution_error(
                                    failure,
                                    operation=operation_name,
                                    classifier=self.error_classifier,
                                )
                                # Prefer protocol facts from the wrapped SDK
                                # error when available (HTTP status, TLS, timeout).
                                if exc.__cause__ is not None:
                                    protocol_error = self.error_classifier.classify(
                                        exc,
                                        source=type(self.source_acquirer).__name__,
                                        operation=operation_name,
                                        details=mapped.details,
                                    )
                                    if protocol_error.code is not ErrorCode.INTERNAL_ERROR:
                                        mapped = protocol_error
                                raise ExecutionErrorRaised(mapped) from exc

                        acquisition_execution = await self.operation_executor.execute(
                            OperationSpec(
                                name=operation_name,
                                idempotent=True,
                                side_effect_level=SideEffectLevel.IDEMPOTENT_WRITE,
                                retry_owner=RetryOwner.RELIABILITY,
                                tool_name=type(self.source_acquirer).__name__,
                                stage=ResearchPhase.ACQUIRE.value,
                                workflow="knowledge_research",
                                budget_costs={BudgetDimension.DOWNLOADS: 1},
                            ),
                            acquire_once,
                            trace_context=trace_context,
                            parent_span_id=stage_span.span_id,
                            tool_call_id=source.search_result_id,
                            input_summary={
                                "search_result_id": source.search_result_id,
                                "url": source.url,
                                "source_level": source.source_level.value,
                            },
                            output_summarizer=lambda value: {
                                "artifact_path": value.local_file,
                                "media_type": value.media_type,
                                "raw_file_hash": value.raw_file_hash,
                                "reused": value.reused,
                            },
                        )
                        if acquisition_execution.status is ExecutionStatus.SUCCESS:
                            if acquisition_execution.value is not None:
                                acquired_sources.append(acquisition_execution.value)
                        else:
                            primary_error = acquisition_execution.primary_error
                            acquisition_error_code = (
                                primary_error.code
                                if primary_error is not None
                                else None
                            )
                            acquisition_policy_error = primary_error
                            details = primary_error.details if primary_error else {}
                            research_code_value = details.get("research_error_code")
                            try:
                                research_code = ResearchErrorCode(research_code_value)
                            except (TypeError, ValueError):
                                research_code = ResearchErrorCode.DOWNLOAD_FAILED
                            failures.append(
                                ResearchFailure(
                                    code=research_code,
                                    message=(
                                        primary_error.message
                                        if primary_error is not None
                                        else "Source acquisition failed without a classified error"
                                    ),
                                    phase=ResearchPhase.ACQUIRE,
                                    source_url=source.url,
                                )
                            )
                    acquired_now = len(acquired_sources) > acquired_before
                    observe_progress(
                        event_type=(
                            "OPERATION_SUCCEEDED"
                            if acquired_now
                            else "OPERATION_FAILED"
                        ),
                        stage=ResearchPhase.ACQUIRE,
                        operation="research.source_acquire",
                        tool_name=type(self.source_acquirer).__name__,
                        raw_arguments={
                            "search_result_id": source.search_result_id,
                            "source_level": source.source_level.value,
                        },
                        target_resource=source.url,
                        error_code=acquisition_error_code,
                        output_identity=(
                            acquired_sources[-1].artifact_id if acquired_now else None
                        ),
                        artifact_count=len(acquired_sources),
                        completed_unit_count=(
                            1 + acquired_before if acquired_now else acquired_before
                        ),
                        successful=acquired_now,
                        span_id=stage_span.span_id,
                        parent_span_id=stage_span.parent_span_id,
                        execution_error=acquisition_policy_error,
                    )
                stage_span.succeed(
                    status=(
                        TraceStatus.PARTIAL
                        if len(failures) > failure_count
                        else TraceStatus.SUCCESS
                    ),
                    output_summary={
                        "selected_source_count": len(selected_sources),
                        "acquired_source_count": len(acquired_sources),
                    },
                )

            phases.append(ResearchPhase.EXTRACT)
            evidence_store = EvidenceStore(
                self.workspace_root,
                run_store.relative_to_workspace(run_store.context.evidence_path),
            )
            with research_trace.stage_span(
                ResearchPhase.EXTRACT,
                parent_span_id=run_span.span_id,
            ) as stage_span:
                failure_count = len(failures)
                for source in acquired_sources:
                    extracted = []
                    extraction_error_code: ErrorCode | None = None
                    extraction_policy_error: ExecutionError | None = None
                    with research_trace.operation_span(
                        ResearchPhase.EXTRACT,
                        "evidence.extract",
                        parent_span_id=stage_span.span_id,
                        tool_name=type(self.evidence_extractor).__name__,
                        tool_call_id=source.artifact_id,
                        input_summary={
                            "artifact_path": source.local_file,
                            "media_type": source.media_type,
                            "raw_file_hash": source.raw_file_hash,
                        },
                    ) as operation_span:
                        try:
                            extracted = self.evidence_extractor.extract(
                                source, workspace_root=self.workspace_root
                            )
                            for evidence_item in extracted:
                                evidence_store.add(evidence_item)
                            operation_span.succeed(
                                output_summary={"evidence_count": len(extracted)}
                            )
                        except EvidenceExtractionError as exc:
                            failure = ResearchFailure(
                                code=exc.code,
                                message=str(exc),
                                phase=ResearchPhase.EXTRACT,
                                source_url=exc.source_url,
                            )
                            failures.append(failure)
                            mapped_error = research_failure_to_execution_error(
                                failure,
                                operation="evidence.extract",
                                classifier=self.error_classifier,
                            )
                            extraction_error_code = mapped_error.code
                            extraction_policy_error = mapped_error
                            operation_span.fail(mapped_error)
                    observe_progress(
                        event_type=(
                            "OPERATION_SUCCEEDED"
                            if extracted
                            else "OPERATION_FAILED"
                        ),
                        stage=ResearchPhase.EXTRACT,
                        operation="research.evidence_extract",
                        tool_name=type(self.evidence_extractor).__name__,
                        raw_arguments={
                            "artifact_id": source.artifact_id,
                            "media_type": source.media_type,
                        },
                        target_resource=source.local_file,
                        error_code=extraction_error_code,
                        output_identity=(
                            sorted(
                                item.evidence_id
                                for item in extracted
                                if item.evidence_id is not None
                            )
                            if extracted
                            else None
                        ),
                        artifact_count=len(acquired_sources),
                        evidence_count=len(evidence_store.list()),
                        successful=bool(extracted),
                        span_id=stage_span.span_id,
                        parent_span_id=stage_span.parent_span_id,
                        execution_error=extraction_policy_error,
                    )
                evidence_store.save()
                evidence = evidence_store.list()
                stage_span.succeed(
                    status=(
                        TraceStatus.PARTIAL
                        if len(failures) > failure_count
                        else TraceStatus.SUCCESS
                    ),
                    output_summary={"evidence_count": len(evidence)},
                )

            phases.append(ResearchPhase.BUILD_RESULT)
            with research_trace.stage_span(
                ResearchPhase.BUILD_RESULT,
                parent_span_id=run_span.span_id,
            ) as stage_span:
                synthesis_input_summary = {
                    "profile_id": profile.profile_id,
                    "evidence_count": len(evidence),
                    "evidence_ids_hash": hashlib.sha256(
                        "|".join(
                            sorted(
                                item.evidence_id
                                for item in evidence
                                if item.evidence_id is not None
                            )
                        ).encode("utf-8")
                    ).hexdigest(),
                }
                if self.operation_executor is None:
                    with research_trace.operation_span(
                        ResearchPhase.BUILD_RESULT,
                        "research.synthesize",
                        parent_span_id=stage_span.span_id,
                        tool_name=type(self.synthesizer).__name__,
                        input_summary=synthesis_input_summary,
                    ) as operation_span:
                        synthesis = await self.synthesizer.synthesize(profile, evidence)
                        operation_span.succeed(
                            output_summary={
                                "finding_count": len(synthesis.key_findings),
                                "limitation_count": len(synthesis.limitations),
                            },
                            token_usage=synthesis.token_usage.model_dump(mode="json"),
                        )
                else:
                    async def synthesize_once(_attempt):
                        return await self.synthesizer.synthesize(profile, evidence)

                    synthesis_budget_costs, synthesis_observational = (
                        self._synthesis_budget_contract(profile, evidence)
                    )
                    retry_owner = getattr(
                        self.synthesizer,
                        "reliability_retry_owner",
                        RetryOwner.NONE,
                    )
                    synthesis_execution = await self.operation_executor.execute(
                        OperationSpec(
                            name="research.llm_synthesis",
                            idempotent=True,
                            side_effect_level=SideEffectLevel.READ_ONLY,
                            retry_owner=RetryOwner(retry_owner),
                            tool_name=type(self.synthesizer).__name__,
                            stage=ResearchPhase.BUILD_RESULT.value,
                            workflow="knowledge_research",
                            budget_costs=synthesis_budget_costs,
                            budget_observational_dimensions=(
                                synthesis_observational
                            ),
                        ),
                        synthesize_once,
                        trace_context=trace_context,
                        parent_span_id=stage_span.span_id,
                        input_summary=synthesis_input_summary,
                        output_summarizer=lambda value: {
                            "finding_count": len(value.key_findings),
                            "limitation_count": len(value.limitations),
                        },
                        token_usage_summarizer=lambda value: value.token_usage.model_dump(
                            mode="json"
                        ),
                    )
                    if synthesis_execution.status is not ExecutionStatus.SUCCESS:
                        primary_error = synthesis_execution.primary_error
                        if primary_error is None:
                            primary_error = ExecutionError(
                                code=ErrorCode.INTERNAL_ERROR,
                                category=ErrorCategory.INTERNAL,
                                message="Synthesis failed without a classified error",
                                retryable=False,
                                source=type(self.synthesizer).__name__,
                                operation="research.llm_synthesis",
                                cause_type="ExecutionResult",
                            )
                        raise ExecutionErrorRaised(primary_error)
                    synthesis = synthesis_execution.value
                    if synthesis is None:
                        raise RuntimeError("Successful synthesis returned no value")
                observe_progress(
                    event_type="OPERATION_SUCCEEDED",
                    stage=ResearchPhase.BUILD_RESULT,
                    operation="research.llm_synthesis",
                    tool_name=type(self.synthesizer).__name__,
                    raw_arguments={
                        "profile_id": profile.profile_id,
                        "evidence_ids": sorted(
                            item.evidence_id
                            for item in evidence
                            if item.evidence_id is not None
                        ),
                    },
                    output_identity=sorted(
                        finding.finding_id
                        for finding in synthesis.key_findings
                        if finding.finding_id is not None
                    ),
                    evidence_count=len(evidence),
                    completed_unit_count=(
                        2 + len(acquired_sources) + len(evidence)
                    ),
                    successful=True,
                    span_id=stage_span.span_id,
                    parent_span_id=stage_span.parent_span_id,
                )
                with research_trace.operation_span(
                    ResearchPhase.BUILD_RESULT,
                    "research_result.build",
                    parent_span_id=stage_span.span_id,
                    tool_name=type(self.result_builder).__name__,
                    input_summary={
                        "evidence_count": len(evidence),
                        "acquired_source_count": len(acquired_sources),
                        "failure_count": len(failures),
                    },
                ) as operation_span:
                    result = self.result_builder.build(
                        run_id=run_id,
                        profile=profile,
                        evidence=evidence,
                        acquired_sources=acquired_sources,
                        synthesis=synthesis,
                        failures=failures,
                    )
                    operation_span.succeed(
                        status=(
                            TraceStatus.SUCCESS
                            if result.status is ResearchStatus.COMPLETED
                            else TraceStatus.PARTIAL
                        ),
                        output_summary={
                            "research_status": result.status.value,
                            "finding_count": len(result.key_findings),
                            "evidence_count": len(result.evidence_ids),
                        },
                    )
                stage_span.succeed(
                    status=(
                        TraceStatus.SUCCESS
                        if result.status is ResearchStatus.COMPLETED
                        else TraceStatus.PARTIAL
                    ),
                    output_summary={"research_status": result.status.value},
                )

            phases.append(ResearchPhase.OUTPUT)
            outputs: list[OutputArtifact] = []
            with research_trace.stage_span(
                ResearchPhase.OUTPUT,
                parent_span_id=run_span.span_id,
            ) as stage_span:
                failed_outputs = 0
                for adapter in self.output_adapters:
                    with research_trace.operation_span(
                        ResearchPhase.OUTPUT,
                        "output.write",
                        parent_span_id=stage_span.span_id,
                        tool_name=adapter.name,
                        tool_call_id=adapter.name,
                        input_summary={"adapter": adapter.name},
                    ) as operation_span:
                        try:
                            artifact = await adapter.write(
                                result=result,
                                evidence_store=evidence_store,
                                run_store=run_store,
                                profile=profile,
                            )
                            outputs.append(artifact)
                            if artifact.status == "FAILED":
                                failed_outputs += 1
                                operation_span.fail(
                                    self.error_classifier.classify(
                                        str(
                                            artifact.details.get(
                                                "message", "output adapter returned FAILED"
                                            )
                                        ),
                                        source=adapter.name,
                                        operation="output.write",
                                    ),
                                    output_summary={
                                        "adapter": artifact.adapter,
                                        "status": artifact.status,
                                        "artifact_path": artifact.path,
                                    },
                                )
                            else:
                                operation_span.succeed(
                                    output_summary={
                                        "adapter": artifact.adapter,
                                        "status": artifact.status,
                                        "artifact_path": artifact.path,
                                    },
                                )
                        except OutputAdapterError as exc:
                            failed_outputs += 1
                            outputs.append(
                                OutputArtifact(
                                    adapter=adapter.name,
                                    status="FAILED",
                                    details={"message": str(exc)},
                                )
                            )
                            operation_span.fail(
                                self.error_classifier.classify(
                                    exc,
                                    source=adapter.name,
                                    operation="output.write",
                                )
                            )
                stage_span.succeed(
                    status=(TraceStatus.PARTIAL if failed_outputs else TraceStatus.SUCCESS),
                    output_summary={
                        "output_count": len(outputs),
                        "failed_output_count": failed_outputs,
                    },
                )

            phases.append(ResearchPhase.COMPLETE)
            distribution = Counter(source.source_level.value for source in acquired_sources)
            metrics = ResearchRunMetrics(
                search_count=len(search_results),
                selected_source_count=len(selected_sources),
                download_success=len(acquired_sources),
                download_failure=len(selected_sources) - len(acquired_sources),
                evidence_count=len(evidence),
                source_level_distribution=dict(sorted(distribution.items())),
                duration_seconds=max(0.0, self.duration_clock() - started),
                llm=synthesis.token_usage,
            )
            outcome = ResearchRunOutcome(
                result=result,
                metrics=metrics,
                failures=failures,
                outputs=outputs,
                phases=phases,
            )
            run_store.write_json(
                "outputs/run_manifest.json",
                outcome.model_dump(mode="json"),
            )
            run_trace_status = (
                TraceStatus.SUCCESS
                if result.status is ResearchStatus.COMPLETED and not failed_outputs
                else TraceStatus.PARTIAL
            )
            if result.status is ResearchStatus.FAILED:
                error = (
                    research_failure_to_execution_error(
                        failures[0], classifier=self.error_classifier
                    )
                    if failures
                    else ExecutionError(
                        code=ErrorCode.INTERNAL_ERROR,
                        category=ErrorCategory.INTERNAL,
                        message="ResearchResult ended with FAILED status",
                        retryable=False,
                        source="knowledge_research",
                        operation="knowledge_research.run",
                        cause_type="ResearchStatus",
                    )
                )
                run_span.fail(error)
            else:
                run_span.succeed(
                    status=run_trace_status,
                    output_summary={
                        "research_status": result.status.value,
                        "search_count": metrics.search_count,
                        "selected_source_count": metrics.selected_source_count,
                        "download_success": metrics.download_success,
                        "download_failure": metrics.download_failure,
                        "evidence_count": metrics.evidence_count,
                        "failure_count": len(failures),
                        "output_count": len(outputs),
                    },
                    token_usage=synthesis.token_usage.model_dump(mode="json"),
                )
            return outcome
        except BaseException as exc:
            if not run_span.ended:
                error = self.error_classifier.classify(
                    exc,
                    source="knowledge_research",
                    operation="knowledge_research.run",
                )
                run_span.fail(
                    error,
                    status=(
                        TraceStatus.CANCELLED
                        if error.code is ErrorCode.CANCELLED
                        else TraceStatus.FAILED
                    ),
                )
            raise
        finally:
            self.last_progress_decisions = tuple(progress_decisions)
            self.last_policy_decisions = tuple(policy_decisions)

    def _synthesis_budget_contract(
        self,
        profile: ResearchProfile,
        evidence: list,
    ) -> tuple[dict[BudgetDimension, int], frozenset[BudgetDimension]]:
        provider = getattr(self.synthesizer, "reliability_budget_contract", None)
        if not callable(provider):
            return {}, frozenset()
        costs, observational = provider(profile, evidence)
        return (
            {BudgetDimension(key): int(value) for key, value in costs.items()},
            frozenset(BudgetDimension(value) for value in observational),
        )
