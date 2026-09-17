"""Local provenance smoke for /retrieve; never prints retrieved body text."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
import unicodedata
from pathlib import Path

import httpx


QUERIES = (
    "系统最大并发要求是什么？",
    "研发文档有哪些验收依据？",
    "项目实施阶段如何划分？",
    "测试报告需要记录哪些内容？",
)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", default="http://127.0.0.1:8765")
    parser.add_argument("--artifact-root", type=Path, required=True)
    args = parser.parse_args()
    manifest = json.loads((args.artifact_root / "artifact_manifest.json").read_text(encoding="utf-8"))
    project_root = Path(__file__).resolve().parents[1]
    chunks_path = project_root / manifest["artifacts"]["chunk_artifact"]["path"]
    chunks = {
        item["chunk_id"]: item
        for item in (json.loads(line) for line in chunks_path.read_text(encoding="utf-8").splitlines())
    }
    with httpx.Client(base_url=args.url, timeout=120) as client:
        health = client.get("/health")
        health.raise_for_status()
        assert health.json()["artifact_status"] == "COMPLETE"
        assert health.json()["retrieval_policy"] == "DENSE_ONLY"
        assert health.json()["dense_representation"] == "SECTION_PATH"
        for query in QUERIES:
            response = client.post("/retrieve", json={"query": query, "top_k": 5})
            response.raise_for_status()
            hits = response.json()["results"]
            assert len(hits) == 5
            assert [hit["rank"] for hit in hits] == [1, 2, 3, 4, 5]
            for hit in hits:
                chunk = chunks[hit["chunk_id"]]
                assert hit["document_id"] == chunk["document_id"]
                assert hit["section_id"] == chunk["section_id"]
                assert hit["section_path"] == chunk["section_path"]
                assert hit["page_number"] == chunk["page_number"]
                assert hit["content"] == chunk["text"]
                normalized = re.sub(r"\s+", " ", unicodedata.normalize("NFKC", chunk["text"])).strip()
                assert hit["content_hash"] == hashlib.sha256(normalized.encode()).hexdigest()
                assert math.isfinite(hit["similarity"])
        assert len(client.post("/retrieve", json={"query": QUERIES[0], "top_k": 1}).json()["results"]) == 1
    print("RAG_SERVICE_START=PASS STARTUP_VALIDATION=PASS POST_RETRIEVE=PASS")
    print("TOP_K=PASS CHUNK_ID_EXISTS=PASS DOCUMENT_ID_VALID=PASS SECTION_METADATA_VALID=PASS")
    print("PAGE_NUMBER_VALID=PASS CONTENT_MATCHES_ARTIFACT=PASS RANK_VALID=PASS SIMILARITY_VALID=PASS")
    print(f"queries={len(QUERIES)} artifact_status={manifest['status']}")


if __name__ == "__main__":
    main()
