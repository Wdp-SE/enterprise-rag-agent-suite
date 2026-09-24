# Retrieval policy decision

Corpus: pinned Apache DolphinScheduler 3.4.2 / 3.4.3; 46 queries; Top-5.
The benchmark uses the same corpus, query set, version scope and language scope for all evaluated policies.
Ground truth is manually curated and verified by exact source markers. This is a small selected-corpus benchmark, not a claim about all DolphinScheduler material.

| Policy | Hit@1 | Hit@3 | Hit@5 | MRR | nDCG@5 | P50 ms | P95 ms |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| dense | 0.2093 | 0.3721 | 0.4186 | 0.2934 | 0.3254 | 1.34 | 3.69 |
| bm25 | 0.3953 | 0.6977 | 0.7907 | 0.5558 | 0.6209 | 1.33 | 2.53 |
| hybrid | 0.3023 | 0.5814 | 0.6047 | 0.4322 | 0.4874 | 1.82 | 3.32 |
| dense_rerank | NOT EVALUATED | — | — | — | — | — | — |
| hybrid_rerank | NOT EVALUATED | — | — | — | — | — | — |

Selected default: **bm25**. Selection rule: highest Hit@1, then MRR, then Hit@5; lower P95 resolves a quality tie.
No conditional router: cross-document and hard-query groups are small, and no alternate strategy improves both recall and latency consistently enough to justify routing.
Hybrid remains experimental. Rerank was **NOT EVALUATED**: a reproducible multilingual reranker was not available within the lightweight public deployment constraints.

The Dense baseline is a 512-dimensional deterministic character-ngram hash and cosine ranking. It is a compact lexical dense baseline, **not** a neural semantic embedding model.
BM25 uses local Unicode Han bigrams and English technical tokens (k1=1.2, b=0.75). Hybrid uses RRF (k=60).
Each request ranked all eligible chunks and returned 5 candidates. Retrieval alone returned candidates for all three intentionally unanswerable queries; the UI must never present those candidates as a proven answer.
P50/P95 are local in-process retrieval timings and exclude network and generation.

## Selected policy by query group

| Group | Queries | Hit@1 | Hit@5 | MRR |
| --- | ---: | ---: | ---: | ---: |
| cross_document | 4 | 0.0 | 0.25 | 0.125 |
| en | 7 | 0.4286 | 0.8571 | 0.6071 |
| exact | 6 | 0.8333 | 1.0 | 0.9167 |
| hard | 5 | 0.2 | 0.4 | 0.24 |
| mixed | 6 | 0.1667 | 0.8333 | 0.4722 |
| no_answer | 3 | N/A | N/A | N/A |
| version | 5 | 0.4 | 0.8 | 0.54 |
| zh | 10 | 0.5 | 1.0 | 0.6917 |

Full per-query rankings and all policy/group metrics: [benchmark_results.json](results/benchmark_results.json).
