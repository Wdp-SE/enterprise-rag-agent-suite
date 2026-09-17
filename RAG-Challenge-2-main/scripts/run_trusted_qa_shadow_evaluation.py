"""Run retrieval-only Trusted QA shadow evaluation without answer or rerank calls."""

from __future__ import annotations

import argparse
import json
import sys
import time
from collections import Counter
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
    collect_retrieval_signals,
    decide_evidence_sufficiency,
    evaluate_shadow_decisions,
    not_available_answer_audit,
)
from src.versioning import VersionResolver


PROFILES = (
    ShadowPolicyProfile.HARD_ONLY,
    ShadowPolicyProfile.HARD_PLUS_SOFT,
    ShadowPolicyProfile.HARD_SOFT_AGREEMENT,
)

HARD_NEGATIVE_CLASSIFICATION = {
    "unanswerable-001": (
        "HARD",
        "The corpus contains accident-reporting rules and retrieves them strongly, but not the requested 2025 national accident count.",
    ),
    "unanswerable-002": (
        "HARD",
        "The corpus discusses elevator safety responsibility and insurance duties, but contains no enterprise-specific annual premium.",
    ),
    "unanswerable-003": (
        "EASY_OR_MEDIUM",
        "The request is commercial price/vendor information; retrieved elevator material is only indirectly related.",
    ),
    "unanswerable-004": (
        "HARD",
        "National registration and penalty provisions are highly similar, but the requested unnamed local rule is absent.",
    ),
    "unanswerable-005": (
        "EASY_OR_MEDIUM",
        "Emergency and elevator-operation text is nearby, but a mandated AI algorithm is outside the corpus evidence.",
    ),
    "unanswerable-006": (
        "HARD",
        "Safety-director duties and qualifications are present, while a national minimum salary is not.",
    ),
    "unanswerable-007": (
        "HARD",
        "The current TSG 08—2026 publication is retrieved directly, but it cannot establish a future revision publication date.",
    ),
}


def _write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def _evaluate_scope(rows: list[dict], dataset_id: str) -> dict:
    selected = [row for row in rows if row["dataset_id"] == dataset_id]
    return evaluate_shadow_decisions(selected)


def _decision_row(
    *,
    dataset_id: str,
    item,
    snapshot,
    decision,
    latency_ms: float,
) -> dict:
    state = decision.decision.value
    is_false_reject = bool(item.answerable and state == "REJECT")
    is_false_accept = bool(not item.answerable and state == "ANSWER")
    return {
        "dataset_id": dataset_id,
        "question_id": item.question_id,
        "ground_truth_answerable": item.answerable,
        "question_type": item.question_type,
        "signal_snapshot": snapshot.model_dump(mode="json"),
        "preconditions": [
            precondition.model_dump(mode="json")
            for precondition in decision.preconditions
        ],
        "shadow_decision": state,
        "reason_codes": [reason.value for reason in decision.reason_codes],
        "signals_used": decision.signals_used,
        "policy_version": decision.policy_version,
        "post_answer_audit": not_available_answer_audit().model_dump(mode="json"),
        "actual_pipeline_result": "RETRIEVAL_ONLY_NO_GENERATION",
        "retrieval_latency_ms": round(latency_ms, 3),
        "is_shadow_false_reject": is_false_reject,
        "is_shadow_false_accept": is_false_accept,
    }


def run(args: argparse.Namespace) -> None:
    manifest = load_corpus_manifest(args.manifest, verify_source_files=True)
    datasets = {
        "domain_eval_v0_1": load_evaluation_dataset(args.domain_dataset),
        "version_eval_v0_1": load_evaluation_dataset(args.version_dataset),
    }
    documents_dir = args.corpus_root / "databases" / "chunked_reports"
    vector_dir = args.corpus_root / "databases" / "vector_dbs"
    historical_documents = (
        args.historical_corpus_root / "databases" / "chunked_reports"
    )
    historical_vectors = (
        args.historical_corpus_root / "databases" / "vector_dbs"
    )
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

    rows_by_profile = {profile: [] for profile in PROFILES}
    snapshot_rows = []
    started_at = datetime.now(timezone.utc).isoformat()
    for dataset_id, items in datasets.items():
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
            latency_ms = (time.perf_counter() - started) * 1000
            snapshot = collect_retrieval_signals(
                question_id=item.question_id,
                retrieval_results=results,
                version_governance_enabled=True,
                version_plan=version_plan,
            )
            snapshot_rows.append(
                {
                    "dataset_id": dataset_id,
                    "ground_truth_answerable": item.answerable,
                    "question_type": item.question_type,
                    "snapshot": snapshot.model_dump(mode="json"),
                    "retrieval_latency_ms": round(latency_ms, 3),
                }
            )
            for profile in PROFILES:
                decision = decide_evidence_sufficiency(
                    snapshot,
                    mode=TrustedQAMode.SHADOW,
                    profile=profile,
                )
                rows_by_profile[profile].append(
                    _decision_row(
                        dataset_id=dataset_id,
                        item=item,
                        snapshot=snapshot,
                        decision=decision,
                        latency_ms=latency_ms,
                    )
                )

    default_rows = rows_by_profile[ShadowPolicyProfile.HARD_PLUS_SOFT]
    run_metadata = {
        "run_kind": "trusted_qa_retrieval_only_shadow",
        "started_at_utc": started_at,
        "completed_at_utc": datetime.now(timezone.utc).isoformat(),
        "trusted_qa_mode": "SHADOW",
        "default_policy_version": POLICY_VERSIONS[
            ShadowPolicyProfile.HARD_PLUS_SOFT
        ],
        "answer_llm_called": False,
        "rerank_called": False,
        "gate_extra_llm_calls": 0,
        "generation_performed": False,
        "embedding_provider": args.embedding_provider,
        "embedding_model": args.embedding_model,
        "top_k": args.top_k,
        "per_document_top_k": args.per_document_top_k,
        "version_governance_enabled": True,
        "version_as_of_date": args.version_as_of_date,
        "corpus_root": args.corpus_root.as_posix(),
        "historical_corpus_root": args.historical_corpus_root.as_posix(),
    }

    shadow_metrics = {
        "run_metadata": run_metadata,
        "default_policy": POLICY_VERSIONS[
            ShadowPolicyProfile.HARD_PLUS_SOFT
        ],
        "domain": _evaluate_scope(default_rows, "domain_eval_v0_1"),
        "version_stress": _evaluate_scope(default_rows, "version_eval_v0_1"),
        "combined": evaluate_shadow_decisions(default_rows),
        "interpretation": "Counterfactual Shadow metrics; not production accuracy.",
    }
    policy_ablation = {
        "run_metadata": run_metadata,
        "threshold_search_performed": False,
        "profiles": {
            profile.value: {
                "policy_version": POLICY_VERSIONS[profile],
                "domain": _evaluate_scope(rows, "domain_eval_v0_1"),
                "version_stress": _evaluate_scope(rows, "version_eval_v0_1"),
                "combined": evaluate_shadow_decisions(rows),
            }
            for profile, rows in rows_by_profile.items()
        },
        "policy_definitions": {
            "HARD_ONLY": "Hard preconditions; otherwise ANSWER.",
            "HARD_PLUS_SOFT": "Hard preconditions plus calibration-only strong-score ANSWER region; all other valid results are UNCERTAIN.",
            "HARD_SOFT_AGREEMENT": "HARD_PLUS_SOFT plus factual document/page-neighborhood agreement observations for ANSWER; never hard-rejects on cosine.",
        },
    }

    domain_unanswerable = {
        row["question_id"]: row
        for row in default_rows
        if row["dataset_id"] == "domain_eval_v0_1"
        and not row["ground_truth_answerable"]
    }
    hard_negative_rows = []
    for question_id, (classification, rationale) in HARD_NEGATIVE_CLASSIFICATION.items():
        row = domain_unanswerable[question_id]
        hard_negative_rows.append(
            {
                "question_id": question_id,
                "classification": classification,
                "rationale": rationale,
                "top1_score": row["signal_snapshot"]["top1_score"],
                "top5_scores": row["signal_snapshot"]["top5_scores"],
                "retrieved_document_count": row["signal_snapshot"][
                    "retrieved_document_count"
                ],
                "shadow_decision": row["shadow_decision"],
                "reason_codes": row["reason_codes"],
            }
        )
    hard_counts = Counter(row["classification"] for row in hard_negative_rows)
    hard_negative_audit = {
        "audit_scope": "existing 7 domain_eval_v0_1 unanswerable questions",
        "classification_method": "Manual semantic audit against corpus scope plus live retrieval observations; no LLM judge.",
        "counts": dict(sorted(hard_counts.items())),
        "hard_negative_minimum_met": hard_counts["HARD"] >= 5,
        "new_hard_negatives_added": 0,
        "reason_no_addition": "Five existing cases meet the hard-negative definition, so the optional dataset expansion was not used.",
        "questions": hard_negative_rows,
    }

    false_rejects = [row for row in default_rows if row["is_shadow_false_reject"]]
    false_accepts = [row for row in default_rows if row["is_shadow_false_accept"]]
    uncertain = [
        {
            "dataset_id": row["dataset_id"],
            "question_id": row["question_id"],
            "ground_truth_answerable": row["ground_truth_answerable"],
            "reason_codes": row["reason_codes"],
            "top1_score": row["signal_snapshot"]["top1_score"],
            "top3_mean": row["signal_snapshot"]["top3_mean"],
        }
        for row in default_rows
        if row["shadow_decision"] == "UNCERTAIN"
    ]
    failure_cases = {
        "policy_version": POLICY_VERSIONS[
            ShadowPolicyProfile.HARD_PLUS_SOFT
        ],
        "false_rejects": false_rejects,
        "false_accepts": false_accepts,
        "uncertain_cases": uncertain,
        "note": "UNCERTAIN is an observation queue, not a production failure.",
    }

    _write_json(
        args.report_dir / "signal_snapshots.json",
        {"run_metadata": run_metadata, "snapshots": snapshot_rows},
    )
    _write_json(
        args.report_dir / "shadow_decisions.json",
        {"run_metadata": run_metadata, "decisions": default_rows},
    )
    _write_json(args.report_dir / "shadow_metrics.json", shadow_metrics)
    _write_json(args.report_dir / "shadow_failure_cases.json", failure_cases)
    _write_json(args.report_dir / "policy_ablation.json", policy_ablation)
    _write_json(args.report_dir / "hard_negative_audit.json", hard_negative_audit)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
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
        default=Path(
            "data/domain_corpus_v0_2/historical_retrieval_assets"
        ),
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
        "--report-dir",
        type=Path,
        default=Path("reports/trusted_qa_shadow_v0_1"),
    )
    parser.add_argument("--embedding-provider", default="dashscope")
    parser.add_argument("--embedding-model", default="text-embedding-v1")
    parser.add_argument("--top-k", type=int, default=5)
    parser.add_argument("--per-document-top-k", type=int, default=8)
    parser.add_argument("--version-as-of-date", default="2026-09-01")
    return parser


if __name__ == "__main__":
    run(build_parser().parse_args())
