import pytest
from pydantic import ValidationError

from src.prompts import AnswerWithRAGContextBooleanPrompt
from src.questions_processing import QuestionsProcessor


def _boolean_payload(final_answer):
    return {
        "step_by_step_analysis": "analysis",
        "reasoning_summary": "summary",
        "relevant_pages": [],
        "final_answer": final_answer,
    }


@pytest.mark.parametrize("value", [True, False, "N/A"])
def test_boolean_schema_accepts_boolean_and_na(value):
    result = AnswerWithRAGContextBooleanPrompt.AnswerSchema.model_validate(
        _boolean_payload(value)
    )

    assert result.final_answer == value


def test_boolean_schema_rejects_unknown_string():
    with pytest.raises(ValidationError):
        AnswerWithRAGContextBooleanPrompt.AnswerSchema.model_validate(
            _boolean_payload("unknown")
        )


def test_no_claimed_citation_does_not_create_pages():
    processor = QuestionsProcessor(questions_file_path=None)
    retrieval_results = [
        {"page": 3, "text": "a"},
        {"page": 5, "text": "b"},
    ]

    assert processor._validate_page_references([], retrieval_results) == []


def test_citation_validation_removes_hallucinations_and_duplicates():
    processor = QuestionsProcessor(questions_file_path=None)
    retrieval_results = [
        {"page": 3, "text": "a"},
        {"page": 5, "text": "b"},
    ]

    assert processor._validate_page_references([3, 99, 3], retrieval_results) == [3]


def test_competition_citation_output_schema_is_unchanged():
    processor = QuestionsProcessor(questions_file_path=None)
    processor.answer_details = [
        {
            "step_by_step_analysis": "analysis",
            "reasoning_summary": "summary",
            "relevant_pages": [3],
        }
    ]
    processed = [
        {
            "question_text": "question",
            "kind": "boolean",
            "value": True,
            "references": [{"pdf_sha1": "abc", "page_index": 3}],
            "answer_details": {"$ref": "#/answer_details/0"},
        }
    ]

    result = processor._post_process_submission_answers(processed)

    assert result[0]["references"] == [{"pdf_sha1": "abc", "page_index": 2}]
    assert set(result[0]) == {
        "question_text",
        "kind",
        "value",
        "references",
        "reasoning_process",
    }
