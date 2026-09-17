# Known limitations

- This Streamlit app is a local interview/demo layer, not a production frontend.
- There is no authentication, RBAC, multi-user isolation, distributed queue, database state center, or production deployment claim.
- The Agent mainly supports structured DOCX templates with Heading 1–3, paragraphs, simple table fields, and placeholders. It does not support arbitrary Word documents.
- Evidence Membership proves an ID belongs to the cache; it is not semantic entailment or absolute factual correctness.
- Every draft requires human review. PARTIAL and MISSING are expected business states when Evidence is insufficient.
- The default demo uses synthetic/public data. Unauthorized real R&D text must not be sent to a public LLM.
- RAG remains DENSE_ONLY + SECTION_PATH. BM25, Hybrid, and Reranker are disabled.
- `/query` depends on the frozen RAG generation configuration. The primary safe Agent path uses retrieval-only `/retrieve`.
- The UI runs synchronous local work. It has no Celery, Redis, message queue, or distributed scheduler.
- Selected relevant regression counts are not the entire repository all-suite result.
- Production Ready = NO CLAIM.

