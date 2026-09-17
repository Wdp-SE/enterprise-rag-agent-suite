"""Evaluation dataset schema and JSONL loader."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import List, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


QuestionType = Literal[
    "single_document",
    "cross_document",
    "unanswerable",
    "version_temporal",
]


class ExpectedPage(BaseModel):
    model_config = ConfigDict(extra="forbid")

    document_id: str
    page_number: int = Field(ge=1)


class EvaluationItem(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    question_id: str
    question: str
    question_type: QuestionType
    answerable: bool
    expected_document_ids: List[str] = Field(default_factory=list)
    expected_pages: List[ExpectedPage] = Field(default_factory=list)
    reference_answer: Optional[str] = None
    key_points: List[str] = Field(default_factory=list)
    notes: str = ""
    review_status: Literal["VERIFIED", "NEEDS_REVIEW"] = "VERIFIED"
    answer_schema: Literal["text", "number", "boolean", "names"] = Field(
        default="text", alias="schema"
    )

    @field_validator("question_id")
    @classmethod
    def validate_question_id(cls, value: str) -> str:
        value = value.strip()
        if not re.fullmatch(r"[A-Za-z0-9._:-]+", value):
            raise ValueError("question_id contains unsupported characters")
        return value

    @model_validator(mode="after")
    def validate_ground_truth(self):
        expected_ids = set(self.expected_document_ids)
        if self.answerable:
            if not expected_ids:
                raise ValueError("answerable items require expected_document_ids")
            if not self.reference_answer:
                raise ValueError("answerable items require reference_answer")
        else:
            if self.question_type != "unanswerable":
                raise ValueError("answerable=false is reserved for unanswerable items")
            if self.expected_document_ids or self.expected_pages:
                raise ValueError("unanswerable items cannot declare expected evidence")
            if self.reference_answer not in (None, ""):
                raise ValueError("unanswerable items cannot declare a reference answer")

        unknown_page_documents = {
            page.document_id for page in self.expected_pages
        } - expected_ids
        if unknown_page_documents:
            raise ValueError(
                "expected_pages reference documents outside expected_document_ids: "
                f"{sorted(unknown_page_documents)}"
            )
        return self


def load_evaluation_dataset(path: Path | str) -> List[EvaluationItem]:
    dataset_path = Path(path)
    items: List[EvaluationItem] = []
    seen_ids = set()
    with dataset_path.open("r", encoding="utf-8") as stream:
        for line_number, line in enumerate(stream, start=1):
            if not line.strip():
                continue
            try:
                item = EvaluationItem.model_validate_json(line)
            except Exception as exc:
                raise ValueError(
                    f"invalid evaluation item at {dataset_path}:{line_number}: {exc}"
                ) from exc
            if item.question_id in seen_ids:
                raise ValueError(f"duplicate question_id: {item.question_id}")
            seen_ids.add(item.question_id)
            items.append(item)
    if not items:
        raise ValueError(f"evaluation dataset is empty: {dataset_path}")
    return items
