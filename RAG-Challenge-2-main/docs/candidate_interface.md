# Candidate Ingestion Interface v2

This is the only supported handoff from an external Agent to the RAG project.
An Agent may create a Candidate Package, but it must not write the formal
knowledge base or any FAISS index. Contract v2 is recommended; legacy v1
packages remain importable.

## Package layout

```text
candidate_id/
├── document.md
├── metadata.json
├── sources.json
└── raw_sources/
    └── downloaded source files
```

`document.md` cites evidence using exact references such as `[source:S01]`.
Every cited ID must exist after source normalization. Sources are never added
automatically.

`metadata.json` keeps Generic `DocumentMetadata` fields plus a separate review
block:

```json
{
  "document_id": "stable-document-id",
  "title": "Document title",
  "document_type": "policy",
  "source": "source organization or collection",
  "source_url": "https://example.org/document",
  "category": "safety",
  "tags": ["inspection"],
  "legacy_company_name": null,
  "candidate": {
    "status": "CANDIDATE",
    "generated_by": "openmanus-agent",
    "requires_review": true,
    "created_at": "2026-08-28T08:00:00+08:00"
  }
}
```

Agent packages must use `CANDIDATE`, a non-empty `generated_by`, and
`requires_review: true`. Agent-supplied `APPROVED` is rejected.

## Candidate Contract v1 (Legacy)

```json
{
  "sources": [
    {
      "source_id": "S01",
      "title": "Official source title",
      "source_type": "pdf",
      "source_url": "https://example.org/document.pdf",
      "raw_path": "raw_sources/document.pdf"
    }
  ]
}
```

v1 does not require hashes. It continues to receive the original structural,
path, raw-file existence, duplicate-ID, and citation validation.

## Candidate Contract v2 (Hash-aware, recommended)

```json
[
  {
    "source_id": "S01",
    "title": "Official source title",
    "organization": "Official organization",
    "url": "https://example.org/document.pdf",
    "local_file": "raw_sources/document.pdf",
    "content_hash": "<64-character SHA-256>",
    "raw_file_hash": "<64-character SHA-256>",
    "document_number": null,
    "publish_date": "2026-01-01",
    "effective_date": null,
    "source_level": "TIER1",
    "retrieved_at": "2026-08-28T08:00:00Z",
    "source_type": "pdf",
    "evidence_id": "ev_example"
  }
]
```

The optional fields shown above are explicitly modeled. Unknown fields are
rejected with `UNKNOWN_SOURCE_FIELD`; misspellings are not silently retained.

Any list root is v2. A v1 wrapper containing a v2-only field is also treated as
v2, so changing only the root shape cannot bypass hash validation.

## Normalization and aliases

All source validation operates on one canonical internal model:

```text
source_url or url  -> source_url
raw_path or local_file -> local_file
v1/v2 root -> list[CandidateSource]
```

If old and new aliases are both present, normalized equal values are accepted.
Different values are rejected with `SOURCE_ALIAS_CONFLICT`. Contract-specific
serialization is confined to the storage boundary: v1 remains a wrapper with
legacy aliases; v2 remains a list with current aliases.

## Hash verification boundary

`content_hash` and `raw_file_hash` have different meanings and are never
compared with each other.

- `content_hash`: hash declared by the Agent for normalized Evidence/source
  text. The RAG Candidate Package does not contain that independent normalized
  Evidence object. RAG therefore validates only the SHA-256 format, normalizes
  it to lowercase, and preserves it. Status:
  `DECLARED_AND_FORMAT_VALIDATED`.
- `raw_file_hash`: SHA-256 of the exact bytes stored at `local_file`. RAG opens
  that file, recomputes SHA-256 over its bytes, and compares it with the
  declaration. Status on accepted v2 import: `RECOMPUTED_AND_VERIFIED`.

RAG does not claim that `content_hash` was recomputed or content-integrity
verified.

## Cross-platform path safety

After slash normalization, `local_file`/`raw_path` must:

- be relative and located below `raw_sources/`;
- contain no `..` escape;
- not be a Windows drive path, UNC path, or POSIX absolute path;
- resolve inside the Candidate Package;
- traverse no symbolic links;
- exist and be a regular readable file.

Relevant issue codes include `INVALID_LOCAL_FILE`, `RAW_SOURCE_NOT_FOUND`,
`PATH_ESCAPE`, and `SYMLINK_NOT_ALLOWED`.

Hash-specific issue codes are `INVALID_CONTENT_HASH`,
`INVALID_RAW_FILE_HASH`, and `RAW_FILE_HASH_MISMATCH`.

## Python API

```python
from src.candidate_knowledge import import_candidate, approve_candidate

result = import_candidate(
    "/path/from/openmanus/candidate-001",
    candidate_root="candidate_knowledge",
)
if not result.accepted:
    for issue in result.issues:
        print(issue.code, issue.message)

# Explicit human-review boundary; never called automatically by import.
approval = approve_candidate(
    "candidate-001",
    candidate_root="candidate_knowledge",
)
```

`ImportResult` records the detected contract and truthful hash-validation
statuses. Both import and approval expose `ingestion_performed: false`. Neither
operation calls Embedding, writes FAISS, or publishes formal knowledge.

Examples:

- `examples/sample_candidate_package/`: legacy v1 regression package.
- `examples/sample_candidate_package_v2/`: recommended hash-aware package.
