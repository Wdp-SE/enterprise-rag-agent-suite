"""Reproducible retrieval-only benchmark over pinned official source evidence."""

from __future__ import annotations

import json
import statistics
import sys
import time
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent
RAG = ROOT.parents[1] / "versioned-rag-service"
sys.path.insert(0, str(RAG))
from src.public_knowledge import PublicKnowledgeIndex  # noqa: E402


POLICIES = ("dense", "bm25", "hybrid")
TOP_K = 5


def read_jsonl(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def relevant_source_index(hit: dict, truth: dict) -> int | None:
    return next((
        index for index, item in enumerate(truth["relevant"])
        if hit["document_key"] == item["document_key"]
        and hit["version"] == item["version"]
        and hit["locale"] == item["locale"]
        and hit["heading"] == item["heading"]
    ), None)


def _measure(rows: list[dict]) -> dict:
    answerable = [row for row in rows if row["answerable"]]
    n = len(answerable)
    rank_lists = [row["relevance"] for row in answerable]
    def hit(k: int) -> float | None:
        return round(sum(any(bits[:k]) for bits in rank_lists) / n, 4) if n else None
    mrr = round(sum(next((1 / rank for rank, bit in enumerate(bits, 1) if bit), 0) for bits in rank_lists) / n, 4) if n else None
    ndcg = []
    for row in answerable:
        actual = sum(bit / __import__("math").log2(i + 2) for i, bit in enumerate(row["relevance"][:5]))
        ideal = sum(1 / __import__("math").log2(i + 2) for i in range(min(row["relevant_count"], 5)))
        ndcg.append(actual / ideal if ideal else 0)
    latencies = sorted(row["latency_ms"] for row in rows)
    def percentile(p: float) -> float:
        if not latencies:
            return 0
        pos = (len(latencies) - 1) * p
        lo = int(pos)
        hi = min(lo + 1, len(latencies) - 1)
        return round(latencies[lo] + (latencies[hi] - latencies[lo]) * (pos - lo), 2)
    no_answer = [row for row in rows if not row["answerable"]]
    cross_document = [
        row for row in answerable
        if row["category"] == "cross_document" and row["relevant_count"] == 2
    ]
    return {
        "queries": len(rows), "answerable": n,
        "hit_at_1": hit(1), "hit_at_3": hit(3), "hit_at_5": hit(5),
        "mrr": mrr, "ndcg_at_5": round(statistics.mean(ndcg), 4) if ndcg else None,
        "p50_ms": percentile(0.5), "p95_ms": percentile(0.95),
        "average_candidates": round(statistics.mean(row["candidates"] for row in rows), 2) if rows else 0,
        "failures": sum(bool(row["error"]) for row in rows),
        "no_answer_queries": len(no_answer),
        "no_answer_false_evidence_rate": round(sum(row["candidates"] > 0 for row in no_answer) / len(no_answer), 4) if no_answer else None,
        "cross_document_both_source_at_5": round(
            sum(
                {0, 1}.issubset(set(row["relevant_source_indices"][:5]))
                for row in cross_document
            ) / len(cross_document), 4
        ) if cross_document else None,
    }


def run() -> dict:
    queries = read_jsonl(ROOT / "queries.jsonl")
    truths = {row["id"]: row for row in read_jsonl(ROOT / "ground_truth.jsonl")}
    index = PublicKnowledgeIndex()
    results: dict[str, dict] = {}
    outdir = ROOT / "results"
    outdir.mkdir(exist_ok=True)
    for policy in POLICIES:
        samples = []
        for query in queries:
            truth = truths[query["id"]]
            start = time.perf_counter()
            error = None
            try:
                hits = index.search(
                    query["query"], top_k=TOP_K, version=query["version_scope"],
                    language="all", policy=policy,
                )
            except Exception as exc:
                hits = []
                error = f"{type(exc).__name__}: {exc}"
            elapsed = (time.perf_counter() - start) * 1000
            relevant_indices = [relevant_source_index(hit, truth) for hit in hits]
            samples.append({
                "id": query["id"], "category": query["category"],
                "query": query["query"], "answerable": truth["answerable_in_corpus"],
                "relevant_count": len(truth["relevant"]),
                "relevance": [int(index is not None) for index in relevant_indices],
                "relevant_source_indices": relevant_indices,
                "ranked_chunk_ids": [hit["chunk_id"] for hit in hits],
                "candidates": len(hits), "latency_ms": round(elapsed, 3), "error": error,
            })
        (outdir / f"{policy}.json").write_text(
            json.dumps(samples, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        groups = defaultdict(list)
        for sample in samples:
            groups[sample["category"]].append(sample)
        results[policy] = {
            "overall": _measure(samples),
            "by_category": {category: _measure(rows) for category, rows in sorted(groups.items())},
        }
    results["dense_rerank"] = {"status": "NOT EVALUATED", "reason": "No reproducible multilingual reranker available in free deployment constraints."}
    results["hybrid_rerank"] = {"status": "NOT EVALUATED", "reason": "No reproducible multilingual reranker available in free deployment constraints."}
    report = {
        "corpus_sha256": __import__("hashlib").sha256(
            (index.root / "corpus_manifest.json").read_bytes()
        ).hexdigest(),
        "query_count": len(queries), "top_k": TOP_K,
        "version_filter": "query-specific pinned version", "language_filter": "all",
        "dense": "512-dimensional deterministic Unicode character 1-3 gram hash + cosine; lexical dense baseline, not neural semantic embeddings",
        "bm25": "local BM25, k1=1.2, b=0.75, Unicode Han bigrams + English technical tokens",
        "hybrid": "reciprocal-rank fusion, k=60, top 50 candidates per branch",
        "results": results,
    }
    (outdir / "benchmark_results.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps({name: value["overall"] for name, value in results.items() if "overall" in value}, indent=2))
    return report


if __name__ == "__main__":
    run()
