from __future__ import annotations

import json
from pathlib import Path

from src.public_knowledge import PublicKnowledgeIndex


PROJECT_ROOT = Path(__file__).resolve().parents[2]


def test_chinese_latest_scope_smoke_queries_retrieve_expected_sources():
    cases_path = PROJECT_ROOT / "evaluation" / "autoware_bilingual_v1" / "cases.jsonl"
    cases = [json.loads(line) for line in cases_path.read_text(encoding="utf-8").splitlines() if line.strip()]
    index = PublicKnowledgeIndex(PROJECT_ROOT / "versioned-rag-service" / "public_corpus_autoware")

    chinese_cases = [case for case in cases if case["language"] == "zh"]
    assert len(chinese_cases) >= 5
    for case in chinese_cases:
        hits = index.search(
            case["query"],
            version=case["version"],
            language=case["language"],
            top_k=5,
        )
        assert hits, case["id"]
        assert {hit["language"] for hit in hits} == {"zh"}, case["id"]
        assert any(hit["document_key"] in case["expected_document_keys"] for hit in hits), case["id"]
        assert all(hit["version"] == "community-zh-2026-07" for hit in hits), case["id"]
