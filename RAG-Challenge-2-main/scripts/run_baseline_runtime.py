"""Run and persist a real-provider RAG baseline verification trace.

The script reuses the project's vector retrieval, parent-page retrieval, LLM
reranker, structured answer generation, and citation validation. It stores
scores and safe document fingerprints instead of complete retrieved pages.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import time
from pathlib import Path
from typing import Any

import faiss
import numpy as np


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))

from src.api_requests import APIProcessor
from src.questions_processing import QuestionsProcessor
from src.reranking import LLMReranker
from src.retrieval import VectorRetriever
from src.vector_utils import l2_normalize_rows


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("runtime_root", type=Path)
    parser.add_argument("--queries", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--sample-size", type=int, default=8)
    parser.add_argument("--top-n", type=int, default=4)
    parser.add_argument("--batch-size", type=int, default=4)
    parser.add_argument("--max-questions", type=int)
    parser.add_argument("--answer-model", default="qwen-turbo")
    parser.add_argument("--rerank-model", default="qwen-turbo")
    parser.add_argument("--embedding-model", default="text-embedding-v1")
    return parser.parse_args()


def _load_json(path: Path) -> Any:
    with path.open("r", encoding="utf-8") as file:
        return json.load(file)


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as file:
        json.dump(payload, file, ensure_ascii=False, indent=2)


def _safe_document_record(document: dict[str, Any], rank: int) -> dict[str, Any]:
    text = document.get("text", "")
    return {
        "rank": rank,
        "page": document.get("page"),
        "similarity_score": document.get("distance"),
        "relevance_score": document.get("relevance_score"),
        "combined_score": document.get("combined_score"),
        "text_length": len(text),
        "text_sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(),
    }


def _sum_usage(calls: list[dict[str, Any]]) -> dict[str, int | None]:
    input_values = [call.get("input_tokens") for call in calls]
    output_values = [call.get("output_tokens") for call in calls]
    known_inputs = [value for value in input_values if isinstance(value, int)]
    known_outputs = [value for value in output_values if isinstance(value, int)]
    input_tokens = sum(known_inputs) if len(known_inputs) == len(input_values) else None
    output_tokens = sum(known_outputs) if len(known_outputs) == len(output_values) else None
    total_tokens = (
        input_tokens + output_tokens
        if input_tokens is not None and output_tokens is not None
        else None
    )
    return {
        "prompt_tokens": input_tokens,
        "completion_tokens": output_tokens,
        "total_tokens": total_tokens,
    }


def _verify_indexes(vector_retriever: VectorRetriever) -> list[dict[str, Any]]:
    verification = []
    for report in vector_retriever.all_dbs:
        index = report["vector_db"]
        vectors = index.reconstruct_n(0, index.ntotal)
        norms = np.linalg.norm(vectors, axis=1) if index.ntotal else np.array([])
        chunks = report["document"]["content"]["chunks"]
        verification.append(
            {
                "document_id": report["name"],
                "company_name": report["document"]["metainfo"].get("company_name"),
                "index_type": type(index).__name__,
                "metric_type": int(index.metric_type),
                "metric_is_inner_product": index.metric_type == faiss.METRIC_INNER_PRODUCT,
                "dimension": index.d,
                "vector_count": index.ntotal,
                "chunk_count": len(chunks),
                "vector_chunk_count_match": index.ntotal == len(chunks),
                "norm_min": float(norms.min()) if len(norms) else None,
                "norm_max": float(norms.max()) if len(norms) else None,
                "norm_mean": float(norms.mean()) if len(norms) else None,
                "all_norms_close_to_one": bool(
                    len(norms) and np.allclose(norms, 1.0, atol=1e-4)
                ),
            }
        )
    return verification


def _target_document(retriever: VectorRetriever, company_name: str) -> dict[str, Any]:
    for report in retriever.all_dbs:
        if report["document"]["metainfo"].get("company_name") == company_name:
            return report["document"]
    raise ValueError(f"No report found with '{company_name}' company name.")


def main() -> None:
    args = parse_args()
    runtime_root = args.runtime_root.absolute()
    queries = _load_json(args.queries.absolute())
    if args.max_questions is not None:
        queries = queries[: args.max_questions]

    vector_retriever = VectorRetriever(
        vector_db_dir=runtime_root / "databases" / "vector_dbs",
        documents_dir=runtime_root / "databases" / "chunked_reports",
        embedding_provider="dashscope",
        embedding_model=args.embedding_model,
    )
    reranker = LLMReranker(provider="dashscope", model=args.rerank_model)
    answer_processor = APIProcessor(provider="dashscope", capability="answer")
    citation_helper = QuestionsProcessor(
        questions_file_path=None,
        new_challenge_pipeline=True,
        subset_path=runtime_root / "subset.csv",
        api_provider="dashscope",
        answering_model=args.answer_model,
        embedding_provider="dashscope",
        embedding_model=args.embedding_model,
        rerank_provider="dashscope",
        rerank_model=args.rerank_model,
    )

    query_embedding_norms: list[dict[str, float]] = []
    original_get_embedding = vector_retriever._get_embedding

    def tracked_get_embedding(text: str):
        embedding = original_get_embedding(text)
        raw = np.asarray(embedding, dtype="float32")
        normalized = l2_normalize_rows(raw)
        query_embedding_norms.append(
            {
                "raw_norm": float(np.linalg.norm(raw)),
                "normalized_norm": float(np.linalg.norm(normalized[0])),
            }
        )
        return embedding

    vector_retriever._get_embedding = tracked_get_embedding

    rerank_usage_calls: list[dict[str, Any]] = []
    original_rerank_send = reranker.processor.send_message

    def tracked_rerank_send(*call_args, **call_kwargs):
        response = original_rerank_send(*call_args, **call_kwargs)
        usage = getattr(reranker.processor.processor, "response_data", {})
        rerank_usage_calls.append(dict(usage or {}))
        return response

    reranker.processor.send_message = tracked_rerank_send

    payload: dict[str, Any] = {
        "run_metadata": {
            "provider": "dashscope",
            "answer_model": args.answer_model,
            "rerank_model": args.rerank_model,
            "embedding_model": args.embedding_model,
            "parent_page_retrieval": True,
            "rerank_sample_size": args.sample_size,
            "top_n": args.top_n,
            "documents_batch_size": args.batch_size,
            "confidence_gate_enabled": False,
            "question_count": len(queries),
        },
        "index_verification": _verify_indexes(vector_retriever),
        "results": [],
    }

    for position, query in enumerate(queries, start=1):
        started = time.perf_counter()
        rerank_usage_calls.clear()
        query_embedding_norms.clear()
        result: dict[str, Any] = {
            "id": query["id"],
            "question": query["question"],
            "company_name": query["company_name"],
            "kind": query["kind"],
            "category": query["category"],
            "expected_behavior": query.get("expected_behavior"),
            "expected_value": query.get("expected_value"),
            "provider": "dashscope",
            "models": {
                "embedding": args.embedding_model,
                "rerank": args.rerank_model,
                "answer": args.answer_model,
            },
            "confidence_gate_applied": False,
            "error": None,
        }
        try:
            retrieval_started = time.perf_counter()
            initial = vector_retriever.retrieve_by_company_name(
                company_name=query["company_name"],
                query=query["question"],
                top_n=args.sample_size,
                return_parent_pages=True,
            )
            retrieval_ms = round((time.perf_counter() - retrieval_started) * 1000, 2)

            target = _target_document(vector_retriever, query["company_name"])
            page_text = {
                page["page"]: page["text"] for page in target["content"]["pages"]
            }
            parent_links_valid = all(
                item.get("page") in page_text
                and item.get("text") == page_text[item.get("page")]
                for item in initial
            )

            rerank_started = time.perf_counter()
            reranked = reranker.rerank_documents(
                query=query["question"],
                documents=initial,
                documents_batch_size=args.batch_size,
                llm_weight=0.7,
            )
            rerank_ms = round((time.perf_counter() - rerank_started) * 1000, 2)
            selected = reranked[: args.top_n]

            before_order = [item["page"] for item in initial]
            after_order = [item["page"] for item in reranked]
            rag_context = citation_helper._format_retrieval_results(selected)

            generation_started = time.perf_counter()
            answer = answer_processor.get_answer_from_rag_context(
                question=query["question"],
                rag_context=rag_context,
                schema=query["kind"],
                model=args.answer_model,
            )
            generation_ms = round((time.perf_counter() - generation_started) * 1000, 2)

            claimed_pages = answer.get("relevant_pages", []) if isinstance(answer, dict) else []
            validated_pages = citation_helper._validate_page_references(
                claimed_pages, selected
            )
            citations = citation_helper._extract_references(
                validated_pages, query["company_name"]
            )
            filtered_pages = sorted(set(claimed_pages) - set(validated_pages))

            generation_usage = dict(answer_processor.response_data or {})
            all_usage = rerank_usage_calls + [generation_usage]
            token_usage = _sum_usage(all_usage)

            final_answer = answer.get("final_answer") if isinstance(answer, dict) else answer
            result.update(
                {
                    "retrieved_documents": [
                        _safe_document_record(item, rank)
                        for rank, item in enumerate(initial, start=1)
                    ],
                    "retrieved_pages": [item["page"] for item in initial],
                    "retrieval_scores": [item["distance"] for item in initial],
                    "query_embedding_norm": query_embedding_norms[-1]
                    if query_embedding_norms
                    else None,
                    "cosine_scores_in_range": all(
                        -1.0001 <= item["distance"] <= 1.0001 for item in initial
                    ),
                    "parent_page_links_valid": parent_links_valid,
                    "reranked_documents": [
                        _safe_document_record(item, rank)
                        for rank, item in enumerate(reranked, start=1)
                    ],
                    "rerank_scores": [
                        {
                            "page": item["page"],
                            "relevance_score": item["relevance_score"],
                            "combined_score": item["combined_score"],
                        }
                        for item in reranked
                    ],
                    "rerank_changed_order": before_order != after_order,
                    "selected_pages": [item["page"] for item in selected],
                    "structured_output_parsed": isinstance(answer, dict)
                    and {"step_by_step_analysis", "reasoning_summary", "relevant_pages", "final_answer"}.issubset(answer),
                    "final_answer": final_answer,
                    "answer_type": "N/A"
                    if final_answer == "N/A"
                    else type(final_answer).__name__,
                    "reasoning_summary": answer.get("reasoning_summary", "")
                    if isinstance(answer, dict)
                    else "",
                    "claimed_pages": claimed_pages,
                    "validated_pages": validated_pages,
                    "filtered_hallucinated_pages": filtered_pages,
                    "citations": citations,
                    "latency_ms": {
                        "retrieval": retrieval_ms,
                        "rerank": rerank_ms,
                        "generation": generation_ms,
                        "total": round((time.perf_counter() - started) * 1000, 2),
                    },
                    "prompt_tokens": token_usage["prompt_tokens"],
                    "completion_tokens": token_usage["completion_tokens"],
                    "total_tokens": token_usage["total_tokens"],
                    "token_breakdown": {
                        "rerank_calls": rerank_usage_calls.copy(),
                        "generation_call": generation_usage,
                        "embedding_usage_included": False,
                    },
                }
            )
            print(
                f"[{position}/{len(queries)}] {query['id']} ok "
                f"answer={final_answer!r} total_ms={result['latency_ms']['total']}"
            )
        except Exception as error:
            result["latency_ms"] = {
                "total": round((time.perf_counter() - started) * 1000, 2)
            }
            result["error"] = {
                "type": type(error).__name__,
                "message": str(error),
            }
            print(f"[{position}/{len(queries)}] {query['id']} error={type(error).__name__}")

        payload["results"].append(result)
        _write_json(args.output.absolute(), payload)


if __name__ == "__main__":
    main()
