# Section-level Version Diff

Version Diff is deterministic and does not call an LLM.

Sections are aligned by normalized `section_path`. A unique aligned path is
classified by content hash:

- present only in the new version: `ADDED`
- present only in the old version: `REMOVED`
- present in both with different hashes: `MODIFIED`
- present in both with the same hash: `UNCHANGED`

Each row retains the old and new section IDs, page ranges, and content hashes.
The response also contains counts for all four change types. Results are sorted
by normalized path, so repeated calls over the same artifacts are stable.

The API is
`GET /documents/{document_id}/diff?from_version_id=...&to_version_id=...`.
Both versions must belong to the requested logical document and both must have
section snapshots.

Known limits: renamed or moved sections are represented as removed plus added;
semantic alignment is not attempted. Duplicate normalized section paths are
rejected instead of guessed. The diff describes structural and hash changes,
not the business meaning or correctness of those changes.

