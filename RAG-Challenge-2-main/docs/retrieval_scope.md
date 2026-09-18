# Retrieval Scope

`RetrievalScope` is one shared contract used by `/retrieve`, `/query`, the
runtime retriever, the Agent adapter, and the Streamlit UI.

| Business mode | Scope |
| --- | --- |
| All current knowledge | `active_only=true` |
| Project | `project_ids=[...]`, `active_only=true` |
| Document type | `document_types=[...]`, `active_only=true` |
| One or more documents | `document_ids=[...]`, `active_only=true` |
| Historical version | `version_ids=[...]`, `active_only=false` |

The fields are combined with AND semantics. Values inside one field use OR
semantics. Duplicate and blank values are rejected. `version_ids` with
`active_only=true` is a validation error because the caller must acknowledge
that an explicitly selected version can be historical.

Scope is applied before ranking. The runtime selects all embedding rows whose
version and document metadata match the scope, then computes exact normalized
dot products inside that subset and returns its real Top K. It never takes a
global Top K and filters afterward. The frozen policy remains
`DENSE_ONLY + SECTION_PATH`; scope changes candidate membership, not embedding
text, similarity math, chunking, or reranking.

Scope expresses business retrieval range. It is not an ACL, RBAC rule, tenant
boundary, or security control.

