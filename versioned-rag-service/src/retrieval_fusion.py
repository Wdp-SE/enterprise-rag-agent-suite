"""Bounded explicit-query facet splitting and reciprocal-rank fusion."""

from __future__ import annotations

import re
from collections import defaultdict


_FACET_SEPARATORS = re.compile(r"[;；\n]+")
_LIST_PREFIX = re.compile(r"^\s*(?:[-*•]|\d+[.)、])\s*")


def split_query_facets(query: str, max_facets: int = 4) -> list[str]:
    """Split explicit clauses only; ordinary single-fact queries stay intact."""
    if not isinstance(query, str) or not query.strip():
        raise ValueError("query must be non-empty")
    if len(query) > 4000:
        raise ValueError("query exceeds 4000 characters")
    if not isinstance(max_facets, int) or max_facets < 1:
        raise ValueError("max_facets must be a positive integer")
    raw_parts = _FACET_SEPARATORS.split(query)
    parts = []
    for raw in raw_parts:
        part = _LIST_PREFIX.sub("", raw).strip()
        if part:
            parts.append(part)
    if len(parts) <= 1:
        return [query]
    if len(parts) > max_facets:
        parts = parts[:max_facets - 1] + ["；".join(parts[max_facets - 1:])]
    return parts


def fuse_ranked_hits(
    rankings: list[list[dict]], *, top_k: int = 20, rrf_k: int = 60,
) -> list[dict]:
    """Fuse facet rankings, preserving source rows and adding an auditable trace."""
    if not isinstance(top_k, int) or top_k < 1:
        raise ValueError("top_k must be positive")
    if not isinstance(rrf_k, int) or rrf_k < 1:
        raise ValueError("rrf_k must be positive")
    if not rankings:
        return []
    if len(rankings) == 1:
        return list(rankings[0][:top_k])

    hits: dict[str, dict] = {}
    scores: dict[str, float] = defaultdict(float)
    traces: dict[str, dict[int, dict]] = defaultdict(dict)
    for facet_id, ranking in enumerate(rankings):
        for rank, hit in enumerate(ranking, 1):
            chunk_id = hit.get("chunk_id")
            if not isinstance(chunk_id, str) or not chunk_id:
                continue
            hits.setdefault(chunk_id, dict(hit))
            scores[chunk_id] += 1.0 / (rrf_k + rank)
            traces[chunk_id].setdefault(facet_id, {
                "rank": rank,
                "retrieval_score": hit.get("retrieval_score"),
            })
    ordered = sorted(hits, key=lambda chunk_id: (-scores[chunk_id], chunk_id))
    result = []
    for chunk_id in ordered[:top_k]:
        row = dict(hits[chunk_id])
        row["rrf_score"] = scores[chunk_id]
        row["retrieved_by"] = sorted(traces[chunk_id])
        row["facet_trace"] = [
            {"facet_id": facet_id, **traces[chunk_id][facet_id]}
            for facet_id in sorted(traces[chunk_id])
        ]
        result.append(row)
    return result
