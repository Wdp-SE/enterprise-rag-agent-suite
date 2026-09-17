# Known limitations

- The parser supports common structured `.docx` constructs: Heading 1–3, paragraphs, simple placeholders, implicit leaf sections, and basic tables. It does not support arbitrary Word templates, complex nested layout, macros, tracked changes, or rich placeholder run formatting.
- Evidence membership proves the cited ID exists in the task cache. It does not prove semantic entailment or absolute factual correctness. Field coverage uses a conservative literal-name match; synonyms may be missed and literal matches still need review.
- Every generated draft requires human review. MISSING means an explicit Evidence match was unavailable; the final safe E2E therefore ends PARTIAL.
- The final E2E uses a safe synthetic/public RAG artifact. Unauthorized real R&D body was not sent to a public LLM. Some real business outage and document-layout cases remain unverified in production conditions.
- Frozen RAG policy remains DENSE_ONLY + SECTION_PATH. BM25/Hybrid and Reranker V2 are disabled. This sprint did not rerun holdout evaluation or retune retrieval.
- Checkpoints are local files with full recovery Evidence text. They need restricted filesystem access and appropriate retention. There is no enterprise Auth/RBAC, distributed task queue, complete frontend, or production deployment claim.
- The Agent regression scope excludes live research and sandbox tests. The workspace copies lack `.git` directories, so change provenance was checked by the performed edits and read-only file audit rather than a Git diff.
