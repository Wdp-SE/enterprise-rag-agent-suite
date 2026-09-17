"""Replay Phase 2 saved answers through the deterministic Phase 3 policy."""

from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.trusted_qa import (
    apply_post_answer_enforcement,
    decide_post_answer_enforcement,
)


SOURCE_RESULTS = PROJECT_ROOT / "reports/trusted_qa_phase2/answer_smoke_results.json"
SOURCE_REVIEW = PROJECT_ROOT / "reports/trusted_qa_phase2/answer_smoke_manual_review.json"
OUTPUT_DIR = PROJECT_ROOT / "reports/trusted_qa_phase3"


def _write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def _ratio(numerator: int, denominator: int) -> float | None:
    return round(numerator / denominator, 6) if denominator else None


def build_replay() -> tuple[dict, dict]:
    saved = json.loads(SOURCE_RESULTS.read_text(encoding="utf-8"))
    review = json.loads(SOURCE_REVIEW.read_text(encoding="utf-8"))
    review_by_id = {item["question_id"]: item for item in review["items"]}
    rows = []
    for item in saved["results"]:
        decision = decide_post_answer_enforcement(
            item["post_answer_audit"], mode="ENFORCE"
        )
        original_result = item["actual_pipeline_result"]
        final_result = apply_post_answer_enforcement(
            original_result,
            decision,
            citation_fields=("sources",),
        )
        manual = review_by_id[item["question_id"]]
        rows.append(
            {
                "question_id": item["question_id"],
                "ground_truth_answerable": item["ground_truth_answerable"],
                "negative_class": item["negative_class"],
                "pre_generation_shadow_decision": item[
                    "pre_generation_shadow_decision"
                ],
                "post_answer_audit": item["post_answer_audit"],
                "manual_result": manual["manual_result"],
                "expected_candidate_action": manual[
                    "post_answer_candidate_action"
                ],
                "enforcement_decision": decision.model_dump(mode="json"),
                "original_result": original_result,
                "final_result": final_result,
            }
        )

    replay = {
        "run_kind": "trusted_qa_phase3_offline_post_answer_replay",
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "source_results": str(SOURCE_RESULTS.relative_to(PROJECT_ROOT)),
        "source_manual_review": str(SOURCE_REVIEW.relative_to(PROJECT_ROOT)),
        "question_count": len(rows),
        "answer_llm_called": False,
        "retrieval_called": False,
        "gate_extra_llm_calls": 0,
        "pre_generation_enforcement": False,
        "post_answer_enforcement": True,
        "enforcement_scope": "POST_ANSWER_ONLY",
        "policy_version": "trusted_qa_post_answer_v1",
        "results": rows,
    }

    known_invalid = [
        row
        for row in rows
        if row["manual_result"]
        in {"ANSWER_CONTENT_ADEQUATE_BUT_UNTRACEABLE", "INCOMPLETE_AND_UNTRACEABLE"}
    ]
    known_valid_answers = [
        row for row in rows if row["manual_result"] == "ANSWER_CONTENT_ADEQUATE"
    ]
    valid_abstentions = [
        row for row in rows if row["manual_result"] == "CORRECT_ABSTENTION"
    ]
    retrieval_miss = [
        row for row in rows if row["manual_result"] == "FALSE_ABSTENTION"
    ]
    intercepted = sum(
        row["enforcement_decision"]["action"] == "FAIL_CLOSED"
        and row["enforcement_decision"]["enforced"]
        for row in known_invalid
    )
    valid_preserved = sum(
        row["enforcement_decision"]["action"] == "PASS"
        and row["final_result"] == row["original_result"]
        for row in known_valid_answers
    )
    abstentions_preserved = sum(
        row["enforcement_decision"]["action"] == "VALID_ABSTENTION"
        and row["final_result"] == row["original_result"]
        for row in valid_abstentions
    )
    false_fail_closed = sum(
        row["enforcement_decision"]["action"] == "FAIL_CLOSED"
        for row in known_valid_answers + valid_abstentions
    )
    citation_failures = [
        row
        for row in rows
        if row["enforcement_decision"]["reason_codes"]
        == ["CITATION_MEMBERSHIP_INVALID"]
    ]
    metrics = {
        "metric_scope": "saved_phase2_replay_plus_manual_labels_not_production_accuracy",
        "policy_version": "trusted_qa_post_answer_v1",
        "question_count": len(rows),
        "known_invalid_count": len(known_invalid),
        "known_invalid_intercepted_count": intercepted,
        "known_invalid_interception_rate": _ratio(intercepted, len(known_invalid)),
        "known_valid_answer_count": len(known_valid_answers),
        "known_valid_answer_preserved_count": valid_preserved,
        "known_valid_answer_preservation_rate": _ratio(
            valid_preserved, len(known_valid_answers)
        ),
        "valid_abstention_count": len(valid_abstentions),
        "valid_abstention_preserved_count": abstentions_preserved,
        "valid_abstention_preservation_rate": _ratio(
            abstentions_preserved, len(valid_abstentions)
        ),
        "false_fail_closed_count": false_fail_closed,
        "citation_membership_failure_count": len(citation_failures),
        "citation_membership_failure_intercepted_count": sum(
            row["enforcement_decision"]["enforced"] for row in citation_failures
        ),
        "citation_membership_failure_interception_rate": _ratio(
            sum(row["enforcement_decision"]["enforced"] for row in citation_failures),
            len(citation_failures),
        ),
        "structured_output_failure_count": 0,
        "structured_output_failure_interception": "FIXTURE_ONLY",
        "retrieval_miss_count": len(retrieval_miss),
        "retrieval_miss_remains_limitation": True,
        "gate_claims_retrieval_miss_fixed": False,
        "gate_extra_llm_calls": 0,
        "pre_generation_enforcement": False,
        "post_answer_enforcement": True,
        "citation_membership_is_semantic_entailment": False,
        "semantic_entailment_verified": False,
    }
    return replay, metrics


def main() -> None:
    replay, metrics = build_replay()
    _write_json(OUTPUT_DIR / "post_answer_enforcement_replay.json", replay)
    _write_json(OUTPUT_DIR / "post_answer_enforcement_metrics.json", metrics)
    if metrics["citation_membership_failure_intercepted_count"] != 2:
        raise RuntimeError("expected both saved citation membership failures to be intercepted")
    if metrics["false_fail_closed_count"] != 0:
        raise RuntimeError("saved replay produced a false fail-closed")
    print(json.dumps(metrics, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
