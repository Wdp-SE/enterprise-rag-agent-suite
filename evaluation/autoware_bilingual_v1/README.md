# Autoware bilingual corpus expansion smoke set

This directory contains a small regression smoke set for the expanded Autoware corpus. It exercises Chinese-only and English-only queries against the default composite `latest` scope and checks that an expected source appears in Top-5.

This is **not** a retrieval benchmark and its pass count is not a quality metric. The ten hand-written examples are not a representative user sample, have no DEV/HOLDOUT split, and do not measure answer correctness, hallucination, latency, no-answer rejection, cross-version discrimination, or image understanding. They exist to catch broken language/version filters and obviously disconnected source paths while the proper bilingual evaluation is prepared.

The current BM25 policy remains a transparent baseline. The earlier Autoware V3 comparison was measured against a much smaller corpus and has a different corpus fingerprint; it is not valid for these sources. Do not promote faceted BM25, OCR, dense, hybrid, or reranking candidates until a frozen bilingual DEV/HOLDOUT set demonstrates source recall, complete required-source coverage, version correctness, no-answer behavior, image evidence coverage, and latency against this exact corpus and implementation.

Run the smoke contract from `versioned-rag-service/`:

```powershell
python -m pytest tests/test_autoware_bilingual_smoke.py -q
```

Queries and expected document routes are in [`cases.jsonl`](cases.jsonl). Keep the examples grounded in the pinned sources, and freeze any future benchmark split before using it for strategy selection.
