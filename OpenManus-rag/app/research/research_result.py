"""Build a generic ResearchResult from grounded synthesis and source artifacts."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Callable

from app.research.identifiers import SOURCE_LEVEL_ORDER
from app.research.live_models import (
    AcquiredSource,
    ResearchFailure,
    ResearchResult,
    ResearchSource,
    ResearchStatus,
    ResearchSynthesis,
)
from app.research.models import Evidence, ResearchProfile
from app.research.research_synthesis import GroundingValidator


class ResearchResultBuilder:
    def __init__(
        self,
        *,
        grounding_validator: GroundingValidator | None = None,
        clock: Callable[[], datetime] | None = None,
    ):
        self.grounding_validator = grounding_validator or GroundingValidator()
        self.clock = clock or (lambda: datetime.now(timezone.utc))

    @staticmethod
    def _sources(
        acquired_sources: list[AcquiredSource],
        evidence: list[Evidence],
    ) -> list[ResearchSource]:
        evidence_by_file: dict[str, list[str]] = {}
        for item in evidence:
            if item.local_file and item.evidence_id:
                evidence_by_file.setdefault(item.local_file, []).append(item.evidence_id)
        ordered = sorted(
            (source for source in acquired_sources if source.local_file in evidence_by_file),
            key=lambda source: (
                SOURCE_LEVEL_ORDER[source.source_level],
                source.organization.casefold(),
                source.final_url,
                source.raw_file_hash,
            ),
        )
        return [
            ResearchSource(
                source_id=f"S{index:02d}",
                title=source.title,
                organization=source.organization,
                url=source.final_url,
                source_type=source.source_type,
                source_level=source.source_level,
                local_file=source.local_file,
                raw_file_hash=source.raw_file_hash,
                retrieved_at=source.retrieved_at,
                evidence_ids=evidence_by_file[source.local_file],
            )
            for index, source in enumerate(ordered, start=1)
        ]

    def build(
        self,
        *,
        run_id: str,
        profile: ResearchProfile,
        evidence: list[Evidence],
        acquired_sources: list[AcquiredSource],
        synthesis: ResearchSynthesis,
        failures: list[ResearchFailure],
    ) -> ResearchResult:
        minimum = profile.output_requirements.minimum_evidence_count
        limitations = list(synthesis.limitations)
        limitations.extend(f"{failure.code.value}: {failure.message}" for failure in failures)
        if len(evidence) < minimum:
            limitations.append(
                f"INSUFFICIENT_EVIDENCE: requires {minimum}, extracted {len(evidence)}."
            )
            return ResearchResult(
                run_id=run_id,
                profile_id=profile.profile_id,
                research_topic=profile.research_topic,
                status=ResearchStatus.INSUFFICIENT_EVIDENCE,
                summary="",
                evidence_ids=[item.evidence_id for item in evidence if item.evidence_id],
                sources=self._sources(acquired_sources, evidence),
                limitations=limitations,
                unresolved_questions=list(profile.research_questions),
                generated_at=self.clock(),
            )

        grounded = self.grounding_validator.validate(synthesis, evidence)
        return ResearchResult(
            run_id=run_id,
            profile_id=profile.profile_id,
            research_topic=profile.research_topic,
            status=ResearchStatus.PARTIAL if failures else ResearchStatus.COMPLETED,
            summary=grounded.summary,
            key_findings=grounded.key_findings,
            evidence_ids=[item.evidence_id for item in evidence if item.evidence_id],
            sources=self._sources(acquired_sources, evidence),
            limitations=limitations,
            unresolved_questions=grounded.unresolved_questions,
            generated_at=self.clock(),
        )

