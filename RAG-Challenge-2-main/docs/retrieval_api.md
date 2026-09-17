# Frozen retrieval only API

`POST /retrieve` returns raw results from the validated R&D V2 frozen dense retriever. It does not call answer generation, structured output generation, BM25, hybrid fusion, or a reranker. The existing `GET /health`, `GET /artifacts/status`, and `POST /query` contracts remain available.

The request accepts `query` (nonempty string, at most 4000 characters) and `top_k` (integer 1–20, default 5):

```json
{"query": "系统最大并发要求是什么？", "top_k": 5}
```

The response contains the original query and ranked frozen chunk results:

```json
{
  "query": "系统最大并发要求是什么？",
  "results": [{
    "chunk_id": "source chunk ID",
    "document_id": "source document ID",
    "section_id": "source section ID",
    "section_path": ["source section title"],
    "page_number": 1,
    "content": "original chunk text",
    "content_hash": "lowercase SHA256 of NFKC and whitespace-normalized content",
    "similarity": 0.82,
    "rank": 1
  }]
}
```

`content` is the original `text` in the frozen chunk artifact. `page_number` is copied from its physical page mapping without an offset. `content_hash` is computed solely from that chunk text so downstream Evidence can validate its normalized-content identity. The service does not infer missing provenance. Invalid requests return 422. Runtime retrieval errors return 503 or 500 without exposing query or source text in the error body. Artifact validation runs before service startup and rejects incomplete lifecycle, hash, count, dimension, or retrieval-policy mismatches.

The formal private namespace remains `DENSE_ONLY` with `SECTION_PATH` representation. The separate `rd-v2-retrieval-final-v1.0-safe-integration` namespace contains only synthetic/public material for the Word workflow demo. Private results were used only for local API and provenance checks and were never sent to an online LLM.
