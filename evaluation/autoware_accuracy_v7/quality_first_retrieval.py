"""Quality-first retrieval primitives for the isolated Autoware V7 benchmark."""

from __future__ import annotations

from collections import defaultdict
from typing import Sequence
import unicodedata

import numpy as np


def dense_rank(
    query_vector: np.ndarray,
    hits: Sequence[dict],
    vectors: np.ndarray,
    *,
    version: str,
    language: str,
    top_k: int,
) -> list[dict]:
    """Rank normalized dense vectors only after applying exact metadata scope."""
    query = np.asarray(query_vector, dtype=np.float32)
    matrix = np.asarray(vectors, dtype=np.float32)
    if matrix.ndim != 2 or matrix.shape[0] != len(hits):
        raise ValueError("vector rows must match the candidate metadata rows")
    if query.ndim != 1 or matrix.shape[1] != query.shape[0]:
        raise ValueError("query and passage vector dimensions must match")
    if not np.isfinite(query).all() or not np.isfinite(matrix).all():
        raise ValueError("vectors must be finite")
    if not np.isclose(np.linalg.norm(query), 1.0, atol=1e-4):
        raise ValueError("query vector must be normalized")
    if len(matrix) and not np.allclose(np.linalg.norm(matrix, axis=1), 1.0, atol=1e-4):
        raise ValueError("passage vectors must be normalized")
    if not isinstance(top_k, int) or isinstance(top_k, bool) or top_k < 1:
        raise ValueError("top_k must be a positive integer")

    scoped = [
        i for i, row in enumerate(hits)
        if str(row.get("version", "")) == version
        and (language == "all" or str(row.get("language", "")) == language)
    ]
    if not scoped:
        return []
    scores = matrix[scoped] @ query
    ordered = sorted(
        zip(scoped, scores.tolist()),
        key=lambda item: (-float(item[1]), str(hits[item[0]].get("chunk_id", ""))),
    )[:top_k]
    return [
        {
            **hits[index],
            "rank": rank,
            "dense_score": float(score),
            "retrieval_score": float(score),
            "retrieval_policy": "bge_dense",
            "retrieval_sources": ["semantic"],
        }
        for rank, (index, score) in enumerate(ordered, start=1)
    ]


def reciprocal_rank_fusion(
    rankings: Sequence[Sequence[dict]],
    *,
    top_k: int,
    rrf_k: int = 60,
    source_names: Sequence[str] = ("lexical", "semantic"),
) -> list[dict]:
    """Fuse scoped ranked lists with deterministic RRF and provenance."""
    if len(rankings) != len(source_names) or not rankings:
        raise ValueError("each ranking must have exactly one source name")
    if not isinstance(top_k, int) or isinstance(top_k, bool) or top_k < 1:
        raise ValueError("top_k must be a positive integer")
    if not isinstance(rrf_k, int) or isinstance(rrf_k, bool) or rrf_k < 1:
        raise ValueError("rrf_k must be a positive integer")
    scores: dict[str, float] = defaultdict(float)
    rows: dict[str, dict] = {}
    sources: dict[str, list[str]] = defaultdict(list)
    for name, ranking in zip(source_names, rankings):
        seen_in_list: set[str] = set()
        for rank, row in enumerate(ranking, start=1):
            chunk_id = str(row.get("chunk_id", ""))
            if not chunk_id or chunk_id in seen_in_list:
                continue
            seen_in_list.add(chunk_id)
            rows.setdefault(chunk_id, row)
            scores[chunk_id] += 1.0 / (rrf_k + rank)
            if name not in sources[chunk_id]:
                sources[chunk_id].append(name)
    ordered = sorted(scores, key=lambda chunk_id: (-scores[chunk_id], chunk_id))[:top_k]
    return [
        {
            **rows[chunk_id],
            "rank": rank,
            "rrf_score": scores[chunk_id],
            "retrieval_score": scores[chunk_id],
            "retrieval_policy": "bm25_bge_rrf",
            "retrieval_sources": sources[chunk_id],
        }
        for rank, chunk_id in enumerate(ordered, start=1)
    ]


def retrieval_metrics(cases: Sequence[dict], results: dict[str, Sequence[dict]], *, ks=(5, 10, 20, 50)) -> dict:
    """Score source retrieval independently of answer generation quality."""
    if not cases:
        raise ValueError("cases must not be empty")
    if any(not isinstance(k, int) or isinstance(k, bool) or k < 1 for k in ks):
        raise ValueError("all evaluation cutoffs must be positive integers")
    required_total = 0
    wrong_version_case_count = 0
    totals = {
        k: {"hit": 0, "complete_cases": 0}
        for k in ks
    }
    reciprocal_rank_sum = {k: 0.0 for k in ks}
    for case in cases:
        case_id = str(case["case_id"])
        required = set(str(value) for value in case.get("required_sources", []))
        hits = list(results.get(case_id, []))
        required_total += len(required)
        if any(str(row.get("version", "")) != str(case.get("version", "")) for row in hits):
            wrong_version_case_count += 1
        for k in ks:
            found = {
                str(row.get("document_id", ""))
                for row in hits[:k]
                if str(row.get("version", "")) == str(case.get("version", ""))
            }
            totals[k]["hit"] += len(required.intersection(found))
            if required and required.issubset(found):
                totals[k]["complete_cases"] += 1
            if required:
                first_relevant = next(
                    (
                        position
                        for position, row in enumerate(hits[:k], start=1)
                        if str(row.get("document_id", "")) in required
                        and str(row.get("version", "")) == str(case.get("version", ""))
                    ),
                    None,
                )
                if first_relevant:
                    reciprocal_rank_sum[k] += 1.0 / first_relevant
    answerable_count = sum(bool(case.get("required_sources")) for case in cases)
    output = {
        "case_count": len(cases),
        "answerable_count": answerable_count,
        "required_source_count": required_total,
        "wrong_version_count": wrong_version_case_count,
    }
    for k in ks:
        output[f"required_source_recall_at_{k}"] = (
            totals[k]["hit"] / required_total if required_total else None
        )
        output[f"complete_required_sources_at_{k}"] = (
            totals[k]["complete_cases"] / answerable_count if answerable_count else None
        )
        output[f"mrr_at_{k}"] = (
            reciprocal_rank_sum[k] / answerable_count if answerable_count else None
        )
    return output


def _normalized_text(value: str) -> str:
    normalized = unicodedata.normalize("NFKC", value).casefold()
    return "".join(character for character in normalized if character.isalnum())


def validate_case_set(
    cases: Sequence[dict],
    *,
    known_sources: set[str],
    old_queries: set[str],
    old_sources: set[str],
) -> dict:
    """Validate scope, labels, split separation, and reuse against prior evals."""
    if not cases:
        raise ValueError("cases cannot be empty")
    ids: set[str] = set()
    queries: set[str] = set()
    family_splits: dict[str, set[str]] = defaultdict(set)
    source_splits: dict[str, set[str]] = defaultdict(set)
    normalized_old_queries = {_normalized_text(query) for query in old_queries if query}
    reused_sources: set[str] = set()
    split_counts = {"dev": 0, "holdout": 0}
    answerable_counts = {"dev": 0, "holdout": 0}
    for case in cases:
        required_fields = {
            "case_id", "split", "family_id", "query", "version", "language",
            "required_sources", "answerable",
        }
        if not isinstance(case, dict) or not required_fields.issubset(case):
            raise ValueError("case missing required fields")
        case_id = case["case_id"]
        if not isinstance(case_id, str) or not case_id or case_id in ids:
            raise ValueError(f"duplicate or empty case ID: {case_id!r}")
        ids.add(case_id)
        split = case["split"]
        if split not in split_counts:
            raise ValueError(f"unsupported split for {case_id}")
        split_counts[split] += 1
        family = case["family_id"]
        if not isinstance(family, str) or not family.strip():
            raise ValueError(f"invalid family ID for {case_id}")
        family_splits[family].add(split)
        if len(family_splits[family]) > 1:
            raise ValueError(f"family split leakage: {family}")
        if case["version"] != "docs-main" or case["language"] != "zh":
            raise ValueError(f"evaluation scope must be Chinese docs-main: {case_id}")
        normalized_query = _normalized_text(str(case["query"]))
        if not normalized_query or normalized_query in queries:
            raise ValueError(f"empty or duplicate query: {case_id}")
        if normalized_query in normalized_old_queries:
            raise ValueError(f"query reused from prior evaluation: {case_id}")
        queries.add(normalized_query)
        required = case["required_sources"]
        if not isinstance(required, list) or len(required) != len(set(required)):
            raise ValueError(f"invalid required_sources for {case_id}")
        if bool(required) != bool(case["answerable"]):
            raise ValueError(f"answerable label disagrees with required sources: {case_id}")
        if case["answerable"]:
            answerable_counts[split] += 1
        for source_id in required:
            if not isinstance(source_id, str) or source_id not in known_sources:
                raise ValueError(f"unknown source label for {case_id}: {source_id}")
            if not source_id.startswith("docs-main:zh:"):
                raise ValueError(f"source label outside Chinese docs-main scope: {case_id}")
            source_splits[source_id].add(split)
            if len(source_splits[source_id]) > 1:
                raise ValueError(f"source split leakage: {source_id}")
            if source_id in old_sources:
                reused_sources.add(source_id)
    if reused_sources:
        raise ValueError(f"source reused from prior evaluation: {sorted(reused_sources)}")
    return {
        "case_count": len(cases),
        "split_counts": split_counts,
        "answerable_counts": answerable_counts,
        "source_count": len(source_splits),
        "source_reuse_from_prior_evals": 0,
        "query_reuse_from_prior_evals": 0,
    }
