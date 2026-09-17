"""Resolve document eligibility from explicit manifest version relationships."""

from __future__ import annotations

from collections import defaultdict
from datetime import date
from pathlib import Path
from typing import Iterable, Optional

from src.evaluation.corpus import CorpusManifest, load_corpus_manifest
from src.versioning.models import (
    DatePrecision,
    VersionAction,
    VersionContext,
    VersionDecision,
    VersionIntent,
    VersionMetadata,
    VersionResolutionPlan,
)
from src.versioning.query_intent import VersionIntentDetector


PREFER_ADJUSTMENT = 0.02
DEMOTE_ADJUSTMENT = -0.02


class VersionResolver:
    def __init__(self, manifest: CorpusManifest, *, as_of_date: Optional[date] = None):
        self.manifest = manifest
        self.as_of_date = as_of_date or date.today()
        self.metadata = self._normalize_metadata(manifest)
        self.by_id = {item.document_id: item for item in self.metadata}
        self.detector = VersionIntentDetector(self.metadata)

    @classmethod
    def from_manifest_path(
        cls, path: Path | str, *, as_of_date: Optional[date] = None
    ) -> "VersionResolver":
        return cls(load_corpus_manifest(path), as_of_date=as_of_date)

    @staticmethod
    def _normalize_metadata(manifest: CorpusManifest) -> list[VersionMetadata]:
        supersedes = defaultdict(list)
        superseded_by = defaultdict(list)
        effective_to = {}
        effective_to_source = {}
        for relation in manifest.version_relations:
            supersedes[relation.newer_document_id].append(relation.older_document_id)
            superseded_by[relation.older_document_id].append(relation.newer_document_id)
            if relation.effective_date:
                effective_to[relation.older_document_id] = relation.effective_date
                effective_to_source[relation.older_document_id] = (
                    "derived_from_version_relation:"
                    f"{relation.older_document_id}->{relation.newer_document_id}"
                )

        return [
            VersionMetadata(
                document_id=document.document_id,
                title=document.title,
                document_number=document.document_number,
                version_family=document.version_family,
                version=document.version,
                status=document.status,
                publish_date=document.publish_date,
                effective_from=document.effective_date,
                effective_to=effective_to.get(document.document_id),
                effective_to_source=effective_to_source.get(document.document_id),
                supersedes=supersedes[document.document_id],
                superseded_by=superseded_by[document.document_id],
            )
            for document in manifest.documents
        ]

    def resolve(
        self,
        question: str,
        *,
        available_document_ids: Iterable[str],
    ) -> VersionResolutionPlan:
        available = set(available_document_ids)
        context = self.detector.detect(question)
        default_ids = set(self.manifest.default_index_document_ids)
        issues = []

        families = defaultdict(list)
        for metadata in self.metadata:
            if metadata.version_family:
                families[metadata.version_family].append(metadata)

        preferred = set()
        eligible = set(default_ids)
        targeted_families = set(context.matched_version_families)

        if context.intent == VersionIntent.EXPLICIT_VERSION:
            eligible.update(context.matched_document_ids)
            preferred.update(context.matched_document_ids)
            for family in targeted_families:
                family_ids = {item.document_id for item in families[family]}
                eligible.difference_update(family_ids - set(context.matched_document_ids))
        elif context.intent == VersionIntent.HISTORICAL:
            historical = {
                item.document_id
                for item in self.metadata
                if item.status == "SUPERSEDED"
                and (
                    not targeted_families
                    or item.version_family in targeted_families
                )
            }
            eligible.update(historical)
            preferred.update(historical)
            for family in targeted_families:
                family_ids = {item.document_id for item in families[family]}
                eligible.difference_update(family_ids - historical)
        elif context.intent == VersionIntent.TEMPORAL_DATE:
            # A bare date is not enough to alter every version family. The
            # family must first be grounded by manifest document/title data.
            for family in targeted_families:
                family_documents = families[family]
                matching = [
                    item
                    for item in family_documents
                    if self._covers_period(item, context)
                ]
                family_ids = {item.document_id for item in family_documents}
                if matching:
                    eligible.difference_update(family_ids)
                    eligible.update(item.document_id for item in matching)
                    preferred.update(item.document_id for item in matching)
                    if (
                        context.date_precision == DatePrecision.YEAR
                        and len(matching) > 1
                    ):
                        context.temporal_ambiguity = True
                        issues.append("TEMPORAL_YEAR_CROSSES_VERSION_BOUNDARY")
                else:
                    issues.append(f"TEMPORAL_FILTER_MISS:{family}")
        else:
            # Default/current retrieval uses only default-index documents. When a
            # family is named, mark its current member as preferred without
            # globally boosting every ACTIVE document.
            if context.intent == VersionIntent.CURRENT:
                for family in targeted_families:
                    for item in families[family]:
                        if item.is_current(self.as_of_date):
                            preferred.add(item.document_id)

        decisions = []
        for item in self.metadata:
            missing = item.status is None or (
                item.version_family is not None
                and (item.version is None or item.effective_from is None)
            )
            if missing:
                issues.append(f"VERSION_METADATA_MISSING:{item.document_id}")

            if item.document_id not in eligible:
                action = VersionAction.EXCLUDE
                adjustment = 0.0
                reason = "not eligible for resolved version intent"
            elif item.document_id in preferred:
                action = VersionAction.PREFER
                adjustment = PREFER_ADJUSTMENT
                reason = "matches explicit or temporal version intent"
            else:
                action = VersionAction.ALLOW
                adjustment = 0.0
                reason = "eligible without a version-specific rank preference"
            decisions.append(
                VersionDecision(
                    document_id=item.document_id,
                    document_status=item.status,
                    version_family=item.version_family,
                    version=item.version,
                    action=action,
                    adjustment=adjustment,
                    reason=reason,
                    index_available=item.document_id in available,
                )
            )

        unavailable = sorted(eligible - available)
        issues.extend(f"INDEX_ASSET_MISSING:{document_id}" for document_id in unavailable)
        eligible.intersection_update(available)
        return VersionResolutionPlan(
            context=context,
            as_of_date=self.as_of_date,
            eligible_document_ids=sorted(eligible),
            decisions=decisions,
            issues=list(dict.fromkeys(issues)),
        )

    @staticmethod
    def _covers_period(metadata: VersionMetadata, context: VersionContext) -> bool:
        start = context.query_period_start
        end = context.query_period_end
        if start is None or end is None or metadata.effective_from is None:
            return False
        version_start = metadata.effective_from
        version_end = metadata.effective_to
        # A query period matches every version active during at least part of
        # that period. This deliberately makes a boundary-crossing year
        # ambiguous instead of choosing Jan 1 or Dec 31 arbitrarily.
        return version_start <= end and (version_end is None or version_end > start)
