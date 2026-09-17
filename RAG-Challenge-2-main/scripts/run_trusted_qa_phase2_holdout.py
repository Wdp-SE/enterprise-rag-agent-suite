"""Run the frozen Trusted QA v0.1 policy once on the frozen held-out set."""

from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import date, datetime, timezone
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.evaluation import load_corpus_manifest, load_evaluation_dataset
from src.retrieval import VectorRetriever
from src.trusted_qa import (
    POLICY_VERSIONS,
    ShadowPolicyProfile,
    TrustedQAMode,
    assert_exact_independence,
    collect_retrieval_signals,
    decide_evidence_sufficiency,
    evaluate_holdout_shadow,
    load_frozen_holdout,
    not_available_answer_audit,
)
from src.versioning import VersionResolver


PHASE1_SMOKE_IDS = {
    "single-001",
    "cross-006",
    "version-002",
    "unanswerable-001",
    "unanswerable-004",
    "unanswerable-007",
}
FROZEN_POLICY = POLICY_VERSIONS[ShadowPolicyProfile.HARD_PLUS_SOFT]


def _write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def _decision_path(snapshot, decision) -> list[str]:
    triggered = [
        item.reason_code.value for item in decision.preconditions if item.triggered
    ]
    if triggered:
        return ["DETERMINISTIC_PRECONDITION", *triggered, decision.decision.value]
    if decision.decision.value == "ANSWER":
        return [
            "RETRIEVAL_STATE_VALID",
            "NO_HARD_PRECONDITION",
            "CALIBRATION_STRONG_SCORE_REGION",
            "ANSWER",
        ]
    return [
        "RETRIEVAL_STATE_VALID",
        "NO_HARD_PRECONDITION",
        decision.reason_codes[0].value,
        "UNCERTAIN",
    ]


def run(args: argparse.Namespace) -> None:
    items, freeze = load_frozen_holdout(args.dataset, args.freeze_metadata)
    calibration_sets = [
        load_evaluation_dataset(args.domain_dataset),
        load_evaluation_dataset(args.version_dataset),
    ]
    assert_exact_independence(
        items,
        calibration_sets,
        excluded_question_ids=PHASE1_SMOKE_IDS,
    )
    manifest = load_corpus_manifest(args.manifest, verify_source_files=True)
    if manifest.corpus_id != freeze.source_corpus_id or manifest.corpus_version != freeze.source_corpus_version:
        raise ValueError("holdout freeze metadata does not match the configured corpus")
    if FROZEN_POLICY != freeze.frozen_policy_version:
        raise ValueError("frozen policy identity drift detected")

    documents_dir = args.corpus_root / "databases" / "chunked_reports"
    vector_dir = args.corpus_root / "databases" / "vector_dbs"
    historical_documents = args.historical_corpus_root / "databases" / "chunked_reports"
    historical_vectors = args.historical_corpus_root / "databases" / "vector_dbs"
    retriever = VectorRetriever(
        vector_dir,
        documents_dir,
        embedding_provider=args.embedding_provider,
        embedding_model=args.embedding_model,
        additional_corpora=[(historical_vectors, historical_documents)],
    )
    resolver = VersionResolver(
        manifest,
        as_of_date=date.fromisoformat(args.version_as_of_date),
    )

    started_at = datetime.now(timezone.utc).isoformat()
    snapshots = []
    decisions = []
    for item in items:
        started = time.perf_counter()
        version_plan = resolver.resolve(
            item.question,
            available_document_ids=retriever.document_ids,
        )
        results = retriever.retrieve(
            query=item.question,
            top_n=args.top_k,
            per_document_top_k=args.per_document_top_k,
            return_parent_pages=True,
            version_plan=version_plan,
        )
        latency_ms = round((time.perf_counter() - started) * 1000, 3)
        snapshot = collect_retrieval_signals(
            question_id=item.question_id,
            retrieval_results=results,
            version_governance_enabled=True,
            version_plan=version_plan,
        )
        decision = decide_evidence_sufficiency(
            snapshot,
            mode=TrustedQAMode.SHADOW,
            profile=ShadowPolicyProfile.HARD_PLUS_SOFT,
        )
        expected_pages = {
            (page.document_id, page.page_number) for page in item.expected_pages
        }
        retrieved_pages = {
            (page.document_id, page.page_number) for page in snapshot.page_ids
        }
        expected_documents = set(item.expected_document_ids)
        retrieved_documents = set(snapshot.document_ids)
        negative_class = (
            item.negative_class.value if item.negative_class is not None else None
        )
        snapshot_row = {
            "question_id": item.question_id,
            "ground_truth_answerable": item.answerable,
            "question_type": item.question_type,
            "difficulty": item.difficulty.value,
            "negative_class": negative_class,
            "expected_document_hit": (
                bool(expected_documents & retrieved_documents)
                if item.answerable
                else None
            ),
            "expected_page_hit": (
                bool(expected_pages & retrieved_pages) if item.answerable else None
            ),
            "snapshot": snapshot.model_dump(mode="json"),
            "version_trace": version_plan.trace(question_id=item.question_id),
            "retrieval_latency_ms": latency_ms,
        }
        snapshots.append(snapshot_row)
        decisions.append(
            {
                "question_id": item.question_id,
                "ground_truth_answerable": item.answerable,
                "question_type": item.question_type,
                "difficulty": item.difficulty.value,
                "negative_class": negative_class,
                "unanswerable_reason": item.unanswerable_reason,
                "signal_snapshot": snapshot.model_dump(mode="json"),
                "preconditions": [
                    condition.model_dump(mode="json")
                    for condition in decision.preconditions
                ],
                "shadow_decision": decision.decision.value,
                "reason_codes": [code.value for code in decision.reason_codes],
                "signals_used": decision.signals_used,
                "decision_path": _decision_path(snapshot, decision),
                "policy_version": decision.policy_version,
                "post_answer_audit": not_available_answer_audit().model_dump(
                    mode="json"
                ),
                "actual_pipeline_result": "RETRIEVAL_ONLY_NO_GENERATION",
                "retrieval_latency_ms": latency_ms,
            }
        )

    completed_at = datetime.now(timezone.utc).isoformat()
    run_metadata = {
        "run_kind": "trusted_qa_frozen_holdout_retrieval_shadow",
        "started_at_utc": started_at,
        "completed_at_utc": completed_at,
        "dataset_id": freeze.dataset_id,
        "dataset_sha256": freeze.dataset_sha256,
        "holdout_contaminated": freeze.holdout_contaminated,
        "policy_version": FROZEN_POLICY,
        "policy_adjusted_before_run": False,
        "answer_llm_called": False,
        "rerank_called": False,
        "gate_extra_llm_calls": 0,
        "generation_performed": False,
        "embedding_provider": args.embedding_provider,
        "embedding_model": args.embedding_model,
        "top_k": args.top_k,
        "per_document_top_k": args.per_document_top_k,
        "parent_page": True,
        "version_governance_enabled": True,
        "version_as_of_date": args.version_as_of_date,
    }
    metrics = {
        "run_metadata": run_metadata,
        **evaluate_holdout_shadow(decisions),
    }
    rejects = [row for row in decisions if row["shadow_decision"] == "REJECT"]
    reject_precision_evidence = {
        "observed_reject_count": len(rejects),
        "verified_unanswerable_reject_count": sum(
            not row["ground_truth_answerable"] for row in rejects
        ),
        "observed_reject_precision": (
            round(
                sum(not row["ground_truth_answerable"] for row in rejects)
                / len(rejects),
                6,
            )
            if rejects
            else None
        ),
        "sample_status": (
            "SAMPLE_SIZE_INSUFFICIENT" if len(rejects) < 5 else "OBSERVED_ONLY"
        ),
        "manual_review_required_before_enforcement": True,
        "rejects": rejects,
    }
    hard_rows = [
        row for row in decisions if row["negative_class"] == "HARD_NEGATIVE"
    ]
    hard_negative_analysis = {
        "dataset_id": freeze.dataset_id,
        "classification_method": "Manual Ground Truth review against the frozen corpus before policy execution; no LLM judge.",
        "hard_negative_count": len(hard_rows),
        "decisions": {
            state: sum(row["shadow_decision"] == state for row in hard_rows)
            for state in ("ANSWER", "REJECT", "UNCERTAIN")
        },
        "questions": [
            {
                "question_id": row["question_id"],
                "unanswerable_reason": row["unanswerable_reason"],
                "top1_score": row["signal_snapshot"]["top1_score"],
                "top5_scores": row["signal_snapshot"]["top5_scores"],
                "shadow_decision": row["shadow_decision"],
                "reason_codes": row["reason_codes"],
                "decision_path": row["decision_path"],
            }
            for row in hard_rows
        ],
    }
    dataset_reference = {
        "dataset_id": freeze.dataset_id,
        "dataset_file": freeze.dataset_file,
        "freeze_metadata_file": args.freeze_metadata.as_posix(),
        "dataset_sha256": freeze.dataset_sha256,
        "status": freeze.status,
        "frozen_at": freeze.frozen_at.isoformat(),
        "question_count": freeze.question_count,
        "answerable_count": freeze.answerable_count,
        "unanswerable_count": freeze.unanswerable_count,
        "easy_negative_count": freeze.easy_negative_count,
        "hard_negative_count": freeze.hard_negative_count,
        "ground_truth_review": freeze.ground_truth_review,
        "exact_overlap_found": False,
        "holdout_contaminated": freeze.holdout_contaminated,
    }

    _write_json(
        args.report_dir / "holdout_dataset_reference.json", dataset_reference
    )
    _write_json(
        args.report_dir / "holdout_signal_snapshots.json",
        {"run_metadata": run_metadata, "snapshots": snapshots},
    )
    _write_json(
        args.report_dir / "holdout_shadow_decisions_v0_1.json",
        {"run_metadata": run_metadata, "decisions": decisions},
    )
    _write_json(args.report_dir / "holdout_shadow_metrics_v0_1.json", metrics)
    _write_json(args.report_dir / "hard_negative_analysis.json", hard_negative_analysis)
    _write_json(
        args.report_dir / "pre_generation_reject_evidence.json",
        reject_precision_evidence,
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--dataset",
        type=Path,
        default=Path("data/evaluation/trusted_qa_holdout_v0_1.jsonl"),
    )
    parser.add_argument(
        "--freeze-metadata",
        type=Path,
        default=Path("data/evaluation/trusted_qa_holdout_v0_1.freeze.json"),
    )
    parser.add_argument(
        "--domain-dataset",
        type=Path,
        default=Path("data/evaluation/domain_eval_v0_1.jsonl"),
    )
    parser.add_argument(
        "--version-dataset",
        type=Path,
        default=Path("data/evaluation/version_eval_v0_1.jsonl"),
    )
    parser.add_argument(
        "--corpus-root", type=Path, default=Path("data/domain_corpus_v0_2")
    )
    parser.add_argument(
        "--manifest",
        type=Path,
        default=Path("data/domain_corpus_v0_2/domain_corpus_manifest.json"),
    )
    parser.add_argument(
        "--historical-corpus-root",
        type=Path,
        default=Path("data/domain_corpus_v0_2/historical_retrieval_assets"),
    )
    parser.add_argument(
        "--report-dir", type=Path, default=Path("reports/trusted_qa_phase2")
    )
    parser.add_argument("--embedding-provider", default="dashscope")
    parser.add_argument("--embedding-model", default="text-embedding-v1")
    parser.add_argument("--top-k", type=int, default=5)
    parser.add_argument("--per-document-top-k", type=int, default=8)
    parser.add_argument("--version-as-of-date", default="2026-09-01")
    return parser


if __name__ == "__main__":
    run(build_parser().parse_args())
