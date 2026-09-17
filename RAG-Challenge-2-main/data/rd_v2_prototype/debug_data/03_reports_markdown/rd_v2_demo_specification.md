

---

# Page 1

R&D Document Intelligence Platform

PROTOTYPE SPECIFICATION - RAG-RD-V2

1 Overview

This specification defines the R&D Document Intelligence Platform. It covers ingestion,

section-aware indexing, retrieval, export, reliability, security, and acceptance controls.

The platform is designed for long requirements, design, interface, test, and acceptance

documents. Every answer must remain traceable to a document identifier and a physical page

number.

Release identifier: RAG-RD-V2. Document status: prototype specification.

RAG-RD-V2 - Synthetic public prototype corpus

Page 1

---

# Page 2

1.1 Data Processing Goals

Module RD-DATA-01 normalizes source records, preserves document_id and page_number,

removes transport-only wrappers, and emits normalized_blocks.

Its main responsibility is to turn parser output into stable evidence records without losing

source provenance. It does not generate answers and it does not decide whether a question is

answerable.

The module accepts PDF parser blocks and OCR blocks through the same normalization

contract.

RAG-RD-V2 - Synthetic public prototype corpus

Page 2

---

# Page 3

2 Architecture

The request path is gateway, ingestion coordinator, parser, RD-DATA-01 normalizer, section

detector, RD-INDEX-02 indexer, retrieval service, and answer service.

The export worker is isolated from online retrieval. Monitoring observes both the ingestion and

export paths, but monitoring does not own business records.

Dense retrieval and sparse retrieval are independent candidate producers. Their raw scores

are not directly added.

RAG-RD-V2 - Synthetic public prototype corpus

Page 3

---

# Page 4

2.1 Ingestion Interface

POST /api/v2/ingest creates an asynchronous ingestion job.

Required request fields are source_uri and document_id. Optional fields are language and

force_ocr.

A successful request returns job_id and accepted_at. The job_id is used to poll ingestion state.

The interface rejects a blank source_uri before any parser work starts.

RAG-RD-V2 - Synthetic public prototype corpus

Page 4

---

# Page 5

2.2 Indexing Contract

RD-INDEX-02 consumes normalized_blocks emitted by RD-DATA-01. It creates child

embeddings, a FAISS IndexFlatIP index, and a local BM25 sparse index.

Every child record retains chunk_id, parent_id, section_id, document_id, and page_number.

The section detector output is consumed before embedding so that a child never crosses a

detected section boundary.

RAG-RD-V2 - Synthetic public prototype corpus

Page 5

---

# Page 6

3 Export Service

POST /api/export starts export operation EXPORT-ASYNC-07. The operation returns an

export_job_id rather than a binary file in the initial response.

The worker reads validated answer records and citation records, then writes a portable JSON

package.

GET /api/export/{export_job_id} returns the current export status.

RAG-RD-V2 - Synthetic public prototype corpus

Page 6

---

# Page 7

3.1 Export Request Fields

The timeout_ms field controls the maximum export wait. Its default value is 30000 milliseconds

and its allowed upper bound is 120000 milliseconds.

The export_format field accepts json or markdown. The include_sources field defaults to true.

Requests above the timeout_ms upper bound fail validation and do not enter the worker

queue.

RAG-RD-V2 - Synthetic public prototype corpus

Page 7

---

# Page 8

4 Performance Requirements

PERF-RD-100 requires sustained retrieval throughput of 1000 req/s for cached query

embeddings.

The maximum supported concurrent user count is 240. Under the reference workload, retrieval

p95 latency must remain at or below 800 ms.

The reference workload uses five evidence results and a 1800 token context budget.

RAG-RD-V2 - Synthetic public prototype corpus

Page 8

---

# Page 9

5 Reliability and Failure Handling

Transient index write failures use retry_count 3 and initial backoff_ms 500. After retries are

exhausted, the job moves to dead-letter queue DLQ-RD.

A failed document does not prevent other documents in the same batch from completing.

Section detection failure is non-fatal: ingestion falls back to the legacy page chunker and

records legacy_fallback in the artifact.

RAG-RD-V2 - Synthetic public prototype corpus

Page 9

---

# Page 10

6 Security Controls

The ingestion endpoint requires OAuth scope rag:ingest. The export endpoint requires scope

rag:export.

Stored source objects use AES-256 encryption. Service logs may include identifiers and

hashes but must not include source document text or access tokens.

External model calls are prohibited for restricted source documents unless an approved data

boundary explicitly permits them.

RAG-RD-V2 - Synthetic public prototype corpus

Page 10

---

# Page 11

7 Acceptance Criteria

AC-RAG-01 requires page-level Hit@3 of at least 0.85 on the frozen answerable retrieval set.

AC-RAG-02 requires citation membership validation success of 100 percent for accepted

generated answers.

AC-RAG-03 requires retrieval p95 latency no greater than 800 ms under the reference

workload.

Ground truth must remain frozen during a comparison run; it may not be edited to improve

reported metrics.

RAG-RD-V2 - Synthetic public prototype corpus

Page 11

---

# Page 12

Appendix A Glossary

RD-DATA-01: source normalization module.

RD-INDEX-02: section-aware dense and sparse indexing module.

EXPORT-ASYNC-07: asynchronous export operation.

normalized_blocks: provenance-preserving output consumed by the indexer.

timeout_ms: maximum export wait in milliseconds.

RAG-RD-V2 - Synthetic public prototype corpus

Page 12