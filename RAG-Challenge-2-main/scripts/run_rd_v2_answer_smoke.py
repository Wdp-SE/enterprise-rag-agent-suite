"""Run three bounded real-provider end-to-end queries through rd_hybrid."""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.questions_processing import QuestionsProcessor


SMOKE_QUESTIONS = [
    {
        "id": "SM01",
        "schema": "text",
        "question": "What does POST /api/v2/ingest do?",
    },
    {
        "id": "SM02",
        "schema": "number",
        "question": "What is the maximum supported concurrent user count?",
    },
    {
        "id": "SM03",
        "schema": "text",
        "question": "How many days are exported packages retained before deletion?",
    },
]


def _usage(payload) -> dict:
    payload = payload or {}
    prompt = payload.get("input_tokens", payload.get("prompt_tokens"))
    completion = payload.get("output_tokens", payload.get("completion_tokens"))
    values = [value for value in (prompt, completion) if isinstance(value, int)]
    return {
        "model": payload.get("model"),
        "prompt_tokens": prompt,
        "completion_tokens": completion,
        "total_tokens": sum(values) if len(values) == 2 else None,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--corpus-root", type=Path, default=Path("data/rd_v2_prototype")
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("reports/rd_v2_prototype/answer_smoke_results.json"),
    )
    args = parser.parse_args()
    databases = args.corpus_root / "databases"
    processor = QuestionsProcessor(
        vector_db_dir=databases / "vector_dbs",
        documents_dir=databases / "chunked_reports",
        routing_mode="generic",
        retrieval_mode="rd_hybrid",
        parent_document_retrieval=False,
        llm_reranking=True,
        llm_reranking_sample_size=4,
        top_n_retrieval=2,
        parallel_requests=1,
        api_provider="dashscope",
        answering_model="qwen-turbo",
        embedding_provider="dashscope",
        embedding_model="text-embedding-v1",
        rerank_provider="dashscope",
        rerank_model="qwen-turbo",
        dense_top_k=4,
        bm25_top_k=4,
        fusion_top_k=4,
        rerank_top_k=2,
        neighbor_children=1,
        context_max_tokens=600,
        trusted_qa_mode="ENFORCE",
        trusted_qa_policy_profile="HARD_PLUS_SOFT",
        trusted_qa_enforcement_scope="POST_ANSWER_ONLY",
    )

    retrieved = []
    original_retrieve = processor.retriever.retrieve

    def capture_retrieve(*positional, **keywords):
        result = original_retrieve(*positional, **keywords)
        retrieved.clear()
        retrieved.extend(result)
        return result

    processor.retriever.retrieve = capture_retrieve
    results = []
    for item in SMOKE_QUESTIONS:
        retrieved.clear()
        processor.response_data = None
        started = time.perf_counter()
        answer = None
        error = None
        try:
            answer = processor.process_question(
                item["question"], item["schema"], question_id=item["id"]
            )
        except Exception as exc:
            error = f"{type(exc).__name__}: {exc}"
        latency_ms = round((time.perf_counter() - started) * 1000, 3)
        retrieved_keys = {
            (result.get("document_id"), result.get("page")) for result in retrieved
        }
        sources = answer.get("sources", []) if isinstance(answer, dict) else []
        citations_valid = all(
            (source.get("document_id"), source.get("page_number")) in retrieved_keys
            for source in sources
        )
        rerank_api = processor.retriever.reranker.processor
        rerank_usage = _usage(
            getattr(getattr(rerank_api, "processor", None), "response_data", None)
        )
        answer_usage = _usage(processor.response_data)
        combined_total_tokens = (
            answer_usage["total_tokens"] + rerank_usage["total_tokens"]
            if answer_usage["total_tokens"] is not None
            and rerank_usage["total_tokens"] is not None
            else None
        )
        results.append(
            {
                **item,
                "retrieval_mode": "rd_hybrid",
                "answer_model": processor.answering_model,
                "rerank_model": processor.rerank_model,
                "latency_ms": latency_ms,
                "retrieved": [
                    {
                        "document_id": result.get("document_id"),
                        "page_number": result.get("page"),
                        "chunk_id": result.get("chunk_id"),
                        "section_id": result.get("section_id"),
                        "context_role": result.get("context_role"),
                        "retrieval_sources": result.get("retrieval_sources"),
                    }
                    for result in retrieved
                ],
                "final_answer": answer.get("final_answer") if answer else None,
                "sources": sources,
                "structured_output_success": bool(
                    isinstance(answer, dict) and "final_answer" in answer
                ),
                "citation_membership_success": citations_valid,
                "answer_usage": answer_usage,
                "rerank_usage": rerank_usage,
                "combined_total_tokens": combined_total_tokens,
                "error": error,
            }
        )

    payload = {
        "query_count": len(SMOKE_QUESTIONS),
        "provider": "dashscope",
        "results": results,
        "trusted_qa_mode": "ENFORCE",
        "trusted_qa_traces": processor.get_trusted_qa_traces(),
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(
        json.dumps(
            {
                "query_count": payload["query_count"],
                "answers": [
                    {
                        "id": result["id"],
                        "final_answer": result["final_answer"],
                        "structured_output_success": result[
                            "structured_output_success"
                        ],
                        "citation_membership_success": result[
                            "citation_membership_success"
                        ],
                        "error": result["error"],
                    }
                    for result in results
                ],
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
