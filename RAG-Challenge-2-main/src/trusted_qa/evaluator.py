"""Counterfactual metrics for Trusted QA shadow decisions."""

from __future__ import annotations

from collections import Counter
from typing import Iterable, Mapping

from src.trusted_qa.models import DecisionState


def _ratio(numerator: int, denominator: int) -> float | None:
    return round(numerator / denominator, 6) if denominator else None


def evaluate_shadow_decisions(records: Iterable[Mapping[str, object]]) -> dict:
    rows = list(records)
    def decision_value(row: Mapping[str, object]) -> str:
        value = row["shadow_decision"]
        return value.value if isinstance(value, DecisionState) else str(value)

    answerable = [row for row in rows if bool(row["ground_truth_answerable"])]
    unanswerable = [row for row in rows if not bool(row["ground_truth_answerable"])]
    answerable_counts = Counter(decision_value(row) for row in answerable)
    unanswerable_counts = Counter(decision_value(row) for row in unanswerable)
    all_counts = Counter(decision_value(row) for row in rows)
    false_rejects = answerable_counts[DecisionState.REJECT.value]
    false_accepts = unanswerable_counts[DecisionState.ANSWER.value]
    correct_decisions = (
        answerable_counts[DecisionState.ANSWER.value]
        + unanswerable_counts[DecisionState.REJECT.value]
    )
    decided = len(rows) - all_counts[DecisionState.UNCERTAIN.value]
    total_rejects = all_counts[DecisionState.REJECT.value]
    return {
        "metric_scope": "counterfactual_shadow_only",
        "question_count": len(rows),
        "answerable_count": len(answerable),
        "unanswerable_count": len(unanswerable),
        "answerable_decisions": {
            state.value: answerable_counts[state.value] for state in DecisionState
        },
        "unanswerable_decisions": {
            state.value: unanswerable_counts[state.value] for state in DecisionState
        },
        "shadow_answerable_acceptance_rate": _ratio(
            answerable_counts[DecisionState.ANSWER.value], len(answerable)
        ),
        "shadow_unanswerable_rejection_rate": _ratio(
            unanswerable_counts[DecisionState.REJECT.value], len(unanswerable)
        ),
        "shadow_false_reject_count": false_rejects,
        "shadow_false_reject_rate": _ratio(false_rejects, len(answerable)),
        "shadow_false_accept_count": false_accepts,
        "shadow_false_accept_rate": _ratio(false_accepts, len(unanswerable)),
        "shadow_uncertain_count": all_counts[DecisionState.UNCERTAIN.value],
        "shadow_uncertain_rate": _ratio(
            all_counts[DecisionState.UNCERTAIN.value], len(rows)
        ),
        "coverage": _ratio(decided, len(rows)),
        "potential_selective_accuracy": _ratio(correct_decisions, decided),
        "shadow_reject_precision": _ratio(
            unanswerable_counts[DecisionState.REJECT.value], total_rejects
        ),
        "production_accuracy": None,
    }
