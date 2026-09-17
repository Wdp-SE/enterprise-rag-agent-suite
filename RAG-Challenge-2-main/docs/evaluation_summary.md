# R&D V2 Evaluation Summary

## Evaluation boundary

The retrieval dataset and final policy were frozen before the single formal
HOLDOUT run. Engineering hardening did not modify Ground Truth, sections,
chunks, the embedding model, representation, or retrieval parameters, and did
not rerun HOLDOUT.

## Final frozen retrieval

The 20-question answerable HOLDOUT result for Dense-only `SECTION_PATH` is:

| Metric | Result |
| --- | ---: |
| Hit@1 | 0.200 |
| Hit@3 | 0.350 |
| Hit@5 | 0.400 |
| Hit@10 | 0.400 |
| Hit@20 | 0.400 |
| Recall@20 | 0.375 |
| MRR@20 | 0.2625 |

These are retrieval metrics, not answer accuracy. The result demonstrates a
working frozen evaluation protocol and also shows that retrieval quality on
real long R&D documents remains limited.

Exact-term and field questions were the clearest weaknesses in HOLDOUT. The
small per-category sample sizes, especially for interface, dependency, and
cross-section questions, do not support broad category-level claims.

## Alternative paths

BM25 and hybrid exploration ended without a stable verified benefit. The final
policy is therefore Dense-only. Reranker validation was constraint-blocked: the
existing paths required online services and no local frozen reranker artifact
was available, so reranking was not enabled merely to preserve a larger stack.

## Structure stress

The diagnostic-only structure stress set was excluded from formal HOLDOUT
metrics. FALLBACK achieved Hit@20 = 1.0 across four cases. PDF_HEURISTIC achieved
Hit@20 = 0 across two candidate cases. Because that set is small and was still
candidate/pending review, it records a compatibility limitation rather than a
reason to reopen the frozen Section Parser.

## Engineering validation

The hardened runtime separately verifies artifact integrity, count/dimension
alignment, lifecycle states, local query embedding, FAISS loading, no-rebuild
query behavior, citation compatibility, fail-closed handling, checkpoint
resume, and the minimal API. This validation is not a new retrieval experiment
and does not change the frozen metrics above.

