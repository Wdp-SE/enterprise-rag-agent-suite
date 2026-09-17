import json

import src.api_requests as api_requests
from src.reranking import LLMReranker


def test_rerank_score_can_change_vector_order(monkeypatch):
    reranker = LLMReranker(provider="dashscope", model="qwen-turbo")
    documents = [
        {"text": "vector first", "distance": 0.9, "page": 1},
        {"text": "llm first", "distance": 0.2, "page": 2},
    ]

    monkeypatch.setattr(
        reranker,
        "get_rank_for_multiple_blocks",
        lambda query, texts: {
            "block_rankings": [
                {"reasoning": "weak evidence", "relevance_score": 0.1},
                {"reasoning": "direct evidence", "relevance_score": 1.0},
            ]
        },
    )

    results = reranker.rerank_documents(
        "query",
        documents,
        documents_batch_size=2,
        llm_weight=0.7,
    )

    assert results[0]["text"] == "llm first"
    assert results[0]["relevance_score"] == 1.0
    assert results[0]["combined_score"] > results[1]["combined_score"]


def test_dashscope_rerank_returns_parsed_scores(monkeypatch):
    expected = {
        "block_rankings": [
            {"reasoning": "direct", "relevance_score": 0.9},
            {"reasoning": "unrelated", "relevance_score": 0.1},
        ]
    }

    class FakeGeneration:
        @staticmethod
        def call(**kwargs):
            return {
                "output": {
                    "choices": [
                        {"message": {"content": json.dumps(expected)}}
                    ]
                }
            }

    class FakeDashscope:
        api_key = None
        Generation = FakeGeneration

    monkeypatch.setattr(api_requests, "dashscope", FakeDashscope)
    reranker = LLMReranker(provider="dashscope", model="qwen-turbo")

    assert reranker.get_rank_for_multiple_blocks("query", ["a", "b"]) == expected


def test_rerank_uses_traceable_pre_rerank_score_without_overwriting_cosine(monkeypatch):
    reranker = LLMReranker(provider="dashscope", model="qwen-turbo")
    documents = [
        {
            "text": "version preferred",
            "distance": 0.5,
            "original_score": 0.5,
            "version_adjustment": 0.02,
            "final_pre_rerank_score": 0.52,
            "page": 1,
        }
    ]
    monkeypatch.setattr(
        reranker,
        "get_rank_for_multiple_blocks",
        lambda query, texts: {
            "block_rankings": [{"reasoning": "relevant", "relevance_score": 0.8}]
        },
    )
    result = reranker.rerank_documents("query", documents, documents_batch_size=2)[0]
    assert result["distance"] == 0.5
    assert result["original_score"] == 0.5
    assert result["combined_score"] == 0.716
