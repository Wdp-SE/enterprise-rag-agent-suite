"""Retrieval-only scoring for the frozen public-corpus selection experiment.

An evidence label names both a source section and a literal marker. A ranked
chunk must contain that marker; another chunk under the same heading is not a
relevant hit. These metrics do not evaluate generated answers.
"""

from __future__ import annotations

import math
import statistics
from collections import defaultdict


TOP_K = 5
NOT_EVALUATED = "NOT_EVALUATED"


def _relevant_source_index(hit: dict, truth: dict) -> int | None:
    text = f"{hit['heading']} {hit['content']}".casefold()
    for index, source in enumerate(truth["relevant"]):
        if (
            hit["document_key"] == source["document_key"]
            and hit["version"] == source["version"]
            and hit["locale"] == source["locale"]
            and hit["heading"] == source["heading"]
            and source["evidence_marker"]
            and source["evidence_marker"].casefold() in text
        ):
            return index
    return None


def score_hits(query: dict, truth: dict, hits: list[dict], latency_ms: float) -> dict:
    """Score one ranked result list against the frozen section and marker labels."""
    if query["id"] != truth["id"]:
        raise ValueError("query and ground-truth IDs differ")
    source_indices = [_relevant_source_index(hit, truth) for hit in hits]
    answerable = bool(truth["answerable_in_corpus"])
    return {
        "id": query["id"],
        "category": query["category"],
        "query": query["query"],
        "answerable": answerable,
        "relevant_count": len(truth["relevant"]),
        "relevance": [int(index is not None) for index in source_indices],
        "relevant_source_indices": source_indices,
        "ranked_chunk_ids": [hit["chunk_id"] for hit in hits],
        "ranked_document_ids": [hit["document_id"] for hit in hits],
        "candidates": len(hits),
        "latency_ms": round(float(latency_ms), 3),
        "rejection": int(not hits) if not answerable else None,
        "false_answer_count": NOT_EVALUATED,
        "error": None,
    }


def _percentile(values: list[float], proportion: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    position = (len(ordered) - 1) * proportion
    lower = int(position)
    upper = min(lower + 1, len(ordered) - 1)
    return round(ordered[lower] + (ordered[upper] - ordered[lower]) * (position - lower), 2)


def summarize(rows: list[dict]) -> dict:
    """Aggregate ranking quality and latency without treating candidates as answers."""
    answerable = [row for row in rows if row["answerable"]]
    no_answer = [row for row in rows if not row["answerable"]]
    cross_document = [
        row for row in answerable
        if row["category"] == "cross_document" and row["relevant_count"] == 2
    ]
    n = len(answerable)

    def hit_at(k: int) -> float | None:
        return round(sum(any(row["relevance"][:k]) for row in answerable) / n, 4) if n else None

    mrr = None
    ndcg = None
    if n:
        mrr = round(sum(
            next((1 / rank for rank, index in enumerate(row["relevant_source_indices"], 1) if index is not None), 0)
            for row in answerable
        ) / n, 4)
        normalized_gains = []
        for row in answerable:
            seen = set()
            actual = 0.0
            for rank, index in enumerate(row["relevant_source_indices"][:TOP_K], 1):
                if index is not None and index not in seen:
                    actual += 1 / math.log2(rank + 1)
                    seen.add(index)
            ideal = sum(
                1 / math.log2(rank + 1)
                for rank in range(1, min(row["relevant_count"], TOP_K) + 1)
            )
            normalized_gains.append(actual / ideal if ideal else 0.0)
        ndcg = round(statistics.mean(normalized_gains), 4)

    both_source = None
    if cross_document:
        both_source = round(sum(
            {0, 1}.issubset(set(row["relevant_source_indices"][:TOP_K]))
            for row in cross_document
        ) / len(cross_document), 4)

    return {
        "queries": len(rows),
        "answerable": n,
        "hit_at_1": hit_at(1),
        "hit_at_3": hit_at(3),
        "hit_at_5": hit_at(5),
        "mrr": mrr,
        "ndcg_at_5": ndcg,
        "cross_document_both_source_at_5": both_source,
        "p50_ms": _percentile([row["latency_ms"] for row in rows], 0.5),
        "p95_ms": _percentile([row["latency_ms"] for row in rows], 0.95),
        "average_candidates": round(statistics.mean(row["candidates"] for row in rows), 2) if rows else 0.0,
        "failures": sum(bool(row.get("error")) for row in rows),
        "no_answer_queries": len(no_answer),
        "no_answer_candidate_count": sum(row["candidates"] for row in no_answer),
        "no_answer_queries_with_candidates": sum(row["candidates"] > 0 for row in no_answer),
        "no_answer_rejection_count": sum(row["rejection"] for row in no_answer),
        "no_answer_rejection_rate": round(sum(row["rejection"] for row in no_answer) / len(no_answer), 4) if no_answer else None,
        "false_answer_count": NOT_EVALUATED,
    }


def by_category(rows: list[dict]) -> dict[str, dict]:
    """Summarize each frozen query category independently."""
    groups: dict[str, list[dict]] = defaultdict(list)
    for row in rows:
        groups[row["category"]].append(row)
    return {category: summarize(group) for category, group in sorted(groups.items())}
