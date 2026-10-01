"""Score saved answers only against explicit human review; never calls a model."""

from __future__ import annotations

import hashlib


def answer_sha256(answer: str) -> str:
    return hashlib.sha256(answer.encode("utf-8")).hexdigest()


def evaluate_saved_answers(cases: list[dict], answers: list[dict], reviews: list[dict]) -> dict:
    case_by_id = {row["case_id"]: row for row in cases}
    answer_by_id = {}
    for row in answers:
        case_id = row.get("case_id")
        if case_id not in case_by_id or case_id in answer_by_id:
            raise ValueError("answer rows must refer to unique known case IDs")
        if not isinstance(row.get("answer"), str) or not isinstance(row.get("citations"), list):
            raise ValueError(f"invalid saved answer row: {case_id}")
        if not isinstance(row.get("retrieved_chunk_ids"), list):
            raise ValueError(f"retrieved_chunk_ids are required: {case_id}")
        answer_by_id[case_id] = row

    review_by_id = {}
    for row in reviews:
        case_id = row.get("case_id")
        if case_id not in answer_by_id or case_id in review_by_id:
            raise ValueError("review rows must refer to unique saved answers")
        if not isinstance(row.get("claims"), list) or not isinstance(row.get("covered_required_points"), list):
            raise ValueError(f"invalid human review row: {case_id}")
        review_by_id[case_id] = row

    citation_total = citation_member_total = 0
    supported_claims = total_claims = 0
    cited_support_total = cited_support_hit = 0
    required_point_total = covered_point_total = 0
    answer_sha_mismatches = 0
    semantic_reviewed = 0
    true_abstain = false_abstain = missed_abstain = 0

    for case_id, answer_row in answer_by_id.items():
        citations = {value for value in answer_row["citations"] if isinstance(value, str)}
        available = {value for value in answer_row["retrieved_chunk_ids"] if isinstance(value, str)}
        citation_total += len(citations)
        citation_member_total += sum(citation in available for citation in citations)
        review = review_by_id.get(case_id)
        if review is None:
            continue
        if review.get("answer_sha256") != answer_sha256(answer_row["answer"]):
            answer_sha_mismatches += 1
            continue
        semantic_reviewed += 1
        case = case_by_id[case_id]
        abstained = review.get("abstained")
        if not isinstance(abstained, bool):
            raise ValueError(f"human review must label abstained: {case_id}")
        if not case.get("answerable", False) and abstained:
            true_abstain += 1
        elif case.get("answerable", False) and abstained:
            false_abstain += 1
        elif not case.get("answerable", False) and not abstained:
            missed_abstain += 1

        point_set = set(case.get("required_answer_points", []))
        if case.get("answerable", False) and point_set:
            required_point_total += len(point_set)
            covered_point_total += len(point_set.intersection(
                point for point in review["covered_required_points"] if isinstance(point, str)
            ))

        reviewed_support_ids = set()
        for claim in review["claims"]:
            if not isinstance(claim, dict) or not isinstance(claim.get("supported"), bool):
                raise ValueError(f"each human-reviewed claim must have a supported label: {case_id}")
            total_claims += 1
            supported = claim["supported"]
            supported_claims += int(supported)
            support_ids = claim.get("supporting_chunk_ids", [])
            if not isinstance(support_ids, list) or any(not isinstance(value, str) for value in support_ids):
                raise ValueError(f"invalid supporting chunk IDs: {case_id}")
            if supported:
                reviewed_support_ids.update(support_ids)
        cited_support_total += len(reviewed_support_ids)
        cited_support_hit += len(reviewed_support_ids.intersection(citations))

    reviewed_answerable = sum(
        bool(case_by_id[key].get("answerable", False))
        for key in review_by_id
        if key in answer_by_id and review_by_id[key].get("answer_sha256") == answer_sha256(answer_by_id[key]["answer"])
    )
    abstained_predictions = true_abstain + false_abstain
    return {
        "saved_answer_count": len(answer_by_id),
        "human_review_row_count": len(review_by_id),
        "semantic_reviewed_answer_count": semantic_reviewed,
        "missing_review_count": len(answer_by_id) - len(review_by_id),
        "answer_sha256_mismatch_count": answer_sha_mismatches,
        "citation_membership_rate": round(citation_member_total / citation_total, 4) if citation_total else None,
        "citation_support_precision": round(cited_support_hit / citation_total, 4) if citation_total else None,
        "citation_support_recall": round(cited_support_hit / cited_support_total, 4) if cited_support_total else None,
        "supported_claim_ratio": round(supported_claims / total_claims, 4) if total_claims else None,
        "reviewed_claim_count": total_claims,
        "required_point_completeness": round(covered_point_total / required_point_total, 4) if required_point_total else None,
        "reviewed_required_point_count": required_point_total,
        "abstention_precision": round(true_abstain / abstained_predictions, 4) if abstained_predictions else None,
        "abstention_recall": round(true_abstain / (true_abstain + missed_abstain), 4) if true_abstain + missed_abstain else None,
        "abstention_confusion": {
            "true_abstain": true_abstain, "false_abstain": false_abstain,
            "missed_abstain": missed_abstain,
        },
        "interpretation": "Semantic support and required-point metrics include only answer-hash-matched human reviews; no model judge or model confidence is used.",
    }
