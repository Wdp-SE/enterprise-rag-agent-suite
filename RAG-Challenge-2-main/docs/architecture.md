# R&D Document RAG V2 Architecture

## Scope

The hardened R&D V2 path is a load-only runtime around artifacts frozen by the
research pipeline. It does not parse, split, embed the corpus, build FAISS, or
select retrieval parameters during service startup or query handling.

The only formal retrieval configuration is:

```text
policy_version        = rd-v2-retrieval-final-v1.0
retrieval_policy      = DENSE_ONLY
dense_representation  = SECTION_PATH
bm25_enabled          = false
hybrid_enabled        = false
reranker_enabled      = false
```

Legacy BM25, hybrid, RRF, and reranker modules remain available for experiment
reproduction. The formal service does not import or route through them.

## Runtime flow

```text
startup
  -> load formal artifact manifest
  -> verify lifecycle state == COMPLETE
  -> verify every artifact hash
  -> verify frozen policy/version
  -> verify chunk count == embedding rows == FAISS ntotal
  -> verify embedding dimension, finite values, and unit norm
  -> load chunks and frozen FAISS index

query
  -> embed Question as SECTION_PATH-compatible query representation
  -> search frozen Dense FAISS (Top 20)
  -> retain final Top 5 primary hits
  -> existing bounded SectionContextExpander (1 neighbor, 1,800-token budget)
  -> existing structured Generation adapter, when explicitly allowed
  -> Citation Membership validation by (document_id, page_number)
  -> existing Trusted QA post-answer enforcement
  -> answer / N/A + validated sources + text-free internal trace
```

Startup validation is fail closed. It returns explicit error codes such as
`ARTIFACT_COUNT_MISMATCH`, `ARTIFACT_HASH_MISMATCH`,
`EMBEDDING_DIMENSION_MISMATCH`, or `POLICY_VERSION_MISMATCH`; it never repairs
or rebuilds an artifact implicitly.

## Artifact boundary

The formal namespace contains compact metadata and immutable references:

```text
data/rd_v2_corpus/retrieval_artifacts/rd-v2-retrieval-final-v1.0/
  artifact_build_state.json
  artifact_manifest.json
  corpus_manifest.json
  structure_sidecar_manifest.json
  retrieval_policy.json
```

The manifest binds the frozen corpus snapshot, source and canonical-PDF hashes,
structure sidecars, child chunks, SECTION_PATH embeddings, FAISS index, and
retrieval policy. Large files are referenced by project-relative path and SHA256
rather than copied. The entire `data/rd_v2_corpus/` tree remains Git-ignored.

## Native process boundary

FAISS stays in the service process. PyTorch and Transformers run in a persistent
spawned embedding worker with one Torch thread and MKLDNN disabled. Every query
embedding is checked for finite values, expected dimension, and unit norm before
it reaches FAISS. See [Native Runtime Notes](native_runtime_notes.md).

## Service boundary

`src.rd_v2_api` exposes only:

- `GET /health`
- `GET /artifacts/status`
- `POST /query`

There are no build, rebuild, corpus upload, policy mutation, or evaluation
endpoints. Provider credentials are read by existing provider adapters from
environment variables only. External generation is disabled unless
`RD_V2_ALLOW_EXTERNAL_GENERATION=true` is explicitly set for a corpus whose data
policy permits it.

