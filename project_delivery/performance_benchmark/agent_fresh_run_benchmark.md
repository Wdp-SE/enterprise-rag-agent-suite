# Agent Fresh Run Benchmark

Offline deterministic EXTRACTIVE benchmark using one synthetic eight-section,
eight-field DOCX template. Human review time is excluded and LLM calls are zero.

| Metric | Value |
|---|---:|
| Sections / fields | 8 / 8 |
| RAG calls | 8 |
| Evidence | 8 |
| Drafted / missing fields | 8 / 0 |
| P50 total | 253.986 ms |
| P95 total | 330.316 ms |
| Mean / std | 260.401 / 35.202 ms |

This is a local engineering latency record, not live-LLM or production latency.
