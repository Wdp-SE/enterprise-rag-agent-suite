"""Deterministic answer checks intended to be paired with manual review."""

from __future__ import annotations

import re
from typing import Iterable, Mapping

from src.evaluation.dataset import EvaluationItem
from src.evaluation.metrics import safe_ratio


def _normalize(value: object) -> str:
    if isinstance(value, list):
        value = " ".join(str(item) for item in value)
    return re.sub(r"[\s，。；：、,.;:()（）\[\]{}]+", "", str(value or "")).casefold()


def evaluate_answers(
    items: Iterable[EvaluationItem],
    answers_by_question: Mapping[str, dict],
) -> dict:
    answerable_count = 0
    answerable_passes = 0
    unanswerable_count = 0
    unanswerable_refusals = 0
    key_points_total = 0
    key_points_matched = 0
    manual_review_required = 0
    per_question = []

    for item in items:
        result = dict(answers_by_question.get(item.question_id, {}))
        answer = result.get("answer", result.get("final_answer"))
        error = result.get("error")
        refusal = answer == "N/A"
        answered = answer not in (None, "", "N/A") and error is None
        normalized_answer = _normalize(answer)
        matched = [point for point in item.key_points if _normalize(point) in normalized_answer]
        missing = [point for point in item.key_points if point not in matched]
        unsupported_claim = result.get("unsupported_claim")
        citation_correct = result.get("citation_correct")
        if unsupported_claim is None or citation_correct is None:
            manual_review_required += 1

        if item.answerable:
            answerable_count += 1
            key_points_total += len(item.key_points)
            key_points_matched += len(matched)
            passed = answered and not missing and unsupported_claim is not True
            answerable_passes += int(passed)
        else:
            unanswerable_count += 1
            unanswerable_refusals += int(refusal)
            passed = refusal

        per_question.append(
            {
                "question_id": item.question_id,
                "answerable": item.answerable,
                "answered": answered,
                "refusal": refusal,
                "error": error,
                "correct_key_points": matched,
                "missing_key_points": missing,
                "unsupported_claim": unsupported_claim,
                "citation_correct": citation_correct,
                "rule_based_pass": passed,
                "manual_review_required": (
                    unsupported_claim is None or citation_correct is None
                ),
            }
        )

    return {
        "evaluation_method": "rule_based_key_points_plus_manual_review_fields",
        "answerable_questions": answerable_count,
        "answerable_accuracy": safe_ratio(answerable_passes, answerable_count),
        "unanswerable_questions": unanswerable_count,
        "unanswerable_refusal_rate": safe_ratio(
            unanswerable_refusals, unanswerable_count
        ),
        "key_point_coverage": safe_ratio(key_points_matched, key_points_total),
        "manual_review_required_count": manual_review_required,
        "limitations": [
            "Exact normalized key-point matching may undercount valid paraphrases.",
            "Unsupported claims and semantic citation support require manual review.",
        ],
        "per_question": per_question,
    }

