"""Held-out validation models and shadow-only Phase 2 metrics.

This module deliberately does not implement response enforcement.  It keeps the
frozen pre-generation policy separate from a deterministic post-answer
candidate analysis that can be evaluated without changing user-visible output.
"""

from __future__ import annotations

import hashlib
from collections import Counter
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Iterable, List, Literal, Mapping, Optional, Sequence

from pydantic import BaseModel, ConfigDict, Field, model_validator

from src.evaluation.dataset import EvaluationItem
from src.trusted_qa.evaluator import evaluate_shadow_decisions
from src.trusted_qa.models import AnswerEvidenceAudit, PostValidationStatus


class HoldoutDifficulty(str, Enum):
    EASY = "EASY"
    MEDIUM = "MEDIUM"
    HARD = "HARD"


class NegativeClass(str, Enum):
    EASY_NEGATIVE = "EASY_NEGATIVE"
    HARD_NEGATIVE = "HARD_NEGATIVE"


class TrustedQAHoldoutItem(EvaluationItem):
    """Strict Ground Truth schema for the frozen Trusted QA validation set."""

    difficulty: HoldoutDifficulty
    negative_class: Optional[NegativeClass] = None
    unanswerable_reason: Optional[str] = None

    @model_validator(mode="after")
    def validate_holdout_ground_truth(self):
        if self.answerable:
            if self.negative_class is not None:
                raise ValueError("answerable items cannot declare negative_class")
            if self.unanswerable_reason not in (None, ""):
                raise ValueError(
                    "answerable items cannot declare unanswerable_reason"
                )
        else:
            if self.negative_class is None:
                raise ValueError("unanswerable items require negative_class")
            if not (self.unanswerable_reason or "").strip():
                raise ValueError("unanswerable items require unanswerable_reason")
            if (
                self.negative_class == NegativeClass.HARD_NEGATIVE
                and self.difficulty != HoldoutDifficulty.HARD
            ):
                raise ValueError("HARD_NEGATIVE items must use difficulty=HARD")
        return self


class HoldoutFreezeMetadata(BaseModel):
    """Immutable identity and review evidence for a frozen JSONL dataset."""

    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["1.0"]
    dataset_id: Literal["trusted_qa_holdout_v0_1"]
    status: Literal["FROZEN"]
    frozen_at: datetime
    dataset_file: str
    dataset_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    source_corpus_id: str
    source_corpus_version: str
    question_count: int = Field(ge=1)
    answerable_count: int = Field(ge=1)
    unanswerable_count: int = Field(ge=1)
    easy_negative_count: int = Field(ge=0)
    hard_negative_count: int = Field(ge=0)
    ground_truth_review: Literal["MANUAL_CORPUS_VERIFIED"]
    manual_independence_review_completed: bool
    evaluated_before_freeze: bool
    holdout_contaminated: bool
    frozen_policy_version: Literal["trusted_qa_shadow_v0_1"]
    notes: str = ""


class PostAnswerCandidateAction(str, Enum):
    ALLOW_ANSWER = "ALLOW_ANSWER"
    VALID_ABSTENTION = "VALID_ABSTENTION"
    FAIL_CLOSED = "FAIL_CLOSED"
    NOT_EVALUATED = "NOT_EVALUATED"


class PostAnswerCandidateReason(str, Enum):
    STRUCTURED_OUTPUT_INVALID = "STRUCTURED_OUTPUT_INVALID"
    EXPLICIT_NA = "EXPLICIT_NA"
    NA_WITH_CITATION_CONTRADICTION = "NA_WITH_CITATION_CONTRADICTION"
    ANSWER_WITHOUT_VALID_CITATION = "ANSWER_WITHOUT_VALID_CITATION"
    CITATION_MEMBERSHIP_FAILED = "CITATION_MEMBERSHIP_FAILED"


class PostAnswerCandidateDecision(BaseModel):
    """Shadow-only candidate action; it never replaces the pipeline response."""

    model_config = ConfigDict(extra="forbid")

    action: PostAnswerCandidateAction
    reason_codes: List[PostAnswerCandidateReason] = Field(default_factory=list)
    policy_version: Literal["trusted_qa_post_answer_candidate_v0_1"] = (
        "trusted_qa_post_answer_candidate_v0_1"
    )
    shadow_only: Literal[True] = True
    response_modified: Literal[False] = False
    semantic_entailment_verified: None = None


def file_sha256(path: Path | str) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def load_holdout_dataset(path: Path | str) -> list[TrustedQAHoldoutItem]:
    dataset_path = Path(path)
    items: list[TrustedQAHoldoutItem] = []
    seen_ids: set[str] = set()
    with dataset_path.open("r", encoding="utf-8") as stream:
        for line_number, line in enumerate(stream, start=1):
            if not line.strip():
                continue
            try:
                item = TrustedQAHoldoutItem.model_validate_json(line)
            except Exception as exc:
                raise ValueError(
                    f"invalid holdout item at {dataset_path}:{line_number}: {exc}"
                ) from exc
            if item.question_id in seen_ids:
                raise ValueError(f"duplicate question_id: {item.question_id}")
            seen_ids.add(item.question_id)
            items.append(item)
    if not items:
        raise ValueError(f"holdout dataset is empty: {dataset_path}")
    return items


def _normalized_question(question: str) -> str:
    return "".join(question.casefold().split())


def assert_exact_independence(
    holdout: Sequence[TrustedQAHoldoutItem],
    excluded_datasets: Iterable[Sequence[EvaluationItem]],
    *,
    excluded_question_ids: Iterable[str] = (),
) -> None:
    excluded_ids = set(excluded_question_ids)
    excluded_questions: set[str] = set()
    for dataset in excluded_datasets:
        for item in dataset:
            excluded_ids.add(item.question_id)
            excluded_questions.add(_normalized_question(item.question))

    overlap_ids = sorted(item.question_id for item in holdout if item.question_id in excluded_ids)
    overlap_questions = sorted(
        item.question_id
        for item in holdout
        if _normalized_question(item.question) in excluded_questions
    )
    if overlap_ids or overlap_questions:
        raise ValueError(
            "holdout is not exactly independent: "
            f"overlap_ids={overlap_ids}, overlap_questions={overlap_questions}"
        )


def load_frozen_holdout(
    dataset_path: Path | str,
    freeze_metadata_path: Path | str,
) -> tuple[list[TrustedQAHoldoutItem], HoldoutFreezeMetadata]:
    dataset_path = Path(dataset_path)
    metadata = HoldoutFreezeMetadata.model_validate_json(
        Path(freeze_metadata_path).read_text(encoding="utf-8")
    )
    actual_hash = file_sha256(dataset_path)
    if actual_hash != metadata.dataset_sha256:
        raise ValueError(
            "frozen holdout hash mismatch: "
            f"expected={metadata.dataset_sha256}, actual={actual_hash}"
        )
    items = load_holdout_dataset(dataset_path)
    counts = Counter(
        "ANSWERABLE"
        if item.answerable
        else item.negative_class.value
        for item in items
    )
    expected_counts = {
        "question_count": len(items),
        "answerable_count": counts["ANSWERABLE"],
        "unanswerable_count": len(items) - counts["ANSWERABLE"],
        "easy_negative_count": counts[NegativeClass.EASY_NEGATIVE.value],
        "hard_negative_count": counts[NegativeClass.HARD_NEGATIVE.value],
    }
    mismatches = {
        key: (getattr(metadata, key), value)
        for key, value in expected_counts.items()
        if getattr(metadata, key) != value
    }
    if mismatches:
        raise ValueError(f"frozen holdout count mismatch: {mismatches}")
    return items, metadata


def holdout_group(item: TrustedQAHoldoutItem | Mapping[str, object]) -> str:
    if isinstance(item, TrustedQAHoldoutItem):
        return "ANSWERABLE" if item.answerable else item.negative_class.value
    if bool(item["ground_truth_answerable"]):
        return "ANSWERABLE"
    value = item.get("negative_class")
    return value.value if isinstance(value, NegativeClass) else str(value)


def evaluate_holdout_shadow(records: Iterable[Mapping[str, object]]) -> dict:
    rows = list(records)
    group_order = ("ANSWERABLE", "EASY_NEGATIVE", "HARD_NEGATIVE")
    grouped = {
        group: [row for row in rows if holdout_group(row) == group]
        for group in group_order
    }
    return {
        "metric_scope": "counterfactual_held_out_shadow_only",
        "overall": evaluate_shadow_decisions(rows),
        "by_ground_truth_group": {
            group: evaluate_shadow_decisions(grouped[group])
            for group in group_order
        },
    }


def decide_post_answer_candidate(
    audit: AnswerEvidenceAudit | Mapping[str, object],
) -> PostAnswerCandidateDecision:
    """Map existing answer observations to a conservative shadow candidate."""

    if not isinstance(audit, AnswerEvidenceAudit):
        audit = AnswerEvidenceAudit.model_validate(audit)
    if not audit.generation_performed:
        return PostAnswerCandidateDecision(
            action=PostAnswerCandidateAction.NOT_EVALUATED
        )
    if audit.structured_output_valid is not True:
        return PostAnswerCandidateDecision(
            action=PostAnswerCandidateAction.FAIL_CLOSED,
            reason_codes=[PostAnswerCandidateReason.STRUCTURED_OUTPUT_INVALID],
        )
    if audit.answer_is_na:
        if (audit.claimed_citation_count or 0) == 0 and (audit.citation_count or 0) == 0:
            return PostAnswerCandidateDecision(
                action=PostAnswerCandidateAction.VALID_ABSTENTION,
                reason_codes=[PostAnswerCandidateReason.EXPLICIT_NA],
            )
        return PostAnswerCandidateDecision(
            action=PostAnswerCandidateAction.FAIL_CLOSED,
            reason_codes=[
                PostAnswerCandidateReason.NA_WITH_CITATION_CONTRADICTION
            ],
        )
    if audit.post_validation_status == PostValidationStatus.EMPTY_VALID_CITATIONS:
        return PostAnswerCandidateDecision(
            action=PostAnswerCandidateAction.FAIL_CLOSED,
            reason_codes=[
                PostAnswerCandidateReason.ANSWER_WITHOUT_VALID_CITATION
            ],
        )
    if (
        audit.post_validation_status
        == PostValidationStatus.INVALID_CITATIONS_FILTERED
        or audit.citation_membership_valid is False
    ):
        return PostAnswerCandidateDecision(
            action=PostAnswerCandidateAction.FAIL_CLOSED,
            reason_codes=[
                PostAnswerCandidateReason.CITATION_MEMBERSHIP_FAILED
            ],
        )
    return PostAnswerCandidateDecision(
        action=PostAnswerCandidateAction.ALLOW_ANSWER
    )


def _ratio(numerator: int, denominator: int) -> float | None:
    return round(numerator / denominator, 6) if denominator else None


def evaluate_post_answer_candidates(
    records: Iterable[Mapping[str, object]],
) -> dict:
    rows = list(records)
    evaluated = [row for row in rows if row.get("post_answer_candidate")]
    answerable = [row for row in evaluated if bool(row["ground_truth_answerable"])]
    unanswerable = [row for row in evaluated if not bool(row["ground_truth_answerable"])]

    def action(row: Mapping[str, object]) -> str:
        candidate = row["post_answer_candidate"]
        return str(candidate["action"])

    correct_abstentions = sum(
        action(row) == PostAnswerCandidateAction.VALID_ABSTENTION.value
        for row in unanswerable
    )
    answerable_valid_answers = sum(
        action(row) == PostAnswerCandidateAction.ALLOW_ANSWER.value
        for row in answerable
    )
    answerable_false_abstentions = sum(
        action(row) == PostAnswerCandidateAction.VALID_ABSTENTION.value
        for row in answerable
    )
    answerable_fail_closed = sum(
        action(row) == PostAnswerCandidateAction.FAIL_CLOSED.value
        for row in answerable
    )
    unsupported_answers = sum(
        action(row) == PostAnswerCandidateAction.ALLOW_ANSWER.value
        for row in unanswerable
    )
    citation_failures = sum(
        "CITATION_MEMBERSHIP_FAILED" in row["post_answer_candidate"].get("reason_codes", [])
        or "ANSWER_WITHOUT_VALID_CITATION" in row["post_answer_candidate"].get("reason_codes", [])
        for row in evaluated
    )
    structured_failures = sum(
        "STRUCTURED_OUTPUT_INVALID" in row["post_answer_candidate"].get("reason_codes", [])
        for row in evaluated
    )
    fail_closed = [
        row
        for row in evaluated
        if action(row) == PostAnswerCandidateAction.FAIL_CLOSED.value
    ]
    deterministic_failure_reasons = {
        PostAnswerCandidateReason.STRUCTURED_OUTPUT_INVALID.value,
        PostAnswerCandidateReason.NA_WITH_CITATION_CONTRADICTION.value,
        PostAnswerCandidateReason.ANSWER_WITHOUT_VALID_CITATION.value,
        PostAnswerCandidateReason.CITATION_MEMBERSHIP_FAILED.value,
    }
    justified_fail_closed = sum(
        bool(
            deterministic_failure_reasons.intersection(
                row["post_answer_candidate"].get("reason_codes", [])
            )
        )
        for row in fail_closed
    )
    return {
        "metric_scope": "post_answer_shadow_candidate_only",
        "question_count": len(evaluated),
        "answerable_count": len(answerable),
        "unanswerable_count": len(unanswerable),
        "correct_abstention_count": correct_abstentions,
        "correct_abstention_rate": _ratio(correct_abstentions, len(unanswerable)),
        "answerable_valid_answer_count": answerable_valid_answers,
        "answerable_valid_answer_rate": _ratio(
            answerable_valid_answers, len(answerable)
        ),
        "answerable_false_abstention_count": answerable_false_abstentions,
        "answerable_false_abstention_rate": _ratio(
            answerable_false_abstentions, len(answerable)
        ),
        "answerable_fail_closed_count": answerable_fail_closed,
        "answerable_fail_closed_rate": _ratio(
            answerable_fail_closed, len(answerable)
        ),
        "unsupported_answer_count": unsupported_answers,
        "unsupported_answer_rate": _ratio(unsupported_answers, len(unanswerable)),
        "citation_membership_failure_count": citation_failures,
        "citation_membership_failure_rate": _ratio(citation_failures, len(evaluated)),
        "structured_output_failure_count": structured_failures,
        "structured_output_failure_rate": _ratio(structured_failures, len(evaluated)),
        "potential_fail_closed_count": len(fail_closed),
        "potential_fail_closed_precision": _ratio(
            justified_fail_closed, len(fail_closed)
        ),
        "potential_fail_closed_ground_truth_unanswerable_count": sum(
            not bool(row["ground_truth_answerable"]) for row in fail_closed
        ),
        "potential_fail_closed_precision_sample_status": (
            "SAMPLE_SIZE_INSUFFICIENT" if len(fail_closed) < 5 else "OBSERVED_ONLY"
        ),
        "potential_fail_closed_precision_definition": "Fraction of candidate FAIL_CLOSED cases backed by an observed deterministic structure/citation invariant; not semantic answer correctness.",
        "citation_membership_is_semantic_entailment": False,
        "response_enforcement_performed": False,
    }
