# Known limitations

- The end-to-end run uses an offline simulated lexical RAG corpus. The frozen RAG V2 service was checked at its public API boundary, but a real-corpus run was intentionally withheld because external generation authorization and source-text availability are unresolved.
- Frozen `/query` has no `top_k` request field. The adapter applies `top_k` to returned citations. If citations have no source text, it uses the returned answer as Evidence content; that is weaker than source-level passages and requires human review. When generation is disabled, the API returns no usable content.
- Field coverage is a conservative literal-name match in Evidence content. It can miss synonyms or mark a string match as sufficient without semantic validation. Drafting copies Evidence text and enforces ID membership only.
- DOCX support is limited to Heading 1–3, body paragraphs, plain placeholders, and simple tables. Replacement can flatten rich run formatting inside a placeholder paragraph. Macros, floating objects, SmartArt, tracked changes, and complex nested layouts are outside scope.
- BudgetLedger, NoProgressDetector, TaskPolicy, TraceContext, and EvidenceStore are reused. HTTP requests have a timeout, but the workflow does not yet use the existing retry owner or ExecutionResult orchestration; failed RAG calls become missing content with an error type in trace.
- The selected 342 tests passed. Docker/sandbox tests and a production RAG end-to-end test were not run. These gaps are why engineering hardening readiness is NO.
