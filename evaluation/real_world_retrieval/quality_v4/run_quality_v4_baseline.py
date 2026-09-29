"""Run the fixed BM25 reference once for the already-selected V4 candidate.

This fills the paired-comparison baseline omitted by the original one-policy
HOLDOUT runner. It cannot select a candidate or overwrite frozen inputs or the
selected candidate's one-shot result.
"""

from __future__ import annotations

import json
import time
from datetime import datetime, timezone

import run_quality_v4 as v4


ROOT = v4.ROOT
SELECTION_PATH = ROOT / "selection_lock.json"
EXECUTION_PATH = ROOT / "holdout_execution.json"
BASELINE_EXECUTION_PATH = ROOT / "baseline_execution.json"
BASELINE_RESULT_PATH = ROOT / "results" / "holdout__bm25_baseline.json"
CANDIDATE_RESULT_PATH = ROOT / "results" / "holdout__bm25_figure_ocr.json"


def validate_baseline_run(
    *, selection: dict, execution: dict, already_executed: bool,
    input_sha256: dict, candidate_fingerprint: dict,
) -> None:
    if already_executed:
        raise ValueError("baseline comparison has already been executed")
    if execution.get("status") != "completed" or execution.get("result_sha256") is None:
        raise ValueError("selected candidate HOLDOUT must be completed first")
    if not selection.get("policy") or selection.get("policy") == "bm25":
        raise ValueError("a non-baseline candidate must be locked first")
    if selection.get("policy") != execution.get("policy"):
        raise ValueError("candidate selection and HOLDOUT policy mismatch")
    if selection.get("input_sha256") != input_sha256 or execution.get("input_sha256") != input_sha256:
        raise ValueError("baseline comparison input hash mismatch")
    if selection.get("candidate_fingerprint") != candidate_fingerprint:
        raise ValueError("candidate selection fingerprint mismatch")
    if execution.get("candidate_fingerprint") != candidate_fingerprint:
        raise ValueError("candidate HOLDOUT fingerprint mismatch")


def compare_results(candidate: dict, baseline: dict) -> dict:
    """Apply the DEV-declared release thresholds to matched retrieval metrics."""
    c, b = candidate["overall"], baseline["overall"]
    cdoc = candidate["by_category"]["cross_document"]["complete_source_at_5"]
    bdoc = baseline["by_category"]["cross_document"]["complete_source_at_5"]
    cversion = candidate["by_category"]["cross_version"]["complete_source_at_5"]
    bversion = baseline["by_category"]["cross_version"]["complete_source_at_5"]
    checks = {
        "image_hit_at_5": c["image_hit_at_5"] >= 0.75,
        "complete_source_noninferiority": c["complete_source_at_5"] >= b["complete_source_at_5"] - 0.05,
        "anchor_noninferiority": c["anchor_recall_at_5"] >= b["anchor_recall_at_5"] - 0.05,
        "cross_document_noninferiority": cdoc >= bdoc,
        "cross_version_noninferiority": cversion >= bversion,
        "version_mismatch_zero": c["version_mismatch_count"] == 0,
        "latency_budget": c["warm_p95_ms"] <= 250,
        "no_answer_candidate_rate_noninferiority": (
            c["no_answer_nonempty_candidate_rate"] <= baseline["overall"]["no_answer_nonempty_candidate_rate"]
        ),
    }
    return {
        "checks": checks,
        "passed": all(checks.values()),
        "deltas": {
            "complete_source_at_5": c["complete_source_at_5"] - b["complete_source_at_5"],
            "anchor_recall_at_5": c["anchor_recall_at_5"] - b["anchor_recall_at_5"],
            "cross_document_complete_at_5": cdoc - bdoc,
            "cross_version_complete_at_5": cversion - bversion,
            "image_hit_at_5": c["image_hit_at_5"] - b["image_hit_at_5"],
            "warm_p95_ms": c["warm_p95_ms"] - b["warm_p95_ms"],
            "no_answer_nonempty_candidate_rate": (
                c["no_answer_nonempty_candidate_rate"] - baseline["overall"]["no_answer_nonempty_candidate_rate"]
            ),
        },
        "decision_basis": "Retrieval-only matched baseline gate; nDCG is excluded because the frozen V4 implementation can overcount duplicate chunks from one relevant source.",
    }


def _validate_candidate_artifact(execution: dict) -> dict:
    if not CANDIDATE_RESULT_PATH.is_file():
        raise FileNotFoundError("locked candidate HOLDOUT result is missing")
    if v4.sha256(CANDIDATE_RESULT_PATH) != execution["result_sha256"]:
        raise ValueError("locked candidate HOLDOUT result hash mismatch")
    candidate = json.loads(CANDIDATE_RESULT_PATH.read_text(encoding="utf-8"))
    if candidate.get("policy") != execution.get("policy") or candidate.get("split") != "holdout":
        raise ValueError("locked candidate HOLDOUT result metadata mismatch")
    return candidate


def run_baseline() -> dict:
    cases, split, lock, _, index = v4.load_frozen()
    selection = json.loads(SELECTION_PATH.read_text(encoding="utf-8"))
    execution = json.loads(EXECUTION_PATH.read_text(encoding="utf-8"))
    fingerprint = v4.candidate_fingerprint()
    validate_baseline_run(
        selection=selection,
        execution=execution,
        already_executed=BASELINE_EXECUTION_PATH.exists() or BASELINE_RESULT_PATH.exists(),
        input_sha256=lock["sha256"],
        candidate_fingerprint=fingerprint,
    )
    candidate = _validate_candidate_artifact(execution)
    # Record the one-shot baseline before making any retrieval calls. An
    # interruption is retained as failed and must be reported rather than retried.
    marker = {
        "policy": "bm25",
        "candidate_policy": selection["policy"],
        "candidate_result_sha256": execution["result_sha256"],
        "candidate_fingerprint": fingerprint,
        "input_sha256": lock["sha256"],
        "opened_at_utc": datetime.now(timezone.utc).isoformat(),
        "status": "running",
    }
    BASELINE_EXECUTION_PATH.write_text(json.dumps(marker, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    from src.public_retrieval_runtime import PublicRetrievalRuntime

    runtime = PublicRetrievalRuntime(index, sidecar_path=v4.SIDECAR)
    selected = [case for case in cases if case["query_id"] in set(split["holdout"])]
    for case in selected:
        runtime.search(case["query"], top_k=v4.TOP_K, version=case["version_scope"], language=case["language"], policy="bm25")
    ranked, elapsed, calls = {}, {}, {}
    for case in selected:
        started = time.perf_counter()
        ranked[case["query_id"]] = runtime.search(
            case["query"], top_k=v4.TOP_K, version=case["version_scope"],
            language=case["language"], policy="bm25",
        )
        elapsed[case["query_id"]] = (time.perf_counter() - started) * 1000
        calls[case["query_id"]] = runtime.last_retrieval_call_count
    baseline = v4.compute_metrics(selected, ranked, elapsed_ms=elapsed, retrieval_calls=calls)
    baseline.update({
        "split": "holdout",
        "policy": "bm25",
        "input_sha256": lock["sha256"],
        "candidate_policy": selection["policy"],
        "candidate_result_sha256": execution["result_sha256"],
        "interpretation": "Fixed BM25 reference for the preselected V4 candidate; retrieval metrics only.",
    })
    comparison = compare_results(candidate, baseline)
    payload = {
        "schema_version": 1,
        "baseline": baseline,
        "candidate": {
            "policy": candidate["policy"],
            "result_sha256": execution["result_sha256"],
            "overall": candidate["overall"],
            "by_category": candidate["by_category"],
        },
        "comparison": comparison,
        "input_sha256": lock["sha256"],
        "candidate_fingerprint": fingerprint,
        "measured_at_utc": datetime.now(timezone.utc).isoformat(),
    }
    BASELINE_RESULT_PATH.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    marker.update({"status": "completed", "result_sha256": v4.sha256(BASELINE_RESULT_PATH)})
    BASELINE_EXECUTION_PATH.write_text(json.dumps(marker, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return payload


if __name__ == "__main__":
    print(json.dumps(run_baseline(), ensure_ascii=False, indent=2))
