"""Run a bounded real-answer smoke for Trusted QA post-answer observation."""

from __future__ import annotations

import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.evaluation import load_evaluation_dataset
from src.questions_processing import QuestionsProcessor


SELECTED_IDS = (
    "single-001",
    "cross-006",
    "version-002",
    "unanswerable-001",
    "unanswerable-004",
    "unanswerable-007",
)


def main() -> None:
    dataset = {
        item.question_id: item
        for item in load_evaluation_dataset(
            Path("data/evaluation/domain_eval_v0_1.jsonl")
        )
    }
    processor = QuestionsProcessor(
        vector_db_dir=Path("data/domain_corpus_v0_2/databases/vector_dbs"),
        documents_dir=Path("data/domain_corpus_v0_2/databases/chunked_reports"),
        questions_file_path=None,
        parent_document_retrieval=True,
        llm_reranking=False,
        llm_reranking_sample_size=8,
        top_n_retrieval=5,
        parallel_requests=1,
        api_provider="dashscope",
        answering_model="qwen-turbo",
        embedding_provider="dashscope",
        embedding_model="text-embedding-v1",
        routing_mode="generic",
        version_governance_enabled=True,
        version_manifest_path=Path(
            "data/domain_corpus_v0_2/domain_corpus_manifest.json"
        ),
        historical_vector_db_dir=Path(
            "data/domain_corpus_v0_2/historical_retrieval_assets/databases/vector_dbs"
        ),
        historical_documents_dir=Path(
            "data/domain_corpus_v0_2/historical_retrieval_assets/databases/chunked_reports"
        ),
        version_as_of_date="2026-09-01",
        trusted_qa_mode="SHADOW",
        trusted_qa_policy_profile="HARD_PLUS_SOFT",
    )

    results = []
    input_tokens = 0
    output_tokens = 0
    started_at = datetime.now(timezone.utc).isoformat()
    for question_id in SELECTED_IDS:
        item = dataset[question_id]
        started = time.perf_counter()
        error = None
        answer = None
        try:
            answer = processor.get_answer_generic(
                item.question,
                item.answer_schema,
                question_id=item.question_id,
            )
        except Exception as exc:
            error = f"{type(exc).__name__}: {exc}"
        latency_ms = round((time.perf_counter() - started) * 1000, 3)
        usage = dict(processor.response_data or {})
        input_tokens += int(usage.get("input_tokens") or 0)
        output_tokens += int(usage.get("output_tokens") or 0)
        trace_by_id = {
            trace["question_id"]: trace
            for trace in processor.get_trusted_qa_traces()
        }
        trace = trace_by_id.get(question_id)
        results.append(
            {
                "question_id": question_id,
                "question": item.question,
                "ground_truth_answerable": item.answerable,
                "question_type": item.question_type,
                "shadow_decision": (
                    trace["shadow_decision"]["decision"] if trace else None
                ),
                "shadow_reason_codes": (
                    trace["shadow_decision"]["reason_codes"] if trace else []
                ),
                "post_answer_audit": (
                    trace["post_answer_audit"] if trace else None
                ),
                "actual_pipeline_result": {
                    "final_answer": answer.get("final_answer") if answer else None,
                    "sources": answer.get("sources", []) if answer else [],
                    "error": error,
                },
                "answer_usage": usage,
                "latency_ms": latency_ms,
            }
        )

    payload = {
        "run_kind": "trusted_qa_bounded_real_answer_smoke",
        "started_at_utc": started_at,
        "completed_at_utc": datetime.now(timezone.utc).isoformat(),
        "question_count": len(results),
        "answerable_count": sum(
            result["ground_truth_answerable"] for result in results
        ),
        "unanswerable_count": sum(
            not result["ground_truth_answerable"] for result in results
        ),
        "configuration": {
            "trusted_qa_mode": "SHADOW",
            "policy_version": "trusted_qa_shadow_v0_1",
            "answer_provider": "dashscope",
            "answer_model": "qwen-turbo",
            "embedding_model": "text-embedding-v1",
            "rerank_enabled": False,
            "top_k": 5,
            "parent_page": True,
            "gate_extra_llm_calls": 0,
        },
        "usage": {
            "prompt_tokens": input_tokens,
            "completion_tokens": output_tokens,
            "total_tokens": input_tokens + output_tokens,
            "scope": "Answer generation only; query embedding usage is not reported by the provider response.",
        },
        "results": results,
    }
    output = Path(
        "reports/trusted_qa_shadow_v0_1/answer_smoke_results.json"
    )
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


if __name__ == "__main__":
    main()
