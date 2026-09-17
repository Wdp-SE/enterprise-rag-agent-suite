"""Document-level retrieval metrics and score-distribution reporting."""

from __future__ import annotations

from collections import defaultdict
from typing import Dict, Iterable, List, Mapping, Sequence

from src.evaluation.dataset import EvaluationItem
from src.evaluation.metrics import safe_ratio, summarize_scores


def _metric_block(records: Sequence[dict], ks: Sequence[int]) -> dict:
    if not records:
        return {
            "evaluated_questions": 0,
            "hit_at_k": {str(k): None for k in ks},
            "recall_at_k": {str(k): None for k in ks},
            "mrr": None,
        }

    hit_at_k = {}
    recall_at_k = {}
    for k in ks:
        hit_at_k[str(k)] = round(
            sum(record["hit_at_k"][str(k)] for record in records) / len(records), 6
        )
        recall_at_k[str(k)] = round(
            sum(record["recall_at_k"][str(k)] for record in records) / len(records),
            6,
        )
    return {
        "evaluated_questions": len(records),
        "hit_at_k": hit_at_k,
        "recall_at_k": recall_at_k,
        "mrr": round(sum(record["reciprocal_rank"] for record in records) / len(records), 6),
    }


def evaluate_retrieval(
    items: Iterable[EvaluationItem],
    results_by_question: Mapping[str, List[dict]],
    *,
    ks: Sequence[int] = (1, 3, 5),
) -> dict:
    ks = tuple(sorted(set(int(k) for k in ks)))
    if not ks or ks[0] <= 0:
        raise ValueError("retrieval K values must be positive")

    per_question = []
    metric_records = []
    grouped = defaultdict(list)
    answerable_top_scores = []
    unanswerable_top_scores = []
    answerable_rerank_scores = []
    unanswerable_rerank_scores = []
    unanswerable_records = []

    for item in items:
        results = list(results_by_question.get(item.question_id, []))
        retrieved_ids = [result.get("document_id") for result in results]
        expected_ids = set(item.expected_document_ids)
        top_distance = results[0].get("distance") if results else None
        top_rerank = results[0].get("relevance_score") if results else None

        if top_distance is not None:
            target = answerable_top_scores if item.answerable else unanswerable_top_scores
            target.append(float(top_distance))
        if top_rerank is not None:
            target = answerable_rerank_scores if item.answerable else unanswerable_rerank_scores
            target.append(float(top_rerank))

        record = {
            "question_id": item.question_id,
            "question_type": item.question_type,
            "answerable": item.answerable,
            "expected_document_ids": item.expected_document_ids,
            "retrieved_document_ids": retrieved_ids,
            "top_distance": top_distance,
            "top_rerank_score": top_rerank,
        }

        if not item.answerable:
            record.update(
                {
                    "hit_at_k": {},
                    "recall_at_k": {},
                    "reciprocal_rank": None,
                    "excluded_from_hit_metrics": True,
                }
            )
            unanswerable_records.append(
                {
                    "question_id": item.question_id,
                    "result_count": len(results),
                    "top_distance": top_distance,
                    "top_rerank_score": top_rerank,
                    "top_document_ids": retrieved_ids[: max(ks)],
                }
            )
        else:
            hit_at_k = {}
            recall_at_k = {}
            for k in ks:
                retrieved_at_k = set(retrieved_ids[:k])
                relevant_count = len(expected_ids & retrieved_at_k)
                hit_at_k[str(k)] = int(relevant_count > 0)
                recall_at_k[str(k)] = round(relevant_count / len(expected_ids), 6)

            first_relevant_rank = next(
                (rank for rank, document_id in enumerate(retrieved_ids, start=1)
                 if document_id in expected_ids),
                None,
            )
            record.update(
                {
                    "hit_at_k": hit_at_k,
                    "recall_at_k": recall_at_k,
                    "reciprocal_rank": (
                        round(1.0 / first_relevant_rank, 6)
                        if first_relevant_rank is not None
                        else 0.0
                    ),
                    "excluded_from_hit_metrics": False,
                }
            )
            metric_records.append(record)
            grouped[item.question_type].append(record)
        per_question.append(record)

    return {
        "ks": list(ks),
        "overall": _metric_block(metric_records, ks),
        "by_question_type": {
            question_type: _metric_block(records, ks)
            for question_type, records in sorted(grouped.items())
        },
        "unanswerable_behavior": {
            "question_count": len(unanswerable_records),
            "questions_with_any_retrieval": sum(
                record["result_count"] > 0 for record in unanswerable_records
            ),
            "any_retrieval_rate": safe_ratio(
                sum(record["result_count"] > 0 for record in unanswerable_records),
                len(unanswerable_records),
            ),
            "per_question": unanswerable_records,
        },
        "score_distribution": {
            "cosine_top1": {
                "answerable": summarize_scores(answerable_top_scores),
                "unanswerable": summarize_scores(unanswerable_top_scores),
            },
            "rerank_top1": {
                "answerable": summarize_scores(answerable_rerank_scores),
                "unanswerable": summarize_scores(unanswerable_rerank_scores),
            },
            "threshold_selected": False,
        },
        "per_question": per_question,
    }

