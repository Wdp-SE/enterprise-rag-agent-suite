# RAG V3 Lifecycle Engineering Report

## Outcome

RAG V3 implements the requested lifecycle MVP around the frozen R&D V2
retrieval core. The embedding representation, chunk/section semantics, dense
similarity math, and final retrieval policy were not changed:

- `FINAL_RETRIEVAL_POLICY = DENSE_ONLY`
- `FINAL_DENSE_REPRESENTATION = SECTION_PATH`

The delivered behavior is basic document version governance, scope-aware
retrieval, incremental content processing with embedding reuse, deterministic
section diff, Agent Evidence freshness, and a unified Streamlit UI. No
production-readiness claim is made.

## Existing-system audit

The RAG audit found a load-only 5,090-row FAISS `IndexFlatIP`, a row-aligned
normalized embedding matrix, immutable child chunks, manifest/hash/count/
dimension/policy validation, canonical page citations, and an earlier
ACTIVE/SUPERSEDED resolver whose version identity was still coupled to physical
document IDs. V3 reuses the frozen vectors and adds stable logical documents
plus independent version identity.

The Agent audit found the shared strict Evidence model, stable Evidence IDs,
EvidenceCache task/query membership, atomic checkpoint state, Resume draft
validation, and Finalization Guard. V3 extends those models rather than adding
a parallel workflow.

The UI audit found one RAG tab, one Agent tab, a thin HTTP RAG client, and
session-state result storage. V3 extends the existing tab and client.

## RAG implementation

`src/document_lifecycle.py` contains the shared `Document`,
`DocumentVersion`, `RetrievalScope`, catalog, deterministic Section Diff, and
local lifecycle service.

The catalog enforces unique IDs, valid references, and at most one ACTIVE
version per logical document. Every source has a SHA-256 identity. Catalog,
version artifact, embedding cache, and active index hashes are validated on
load. Chunk/version references, vector counts, dimensions, finiteness,
normalization, and ACTIVE membership fail closed.

`/retrieve` and `/query` accept the same optional scope. Old payloads still
work and now mean all ACTIVE versions. Candidate rows are selected before
ranking; normalized exact dot product then returns the real Top K in that
scope. `/documents`, per-document versions, and Section Diff are read-only.

Frozen V2 artifacts are mapped to one compatibility ACTIVE version per current
document. This mapping does not rewrite the frozen artifacts.

## Incremental update

The lifecycle service compares source hash, normalized Section identity, and
Section content hash. Unchanged content gets a new version-specific chunk
identity and reuses its cached vector. Modified and added content is embedded.
Removed content remains in the prior version artifact and is absent from the
new active version.

The service writes the new version artifact, refreshed active-vector snapshot,
and embedding cache before atomically replacing the catalog. A failed embed or
validation leaves the old ACTIVE catalog intact.

The actual strategy is `CACHED_VECTOR_EXACT_MATRIX_REFRESH`. It rebuilds the
small active matrix from cached vectors. It does not update FAISS in place and
does not re-embed the full corpus.

The synthetic V1-to-V2 build reported:

| Metric | Result |
| --- | ---: |
| total sections | 3 |
| unchanged | 1 |
| modified | 1 |
| added | 1 |
| removed | 1 |
| reused embeddings | 1 |
| new embeddings | 2 |
| active chunks after V2 | 4 |

## Agent freshness

Versioned Evidence records include logical document ID, version ID, version
status, chunk, page, content hash, and freshness. Stable ID generation includes
the version/chunk identity when present.

On Resume the Agent loads the current document catalog. FRESH Evidence remains
usable; STALE or UNKNOWN versioned Evidence is excluded. Only SectionTasks that
reference invalid Evidence are reset. Unaffected completed tasks and drafts
remain intact. Explicit historical scope keeps its selected version valid.
The Finalization Guard rejects versioned Evidence unless it is FRESH.

## UI

The RAG tab loads the real catalog and exposes five scopes: all active,
project, document type, one or more documents, and explicit version/history.
Every Evidence row displays the user-facing document title, version, status,
page, section, and score. The Version Diff expander shows four summary counts
and expandable Section citations. Agent Evidence displays version and
freshness.

## Safe E2E

The offline synthetic corpus contains Requirements V1, Requirements V2, and
Design V1. No online model was called.

- Scenario A: V1 ACTIVE returns concurrency 500.
- Scenario B: V2 activation supersedes V1; default retrieval returns 1000.
- Scenario C: explicit V1 retrieval returns historical value 500.
- Scenario D: DESIGN scope returns only DESIGN.
- Scenario E: V1 to V2 diff returns one ADDED, REMOVED, MODIFIED, and UNCHANGED
  Section with page/hash citations.
- Scenario F: Agent Resume marks V1 Evidence STALE, skips an unaffected
  completed task, and retrieves V2 FRESH Evidence for the affected task.

Artifacts are retained under `RAG-Challenge-2-main/reports/`.

## Performance sample

The sample used the local frozen 5,090-chunk artifact, ten repetitions, and a
fixed already-computed query vector. It therefore measures candidate filtering
and ranking, not embedding latency.

| Metric | Result |
| --- | ---: |
| Artifact + catalog startup | 770.199 ms |
| All ACTIVE retrieval median | 8.230 ms |
| Single-document retrieval median | 3.000 ms |
| Full rebuild baseline | not measured |

These figures are local engineering samples. No production QPS claim is made.

## Verification

- Original RAG V2 regression: 290 passed, 0 failed.
- Original non-Docker Agent regression: 364 passed, 0 failed.
- Original UI regression: 6 passed, 0 failed.
- Final RAG suite: 303 passed, 0 failed.
- Final non-Docker Agent suite: 368 passed, 0 failed.
- Final UI suite: 9 passed, 0 failed.
- Streamlit live smoke: local port 8503, health 200/`ok`, page 200.

The Docker Sandbox test group was also attempted. Seven tests failed and 18
errored because Docker Desktop's `//./pipe/docker_engine` daemon was absent.
Three Sandbox tests completed before that failure. This environmental group is
outside the RAG/Document Workflow V3 scope and is excluded from the regression
pass totals above.

The category counts below are acceptance assertion groups and overlap; they
are not intended to sum to the final suite total.

## Acceptance matrix

```text
DOCUMENT_MODEL_READY = YES

DOCUMENT_VERSION_MODEL_READY = YES

SINGLE_ACTIVE_VERSION_ENFORCED = PASS

ACTIVE_SUPERSEDED_LIFECYCLE = PASS

DEFAULT_ACTIVE_ONLY_RETRIEVAL = PASS

HISTORICAL_VERSION_RETRIEVAL = PASS

RETRIEVAL_SCOPE_READY = YES

ALL_DOCUMENT_SCOPE = PASS

PROJECT_SCOPE = PASS

DOCUMENT_TYPE_SCOPE = PASS

SINGLE_DOCUMENT_SCOPE = PASS

MULTI_DOCUMENT_SCOPE = PASS

VERSION_SCOPE = PASS

SCOPED_TOPK_CORRECT = PASS

DOCUMENT_CATALOG_API = PASS

VERSION_CATALOG_API = PASS

CHANGE_DETECTION = PASS

UNCHANGED_SECTION_REUSE = PASS

EMBEDDING_REUSE = PASS

MODIFIED_SECTION_REEMBED = PASS

ADDED_SECTION_INDEXED = PASS

REMOVED_SECTION_EXCLUDED_FROM_ACTIVE = PASS

FAILED_BUILD_PRESERVES_CURRENT_ACTIVE = PASS

INDEX_REFRESH_STRATEGY = CACHED_VECTOR_EXACT_MATRIX_REFRESH

FULL_CORPUS_REEMBED_REQUIRED = NO

VERSION_DIFF_READY = YES

DIFF_ADDED = PASS

DIFF_REMOVED = PASS

DIFF_MODIFIED = PASS

DIFF_UNCHANGED = PASS

DIFF_CITATION_PRESERVED = PASS

DIFF_USES_LLM = NO

AGENT_EVIDENCE_VERSION_AWARE = YES

EVIDENCE_FRESHNESS_READY = YES

STALE_EVIDENCE_DETECTION = PASS

EXPLICIT_HISTORICAL_EVIDENCE_VALID = PASS

RESUME_STALE_REFRESH = PASS

ONLY_AFFECTED_SECTION_REFRESHED = PASS

STALE_EVIDENCE_BLOCKS_FINALIZATION = PASS

RAG_UI_SCOPE_SELECTOR = PASS

RAG_UI_DOCUMENT_SELECTOR = PASS

RAG_UI_VERSION_SELECTOR = PASS

RAG_UI_VERSION_DIFF = PASS

AGENT_UI_FRESHNESS_VISIBLE = PASS

V2_RETRIEVAL_BACKWARD_COMPATIBLE = PASS

V2_AGENT_WORKFLOW_BACKWARD_COMPATIBLE = PASS

SAFE_VERSIONED_E2E = PASS

REAL_INTERNAL_DATA_SENT_TO_ONLINE_LLM = NO

DATA_POLICY = PASS

V2_REGRESSION = 660 passed / 0 failed

V3_VERSION_TESTS = 7 passed / 0 failed

V3_SCOPE_TESTS = 5 passed / 0 failed

V3_INCREMENTAL_TESTS = 5 passed / 0 failed

V3_DIFF_TESTS = 2 passed / 0 failed

V3_AGENT_FRESHNESS_TESTS = 4 passed / 0 failed

UI_SMOKE = PASS

READY_FOR_RESUME = YES

READY_FOR_INTERVIEW = YES

READY_FOR_DEMO = YES

PRODUCTION_READY = NO CLAIM
```

