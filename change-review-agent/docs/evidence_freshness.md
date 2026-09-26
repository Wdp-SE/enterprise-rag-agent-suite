# Agent Evidence Freshness

RAG Evidence now retains `document_id`, `version_id`, `chunk_id`, page,
`content_hash`, version status, and freshness. The stable Evidence ID includes
the version and chunk identity when present, so the same version/chunk remains
stable while a newer version produces a different ID.

Freshness states are:

- `FRESH`: the Evidence version is currently active, or it is inside an
  explicitly requested historical scope.
- `STALE`: the document has a different current active version.
- `UNKNOWN`: document or version metadata is incomplete, or the active catalog
  cannot confirm it.

On workflow Resume, the HTTP RAG adapter loads the current `/documents`
catalog and validates checkpoint Evidence. Only SectionTasks referencing
`STALE` or `UNKNOWN` Evidence are reset and retrieved again. Unaffected
completed tasks keep their drafts and do not consume another RAG call. Old
Evidence remains in the audit snapshot with its stale status, while task
membership and drafting ignore it.

The Finalization Guard rejects versioned Evidence unless it is `FRESH`. Catalog
failure therefore fails closed through Resume or requires human intervention;
it is never silently treated as current knowledge. A deliberately selected
historical version remains valid only for the workflow carrying that explicit
historical scope.

