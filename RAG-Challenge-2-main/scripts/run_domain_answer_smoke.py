"""Run a small, budgeted real-provider answer smoke on Domain Corpus v0.1.

This runner is deliberately limited to explicitly selected question ids.  It
records vector retrieval, reranking, structured answers, validated citations,
latency, and the provider-reported token usage without introducing a reject
threshold or changing the RAG pipeline.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.evaluation import evaluate_answers, evaluate_citations, load_evaluation_dataset
from src.questions_processing import QuestionsProcessor


DEFAULT_QUESTION_IDS = ["single-006", "cross-002", "unanswerable-003"]


def _compact_result(result: dict, rank: int) -> dict:
    return {
        "rank": rank,
        "document_id": result.get("document_id"),
        "document_title": result.get("document_title"),
        "page_number": result.get("page"),
        "chunk_id": result.get("chunk_id"),
        "cosine_similarity": result.get("distance"),
        "rerank_score": result.get("relevance_score"),
        "combined_score": result.get("combined_score"),
        "text_preview": result.get("text", "")[:240],
    }


def _sum_usage(calls: list[dict]) -> dict:
    input_tokens = sum(call.get("input_tokens") or 0 for call in calls)
    output_tokens = sum(call.get("output_tokens") or 0 for call in calls)
    return {
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "total_tokens": input_tokens + output_tokens,
    }


def run(args: argparse.Namespace) -> None:
    items = load_evaluation_dataset(args.dataset)
    by_id = {item.question_id: item for item in items}
    missing = set(args.question_id) - set(by_id)
    if missing:
        raise ValueError(f"unknown question ids: {sorted(missing)}")
    selected = [by_id[question_id] for question_id in args.question_id]

    databases = args.corpus_root / "databases"
    processor = QuestionsProcessor(
        vector_db_dir=databases / "vector_dbs",
        documents_dir=databases / "chunked_reports",
        routing_mode="generic",
        parent_document_retrieval=True,
        llm_reranking=True,
        llm_reranking_sample_size=args.rerank_sample_size,
        top_n_retrieval=args.top_n,
        parallel_requests=1,
        api_provider=args.answer_provider,
        answering_model=args.answer_model,
        embedding_provider=args.embedding_provider,
        embedding_model=args.embedding_model,
        rerank_provider=args.rerank_provider,
        rerank_model=args.rerank_model,
    )

    vector_results: list[dict] = []
    reranked_results: list[dict] = []
    rerank_usage_calls: list[dict] = []

    vector_retrieve = processor.retriever.vector_retriever.retrieve

    def capture_vector_retrieve(*call_args, **call_kwargs):
        results = vector_retrieve(*call_args, **call_kwargs)
        vector_results.clear()
        vector_results.extend(results)
        return results

    processor.retriever.vector_retriever.retrieve = capture_vector_retrieve

    rerank_send = processor.retriever.reranker.processor.send_message

    def capture_rerank_send(*call_args, **call_kwargs):
        response = rerank_send(*call_args, **call_kwargs)
        usage = processor.retriever.reranker.processor.processor.response_data
        rerank_usage_calls.append(dict(usage or {}))
        return response

    processor.retriever.reranker.processor.send_message = capture_rerank_send

    hybrid_retrieve = processor.retriever.retrieve

    def capture_hybrid_retrieve(*call_args, **call_kwargs):
        results = hybrid_retrieve(*call_args, **call_kwargs)
        reranked_results.clear()
        reranked_results.extend(results)
        return results

    processor.retriever.retrieve = capture_hybrid_retrieve

    outputs = []
    answers_by_question = {}
    citations_by_question = {}
    for item in selected:
        vector_results.clear()
        reranked_results.clear()
        rerank_usage_calls.clear()
        started = time.perf_counter()
        answer = None
        error = None
        try:
            answer = processor.process_question(item.question, item.answer_schema)
        except Exception as exc:  # Preserve real provider/runtime failure details.
            error = f"{type(exc).__name__}: {exc}"
        latency_ms = round((time.perf_counter() - started) * 1000, 3)
        answer_usage = dict(processor.response_data or {})
        all_usage_calls = [*rerank_usage_calls]
        if answer_usage:
            all_usage_calls.append(answer_usage)
        aggregate_usage = _sum_usage(all_usage_calls)
        sources = answer.get("sources", []) if answer else []
        final_answer = answer.get("final_answer") if answer else None
        answers_by_question[item.question_id] = {
            "final_answer": final_answer,
            "error": error,
            "citation_correct": None,
            "unsupported_claim": None,
        }
        citations_by_question[item.question_id] = sources
        before_keys = [
            (result.get("document_id"), result.get("page")) for result in vector_results
        ]
        after_keys = [
            (result.get("document_id"), result.get("page")) for result in reranked_results
        ]
        outputs.append(
            {
                "question_id": item.question_id,
                "question": item.question,
                "question_type": item.question_type,
                "answerable": item.answerable,
                "schema": item.answer_schema,
                "vector_results": [
                    _compact_result(result, rank)
                    for rank, result in enumerate(vector_results, start=1)
                ],
                "reranked_results": [
                    _compact_result(result, rank)
                    for rank, result in enumerate(reranked_results, start=1)
                ],
                "rerank_changed_order": before_keys[: len(after_keys)] != after_keys,
                "final_answer": final_answer,
                "answer_type": type(final_answer).__name__ if answer else None,
                "citations": sources,
                "provider": args.answer_provider,
                "models": {
                    "answer": args.answer_model,
                    "embedding": args.embedding_model,
                    "rerank": args.rerank_model,
                },
                "latency_ms": latency_ms,
                "rerank_usage_calls": rerank_usage_calls.copy(),
                "answer_usage": answer_usage,
                "aggregate_usage": aggregate_usage,
                "error": error,
            }
        )

    aggregate_usage = _sum_usage(
        [result["aggregate_usage"] for result in outputs]
    )
    per_question_tokens = [
        result["aggregate_usage"]["total_tokens"] for result in outputs
    ]
    formal_question_count = len(items)
    point_estimate = (
        aggregate_usage["total_tokens"] / len(selected) * formal_question_count
    )
    estimate_exceeds_budget = point_estimate > args.budget_boundary
    payload = {
        "run_kind": "domain_answer_smoke",
        "full_answer_evaluation_performed": False,
        "question_count": len(selected),
        "configuration": {
            "routing_mode": "generic",
            "parent_document_retrieval": True,
            "rerank_sample_size": args.rerank_sample_size,
            "top_n": args.top_n,
            "confidence_threshold": None,
            "reject_policy_added": False,
        },
        "usage_scope": (
            "DashScope rerank and answer calls only; query-embedding token usage "
            "is not reported by the current embedding response."
        ),
        "usage": aggregate_usage,
        "answer_metrics": evaluate_answers(selected, answers_by_question),
        "citation_metrics": evaluate_citations(
            selected,
            citations_by_question,
            evaluation_mode="generated_answer_citations_smoke_only",
        ),
        "results": outputs,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    budget_payload = {
        "decision": (
            "STOP_BEFORE_FULL_ANSWER_EVALUATION"
            if estimate_exceeds_budget
            else "WITHIN_BUDGET_BOUNDARY"
        ),
        "budget_boundary_tokens": args.budget_boundary,
        "estimate_basis": (
            "One real-provider Domain Corpus smoke using the same Generic "
            "Parent-Page + Qwen rerank + structured-answer path planned for "
            "the formal run."
        ),
        "smoke_questions": len(selected),
        "smoke_input_tokens": aggregate_usage["input_tokens"],
        "smoke_output_tokens": aggregate_usage["output_tokens"],
        "smoke_total_tokens": aggregate_usage["total_tokens"],
        "mean_tokens_per_question": round(
            aggregate_usage["total_tokens"] / len(selected), 6
        ),
        "minimum_observed_tokens_per_question": min(per_question_tokens),
        "maximum_observed_tokens_per_question": max(per_question_tokens),
        "formal_question_count": formal_question_count,
        "point_estimate_full_run_tokens": round(point_estimate, 6),
        "observed_range_extrapolation_tokens": {
            "minimum": min(per_question_tokens) * formal_question_count,
            "maximum": max(per_question_tokens) * formal_question_count,
        },
        "usage_scope": (
            "Rerank and answer calls only. Query-embedding tokens are excluded "
            "because the current embedding response does not report them."
        ),
        "full_answer_evaluation_performed": False,
    }
    (args.output.parent / "token_budget_estimate.json").write_text(
        json.dumps(budget_payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    answer_metrics = {
        "status": (
            "SMOKE_ONLY_FULL_RUN_SKIPPED_BY_BUDGET"
            if estimate_exceeds_budget
            else "SMOKE_ONLY_FULL_RUN_NOT_REQUESTED"
        ),
        "formal_question_count": formal_question_count,
        "formal_answer_evaluation_performed": False,
        "reason": (
            f"The {len(selected)}-question real-provider smoke used "
            f"{aggregate_usage['total_tokens']} rerank-plus-answer tokens. "
            f"A same-configuration {formal_question_count}-question run is "
            f"estimated at {round(point_estimate)} tokens against a "
            f"{args.budget_boundary}-token boundary."
        ),
        "smoke_question_count": len(selected),
        "smoke_answerable_questions": payload["answer_metrics"]["answerable_questions"],
        "smoke_answerable_accuracy": payload["answer_metrics"]["answerable_accuracy"],
        "smoke_unanswerable_questions": payload["answer_metrics"]["unanswerable_questions"],
        "smoke_unanswerable_refusal_rate": payload["answer_metrics"]["unanswerable_refusal_rate"],
        "smoke_key_point_coverage": payload["answer_metrics"]["key_point_coverage"],
        "manual_review_required_count": payload["answer_metrics"]["manual_review_required_count"],
        "limitations": [
            "Smoke metrics are not formal full-dataset answer metrics.",
            *payload["answer_metrics"]["limitations"],
        ],
        "details_file": args.output.name,
    }
    (args.output.parent / "answer_metrics.json").write_text(
        json.dumps(answer_metrics, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps(payload, ensure_ascii=False, indent=2))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    parser.add_argument("--corpus-root", type=Path, default=Path("data/domain_corpus"))
    parser.add_argument(
        "--dataset", type=Path, default=Path("data/evaluation/domain_eval_v0_1.jsonl")
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("reports/domain_evaluation_v0_1/answer_smoke_results.json"),
    )
    parser.add_argument("--question-id", action="append", default=[])
    parser.add_argument("--rerank-sample-size", type=int, default=4)
    parser.add_argument("--top-n", type=int, default=3)
    parser.add_argument("--budget-boundary", type=int, default=50000)
    parser.add_argument("--answer-provider", default="dashscope")
    parser.add_argument("--answer-model", default="qwen-turbo")
    parser.add_argument("--embedding-provider", default="dashscope")
    parser.add_argument("--embedding-model", default="text-embedding-v1")
    parser.add_argument("--rerank-provider", default="dashscope")
    parser.add_argument("--rerank-model", default="qwen-turbo")
    return parser


if __name__ == "__main__":
    parser = build_parser()
    arguments = parser.parse_args()
    if not arguments.question_id:
        arguments.question_id = DEFAULT_QUESTION_IDS
    run(arguments)
