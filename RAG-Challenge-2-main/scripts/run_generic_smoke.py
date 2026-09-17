import argparse
import json
import sys
import time
from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))

from src.questions_processing import QuestionsProcessor


DEFAULT_QUESTIONS = [
    {
        "id": "G01",
        "schema": "text",
        "question": "Who remained the Chief Executive Officer after the President and CEO roles were split in 2022?",
    },
    {
        "id": "G02",
        "schema": "boolean",
        "question": "Did the reporting entity open a staffed branch on the Moon during 2022?",
    },
]


def _compact_retrieval_result(result):
    return {
        "document_id": result["document_id"],
        "document_title": result["document_title"],
        "page_number": result["page"],
        "similarity_score": result["distance"],
        "relevance_score": result.get("relevance_score"),
        "combined_score": result.get("combined_score"),
        "chunk_id": result.get("chunk_id"),
    }


def main():
    parser = argparse.ArgumentParser(description="Run a small real-provider generic RAG smoke test.")
    parser.add_argument("dataset_root", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    databases = args.dataset_root / "databases"
    processor = QuestionsProcessor(
        vector_db_dir=databases / "vector_dbs",
        documents_dir=databases / "chunked_reports",
        routing_mode="generic",
        parent_document_retrieval=True,
        llm_reranking=True,
        llm_reranking_sample_size=4,
        top_n_retrieval=3,
        parallel_requests=1,
        api_provider="dashscope",
        answering_model="qwen-turbo",
        embedding_provider="dashscope",
        embedding_model="text-embedding-v1",
        rerank_provider="dashscope",
        rerank_model="qwen-turbo",
    )

    captured_results = []
    original_retrieve = processor.retriever.retrieve

    def capture_retrieve(*args, **kwargs):
        results = original_retrieve(*args, **kwargs)
        captured_results.clear()
        captured_results.extend(results)
        return results

    processor.retriever.retrieve = capture_retrieve
    smoke_results = []
    for item in DEFAULT_QUESTIONS:
        captured_results.clear()
        started = time.perf_counter()
        error = None
        answer = None
        try:
            answer = processor.process_question(item["question"], item["schema"])
        except Exception as exc:  # The artifact records real provider/runtime failures.
            error = f"{type(exc).__name__}: {exc}"
        latency_ms = round((time.perf_counter() - started) * 1000, 2)
        smoke_results.append(
            {
                **item,
                "routing_mode": processor.routing_mode,
                "provider": processor.api_provider,
                "models": {
                    "answer": processor.answering_model,
                    "embedding": processor.embedding_model,
                    "rerank": processor.rerank_model,
                },
                "retrieved": [
                    _compact_retrieval_result(result) for result in captured_results
                ],
                "final_answer": answer.get("final_answer") if answer else None,
                "sources": answer.get("sources", []) if answer else [],
                "latency_ms": latency_ms,
                "answer_usage": processor.response_data,
                "error": error,
            }
        )

    payload = {
        "document_count": len(processor.retriever.vector_retriever.all_dbs),
        "question_count": len(DEFAULT_QUESTIONS),
        "results": smoke_results,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(payload, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
