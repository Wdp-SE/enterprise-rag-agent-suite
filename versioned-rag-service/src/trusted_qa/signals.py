"""Dense-only retrieval signal collection for Trusted QA."""

from __future__ import annotations

import math
import statistics
from collections import Counter, defaultdict
from typing import Mapping, Sequence

from src.trusted_qa.models import (
    PageIdentity,
    RetrievalSignalSnapshot,
    VersionResolutionStatus,
)


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
    version_governance_enabled: bool = True,
    version_resolution_status: VersionResolutionStatus = VersionResolutionStatus.RESOLVED,
    eligible_document_count: int | None = None,
    version_intent: str | None = None,
    version_ambiguity: bool = False,
    version_resolution_issues: Sequence[str] = (),
) -> RetrievalSignalSnapshot:
    """Collect observable dense-retrieval facts without making a verdict."""

    results = list(retrieval_results or [])
    state_issues: list[str] = []
    scores: list[float] = []
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

        raw_page = result.get("page_number", result.get("page"))
        if not isinstance(raw_page, int) or isinstance(raw_page, bool) or raw_page < 1:
            state_issues.append(f"RESULT_{index}_INVALID_PAGE")
        elif document_id and (document_id, raw_page) not in seen_pages:
            seen_pages.add((document_id, raw_page))
            page_ids.append(
                PageIdentity(document_id=document_id, page_number=raw_page)
            )

        raw_score = result.get("dense_score", result.get("distance"))
        if not isinstance(raw_score, (int, float)) or isinstance(raw_score, bool):
            state_issues.append(f"RESULT_{index}_MISSING_SCORE")
        else:
            score = float(raw_score)
            if not math.isfinite(score) or not -1.0001 <= score <= 1.0001:
                state_issues.append(f"RESULT_{index}_INVALID_SCORE")
            scores.append(score)

    counts = Counter(
        item.get("document_id")
        for item in results
        if isinstance(item.get("document_id"), str) and item.get("document_id")
    )
    top3 = results[:3]
    top3_counts = Counter(
        item.get("document_id")
        for item in top3
        if isinstance(item.get("document_id"), str) and item.get("document_id")
    )
    dominant_ratio = max(counts.values()) / len(results) if results and counts else None
    top3_ratio = (
        max(top3_counts.values()) / len(top3) if top3 and top3_counts else None
    )
    if eligible_document_count is None and version_governance_enabled:
        eligible_document_count = len(document_ids)

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
        top3_mean=round(statistics.mean(scores[:3]), 6) if scores else None,
        top5_mean=round(statistics.mean(scores[:5]), 6) if scores else None,
        retrieved_document_count=len(document_ids),
        retrieved_page_count=len(page_ids),
        document_ids=document_ids,
        page_ids=page_ids,
        dominant_document_ratio=(
            round(dominant_ratio, 6) if dominant_ratio is not None else None
        ),
        top3_document_concentration=(
            round(top3_ratio, 6) if top3_ratio is not None else None
        ),
        adjacent_page_pair_count=_adjacent_page_pairs(page_ids),
        version_governance_enabled=version_governance_enabled,
        version_intent=version_intent,
        version_resolution_status=version_resolution_status,
        version_ambiguity=version_ambiguity,
        eligible_document_count=eligible_document_count,
        version_resolution_issues=list(version_resolution_issues),
        citation_candidates_available=bool(page_ids),
        citation_candidate_count=len(page_ids),
        retrieval_state_valid=not state_issues,
        retrieval_state_issues=state_issues,
    )
