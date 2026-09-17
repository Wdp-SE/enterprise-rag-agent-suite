"""Pure signal collection for Trusted QA observation."""

from __future__ import annotations

import math
import statistics
from collections import Counter, defaultdict
from typing import Mapping, Optional, Sequence

from src.trusted_qa.models import (
    PageIdentity,
    RetrievalSignalSnapshot,
    VersionResolutionStatus,
)
from src.versioning.models import VersionResolutionPlan


_VERSION_FAILURE_PREFIXES = (
    "DATASET_SOURCE_MISSING:",
    "INDEX_ASSET_MISSING:",
    "TEMPORAL_FILTER_MISS:",
)


def _version_status(
    enabled: bool, plan: Optional[VersionResolutionPlan]
) -> VersionResolutionStatus:
    if not enabled:
        return VersionResolutionStatus.DISABLED
    if plan is None:
        return VersionResolutionStatus.FAILED
    if plan.context.temporal_ambiguity:
        return VersionResolutionStatus.AMBIGUOUS
    if any(
        issue.startswith(_VERSION_FAILURE_PREFIXES) for issue in plan.issues
    ):
        return VersionResolutionStatus.FAILED
    if plan.issues:
        return VersionResolutionStatus.RESOLVED_WITH_ISSUES
    return VersionResolutionStatus.RESOLVED


def _adjacent_page_pairs(page_ids: Sequence[PageIdentity]) -> int:
    pages_by_document: dict[str, list[int]] = defaultdict(list)
    for page_id in page_ids:
        pages_by_document[page_id.document_id].append(page_id.page_number)
    pairs = 0
    for pages in pages_by_document.values():
        ordered = sorted(set(pages))
        pairs += sum(right - left == 1 for left, right in zip(ordered, ordered[1:]))
    return pairs


def collect_retrieval_signals(
    *,
    question_id: str,
    retrieval_results: Sequence[Mapping[str, object]],
    version_governance_enabled: bool = False,
    version_plan: Optional[VersionResolutionPlan] = None,
) -> RetrievalSignalSnapshot:
    """Collect factual retrieval signals without making a quality decision."""

    results = list(retrieval_results or [])
    state_issues: list[str] = []
    scores: list[float] = []
    rerank_scores: list[float] = []
    document_ids: list[str] = []
    seen_documents: set[str] = set()
    page_ids: list[PageIdentity] = []
    seen_pages: set[tuple[str, int]] = set()

    for index, result in enumerate(results):
        document_id = result.get("document_id")
        if not isinstance(document_id, str) or not document_id.strip():
            state_issues.append(f"RESULT_{index}_MISSING_DOCUMENT_ID")
            document_id = ""
        elif document_id not in seen_documents:
            seen_documents.add(document_id)
            document_ids.append(document_id)

        raw_page = result.get("page", result.get("page_number"))
        if not isinstance(raw_page, int) or isinstance(raw_page, bool) or raw_page < 1:
            state_issues.append(f"RESULT_{index}_INVALID_PAGE")
        elif document_id:
            page_key = (document_id, raw_page)
            if page_key not in seen_pages:
                seen_pages.add(page_key)
                page_ids.append(
                    PageIdentity(document_id=document_id, page_number=raw_page)
                )

        raw_score = result.get("distance")
        if not isinstance(raw_score, (int, float)) or isinstance(raw_score, bool):
            state_issues.append(f"RESULT_{index}_MISSING_SCORE")
        else:
            score = float(raw_score)
            if not math.isfinite(score) or not -1.0001 <= score <= 1.0001:
                state_issues.append(f"RESULT_{index}_INVALID_SCORE")
            scores.append(score)

        raw_rerank = result.get("relevance_score")
        if raw_rerank is not None:
            if not isinstance(raw_rerank, (int, float)) or isinstance(raw_rerank, bool):
                state_issues.append(f"RESULT_{index}_INVALID_RERANK_SCORE")
            elif math.isfinite(float(raw_rerank)):
                rerank_scores.append(float(raw_rerank))
            else:
                state_issues.append(f"RESULT_{index}_INVALID_RERANK_SCORE")

    document_counts = Counter(
        result.get("document_id")
        for result in results
        if isinstance(result.get("document_id"), str)
        and result.get("document_id")
    )
    dominant_document_ratio = (
        max(document_counts.values()) / len(results)
        if results and document_counts
        else None
    )
    top3 = results[:3]
    top3_counts = Counter(
        result.get("document_id")
        for result in top3
        if isinstance(result.get("document_id"), str)
        and result.get("document_id")
    )
    top3_concentration = (
        max(top3_counts.values()) / len(top3)
        if top3 and top3_counts
        else None
    )

    version_status = _version_status(version_governance_enabled, version_plan)
    version_issues = list(version_plan.issues) if version_plan is not None else []
    eligible_count = (
        len(version_plan.eligible_document_ids) if version_plan is not None else None
    )

    return RetrievalSignalSnapshot(
        question_id=question_id,
        retrieved_count=len(results),
        top1_score=round(scores[0], 6) if scores else None,
        top2_score=round(scores[1], 6) if len(scores) >= 2 else None,
        top3_score=round(scores[2], 6) if len(scores) >= 3 else None,
        top5_scores=[round(score, 6) for score in scores[:5]],
        top1_top2_margin=(
            round(scores[0] - scores[1], 6) if len(scores) >= 2 else None
        ),
        top3_mean=(round(statistics.mean(scores[:3]), 6) if scores else None),
        top5_mean=(round(statistics.mean(scores[:5]), 6) if scores else None),
        retrieved_document_count=len(document_ids),
        retrieved_page_count=len(page_ids),
        document_ids=document_ids,
        page_ids=page_ids,
        dominant_document_ratio=(
            round(dominant_document_ratio, 6)
            if dominant_document_ratio is not None
            else None
        ),
        top3_document_concentration=(
            round(top3_concentration, 6)
            if top3_concentration is not None
            else None
        ),
        adjacent_page_pair_count=_adjacent_page_pairs(page_ids),
        version_governance_enabled=version_governance_enabled,
        version_intent=(
            version_plan.context.intent.value if version_plan is not None else None
        ),
        version_resolution_status=version_status,
        version_ambiguity=(
            bool(version_plan.context.temporal_ambiguity)
            if version_plan is not None
            else False
        ),
        eligible_document_count=eligible_count,
        version_resolution_issues=version_issues,
        citation_candidates_available=bool(page_ids),
        citation_candidate_count=len(page_ids),
        rerank_available=bool(rerank_scores),
        rerank_score=(round(rerank_scores[0], 6) if rerank_scores else None),
        rerank_scores=[round(score, 6) for score in rerank_scores[:5]],
        rerank_margin=(
            round(rerank_scores[0] - rerank_scores[1], 6)
            if len(rerank_scores) >= 2
            else None
        ),
        retrieval_state_valid=not state_issues,
        retrieval_state_issues=state_issues,
    )

