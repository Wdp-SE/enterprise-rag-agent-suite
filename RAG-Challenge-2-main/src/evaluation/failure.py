"""Baseline failure taxonomy without automatic remediation."""

from __future__ import annotations

from enum import Enum
from typing import Iterable, List, Mapping, Optional

from pydantic import BaseModel, ConfigDict

from src.evaluation.dataset import EvaluationItem


class FailureType(str, Enum):
    PARSE_FAILURE = "PARSE_FAILURE"
    CHUNKING_MISS = "CHUNKING_MISS"
    RETRIEVAL_MISS = "RETRIEVAL_MISS"
    RERANK_MISS = "RERANK_MISS"
    PARENT_PAGE_MISS = "PARENT_PAGE_MISS"
    CITATION_MISS = "CITATION_MISS"
    ANSWER_GENERATION_ERROR = "ANSWER_GENERATION_ERROR"
    UNSUPPORTED_CLAIM = "UNSUPPORTED_CLAIM"
    UNANSWERABLE_HALLUCINATION = "UNANSWERABLE_HALLUCINATION"
    VERSION_AMBIGUITY = "VERSION_AMBIGUITY"
    WRONG_ACTIVE_VERSION = "WRONG_ACTIVE_VERSION"
    WRONG_HISTORICAL_VERSION = "WRONG_HISTORICAL_VERSION"
    TEMPORAL_FILTER_MISS = "TEMPORAL_FILTER_MISS"
    VERSION_METADATA_MISSING = "VERSION_METADATA_MISSING"
    DATASET_SOURCE_MISSING = "DATASET_SOURCE_MISSING"
    UNKNOWN = "UNKNOWN"


class FailureCase(BaseModel):
    model_config = ConfigDict(extra="forbid")

    question_id: str
    failure_type: FailureType
    evidence: str
    likely_cause: str


def classify_failures(
    items: Iterable[EvaluationItem],
    retrieval_results: Mapping[str, List[dict]],
    *,
    citations_by_question: Optional[Mapping[str, List[dict]]] = None,
    answers_by_question: Optional[Mapping[str, dict]] = None,
    parse_blocked_document_ids: Optional[set[str]] = None,
    version_traces_by_question: Optional[Mapping[str, dict]] = None,
) -> List[FailureCase]:
    citations_by_question = citations_by_question or {}
    answers_by_question = answers_by_question or {}
    parse_blocked_document_ids = parse_blocked_document_ids or set()
    version_traces_by_question = version_traces_by_question or {}
    failures = []

    for item in items:
        results = list(retrieval_results.get(item.question_id, []))
        retrieved_ids = {result.get("document_id") for result in results}
        retrieved_pages = {
            (result.get("document_id"), result.get("page", result.get("page_number")))
            for result in results
        }
        expected_ids = set(item.expected_document_ids)
        expected_pages = {
            (page.document_id, page.page_number) for page in item.expected_pages
        }
        answer = dict(answers_by_question.get(item.question_id, {}))
        version_trace = dict(version_traces_by_question.get(item.question_id, {}))

        failure_type = None
        evidence = ""
        cause = ""
        if not item.answerable and answer.get("answer", answer.get("final_answer")) not in (
            None,
            "",
            "N/A",
        ):
            failure_type = FailureType.UNANSWERABLE_HALLUCINATION
            evidence = "The system produced a substantive answer for an unanswerable item."
            cause = "No reject policy is active in the baseline."
        elif answer.get("error"):
            failure_type = FailureType.ANSWER_GENERATION_ERROR
            evidence = str(answer["error"])
            cause = "The answer-generation call or structured parsing failed."
        elif answer.get("unsupported_claim") is True:
            failure_type = FailureType.UNSUPPORTED_CLAIM
            evidence = "Manual review marked at least one answer claim unsupported."
            cause = "Generation exceeded the retrieved evidence."
        elif expected_ids & parse_blocked_document_ids:
            failure_type = FailureType.PARSE_FAILURE
            evidence = f"Expected documents blocked from ingestion: {sorted(expected_ids & parse_blocked_document_ids)}"
            cause = "The source PDF requires OCR or failed parsing."
        elif item.answerable and not (expected_ids & retrieved_ids):
            failure_type = _classify_retrieval_failure(
                item, expected_ids, version_trace
            )
            evidence = f"Expected {sorted(expected_ids)}; retrieved {sorted(x for x in retrieved_ids if x)}"
            cause = (
                "The baseline does not resolve current and historical versions."
                if item.question_type == "version_temporal"
                else "No expected document appeared in the evaluated top-k results."
            )
        elif item.answerable and expected_pages and not (expected_pages & retrieved_pages):
            failure_type = FailureType.PARENT_PAGE_MISS
            evidence = f"Expected pages {sorted(expected_pages)} were absent from retrieved parent pages."
            cause = "The right document was found but the supporting page was not returned."
        elif item.answerable and item.question_id in citations_by_question:
            citation_keys = {
                (
                    citation.get("document_id"),
                    citation.get("page_number", citation.get("page")),
                )
                for citation in citations_by_question[item.question_id]
            }
            if expected_pages and not (expected_pages & citation_keys):
                failure_type = FailureType.CITATION_MISS
                evidence = f"Expected citation pages {sorted(expected_pages)}; got {sorted(citation_keys)}"
                cause = "Generated citations did not hit a ground-truth page."

        if failure_type is not None:
            failures.append(
                FailureCase(
                    question_id=item.question_id,
                    failure_type=failure_type,
                    evidence=evidence,
                    likely_cause=cause,
                )
            )
    return failures


def _classify_retrieval_failure(
    item: EvaluationItem,
    expected_ids: set[str],
    version_trace: Mapping[str, object],
) -> FailureType:
    if item.question_type != "version_temporal":
        return FailureType.RETRIEVAL_MISS
    if not version_trace:
        return FailureType.VERSION_AMBIGUITY

    issues = {str(issue) for issue in version_trace.get("issues", [])}
    if any(
        f"INDEX_ASSET_MISSING:{document_id}" in issues
        or f"DATASET_SOURCE_MISSING:{document_id}" in issues
        for document_id in expected_ids
    ):
        return FailureType.DATASET_SOURCE_MISSING
    if any(issue.startswith("VERSION_METADATA_MISSING:") for issue in issues):
        return FailureType.VERSION_METADATA_MISSING
    if any(issue.startswith("TEMPORAL_FILTER_MISS:") for issue in issues):
        return FailureType.TEMPORAL_FILTER_MISS

    decisions = {
        decision.get("candidate_document_id"): decision
        for decision in version_trace.get("candidate_documents", [])
        if isinstance(decision, dict)
    }
    expected_statuses = {
        decisions[document_id].get("document_status")
        for document_id in expected_ids
        if document_id in decisions
    }
    if version_trace.get("temporal_ambiguity"):
        return FailureType.VERSION_AMBIGUITY
    intent = version_trace.get("version_intent")
    if intent in {"HISTORICAL", "EXPLICIT_VERSION"} or "SUPERSEDED" in expected_statuses:
        return FailureType.WRONG_HISTORICAL_VERSION
    if intent in {"CURRENT", "UNSPECIFIED", "TEMPORAL_DATE"}:
        return FailureType.WRONG_ACTIVE_VERSION
    return FailureType.VERSION_AMBIGUITY
