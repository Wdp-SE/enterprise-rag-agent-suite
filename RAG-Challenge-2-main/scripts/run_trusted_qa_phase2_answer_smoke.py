"""Run the single bounded 5+5 Phase 2 answer smoke in non-enforcing mode."""

from __future__ import annotations

import json
import math
import sys
import time
from datetime import datetime, timezone
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.questions_processing import QuestionsProcessor
from src.trusted_qa import (
    decide_post_answer_candidate,
    evaluate_post_answer_candidates,
    load_frozen_holdout,
)


SELECTED_ANSWERABLE_IDS = (
    "tqa-holdout-a02",  # frozen retrieval miss / low-score answerable
    "tqa-holdout-a04",
    "tqa-holdout-a05",
    "tqa-holdout-a06",
    "tqa-holdout-a09",
)
SELECTED_HARD_NEGATIVE_IDS = (
    "tqa-holdout-n01",  # v0.1 false accept
    "tqa-holdout-n03",  # v0.1 false accept
    "tqa-holdout-n04",
    "tqa-holdout-n05",  # v0.1 false accept
    "tqa-holdout-n07",
)
SELECTED_IDS = SELECTED_ANSWERABLE_IDS + SELECTED_HARD_NEGATIVE_IDS
HISTORICAL_SMOKE_QUESTIONS = 6
HISTORICAL_SMOKE_TOKENS = 11822
CONSERVATIVE_FACTOR = 1.25
TOKEN_LIMIT = 30000


def _write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def main() -> None:
    report_dir = Path("reports/trusted_qa_phase2")
    items, freeze = load_frozen_holdout(
        Path("data/evaluation/trusted_qa_holdout_v0_1.jsonl"),
        Path("data/evaluation/trusted_qa_holdout_v0_1.freeze.json"),
    )
    dataset = {item.question_id: item for item in items}
    selected = [dataset[question_id] for question_id in SELECTED_IDS]
    if sum(item.answerable for item in selected) != 5:
        raise ValueError("answer smoke must contain exactly 5 answerable items")
    if sum(
        not item.answerable and item.negative_class.value == "HARD_NEGATIVE"
        for item in selected
    ) != 5:
        raise ValueError("answer smoke must contain exactly 5 hard negatives")

    point_estimate = math.ceil(
        HISTORICAL_SMOKE_TOKENS / HISTORICAL_SMOKE_QUESTIONS * len(selected)
    )
    conservative_estimate = math.ceil(point_estimate * CONSERVATIVE_FACTOR)
    estimate = {
        "estimate_created_before_answer_calls": True,
        "historical_source": "reports/trusted_qa_shadow_v0_1/answer_smoke_results.json",
        "historical_question_count": HISTORICAL_SMOKE_QUESTIONS,
        "historical_total_tokens": HISTORICAL_SMOKE_TOKENS,
        "selected_question_count": len(selected),
        "point_estimate_tokens": point_estimate,
        "conservative_factor": CONSERVATIVE_FACTOR,
        "conservative_estimate_tokens": conservative_estimate,
        "stop_threshold_tokens": TOKEN_LIMIT,
        "within_budget": conservative_estimate <= TOKEN_LIMIT,
        "selected_answerable_ids": list(SELECTED_ANSWERABLE_IDS),
        "selected_hard_negative_ids": list(SELECTED_HARD_NEGATIVE_IDS),
        "selection_basis": "Frozen retrieval-signal overlap plus the frozen retrieval miss; no policy tuning.",
    }
    _write_json(report_dir / "answer_smoke_token_estimate.json", estimate)
    if conservative_estimate > TOKEN_LIMIT:
        raise RuntimeError(
            f"conservative token estimate {conservative_estimate} exceeds {TOKEN_LIMIT}"
        )

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
    for item in selected:
        processor.response_data = None
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
        trace = trace_by_id.get(item.question_id)
        audit = trace["post_answer_audit"] if trace else None
        candidate = (
            decide_post_answer_candidate(audit).model_dump(mode="json")
            if audit
            else None
        )
        results.append(
            {
                "question_id": item.question_id,
                "question": item.question,
                "ground_truth_answerable": item.answerable,
                "negative_class": (
                    item.negative_class.value
                    if item.negative_class is not None
                    else None
                ),
                "reference_answer": item.reference_answer,
                "key_points": item.key_points,
                "unanswerable_reason": item.unanswerable_reason,
                "pre_generation_shadow_decision": (
                    trace["shadow_decision"]["decision"] if trace else None
                ),
                "pre_generation_reason_codes": (
                    trace["shadow_decision"]["reason_codes"] if trace else []
                ),
                "signal_snapshot": trace["signal_snapshot"] if trace else None,
                "post_answer_audit": audit,
                "post_answer_candidate": candidate,
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
        "run_kind": "trusted_qa_phase2_bounded_real_answer_smoke",
        "started_at_utc": started_at,
        "completed_at_utc": datetime.now(timezone.utc).isoformat(),
        "dataset_id": freeze.dataset_id,
        "dataset_sha256": freeze.dataset_sha256,
        "holdout_contaminated": freeze.holdout_contaminated,
        "question_count": len(results),
        "answerable_count": sum(
            result["ground_truth_answerable"] for result in results
        ),
        "hard_negative_count": sum(
            result["negative_class"] == "HARD_NEGATIVE" for result in results
        ),
        "configuration": {
            "trusted_qa_mode": "SHADOW",
            "pre_generation_policy_version": "trusted_qa_shadow_v0_1",
            "post_answer_candidate_policy_version": "trusted_qa_post_answer_candidate_v0_1",
            "answer_provider": "dashscope",
            "answer_model": "qwen-turbo",
            "embedding_provider": "dashscope",
            "embedding_model": "text-embedding-v1",
            "rerank_enabled": False,
            "top_k": 5,
            "parent_page": True,
            "gate_extra_llm_calls": 0,
            "response_enforcement_performed": False,
        },
        "usage": {
            "prompt_tokens": input_tokens,
            "completion_tokens": output_tokens,
            "total_tokens": input_tokens + output_tokens,
            "within_pre_run_limit": input_tokens + output_tokens <= TOKEN_LIMIT,
            "scope": "Answer generation only; query embedding usage is not reported by the provider response.",
        },
        "results": results,
    }
    _write_json(report_dir / "answer_smoke_results.json", payload)
    _write_json(
        report_dir / "post_answer_candidate_metrics.json",
        {
            "run_metadata": {
                "dataset_id": freeze.dataset_id,
                "question_count": len(results),
                "post_answer_policy": "trusted_qa_post_answer_candidate_v0_1",
                "shadow_only": True,
                "response_enforcement_performed": False,
            },
            **evaluate_post_answer_candidates(results),
        },
    )


if __name__ == "__main__":
    main()
