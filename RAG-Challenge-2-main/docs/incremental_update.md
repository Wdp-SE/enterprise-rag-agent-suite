# Incremental Version Update

The V3 lifecycle service accepts section snapshots produced by the existing
parser. It does not reparse, rechunk, or re-embed unrelated documents.

For a new version it compares SHA-256 source identity, normalized section path,
and normalized section content hash:

- `UNCHANGED`: create version-specific chunk membership and reuse the cached
  embedding by content hash.
- `MODIFIED`: create a new version-specific chunk and embed its new content.
- `ADDED`: create and embed the new section.
- `REMOVED`: retain it in the old version artifact but omit it from the new
  active version.

Chunk identity and content identity are separate. An unchanged section gets a
new chunk ID containing the new `version_id`, while its embedding is reused.
This prevents ambiguous cross-version chunk membership.

The build report records total, unchanged, modified, added, and removed
sections; reused and new embeddings; active chunk count; processing time; and
the index refresh strategy.

The actual V3 MVP index strategy is
`CACHED_VECTOR_EXACT_MATRIX_REFRESH`. Cached normalized vectors from all active
versions are assembled into a new active snapshot. Scoped searches can also
select version rows from persisted version artifacts and rank them with exact
dot products. There is no claim of in-place FAISS deletion or update. The
frozen V2 FAISS artifact remains load-only and unchanged.

Parsing is incremental at the service boundary because only the supplied new
version has to be parsed by the existing pipeline. Chunk construction is
incremental per changed version. Embedding is incremental by content hash.
Refreshing the active matrix does not require full-corpus re-embedding.

`scripts/manage_document_versions.py` provides local `ingest-version`,
`activate-version`, `diff`, and `catalog` commands. It consumes precomputed
embeddings and never sends source text to an online service.

