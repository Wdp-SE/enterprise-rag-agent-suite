"""Score only saved answers that have an exact-hash human review."""

from __future__ import annotations

from collections import Counter


def _index_unique(rows: list[dict], label: str) -> dict[str, dict]:
    indexed: dict[str, dict] = {}
    for row in rows:
        if not isinstance(row, dict) or not isinstance(row.get("case_id"), str) or not row["case_id"]:
            raise ValueError(f"{label} row must have a non-empty case_id")
        if row["case_id"] in indexed:
            raise ValueError(f"duplicate {label} row for {row['case_id']}")
        indexed[row["case_id"]] = row
    return indexed


def _string_ids(value: object, *, label: str) -> list[str]:
    if not isinstance(value, list) or any(not isinstance(item, str) or not item.strip() for item in value):
        raise ValueError(f"{label} must be a list of non-empty strings")
    if len(value) != len(set(value)):
        raise ValueError(f"{label} must not contain duplicate IDs")
    return value


def _safe_ratio(numerator: int, denominator: int) -> float | None:
    return numerator / denominator if denominator else None


def evaluate_saved_answers(cases: list[dict], answer_rows: list[dict], human_reviews: list[dict]) -> dict:
    """Return citation/support and abstention metrics for reviewed answer snapshots.

    Hash mismatch and missing rows are excluded. Retrieval candidate quality is kept
    separate from answer correctness; only human review supplies semantic support.
    """
    answers = _index_unique(answer_rows, "answer")
    reviews = _index_unique(human_reviews, "review")
    case_index = _index_unique(cases, "case")
    accepted: list[tuple[dict, dict, dict]] = []
    excluded = 0
    for case_id, case in case_index.items():
        answer = answers.get(case_id)
        review = reviews.get(case_id)
        if (
            answer is None or review is None
            or not isinstance(answer.get("answer_sha256"), str)
            or not answer.get("answer_sha256")
            or answer.get("answer_sha256") != review.get("answer_sha256")
        ):
            excluded += 1
            continue
        accepted.append((case, answer, review))

    claim_count = unsupported_count = covered_points = required_points = 0
    cited_ids: list[str] = []
    retrieved_ids: list[str] = []
    semantically_supported_ids: list[str] = []
    valid_citations = citation_count = 0
    abstention_tp = abstention_fp = abstention_fn = 0
    review_disagreements = 0
    rows = []

    for case, answer, review in accepted:
        if not isinstance(answer.get("abstained"), bool):
            raise ValueError(f"answer abstained must be a boolean for {case['case_id']}")
        answer_claims = answer.get("claims")
        review_claims = review.get("claims")
        if not isinstance(answer_claims, list) or not isinstance(review_claims, list):
            raise ValueError(f"answer and review claims must be lists for {case['case_id']}")
        answer_by_id = {}
        for claim in answer_claims:
            if not isinstance(claim, dict) or not isinstance(claim.get("claim_id"), str) or not claim["claim_id"]:
                raise ValueError(f"answer claim requires claim_id for {case['case_id']}")
            if claim["claim_id"] in answer_by_id:
                raise ValueError(f"duplicate answer claim id for {case['case_id']}")
            answer_by_id[claim["claim_id"]] = claim
            _string_ids(claim.get("evidence_ids"), label="claim evidence_ids")
        review_by_id = {}
        for claim in review_claims:
            if not isinstance(claim, dict) or not isinstance(claim.get("claim_id"), str) or not claim["claim_id"]:
                raise ValueError(f"review claim requires claim_id for {case['case_id']}")
            if claim["claim_id"] in review_by_id:
                raise ValueError(f"duplicate review claim id for {case['case_id']}")
            if not isinstance(claim.get("supported"), bool):
                raise ValueError(f"review claim supported must be a boolean for {case['case_id']}")
            support_ids = _string_ids(claim.get("supporting_chunk_ids"), label="supporting_chunk_ids")
            if claim["supported"] and not support_ids:
                raise ValueError(f"supported claim requires supporting chunk IDs for {case['case_id']}")
            review_by_id[claim["claim_id"]] = {**claim, "supporting_chunk_ids": support_ids}

        retrieved = _string_ids(answer.get("retrieved_evidence_ids"), label="retrieved_evidence_ids")
        case_citations = []
        case_supported_ids = []
        case_claim_count = 0
        case_unsupported = 0
        for claim_id, answer_claim in answer_by_id.items():
            review_claim = review_by_id.get(claim_id)
            if review_claim is None:
                # Unreviewed claims are excluded from semantic correctness, never assumed supported.
                continue
            case_claim_count += 1
            case_unsupported += int(not review_claim["supported"])
            claim_citations = answer_claim["evidence_ids"]
            case_citations.extend(claim_citations)
            support = review_claim["supporting_chunk_ids"] if review_claim["supported"] else []
            case_supported_ids.extend(support)
        case_citations = list(dict.fromkeys(case_citations))
        case_supported_ids = list(dict.fromkeys(case_supported_ids))
        case_retrieved_citations = [item for item in case_citations if item in set(retrieved)]
        citation_count += len(case_citations)
        valid_citations += len(case_retrieved_citations)
        cited_ids.extend(case_citations)
        retrieved_ids.extend(retrieved)
        semantically_supported_ids.extend(case_supported_ids)

        required = case.get("required_answer_points", [])
        if not isinstance(required, list) or any(not isinstance(point, str) or not point for point in required):
            raise ValueError(f"required_answer_points must be strings for {case['case_id']}")
        covered = review.get("covered_required_points", [])
        if not isinstance(covered, list) or any(not isinstance(point, str) or not point for point in covered):
            raise ValueError(f"covered_required_points must be strings for {case['case_id']}")
        required_points += len(required)
        covered_points += len(set(required) & set(covered))
        should_abstain = review.get("should_abstain")
        if not isinstance(should_abstain, bool):
            raise ValueError(f"review should_abstain must be a boolean for {case['case_id']}")
        answer_abstained = answer["abstained"]
        abstention_tp += int(should_abstain and answer_abstained)
        abstention_fp += int(not should_abstain and answer_abstained)
        abstention_fn += int(should_abstain and not answer_abstained)
        review_disagreements += int(should_abstain == bool(case.get("answerable")))
        claim_count += case_claim_count
        unsupported_count += case_unsupported
        rows.append({
            "case_id": case["case_id"], "reviewed_claim_count": case_claim_count,
            "unsupported_claim_count": case_unsupported,
            "citation_ids": case_citations, "human_supporting_ids": case_supported_ids,
            "citation_ids_in_retrieval": case_retrieved_citations,
            "should_abstain": should_abstain, "model_abstained": answer_abstained,
        })

    cited_counter = Counter(cited_ids)
    supported_counter = Counter(semantically_supported_ids)
    citation_true_positive = sum(min(count, supported_counter[evidence_id]) for evidence_id, count in cited_counter.items())
    supporting_total = sum(supported_counter.values())
    metrics = {
        "claim_support_rate": _safe_ratio(claim_count - unsupported_count, claim_count),
        "unsupported_claim_count": unsupported_count,
        "required_point_coverage": _safe_ratio(covered_points, required_points),
        "citation_precision": _safe_ratio(citation_true_positive, citation_count),
        "citation_recall": _safe_ratio(citation_true_positive, supporting_total),
        "citation_retrieval_membership_rate": _safe_ratio(valid_citations, citation_count),
        "abstention_precision": _safe_ratio(abstention_tp, abstention_tp + abstention_fp),
        "abstention_recall": _safe_ratio(abstention_tp, abstention_tp + abstention_fn),
        "review_label_disagreement_count": review_disagreements,
    }
    return {
        "evaluated_count": len(accepted), "excluded_count": excluded,
        "claim_count": claim_count, "metrics": metrics,
        # Keep top-level aliases for simple machine consumers in the first V2 report.
        "claim_support_rate": metrics["claim_support_rate"],
        "required_point_coverage": metrics["required_point_coverage"],
        "citation_precision": metrics["citation_precision"],
        "citation_recall": metrics["citation_recall"],
        "abstention_precision": metrics["abstention_precision"],
        "abstention_recall": metrics["abstention_recall"],
        "cases": rows,
        "metric_scope": "human-reviewed answer snapshots only; unsupported claims are not inferred from retrieval scores",
    }
