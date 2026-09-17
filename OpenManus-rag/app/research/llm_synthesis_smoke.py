"""One-call LLM synthesis over an existing, persisted EvidenceStore."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from pydantic import Field

from app.research.evidence_budget import (
    EvidenceBudgetPlanner,
    EvidenceSelectionReport,
    EvidenceSelectionStatus,
)
from app.research.evidence_store import EvidenceStore
from app.research.live_models import ResearchResult, ResearchStatus
from app.research.models import Evidence, ResearchProfile, StrictModel
from app.research.output_adapters import MarkdownReportAdapter
from app.research.research_synthesis import LLMResearchSynthesizer
from app.research.run_store import ResearchRunStore


class LLMSynthesisSmokeError(RuntimeError):
    pass


class GroundingValidationResult(StrictModel):
    passed: bool
    validation_scope: str
    selected_evidence_only: bool
    semantic_entailment_verified: bool = False


class LLMSynthesisMetrics(StrictModel):
    model: str
    original_evidence_count: int = Field(ge=0)
    selected_evidence_count: int = Field(ge=0)
    original_estimated_tokens: int = Field(ge=0)
    selected_estimated_tokens: int = Field(ge=0)
    selected_prompt_estimated_tokens: int = Field(ge=0)
    prompt_tokens: int = Field(ge=0)
    completion_tokens: int = Field(ge=0)
    total_tokens: int = Field(ge=0)
    latency_ms: float = Field(ge=0)
    finding_count: int = Field(ge=0)
    grounded_finding_count: int = Field(ge=0)
    rejected_finding_count: int = Field(ge=0)
    selected_evidence_ids: list[str]
    grounding_validator_result: GroundingValidationResult


def _load_existing_run(
    *,
    workspace_root: str | Path,
    run_id: str,
    profile: ResearchProfile,
) -> tuple[ResearchRunStore, EvidenceStore, list[Evidence], ResearchResult]:
    run_store = ResearchRunStore(workspace_root, run_id)
    run_store.open_existing()
    evidence_store = EvidenceStore(
        workspace_root,
        run_store.relative_to_workspace(run_store.context.evidence_path),
    ).load()
    structured_path = run_store.context.outputs_root / "structured_result.json"
    if not structured_path.is_file() or structured_path.is_symlink():
        raise LLMSynthesisSmokeError("existing run has no structured_result.json")
    prior = ResearchResult.model_validate_json(structured_path.read_text(encoding="utf-8"))
    if prior.profile_id != profile.profile_id or prior.research_topic != profile.research_topic:
        raise LLMSynthesisSmokeError("existing run does not match ResearchProfile")
    evidence = evidence_store.list()
    if set(prior.evidence_ids) != {
        item.evidence_id for item in evidence if item.evidence_id is not None
    }:
        raise LLMSynthesisSmokeError("existing ResearchResult and EvidenceStore disagree")
    return run_store, evidence_store, evidence, prior


def _persist_or_verify_selection_report(
    run_store: ResearchRunStore,
    report: EvidenceSelectionReport,
) -> str:
    report_path = run_store.context.outputs_root / "evidence_selection_report.json"
    if report_path.is_symlink():
        raise LLMSynthesisSmokeError("Evidence selection report cannot be a symlink")
    if report_path.exists():
        persisted = EvidenceSelectionReport.model_validate_json(
            report_path.read_text(encoding="utf-8")
        )
        if persisted != report:
            raise LLMSynthesisSmokeError(
                "persisted Evidence selection report does not match deterministic replanning"
            )
        return run_store.relative_to_workspace(report_path)
    return run_store.write_json(
        "outputs/evidence_selection_report.json",
        report.model_dump(mode="json"),
    )


def plan_existing_run(
    *,
    workspace_root: str | Path,
    run_id: str,
    profile: ResearchProfile,
    planner: EvidenceBudgetPlanner,
) -> tuple[list[Evidence], EvidenceSelectionReport, str]:
    """Plan one synthesis input without Search, acquisition, extraction, or LLM calls."""

    run_store, _, evidence, _ = _load_existing_run(
        workspace_root=workspace_root,
        run_id=run_id,
        profile=profile,
    )
    selected, report = planner.plan(profile, evidence)
    report_path = _persist_or_verify_selection_report(run_store, report)
    if report.status is EvidenceSelectionStatus.INSUFFICIENT_EVIDENCE:
        raise LLMSynthesisSmokeError("INSUFFICIENT_EVIDENCE after budget planning")
    if report.selected_estimated_tokens >= report.max_evidence_budget:
        raise LLMSynthesisSmokeError("selected Evidence does not preserve budget headroom")
    return selected, report, report_path


def _merge_text_values(*groups: list[str]) -> list[str]:
    merged: list[str] = []
    for group in groups:
        for value in group:
            if value not in merged:
                merged.append(value)
    return merged


async def synthesize_existing_run(
    *,
    workspace_root: str | Path,
    run_id: str,
    profile: ResearchProfile,
    synthesizer: LLMResearchSynthesizer,
    planner: EvidenceBudgetPlanner | None = None,
) -> tuple[ResearchResult, str, str]:
    """Reuse disk Evidence and make one synthesis call over the planned subset."""

    run_store, evidence_store, evidence, prior = _load_existing_run(
        workspace_root=workspace_root,
        run_id=run_id,
        profile=profile,
    )
    final_paths = [
        run_store.context.outputs_root / "structured_result_llm.json",
        run_store.context.outputs_root / "research_report_llm.md",
        run_store.context.outputs_root / "llm_synthesis_metrics.json",
    ]
    if any(path.exists() for path in final_paths):
        raise LLMSynthesisSmokeError("LLM synthesis output already exists for this run")

    if planner is None:
        counter = getattr(synthesizer.client, "count_tokens", None)
        planner = EvidenceBudgetPlanner(
            token_counter=counter if callable(counter) else None
        )
    selected, selection_report = planner.plan(profile, evidence)
    _persist_or_verify_selection_report(run_store, selection_report)
    if selection_report.status is EvidenceSelectionStatus.INSUFFICIENT_EVIDENCE:
        raise LLMSynthesisSmokeError("INSUFFICIENT_EVIDENCE after budget planning")
    if selection_report.selected_estimated_tokens >= selection_report.max_evidence_budget:
        raise LLMSynthesisSmokeError("selected Evidence does not preserve budget headroom")

    synthesis = await synthesizer.synthesize(profile, selected)
    status = prior.status
    if synthesis.limitations and status is ResearchStatus.COMPLETED:
        status = ResearchStatus.PARTIAL
    payload = prior.model_dump(mode="json")
    payload.update(
        {
            "status": status.value,
            "summary": synthesis.summary,
            "key_findings": [
                finding.model_dump(mode="json") for finding in synthesis.key_findings
            ],
            "limitations": _merge_text_values(
                prior.limitations, synthesis.limitations
            ),
            "unresolved_questions": _merge_text_values(
                prior.unresolved_questions, synthesis.unresolved_questions
            ),
            "generated_at": datetime.now(timezone.utc).isoformat(),
        }
    )
    result = ResearchResult.model_validate(payload)
    result_path = run_store.write_json(
        "outputs/structured_result_llm.json", result.model_dump(mode="json")
    )
    await MarkdownReportAdapter().write(
        result=result,
        evidence_store=evidence_store,
        run_store=run_store,
        profile=profile,
        relative_path="outputs/research_report_llm.md",
    )
    usage = synthesis.token_usage
    metrics = LLMSynthesisMetrics(
        model=usage.model,
        original_evidence_count=selection_report.total_evidence_count,
        selected_evidence_count=selection_report.selected_evidence_count,
        original_estimated_tokens=selection_report.total_estimated_tokens,
        selected_estimated_tokens=selection_report.selected_estimated_tokens,
        selected_prompt_estimated_tokens=(
            selection_report.selected_prompt_estimated_tokens
        ),
        prompt_tokens=usage.prompt_tokens,
        completion_tokens=usage.completion_tokens,
        total_tokens=usage.total_tokens,
        latency_ms=round(usage.latency_seconds * 1000, 3),
        finding_count=len(synthesis.key_findings),
        grounded_finding_count=len(synthesis.key_findings),
        rejected_finding_count=0,
        selected_evidence_ids=selection_report.selected_evidence_ids,
        grounding_validator_result=GroundingValidationResult(
            passed=True,
            validation_scope=(
                "evidence_id membership in SelectedEvidence plus exact normalized "
                "extractive-span containment"
            ),
            selected_evidence_only=True,
            semantic_entailment_verified=False,
        ),
    )
    metrics_path = run_store.write_json(
        "outputs/llm_synthesis_metrics.json",
        metrics.model_dump(mode="json"),
    )
    return result, result_path, metrics_path


__all__ = [
    "GroundingValidationResult",
    "LLMSynthesisMetrics",
    "LLMSynthesisSmokeError",
    "plan_existing_run",
    "synthesize_existing_run",
]
