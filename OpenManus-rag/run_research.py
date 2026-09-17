"""Independent entrypoint for the pluggable Knowledge Research Workflow."""

from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parent


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run the independent OpenManus Knowledge Research Workflow"
    )
    parser.add_argument(
        "--profile",
        type=Path,
        default=PROJECT_ROOT
        / "config/research_profiles/special_equipment_validation.toml",
    )
    parser.add_argument(
        "--policy",
        type=Path,
        default=PROJECT_ROOT / "config/research_policies/default.toml",
    )
    parser.add_argument(
        "--workspace",
        type=Path,
        default=PROJECT_ROOT / "workspace",
    )
    parser.add_argument("--max-candidates", type=int, default=8, choices=range(1, 9))
    parser.add_argument("--max-sources", type=int, default=3, choices=range(1, 4))
    parser.add_argument(
        "--browser-fallback",
        action="store_true",
        help=(
            "Use BrowserUseTool only if it exposes the public get_current_document interface; "
            "the current core does not, so no private page access is attempted"
        ),
    )
    parser.add_argument("--no-candidate", action="store_true")
    synthesis_group = parser.add_mutually_exclusive_group()
    synthesis_group.add_argument(
        "--llm-preflight-run",
        help=(
            "Reuse an existing run and persist deterministic Evidence selection; "
            "no LLM API call is made"
        ),
    )
    synthesis_group.add_argument(
        "--llm-synthesis-run",
        help=(
            "Reuse an existing run's planned Evidence subset for exactly one LLM "
            "synthesis API attempt"
        ),
    )
    return parser


async def run_live(args) -> dict:
    from app.agent.knowledge_research import KnowledgeResearchAgent
    from app.research.candidate_builder import CandidateBuilder
    from app.research.candidate_validator import CandidateValidator
    from app.research.evidence_extraction import CompositeEvidenceExtractor
    from app.research.output_adapters import (
        CandidatePackageAdapter,
        JsonResultAdapter,
        MarkdownReportAdapter,
    )
    from app.research.profile_loader import load_research_profile
    from app.research.research_synthesis import DeterministicResearchSynthesizer
    from app.research.search_adapter import WebSearchAdapter
    from app.research.source_acquisition import (
        BrowserSourceAcquirer,
        CompositeSourceAcquirer,
        HttpSourceAcquirer,
    )
    from app.research.source_policy import SourcePolicy
    from app.research.source_selection import SourceSelector
    from app.research.workflow import KnowledgeResearchWorkflow
    from app.tool.web_search import WebSearch

    profile = load_research_profile(args.profile)
    policy = SourcePolicy.from_toml(args.policy)
    browser_tool = None
    browser_acquirer = None
    if args.browser_fallback:
        from app.tool.browser_use_tool import BrowserUseTool

        browser_tool = BrowserUseTool()
        browser_acquirer = BrowserSourceAcquirer(browser_tool)
    validator = CandidateValidator()
    adapters = [MarkdownReportAdapter(), JsonResultAdapter()]
    if not args.no_candidate:
        builder = CandidateBuilder(workspace_root=args.workspace, validator=validator)
        adapters.append(
            CandidatePackageAdapter(
                None,
                validator,
                candidate_builder=builder,
            )
        )
    workflow = KnowledgeResearchWorkflow(
        workspace_root=args.workspace,
        search_provider=WebSearchAdapter(WebSearch()),
        source_selector=SourceSelector(policy),
        source_acquirer=CompositeSourceAcquirer(
            HttpSourceAcquirer(), browser_acquirer
        ),
        evidence_extractor=CompositeEvidenceExtractor(),
        synthesizer=DeterministicResearchSynthesizer(),
        output_adapters=adapters,
        max_search_candidates=args.max_candidates,
        max_selected_sources=args.max_sources,
    )
    try:
        outcome = await KnowledgeResearchAgent(workflow).run_research(profile)
        return outcome.model_dump(mode="json")
    finally:
        if browser_tool is not None:
            await browser_tool.cleanup()


async def run_llm_smoke(args) -> dict:
    from app.research.evidence_budget import EvidenceBudgetPlanner
    from app.research.llm_synthesis_smoke import synthesize_existing_run
    from app.research.profile_loader import load_research_profile
    from app.research.research_synthesis import (
        LLMResearchSynthesizer,
        OpenManusLLMSynthesisClient,
    )

    profile = load_research_profile(args.profile)
    from app.llm import LLM

    client = OpenManusLLMSynthesisClient(LLM())
    planner = EvidenceBudgetPlanner(token_counter=client.count_tokens)
    result, result_path, usage_path = await synthesize_existing_run(
        workspace_root=args.workspace,
        run_id=args.llm_synthesis_run,
        profile=profile,
        synthesizer=LLMResearchSynthesizer(client, max_prompt_tokens=20_000),
        planner=planner,
    )
    return {
        "run_id": result.run_id,
        "result_path": result_path,
        "report_path": (
            f"research_runs/{result.run_id}/outputs/research_report_llm.md"
        ),
        "selection_report_path": (
            f"research_runs/{result.run_id}/outputs/evidence_selection_report.json"
        ),
        "usage_path": usage_path,
    }


async def run_llm_preflight(args) -> dict:
    from app.llm import LLM
    from app.research.evidence_budget import EvidenceBudgetPlanner
    from app.research.llm_synthesis_smoke import plan_existing_run
    from app.research.profile_loader import load_research_profile

    profile = load_research_profile(args.profile)
    llm = LLM()
    selected, report, report_path = plan_existing_run(
        workspace_root=args.workspace,
        run_id=args.llm_preflight_run,
        profile=profile,
        planner=EvidenceBudgetPlanner(token_counter=llm.count_tokens),
    )
    return {
        "run_id": args.llm_preflight_run,
        "original_evidence_count": report.total_evidence_count,
        "selected_evidence_count": len(selected),
        "original_estimated_tokens": report.total_estimated_tokens,
        "selected_estimated_tokens": report.selected_estimated_tokens,
        "selected_prompt_estimated_tokens": report.selected_prompt_estimated_tokens,
        "max_evidence_budget": report.max_evidence_budget,
        "max_context_budget": report.max_context_budget,
        "selection_report_path": report_path,
    }


async def main() -> None:
    args = build_parser().parse_args()
    if args.llm_preflight_run:
        payload = await run_llm_preflight(args)
    elif args.llm_synthesis_run:
        payload = await run_llm_smoke(args)
    else:
        payload = await run_live(args)
    print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))


if __name__ == "__main__":
    asyncio.run(main())
