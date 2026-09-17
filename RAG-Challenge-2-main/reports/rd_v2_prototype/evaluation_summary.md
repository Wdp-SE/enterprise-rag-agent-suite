# R&D Document RAG V2 Prototype Retrieval Evaluation

Corpus: Synthetic public engineering specification; no restricted data

Questions: 13 total, 12 answerable, 1 unanswerable.

Unanswerable items are excluded from Hit/MRR and no cosine rejection threshold is selected.

| Mode | Hit@1 | Hit@3 | Hit@5 | MRR |
|---|---:|---:|---:|---:|
| generic_dense | 0.917 | 0.917 | 1.000 | 0.938 |
| rd_hybrid | 0.833 | 1.000 | 1.000 | 0.903 |

Improved cases: 1
Unchanged cases: 10
Regressed cases: 1
BM25 traceable contributions: 1
Questions where bounded expansion added relevant sibling evidence: 7
Context-expanded evidence is prompt assembly order, so separate Hit/MRR is intentionally not reported.

The complete ranks, evidence metadata, latency, and case lists are in `evaluation_results.json`.
