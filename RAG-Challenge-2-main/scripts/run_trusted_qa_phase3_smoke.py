"""Run one bounded 2+2 real ENFORCE smoke after local verification passes."""

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
from src.trusted_qa import load_frozen_holdout


SELECTED_IDS = (
    "tqa-holdout-a06",
    "tqa-holdout-a09",
    "tqa-holdout-n04",
    "tqa-holdout-n07",
)
HISTORICAL_QUESTION_COUNT = 10
HISTORICAL_TOTAL_TOKENS = 23183
CONSERVATIVE_FACTOR = 1.25
TOKEN_LIMIT = 20000
REPORT_DIR = PROJECT_ROOT / "reports/trusted_qa_phase3"


def _write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def main() -> None:
    point_estimate = math.ceil(
        HISTORICAL_TOTAL_TOKENS / HISTORICAL_QUESTION_COUNT * len(SELECTED_IDS)
    )
    conservative_estimate = math.ceil(point_estimate * CONSERVATIVE_FACTOR)
    estimate = {
        "estimate_created_before_answer_calls": True,
        "historical_source": "reports/trusted_qa_phase2/answer_smoke_results.json",
        "historical_question_count": HISTORICAL_QUESTION_COUNT,
        "historical_total_tokens": HISTORICAL_TOTAL_TOKENS,
        "selected_question_count": len(SELECTED_IDS),
        "point_estimate_tokens": point_estimate,
        "conservative_factor": CONSERVATIVE_FACTOR,
        "conservative_estimate_tokens": conservative_estimate,
        "stop_threshold_tokens": TOKEN_LIMIT,
        "within_budget": conservative_estimate <= TOKEN_LIMIT,
        "selected_question_ids": list(SELECTED_IDS),
    }
    _write_json(REPORT_DIR / "runtime_smoke_token_estimate.json", estimate)
    if conservative_estimate > TOKEN_LIMIT:
        raise RuntimeError(
            f"conservative estimate {conservative_estimate} exceeds {TOKEN_LIMIT}"
        )

    items, freeze = load_frozen_holdout(
        PROJECT_ROOT / "data/evaluation/trusted_qa_holdout_v0_1.jsonl",
        PROJECT_ROOT / "data/evaluation/trusted_qa_holdout_v0_1.freeze.json",
    )
    dataset = {item.question_id: item for item in items}
    selected = [dataset[question_id] for question_id in SELECTED_IDS]
    if sum(item.answerable for item in selected) != 2:
        raise ValueError("Phase 3 smoke must contain exactly two answerable items")
    if sum(not item.answerable for item in selected) != 2:
        raise ValueError("Phase 3 smoke must contain exactly two hard negatives")

    processor = QuestionsProcessor(
        # FAISS on this Windows environment cannot reliably open non-ASCII
        # absolute paths. Keep the same project-root relative paths used by the
        # already verified Phase 2 runtime script.
        vector_db_dir=Path("data/domain_corpus_v0_2/databases/vector_dbs"),
        documents_dir=Path("data/domain_corpus_v0_2/databases/chunked_reports"),
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
        trusted_qa_mode="ENFORCE",
        trusted_qa_policy_profile="HARD_PLUS_SOFT",
        trusted_qa_enforcement_scope="POST_ANSWER_ONLY",
    )

    results = []
    prompt_tokens = 0
    completion_tokens = 0
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
        prompt_tokens += int(usage.get("input_tokens") or 0)
        completion_tokens += int(usage.get("output_tokens") or 0)
        trace = {
            row["question_id"]: row for row in processor.get_trusted_qa_traces()
        }.get(item.question_id)
        audit = trace["post_answer_audit"] if trace else None
        enforcement = trace["post_answer_enforcement"] if trace else None
        results.append(
            {
                "question_id": item.question_id,
                "question": item.question,
                "ground_truth_answerable": item.answerable,
                "negative_class": (
                    item.negative_class.value if item.negative_class else None
                ),
                "reference_answer": item.reference_answer,
                "unanswerable_reason": item.unanswerable_reason,
                "pre_generation_shadow_decision": (
                    trace["shadow_decision"]["decision"] if trace else None
                ),
                "generation_result": (
                    trace["original_pipeline_result"] if trace else None
                ),
                "structured_output_valid": (
                    audit["structured_output_valid"] if audit else None
                ),
                "citation_count": audit["citation_count"] if audit else None,
                "citation_membership_valid": (
                    audit["citation_membership_valid"] if audit else None
                ),
                "post_answer_action": enforcement["action"] if enforcement else None,
                "reason_codes": enforcement["reason_codes"] if enforcement else [],
                "enforced": enforcement["enforced"] if enforcement else False,
                "final_result": {
                    "final_answer": answer.get("final_answer") if answer else None,
                    "sources": answer.get("sources", []) if answer else [],
                    "error": error,
                },
                "answer_usage": usage,
                "latency_ms": latency_ms,
            }
        )

    total_tokens = prompt_tokens + completion_tokens
    payload = {
        "run_kind": "trusted_qa_phase3_bounded_real_enforce_smoke",
        "started_at_utc": started_at,
        "completed_at_utc": datetime.now(timezone.utc).isoformat(),
        "dataset_id": freeze.dataset_id,
        "dataset_sha256": freeze.dataset_sha256,
        "question_count": len(results),
        "answerable_count": 2,
        "hard_negative_count": 2,
        "configuration": {
            "trusted_qa_mode": "ENFORCE",
            "enforcement_scope": "POST_ANSWER_ONLY",
            "pre_generation_enforcement": False,
            "post_answer_enforcement": True,
            "pre_generation_policy_version": "trusted_qa_shadow_v0_1",
            "post_answer_policy_version": "trusted_qa_post_answer_v1",
            "answer_provider": "dashscope",
            "answer_model": "qwen-turbo",
            "embedding_provider": "dashscope",
            "embedding_model": "text-embedding-v1",
            "rerank_enabled": False,
            "top_k": 5,
            "parent_page": True,
            "gate_extra_llm_calls": 0,
            "semantic_entailment_verified": False,
        },
        "usage": {
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
            "total_tokens": total_tokens,
            "within_limit": total_tokens <= TOKEN_LIMIT,
            "scope": "Answer generation only; query embedding usage is not reported by the provider response.",
        },
        "results": results,
    }
    _write_json(REPORT_DIR / "runtime_smoke_results.json", payload)
    print(json.dumps(payload, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
