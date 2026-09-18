# Known Limitations

- V3 adds business lifecycle metadata around the frozen DENSE_ONLY + SECTION_PATH retrieval core. It does not retune embeddings, chunks, sections, similarity, or ranking.
- Frozen V2 artifacts predate separate version IDs. The compatibility catalog maps each legacy document to one initial ACTIVE version. Real multi-version operation requires lifecycle artifacts produced by the V3 service.
- The incremental service starts from section snapshots produced by the existing parser. It does not add support for arbitrary Word files or redesign parsing.
- Embeddings are reused by normalized content hash. The active search snapshot is rebuilt from cached vectors; FAISS is not updated in place.
- Exact matrix search is appropriate for the current roughly 5,090-chunk MVP corpus. No production QPS, horizontal scaling, or large-corpus claim is made.
- Section Diff aligns normalized paths and hashes. Renamed or moved sections appear as removed plus added, and no semantic meaning is inferred.
- RetrievalScope is a business filter, not a security boundary. V3 does not implement ACL, RBAC, authentication, tenants, or row-level authorization.
- Version writes are exposed through a local service and CLI. There is no unauthenticated HTTP administration or upload endpoint.
- Agent freshness depends on a reachable, consistent /documents catalog during Resume. Unknown freshness fails closed or requires human review.
- External answer generation remains governed by the existing data policy. The V3 synthetic E2E and Version Diff make no online model call.
- Human review remains mandatory for generated workflow drafts.

