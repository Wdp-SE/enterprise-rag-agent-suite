"""Select the deployed retrieval policy from measured results, not a preset winner."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parent
CORPUS = ROOT.parents[1] / "versioned-rag-service" / "public_corpus"


def select() -> dict:
    benchmark = json.loads((ROOT / "results" / "benchmark_results.json").read_text(encoding="utf-8"))
    scores = benchmark["results"]
    evaluated = {
        name: scores[name]["overall"]
        for name in ("dense", "bm25", "hybrid")
        if "overall" in scores[name] and scores[name]["overall"]["failures"] == 0
    }
    if not evaluated:
        raise ValueError("no successfully evaluated retrieval policy")
    # Prioritize users seeing the correct top result, then MRR and Hit@5.
    # The smallest measured p95 breaks a genuine quality tie.
    winner = max(
        evaluated,
        key=lambda name: (
            evaluated[name]["hit_at_1"],
            evaluated[name]["mrr"],
            evaluated[name]["hit_at_5"],
            -evaluated[name]["p95_ms"],
        ),
    )
    policy = {
        "default_policy": winner,
        "benchmark_query_count": benchmark["query_count"],
        "benchmark_corpus_sha256": benchmark["corpus_sha256"],
        "index_artifacts_sha256": {
            name: hashlib.sha256((CORPUS / name).read_bytes()).hexdigest()
            for name in ("chunks.json", "dense_vectors.npy")
        },
        "quality_rule": "highest Hit@1, then MRR, then Hit@5; lower P95 resolves a quality tie",
        "conditional_router_enabled": False,
        "reranker_enabled": False,
        "reason": "Winner has the strongest measured overall top-result quality; group samples do not support a stable router.",
    }
    (CORPUS / "retrieval_policy.json").write_text(
        json.dumps(policy, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    rows = []
    for name in ("dense", "bm25", "hybrid"):
        row = scores[name]["overall"]
        rows.append(
            f"| {name} | {row['hit_at_1']:.4f} | {row['hit_at_3']:.4f} | "
            f"{row['hit_at_5']:.4f} | {row['mrr']:.4f} | {row['ndcg_at_5']:.4f} | "
            f"{row['p50_ms']:.2f} | {row['p95_ms']:.2f} |"
        )
    for name in ("dense_rerank", "hybrid_rerank"):
        rows.append(f"| {name} | NOT EVALUATED | — | — | — | — | — | — |")
    groups = []
    for category in scores[winner]["by_category"]:
        values = scores[winner]["by_category"][category]
        groups.append(
            f"| {category} | {values['queries']} | "
            f"{values['hit_at_1'] if values['hit_at_1'] is not None else 'N/A'} | "
            f"{values['hit_at_5'] if values['hit_at_5'] is not None else 'N/A'} | "
            f"{values['mrr'] if values['mrr'] is not None else 'N/A'} |"
        )
    text = f"""# Retrieval policy decision

Corpus: pinned Apache DolphinScheduler 3.4.2 / 3.4.3; {benchmark['query_count']} queries (43 answerable and 3 no-answer probes); Top-{benchmark['top_k']}.
Hit@K, MRR and nDCG use the answerable queries as their denominator. The policy-selection set is also the reported set; there is no held-out user-query validation.
The benchmark uses the same corpus, query set, version scope and language scope for all evaluated policies.
Ground truth is manually curated and verified by exact source markers. This is a small selected-corpus benchmark, not a claim about all DolphinScheduler material.

| Policy | Hit@1 | Hit@3 | Hit@5 | MRR | nDCG@5 | P50 ms | P95 ms |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
{chr(10).join(rows)}

Selected default: **{winner}**. Selection rule: {policy['quality_rule']}.
No conditional router: cross-document and hard-query groups are small, and no alternate strategy improves both recall and latency consistently enough to justify routing.
For cross-document questions, Hit@5 means *either* cited source appears. The selected policy found both required sources in Top-5 for {scores[winner]['by_category']['cross_document']['cross_document_both_source_at_5']:.0%} of the four questions; do not treat any-source Hit@5 as complete multi-source recall.
Hybrid remains experimental. Rerank was **NOT EVALUATED**: a reproducible multilingual reranker was not available within the lightweight public deployment constraints.

The Dense baseline is a 512-dimensional deterministic character-ngram hash and cosine ranking. It is a compact lexical dense baseline, **not** a neural semantic embedding model.
BM25 uses local Unicode Han bigrams and English technical tokens (k1=1.2, b=0.75). Hybrid uses RRF (k=60).
Each request ranked all eligible chunks and returned 5 candidates. Retrieval alone returned candidates for all three intentionally unanswerable queries; the UI must never present those candidates as a proven answer.
P50/P95 are local in-process retrieval timings and exclude network and generation.

## Selected policy by query group

| Group | Queries | Hit@1 | Hit@5 | MRR |
| --- | ---: | ---: | ---: | ---: |
{chr(10).join(groups)}

Full per-query rankings and all policy/group metrics: [benchmark_results.json](results/benchmark_results.json).
"""
    (ROOT / "retrieval_policy_report.md").write_text(text, encoding="utf-8")
    print(json.dumps(policy, indent=2))
    return policy


if __name__ == "__main__":
    select()
