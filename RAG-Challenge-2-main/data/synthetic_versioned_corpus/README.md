# Synthetic Versioned Corpus

This public, synthetic corpus exists only to validate RAG V3 lifecycle behavior.
`requirements_v1.json` and `requirements_v2.json` intentionally contain one
unchanged, one modified, one removed, and one added section. The capacity value
changes from 500 to 1000 and V2 adds a 200 MB/s throughput requirement.

No internal source material or online model call is involved.

