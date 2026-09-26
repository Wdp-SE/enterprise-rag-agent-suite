# RAG Incremental Update Benchmark

Controlled synthetic version fixture: 12 V2 sections, with 9 unchanged, 2
modified, 1 added, and 1 V1-only removed section. Every one of the five measured
runs started from a new lifecycle store. Both paths used the same warm local
`BAAI/bge-small-zh-v1.5` snapshot; no online model was called.

| Metric | Full rebuild | Incremental |
|---|---:|---:|
| P50 total seconds | 0.555 | 0.381 |
| P95 total seconds | 0.650 | 0.419 |
| P50 Embedding seconds | 0.329 | 0.114 |
| P50 index-refresh seconds | 0.071 | 0.068 |
| Embeddings computed | 12 | 3 |

- Reused embeddings: **9 / 12 (75.000%)**
- P50 elapsed reduction: **31.351%**
- Embedding compute-count reduction: **75.000%**
- Observed P50 embedding-time reduction: **65.350%**
- Effect: **MODERATE**

`FULL_REBUILD_SCOPE = target document from normalized SectionSnapshot input`.
Upstream source-format parsing is excluded equally because the formal lifecycle
API receives normalized sections. The update reuses content-hash embeddings and
then applies `CACHED_VECTOR_EXACT_MATRIX_REFRESH`: it rewrites the exact
active vector matrix from cached vectors and is not an in-place FAISS update.

ACTIVE default, explicit historical scope, and version diff correctness passed.
