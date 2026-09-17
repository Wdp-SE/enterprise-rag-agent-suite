"""Injectable boundaries used by Knowledge Research live orchestration."""

from __future__ import annotations

from typing import Protocol

from app.research.evidence_store import EvidenceStore
from app.research.live_models import (
    AcquiredSource,
    OutputArtifact,
    ResearchResult,
    ResearchSearchResult,
    SelectedSource,
    TokenUsage,
)
from app.research.models import Evidence, ResearchProfile


class SearchProvider(Protocol):
    async def search(
        self,
        profile: ResearchProfile,
        *,
        max_candidates: int,
    ) -> list[ResearchSearchResult]: ...


class SourceAcquirer(Protocol):
    async def acquire(self, source: SelectedSource, run_store) -> AcquiredSource: ...


class EvidenceExtractor(Protocol):
    def extract(self, source: AcquiredSource, *, workspace_root) -> list[Evidence]: ...


class SynthesisOutput(Protocol):
    summary: str
    key_findings: list
    limitations: list[str]
    unresolved_questions: list[str]
    token_usage: TokenUsage


class ResearchSynthesizer(Protocol):
    async def synthesize(
        self,
        profile: ResearchProfile,
        evidence: list[Evidence],
    ) -> SynthesisOutput: ...


class OutputAdapter(Protocol):
    name: str

    async def write(
        self,
        *,
        result: ResearchResult,
        evidence_store: EvidenceStore,
        run_store,
        profile: ResearchProfile,
    ) -> OutputArtifact: ...


class CandidateImporter(Protocol):
    def import_candidate(self, package_path: str) -> object: ...

