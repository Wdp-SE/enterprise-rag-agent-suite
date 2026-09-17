"""Deterministic source classification, ranking, and selection."""

from __future__ import annotations

from pathlib import PurePosixPath
from urllib.parse import unquote, urlsplit

from app.research.identifiers import SOURCE_LEVEL_ORDER
from app.research.live_models import AcquiredSource, ResearchSearchResult, SelectedSource
from app.research.models import ResearchProfile
from app.research.source_policy import SourcePolicy


class SourceSelectionError(ValueError):
    pass


class SourceSelector:
    MAX_SELECTED_SOURCES = 3

    def __init__(self, source_policy: SourcePolicy):
        self.source_policy = source_policy

    @staticmethod
    def _describe(result: ResearchSearchResult) -> tuple[str, str, str | None]:
        parsed = urlsplit(result.url)
        hostname = parsed.hostname or "unknown-public-source"
        suffix = PurePosixPath(unquote(parsed.path)).suffix.casefold()
        source_type = "pdf" if suffix == ".pdf" else "webpage"
        return hostname, source_type, None

    def select(
        self,
        results: list[ResearchSearchResult],
        profile: ResearchProfile,
        *,
        max_sources: int | None = None,
    ) -> list[SelectedSource]:
        requested = max_sources if max_sources is not None else profile.max_sources
        if requested < 1:
            raise SourceSelectionError("max_sources must be positive")
        limit = min(requested, profile.max_sources, self.MAX_SELECTED_SOURCES)
        preferred = {value.casefold() for value in profile.preferred_source_types}

        candidates: list[tuple[SelectedSource, bool]] = []
        seen_urls: set[str] = set()
        for result in results:
            if result.url in seen_urls:
                continue
            seen_urls.add(result.url)
            organization, source_type, organization_type = self._describe(result)
            decision = self.source_policy.classify(
                source_url=result.url,
                organization_type=organization_type,
                source_type=source_type,
            )
            preferred_match = source_type.casefold() in preferred
            reason = decision.reason
            if preferred_match:
                reason = f"{reason} Matches a preferred source type."
            candidates.append(
                (
                    SelectedSource(
                        search_result_id=result.search_result_id,
                        title=result.title,
                        url=result.url,
                        organization=organization,
                        organization_type=organization_type,
                        source_type=source_type,
                        source_level=decision.level,
                        selection_reason=reason,
                        search_engine=result.engine,
                        search_position=result.position,
                    ),
                    preferred_match,
                )
            )

        candidates.sort(
            key=lambda item: (
                SOURCE_LEVEL_ORDER[item[0].source_level],
                not item[1],
                item[0].search_position,
                item[0].url,
            )
        )
        return [candidate for candidate, _ in candidates[:limit]]

    def refine_acquired(self, source: AcquiredSource) -> AcquiredSource:
        """Re-apply the same configured policy after redirects reveal the final URL."""

        hostname = urlsplit(source.final_url).hostname or source.organization
        decision = self.source_policy.classify(
            source_url=source.final_url,
            source_type=source.source_type,
        )
        return AcquiredSource.model_validate(
            {
                **source.model_dump(mode="json"),
                "artifact_id": None,
                "organization": hostname,
                "source_level": decision.level.value,
            }
        )
