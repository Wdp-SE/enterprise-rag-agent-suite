"""Independent Markdown, JSON, and optional Candidate Package outputs."""

from __future__ import annotations

import json
from pathlib import Path

from app.research.candidate_types import CandidateBuildResult, CandidateBuildStatus
from app.research.evidence_store import EvidenceStore
from app.research.live_models import OutputArtifact, ResearchResult
from app.research.models import Evidence, ResearchProfile


class OutputAdapterError(RuntimeError):
    pass


class MarkdownReportAdapter:
    name = "markdown_report"

    async def write(
        self,
        *,
        result: ResearchResult,
        evidence_store: EvidenceStore,
        run_store,
        profile: ResearchProfile,
        relative_path: str = "outputs/research_report.md",
    ) -> OutputArtifact:
        source_by_evidence = {
            evidence_id: source.source_id
            for source in result.sources
            for evidence_id in source.evidence_ids
        }
        lines = [
            f"# {result.research_topic}",
            "",
            "## Research Scope",
            "",
            f"- Profile: `{result.profile_id}`",
            f"- Domain: `{profile.domain}`",
            f"- Status: `{result.status.value}`",
            "",
            "## Sources",
            "",
        ]
        if result.sources:
            lines.extend(
                f"- [source:{source.source_id}] {source.title} — "
                f"{source.organization} — {source.url} ({source.source_level.value})"
                for source in result.sources
            )
        else:
            lines.append("- 未获得可追溯的正式来源。")
        lines.extend(["", "## Key Findings", ""])
        if result.key_findings:
            for finding in result.key_findings:
                citations = "".join(
                    f"[source:{source_id}]"
                    for source_id in sorted(
                        {
                            source_by_evidence[evidence_id]
                            for evidence_id in finding.evidence_ids
                            if evidence_id in source_by_evidence
                        }
                    )
                )
                lines.append(f"- {finding.statement} {citations}".rstrip())
        else:
            lines.append("- 当前 Evidence 不足，未形成确定性专业结论。")
        lines.extend(["", "## Limitations", ""])
        lines.extend(f"- {value}" for value in result.limitations)
        if not result.limitations:
            lines.append("- 未记录额外限制。")
        lines.extend(["", "## Unresolved Questions", ""])
        lines.extend(f"- {value}" for value in result.unresolved_questions)
        if not result.unresolved_questions:
            lines.append("- 无。")
        lines.extend(
            [
                "",
                "## Generated From Public Sources",
                "",
                "本报告基于公开资料生成，不代表企业内部业务流程或正式法律意见。",
                "",
            ]
        )
        path = run_store.write_text(relative_path, "\n".join(lines))
        return OutputArtifact(adapter=self.name, status="CREATED", path=path)


class JsonResultAdapter:
    name = "json_result"

    async def write(
        self,
        *,
        result: ResearchResult,
        evidence_store: EvidenceStore,
        run_store,
        profile: ResearchProfile,
    ) -> OutputArtifact:
        path = run_store.write_json(
            "outputs/structured_result.json",
            result.model_dump(mode="json"),
        )
        return OutputArtifact(adapter=self.name, status="CREATED", path=path)


class CandidateEvidenceSelector:
    """Choose a stable representative subset before KnowledgeDraftTool is called."""

    def select(
        self,
        result: ResearchResult,
        evidence_store: EvidenceStore,
        profile: ResearchProfile,
    ) -> list[Evidence]:
        referenced = {
            evidence_id
            for finding in result.key_findings
            for evidence_id in finding.evidence_ids
        }
        selected_ids: list[str] = []
        # First preserve source diversity using the ResearchResult's stable Sxx order.
        for source in sorted(result.sources, key=lambda item: item.source_id):
            candidates = sorted(set(source.evidence_ids) & referenced)
            if candidates:
                selected_ids.append(candidates[0])
        # Only fill when source representatives do not meet the Candidate minimum.
        # This keeps the adapter a representative subset rather than a max-size dump.
        if len(selected_ids) < profile.output_requirements.minimum_evidence_count:
            for evidence_id in sorted(referenced):
                if evidence_id not in selected_ids:
                    selected_ids.append(evidence_id)
                if len(selected_ids) >= profile.output_requirements.minimum_evidence_count:
                    break
        if len(selected_ids) < profile.output_requirements.minimum_evidence_count:
            for evidence_id in result.evidence_ids:
                if evidence_id not in selected_ids:
                    selected_ids.append(evidence_id)
                if len(selected_ids) >= profile.output_requirements.minimum_evidence_count:
                    break
        selected_ids = selected_ids[: profile.max_sources]
        selected = [evidence_store.get(evidence_id) for evidence_id in selected_ids]
        return [item for item in selected if item is not None]


class CandidatePackageAdapter:
    name = "candidate_package"

    def __init__(
        self,
        knowledge_draft_tool,
        candidate_validator,
        *,
        candidate_builder=None,
        evidence_selector: CandidateEvidenceSelector | None = None,
    ):
        self.knowledge_draft_tool = knowledge_draft_tool
        self.candidate_validator = candidate_validator
        self.candidate_builder = candidate_builder
        self.evidence_selector = evidence_selector or CandidateEvidenceSelector()

    async def write(
        self,
        *,
        result: ResearchResult,
        evidence_store: EvidenceStore,
        run_store,
        profile: ResearchProfile,
    ) -> OutputArtifact:
        selected = self.evidence_selector.select(result, evidence_store, profile)
        minimum = profile.output_requirements.minimum_evidence_count
        if len(selected) < minimum:
            return OutputArtifact(
                adapter=self.name,
                status=CandidateBuildStatus.INSUFFICIENT_EVIDENCE.value,
                details={
                    "reason": f"Candidate requires {minimum} representative Evidence records",
                    "evidence_ids": [item.evidence_id for item in selected],
                },
            )
        selected_ids = [item.evidence_id for item in selected if item.evidence_id]
        tool = self.knowledge_draft_tool
        if tool is None:
            if self.candidate_builder is None:
                raise OutputAdapterError("CandidatePackageAdapter has no CandidateBuilder")
            from app.tool.knowledge_draft import KnowledgeDraftTool

            tool = KnowledgeDraftTool(
                profile=profile,
                evidence_store=evidence_store,
                candidate_builder=self.candidate_builder,
            )
        tool_result = await tool.execute(
            research_topic=profile.research_topic,
            domain=profile.domain,
            category=profile.knowledge_category,
            evidence_ids=selected_ids,
        )
        if tool_result.error:
            raise OutputAdapterError(f"KnowledgeDraftTool failed: {tool_result.error}")
        try:
            build_result = CandidateBuildResult.model_validate(json.loads(tool_result.output))
        except (TypeError, ValueError, json.JSONDecodeError) as exc:
            raise OutputAdapterError(f"invalid KnowledgeDraftTool result: {exc}") from exc
        if not build_result.package_path:
            return OutputArtifact(
                adapter=self.name,
                status=build_result.status.value,
                details={"reason": build_result.reason, "evidence_ids": selected_ids},
            )

        package_path = Path(run_store.workspace_root) / build_result.package_path
        evidence_by_id = {item.evidence_id: item for item in selected if item.evidence_id}
        validation = self.candidate_validator.validate(
            package_path,
            evidence_by_id=evidence_by_id,
            expected_candidate_id=build_result.candidate_id,
            expected_document_id=build_result.document_id,
        )
        if not validation.accepted:
            raise OutputAdapterError(
                "CandidateValidator rejected output: "
                + "; ".join(f"{issue.code}: {issue.message}" for issue in validation.issues)
            )
        package_sources = json.loads(
            (package_path / "sources.json").read_text(encoding="utf-8")
        )
        package_evidence_ids = sorted(source["evidence_id"] for source in package_sources)
        if package_evidence_ids != sorted(selected_ids):
            raise OutputAdapterError("Candidate Package does not match selected Evidence subset")
        return OutputArtifact(
            adapter=self.name,
            status=build_result.status.value,
            path=build_result.package_path,
            details={
                "candidate_id": build_result.candidate_id,
                "document_id": build_result.document_id,
                "evidence_ids": selected_ids,
                "accepted": True,
            },
        )
