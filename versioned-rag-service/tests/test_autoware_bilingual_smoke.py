from __future__ import annotations

import json
from pathlib import Path

from src.public_knowledge import PublicKnowledgeIndex


PROJECT_ROOT = Path(__file__).resolve().parents[2]


def test_bilingual_latest_scope_smoke_queries_retrieve_expected_sources():
    cases_path = PROJECT_ROOT / "evaluation" / "autoware_bilingual_v1" / "cases.jsonl"
    cases = [json.loads(line) for line in cases_path.read_text(encoding="utf-8").splitlines() if line.strip()]
    index = PublicKnowledgeIndex(PROJECT_ROOT / "versioned-rag-service" / "public_corpus_autoware")

    assert len(cases) >= 10
    for case in cases:
        hits = index.search(
            case["query"],
            version=case["version"],
            language=case["language"],
            top_k=5,
        )
        assert hits, case["id"]
        assert {hit["language"] for hit in hits} == {case["language"]}, case["id"]
        assert any(hit["document_key"] in case["expected_document_keys"] for hit in hits), case["id"]
        assert all(hit["version"] in {"docs-main", "0.52.0"} for hit in hits), case["id"]
