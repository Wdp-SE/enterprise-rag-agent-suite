# RAG + Agent Engineering Performance Benchmark Plan

## 1. Audit decision

```text
BENCHMARK_CORE_CODE_MODIFICATION_REQUIRED = NO
CORE_BUSINESS_CODE_CHANGED = NO
FINAL_RETRIEVAL_POLICY = DENSE_ONLY
FINAL_DENSE_REPRESENTATION = SECTION_PATH
```

The frozen business runtime exposes all operations and counters needed by an
external benchmark harness. Benchmark code will live under this delivery
directory and will not change retrieval, lifecycle, Agent workflow, prompts,
timeouts, retries, chunking, embedding model, TopK, or test data in the product
runtime.

Benchmark baseline Git commit: `1ff9d5f705706063926a6343feda202ab560ca65`.

## 2. RAG audit

| Audit item | Formal path and conclusion |
|---|---|
| `/retrieve` | `src.rd_v2_api.create_app` → `runtime.retriever.retrieve` → `FrozenDenseRetriever.retrieve`. The route validates `top_k`, checks artifact status, runs retrieval in a worker thread, and serializes provenance. |
| Scoped retrieval | `RetrieveRequest.scope` → `RetrievalScope` → `DocumentCatalog.matches`. Filtering occurs before dense matrix scoring. |
| Document/version lifecycle | `DocumentCatalog`, `DocumentVersion`, `VersionLifecycleService`, `activate_version`, and `diff` implement ACTIVE/SUPERSEDED and explicit version scope. |
| Full ingestion/rebuild | `VersionLifecycleService.ingest_version` accepts normalized `SectionSnapshot` rows and an embedder. A fresh store with V2 alone is a fair target-document full rebuild baseline. |
| Incremental update | Ingest V1, then V2 into the same store. `compare_section_versions` records UNCHANGED/MODIFIED/ADDED/REMOVED. |
| Embedding reuse | Content-hash vectors are persisted in `embedding_cache.json`; unchanged content hashes are reused. `IncrementalBuildReport` exposes reused/new embedding counts. |
| Active index refresh | Each activation rewrites an exact active vector matrix from cached vectors. Strategy is `CACHED_VECTOR_EXACT_MATRIX_REFRESH`; it is not an in-place FAISS update. |
| Artifact loading | `FrozenArtifactValidator.validate_and_load` validates COMPLETE state, hashes, corpus files, policy, chunks, embeddings, FAISS index, and catalog before serving. |
| Online embedding risk | Frozen `/retrieve` uses the locally discovered `BAAI/bge-small-zh-v1.5` revision snapshot through `LocalEmbeddingProcessClient`. External generation remains disabled. No online embedding or LLM call is permitted by the benchmark. |
| Current corpus | Frozen local approved corpus: 3 documents, 5,090 chunks/vectors, 512 dimensions. Retrieval requests do not transmit corpus text externally. |

Historical `/retrieve` latency is marked not applicable for the frozen corpus
because every frozen document currently has one ACTIVE version and no retained
SUPERSEDED version. Historical-scope correctness will instead be checked in the
controlled version-lifecycle fixture.

## 3. Agent audit

| Audit item | Formal path and conclusion |
|---|---|
| Fresh run | `DocumentWorkflow.run` → `_execute`; facade entry is `DocumentWorkflowFacade.run_workflow`. |
| Resume | `DocumentWorkflow.resume` validates template, config, output, and scope fingerprints, restores checkpoint state, and skips COMPLETE sections. |
| Checkpoint | `CheckpointStore` writes atomic JSON checkpoints after state transitions and evidence growth. |
| Evidence freshness | On resume, `EvidenceFreshnessValidator` compares evidence version IDs with `active_versions()`. |
| Stale local refresh | Only tasks referenced by STALE evidence are reset; unaffected COMPLETE tasks and drafts remain. |
| RAG call counting | `WorkflowState.rag_call_count`, section trace `rag_calls`, and a benchmark retrieval client provide independent counts. |
| Section/field counting | `SectionTaskPlanner`, parsed schema sections, task required fields, drafts, and trace sections are directly observable. |
| Drafting network use | Default `FieldDraftingService` is EXTRACTIVE. GENERATIVE requires an injected backend and approved policy; benchmark configuration stays EXTRACTIVE, so LLM calls are zero. |
| Safe data | The benchmark will generate a dedicated synthetic DOCX template and deterministic synthetic retrieval records. Existing Safe E2E remains a regression target, not a source of online traffic. |

Evidence cache benchmarking is excluded unless a natural repeated-query case is
observed. The primary Agent comparisons are Resume and stale local refresh.

## 4. Fixed methodology

- Same machine, interpreter, data, configuration, TopK, and code revision within each comparison.
- RAG HTTP latency: 5 complete warm-up rounds and 30 measured rounds over a fixed 15-query set, `top_k=5`.
- Scopes: ALL ACTIVE, SINGLE DOCUMENT, and MULTI DOCUMENT. Candidate counts are computed from the same validated frozen chunk catalog.
- Latency output: count, mean, P50, P90, P95, min, max, and population standard deviation in milliseconds.
- Correctness gates: single/multi document membership, ACTIVE-only default, result schema, rank, and `top_k` invariants.
- Incremental comparison: five independent cold runs, each recreated from the same synthetic V1/V2 fixture. V2 has 12 sections: 9 unchanged, 2 modified, 1 added; V1-only has 1 removed section. This gives 75% unchanged V2 content and a non-extreme change set.
- Full rebuild scope: target document V2 only, with an empty vector cache. Incremental scope: the same V2 target after V1 has populated the content-hash cache.
- Both full and incremental paths use the same local frozen BGE model process and identical V2 content. Model load/warm-up is excluded equally from both timed regions; no later run inherits another run's lifecycle store.
- Agent comparisons use the same generated synthetic template, scope, deterministic retrieval behavior, EXTRACTIVE drafting, and new runtime directory per sample.
- Agent timing uses at least 5 warm-ups and 30 measured runs for fresh run, resume scenarios, and stale refresh comparison. All valid runs enter statistics.
- Resume scenarios: checkpoints after 25%, 50%, and 75% of sections, created through a deterministic interruption. Baseline restarts the complete workflow; optimized execution resumes the matching checkpoint.
- Stale refresh: a completed V1 workflow is resumed after only a subset of document versions changes. Baseline runs the full V2 workflow from scratch; optimized execution resumes and refreshes only affected sections.
- Human review time is excluded. No external LLM is called. Agent measurements are offline deterministic engineering benchmarks.
- Percentage formula: `(baseline - optimized) / baseline * 100`; reuse rate: `reused / full-required * 100`.

## 5. Artifacts and Git hygiene

Tracked deliverables:

- environment JSON;
- fixed fixture/query JSON and benchmark scripts;
- raw aggregate benchmark JSON;
- Markdown summaries and final report;
- resume-ready metric recommendations.

Transient stores, DOCX render outputs, checkpoints, process logs, and generated
embedding artifacts go under `runtime/`, which is ignored. No benchmark runtime
artifact will be committed as product data.

## 6. Stop conditions

The run stops and reports `NOT FAIRLY BENCHMARKABLE` for a metric if it would
require changing core behavior, reducing work, changing retrieval settings, or
using unsafe data. Any correctness failure invalidates the corresponding
performance comparison. No performance optimization or product feature work is
authorized after the report is complete.
