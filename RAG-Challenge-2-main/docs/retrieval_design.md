# R&D V2 Retrieval Design

## Frozen decision

The final runtime uses Dense-only retrieval with the already-built
`SECTION_PATH` representation and `BAAI/bge-small-zh-v1.5` artifacts. Corpus,
chunk, section, embedding model, and representation are frozen. Runtime defaults
are Dense Top 20, final Top 5, one neighboring child per hit, and a 1,800-token
context budget.

`SECTION_PATH` was selected on the frozen DEV set before HOLDOUT was run. At the
reranker candidate depth of 12 child chunks, its candidate Hit@12 was 0.45,
versus 0.40 for `DOCUMENT_SECTION_PATH`. This selection does not claim that it
wins every shallower metric or every query category.

## Enabled path

1. A question is embedded locally using the frozen model revision and query
   prefix recorded in the manifest.
2. `IndexFlatIP` searches 5,090 unit-normalized vectors.
3. The first five Dense hits become primary evidence.
4. The existing section-aware expander adds a section anchor and neighboring
   children under the fixed context budget.
5. Only generated citations present in the expanded evidence set survive
   `(document_id, page_number)` membership validation.

No query-time parsing, chunking, corpus embedding, FAISS construction, BM25,
RRF, hybrid fusion, reranking, classifier, or query routing occurs.

## Implemented but not enabled

- BM25 V1 and Technical Tokenizer V2 were evaluated but did not improve the
  relevant field, exact-term, or interface failures consistently.
- Hybrid retrieval produced partial gains alongside semantic regressions, so it
  did not demonstrate a stable net benefit.
- The repository retains online LLM and Jina reranker implementations, but no
  admissible local reranker artifact existed for the frozen validation. Reranker
  value is therefore not verified and the final policy disables it.

These paths are legacy/experimental compatibility code. Their presence is not a
signal that the service may activate them automatically.

## Trace and citation contract

Public sources retain only `document_id` and one-based `page_number`. Internal
in-memory trace may additionally contain `chunk_id`, `section_id`,
`section_source`, retrieval rank, similarity score, and context role. Document
text and questions are not written to the artifact lifecycle, service logs, or
long-lived traces.

Citation Membership proves only that a cited document/page was in retrieved
evidence. It does not prove semantic entailment or factual correctness.

