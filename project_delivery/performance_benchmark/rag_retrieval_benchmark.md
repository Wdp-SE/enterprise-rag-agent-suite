# RAG `/retrieve` Benchmark

- Policy: `DENSE_ONLY + SECTION_PATH`
- Transport: loopback HTTP
- Fixed queries: 15
- TopK: 5
- Warm-up: 5 rounds per query/scope
- Measured: 30 rounds per query/scope
- Online model calls: NO

| Scope | Candidate vectors | Samples | Mean ms | P50 ms | P90 ms | P95 ms | Std ms |
|---|---:|---:|---:|---:|---:|---:|---:|
| All ACTIVE | 5090 | 450 | 81.226 | 82.166 | 97.096 | 101.074 | 13.934 |
| Single document | 20 | 450 | 71.195 | 71.549 | 85.594 | 89.320 | 12.846 |
| Two documents | 2067 | 450 | 75.798 | 76.778 | 91.957 | 97.355 | 13.849 |

All Scope membership, ACTIVE-only, rank, and TopK correctness gates passed.
The single-document P50 was 12.921% lower in this corpus, but
this is not promoted as a primary optimization claim: the selected document has
only 20 vectors, while ALL ACTIVE has
5090. Scope's primary value is business
correctness.

Cold-start engineering record (one sample): health ready in
2644.112 ms; first
retrieve ready in 16389.680
ms. The first retrieve includes local model-worker startup and is not a resume
metric.

Historical-version latency is `NOT_APPLICABLE_TO_FROZEN_CORPUS`: the frozen
artifact has one ACTIVE version per document. Historical correctness is covered
by the synthetic lifecycle benchmark.
