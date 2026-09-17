"""Ground-truth document/page citation metrics."""

from __future__ import annotations

from typing import Iterable, List, Mapping

from src.evaluation.dataset import EvaluationItem
from src.evaluation.metrics import safe_ratio


def _citation_key(source: dict) -> tuple:
    return (source.get("document_id"), source.get("page_number", source.get("page")))


def evaluate_citations(
    items: Iterable[EvaluationItem],
    citations_by_question: Mapping[str, List[dict]],
    *,
    evaluation_mode: str = "answer_citations",
) -> dict:
    total_answerable = 0
    total_claimed = 0
    correct_document_claims = 0
    correct_page_claims = 0
    document_hit_questions = 0
    page_hit_questions = 0
    unanswerable_count = 0
    unanswerable_empty = 0
    per_question = []

    for item in items:
        citations = list(citations_by_question.get(item.question_id, []))
        cited_keys = [_citation_key(source) for source in citations]
        cited_documents = {key[0] for key in cited_keys if key[0]}
        cited_pages = {key for key in cited_keys if key[0] and key[1] is not None}

        if not item.answerable:
            unanswerable_count += 1
            unanswerable_empty += int(not citations)
            per_question.append(
                {
                    "question_id": item.question_id,
                    "answerable": False,
                    "citation_count": len(citations),
                    "empty_as_expected": not citations,
                }
            )
            continue

        total_answerable += 1
        expected_documents = set(item.expected_document_ids)
        expected_pages = {
            (page.document_id, page.page_number) for page in item.expected_pages
        }
        document_correct = sum(key[0] in expected_documents for key in cited_keys)
        page_correct = sum(key in expected_pages for key in cited_keys)
        document_hit = bool(cited_documents & expected_documents)
        page_hit = bool(cited_pages & expected_pages)

        total_claimed += len(cited_keys)
        correct_document_claims += document_correct
        correct_page_claims += page_correct
        document_hit_questions += int(document_hit)
        page_hit_questions += int(page_hit)
        per_question.append(
            {
                "question_id": item.question_id,
                "answerable": True,
                "citation_count": len(citations),
                "document_correct_claims": document_correct,
                "page_correct_claims": page_correct,
                "document_hit": document_hit,
                "page_hit": page_hit,
            }
        )

    return {
        "evaluation_mode": evaluation_mode,
        "answerable_questions": total_answerable,
        "claimed_citations": total_claimed,
        "document_citation_accuracy": safe_ratio(
            correct_document_claims, total_claimed
        ),
        "page_citation_accuracy": safe_ratio(correct_page_claims, total_claimed),
        "document_citation_hit_rate": safe_ratio(
            document_hit_questions, total_answerable
        ),
        "page_citation_hit_rate": safe_ratio(page_hit_questions, total_answerable),
        "unanswerable_empty_citation_rate": safe_ratio(
            unanswerable_empty, unanswerable_count
        ),
        "per_question": per_question,
    }

