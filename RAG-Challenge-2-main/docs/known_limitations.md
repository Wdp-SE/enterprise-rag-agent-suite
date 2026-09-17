# R&D V2 Known Limitations

1. Retrieval metrics on the real long-document R&D corpus remain limited. The
   frozen 20-question HOLDOUT result is Hit@1 0.20, Hit@5 0.40, Hit@20 0.40,
   and MRR 0.2625.
2. Dense retrieval remains weak for field and exact-term questions. Engineering
   hardening does not solve that quality limitation.
3. BM25 and hybrid implementations did not show a stable net gain. They remain
   reproducible experimental/legacy paths and are disabled by default.
4. Reranker value was not verified under the frozen constraints. Existing
   optional rerankers require online services, so the final V2 disables them.
5. The primary validated structure path is Word/DOC/DOCX to local canonical PDF
   plus a Word structure sidecar. PDF-only heading heuristic reliability has not
   been demonstrated at the same level; its two-case diagnostic stress result
   was a miss at Top 20. FALLBACK remains a compatibility path.
6. Citation Membership proves that `(document_id, page_number)` belongs to
   retrieved evidence. It does not prove semantic support, factual correctness,
   completeness, or absence of hallucination.
7. Trusted QA fail-closed covers deterministic structured-output and citation
   invariants. It is not a general factuality or hallucination detector.
8. The minimal API has no production authentication, authorization, rate limit,
   distributed task queue, multi-tenant isolation, or observability platform.
9. External generation is disabled for the real R&D corpus until its data owner
   explicitly authorizes transmission. The engineering sprint therefore makes
   no claim about real-corpus end-to-end answer quality.

This project does not claim Production Ready and does not claim zero
hallucinations.

