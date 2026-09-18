# Document Version Governance

RAG V3 separates the stable logical `Document` from each immutable
`DocumentVersion`.

`Document` contains `document_id`, `project_id`, `document_type`, `title`, and
`created_at`. `DocumentVersion` contains `version_id`, `document_id`, a display
`version_label`, `status`, SHA-256 `source_hash`, lifecycle timestamps,
`previous_version_id`, source identity, and metadata. Version labels are never
used to decide which version is current; `status` and `activated_at` are the
authority.

The MVP has two states:

- `ACTIVE`: eligible for default retrieval.
- `SUPERSEDED`: retained for audit, diff, and explicit historical retrieval.

At most one version of a logical document may be `ACTIVE`. Catalog validation
rejects duplicate active versions, invalid previous-version references, invalid
chunk membership, and manifest or artifact hash mismatches. A new version is
built and validated first. Its version artifact and active-vector snapshot are
written before a catalog-last atomic `os.replace` publishes the activation. A
failed build therefore leaves the previous `ACTIVE` version available.

Default `/retrieve` and `/query` requests use only `ACTIVE` versions. A caller
may retrieve a `SUPERSEDED` version only by explicitly passing its `version_id`
with `active_only=false`.

The read-only catalog endpoints are:

- `GET /documents`
- `GET /documents/{document_id}/versions`
- `GET /documents/{document_id}/diff`

Frozen V2 artifacts do not contain separate version IDs. At startup they are
mapped compatibly to one initial `ACTIVE` version per existing document. This
does not rewrite the frozen chunks or change their retrieval representation.

