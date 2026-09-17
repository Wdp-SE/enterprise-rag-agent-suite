"""OpenManus tool boundary for offline Evidence-to-Candidate construction."""

from __future__ import annotations

from typing import Any

from pydantic import Field

from app.research.candidate_types import CandidateBuildResult, CandidateBuildStatus
from app.research.evidence_store import EvidenceStore
from app.research.models import ResearchProfile
from app.tool.base import BaseTool, ToolResult


class KnowledgeDraftTool(BaseTool):
    """Build a Candidate Package using only Evidence already in EvidenceStore."""

    name: str = "knowledge_draft"
    description: str = (
        "Build an offline, review-required Candidate Package from validated Evidence IDs."
    )
    parameters: dict = {
        "type": "object",
        "properties": {
            "research_topic": {"type": "string"},
            "domain": {"type": "string"},
            "category": {"type": "string"},
            "evidence_ids": {
                "type": "array",
                "items": {"type": "string", "pattern": "^ev_[0-9a-f]{20}$"},
                "minItems": 1,
            },
        },
        "required": ["research_topic", "domain", "category", "evidence_ids"],
        "additionalProperties": False,
    }

    profile: ResearchProfile = Field(exclude=True)
    evidence_store: EvidenceStore = Field(exclude=True)
    candidate_builder: Any = Field(exclude=True)

    def _insufficient(self, reason: str) -> ToolResult:
        result = CandidateBuildResult(
            status=CandidateBuildStatus.INSUFFICIENT_EVIDENCE,
            reason=reason,
        )
        return self.success_response(result.model_dump(mode="json"))

    async def execute(
        self,
        *,
        research_topic: str,
        domain: str,
        category: str,
        evidence_ids: list[str],
    ) -> ToolResult:
        if (
            research_topic != self.profile.research_topic
            or domain != self.profile.domain
            or category != self.profile.knowledge_category
        ):
            return self.fail_response("PROFILE_MISMATCH: tool inputs must match ResearchProfile")

        unique_ids = sorted(set(evidence_ids))
        if len(unique_ids) > self.profile.max_sources:
            return self.fail_response("MAX_SOURCES_EXCEEDED: evidence_ids exceed profile max_sources")

        evidence_list = []
        missing_ids = []
        for evidence_id in unique_ids:
            evidence = self.evidence_store.get(evidence_id)
            if evidence is None:
                missing_ids.append(evidence_id)
            else:
                evidence_list.append(evidence)

        minimum = self.profile.output_requirements.minimum_evidence_count
        if missing_ids:
            return self._insufficient(f"EvidenceStore does not contain: {', '.join(missing_ids)}")
        if len(evidence_list) < minimum:
            return self._insufficient(
                f"profile requires at least {minimum} Evidence records; received {len(evidence_list)}"
            )
        if any(evidence.local_file is None for evidence in evidence_list):
            return self._insufficient("every Evidence record must reference an original local_file")

        result = self.candidate_builder.build(
            profile=self.profile,
            evidence_list=evidence_list,
        )
        if not isinstance(result, CandidateBuildResult):
            return self.fail_response("INVALID_BUILDER_RESULT")
        return self.success_response(result.model_dump(mode="json"))
