from __future__ import annotations

from copy import deepcopy

import pytest

import src.questions_processing as questions_processing
from src.candidate_knowledge import CandidatePackageMetadata
from src.document_metadata import DocumentMetadata
from src.pipeline import RunConfig
from src.questions_processing import QuestionsProcessor
from src.trusted_qa import (
    AnswerEvidenceAudit,
    DecisionState,
    PostAnswerEnforcementAction,
    PostAnswerEnforcementReason,
    decide_evidence_sufficiency,
    decide_post_answer_enforcement,
)
from scripts.run_trusted_qa_phase3_replay import build_replay


def _audit(**updates) -> AnswerEvidenceAudit:
    payload = {
        "generation_performed": True,
        "structured_output_valid": True,
        "answer_is_na": False,
        "claimed_citation_count": 1,
        "citation_count": 1,
        "citation_membership_valid": True,
        "semantic_support_verified": None,
        "post_validation_status": "VALID",
        "post_answer_shadow_decision": "ANSWER",
        "reason_codes": [],
        "generation_error_type": None,
    }
    payload.update(updates)
    return AnswerEvidenceAudit.model_validate(payload)


def _result(score=0.91, page=1):
    return {
        "document_id": "doc-a",
        "document_title": "Policy",
        "document_type": "policy",
        "source": "policy.pdf",
        "source_url": "https://example.test/policy",
        "category": "safety",
        "tags": [],
        "chunk_id": f"doc-a:{page}",
        "page": page,
        "text": "Evidence text.",
        "distance": score,
    }


class FakeRetriever:
    scores = (0.91, 0.84, 0.78)
    calls = 0

    def __init__(self, *args, **kwargs):
        pass

    def retrieve(self, **kwargs):
        type(self).calls += 1
        return [_result(score, index + 1) for index, score in enumerate(self.scores)]

    def retrieve_by_company_name(self, **kwargs):
        type(self).calls += 1
        return [_result(self.scores[0], 1)]


class FakeAnswerProcessor:
    calls = 0
    response_data = {"model": "fake-local", "input_tokens": 1, "output_tokens": 1}
    payload = {
        "step_by_step_analysis": "analysis",
        "reasoning_summary": "summary",
        "relevant_pages": [],
        "relevant_sources": [{"document_id": "doc-a", "page_number": 1}],
        "final_answer": "supported answer",
    }
    error = None

    def __init__(self, *args, **kwargs):
        pass

    def get_answer_from_rag_context(self, **kwargs):
        type(self).calls += 1
        if type(self).error is not None:
            raise type(self).error
        return deepcopy(type(self).payload)


def _processor(monkeypatch, mode="ENFORCE", *, scores=None, payload=None, error=None, **kwargs):
    FakeRetriever.calls = 0
    FakeRetriever.scores = scores or (0.91, 0.84, 0.78)
    FakeAnswerProcessor.calls = 0
    FakeAnswerProcessor.error = error
    FakeAnswerProcessor.payload = payload or {
        "step_by_step_analysis": "analysis",
        "reasoning_summary": "summary",
        "relevant_pages": [],
        "relevant_sources": [{"document_id": "doc-a", "page_number": 1}],
        "final_answer": "supported answer",
    }
    monkeypatch.setattr(questions_processing, "VectorRetriever", FakeRetriever)
    monkeypatch.setattr(questions_processing, "APIProcessor", FakeAnswerProcessor)
    return QuestionsProcessor(
        routing_mode="generic", trusted_qa_mode=mode, **kwargs
    )


def test_valid_factual_answer_with_valid_citation_passes():
    decision = decide_post_answer_enforcement(_audit(), mode="ENFORCE")
    assert decision.action == PostAnswerEnforcementAction.PASS
    assert decision.enforced is False


def test_explicit_na_with_empty_citations_is_valid_abstention():
    decision = decide_post_answer_enforcement(
        _audit(
            answer_is_na=True,
            claimed_citation_count=0,
            citation_count=0,
            post_validation_status="ANSWER_IS_NA",
            post_answer_shadow_decision="REJECT",
            reason_codes=["ANSWER_IS_NA"],
        ),
        mode="ENFORCE",
    )
    assert decision.action == PostAnswerEnforcementAction.VALID_ABSTENTION
    assert decision.reason_codes == [
        PostAnswerEnforcementReason.VALID_MODEL_ABSTENTION
    ]
    assert decision.enforced is False


def test_invalid_structured_output_fails_closed():
    decision = decide_post_answer_enforcement(
        _audit(
            structured_output_valid=False,
            answer_is_na=None,
            claimed_citation_count=None,
            citation_count=None,
            citation_membership_valid=None,
            post_validation_status="STRUCTURED_OUTPUT_INVALID",
            post_answer_shadow_decision="REJECT",
            reason_codes=["STRUCTURED_OUTPUT_INVALID"],
        ),
        mode="ENFORCE",
    )
    assert decision.action == PostAnswerEnforcementAction.FAIL_CLOSED
    assert decision.reason_codes == [
        PostAnswerEnforcementReason.STRUCTURED_OUTPUT_INVALID
    ]
    assert decision.enforced is True


def test_substantive_answer_without_citation_fails_closed():
    decision = decide_post_answer_enforcement(
        _audit(
            claimed_citation_count=0,
            citation_count=0,
            citation_membership_valid=False,
            post_validation_status="EMPTY_VALID_CITATIONS",
            post_answer_shadow_decision="REJECT",
            reason_codes=["ANSWER_WITHOUT_VALID_CITATION"],
        ),
        mode="ENFORCE",
    )
    assert decision.reason_codes == [
        PostAnswerEnforcementReason.SUBSTANTIVE_ANSWER_WITHOUT_CITATION
    ]
    assert decision.enforced is True


@pytest.mark.parametrize("valid_count", [0, 1])
def test_invalid_or_mixed_citation_membership_fails_closed(valid_count):
    decision = decide_post_answer_enforcement(
        _audit(
            claimed_citation_count=2,
            citation_count=valid_count,
            citation_membership_valid=False,
            post_validation_status=(
                "EMPTY_VALID_CITATIONS"
                if valid_count == 0
                else "INVALID_CITATIONS_FILTERED"
            ),
            post_answer_shadow_decision="UNCERTAIN",
            reason_codes=["CITATION_MEMBERSHIP_FAILED"],
        ),
        mode="ENFORCE",
    )
    assert decision.action == PostAnswerEnforcementAction.FAIL_CLOSED
    assert decision.reason_codes == [
        PostAnswerEnforcementReason.CITATION_MEMBERSHIP_INVALID
    ]


def test_na_with_a_citation_is_state_conflict():
    decision = decide_post_answer_enforcement(
        _audit(
            answer_is_na=True,
            post_validation_status="ANSWER_IS_NA",
            post_answer_shadow_decision="REJECT",
            reason_codes=["ANSWER_IS_NA"],
        ),
        mode="ENFORCE",
    )
    assert decision.action == PostAnswerEnforcementAction.FAIL_CLOSED
    assert decision.reason_codes == [
        PostAnswerEnforcementReason.ANSWER_CITATION_STATE_CONFLICT
    ]


def test_pre_generation_uncertain_does_not_block_valid_answer(monkeypatch):
    processor = _processor(monkeypatch, scores=(0.68, 0.64, 0.61))
    answer = processor.process_question("question", "text", question_id="q-uncertain")
    trace = processor.get_trusted_qa_traces()[0]

    assert trace["shadow_decision"]["decision"] == "UNCERTAIN"
    assert trace["post_answer_enforcement"]["action"] == "PASS"
    assert answer["final_answer"] == "supported answer"
    assert FakeAnswerProcessor.calls == 1


def test_pre_generation_answer_cannot_bypass_invalid_citation(monkeypatch):
    payload = deepcopy(FakeAnswerProcessor.payload)
    payload["relevant_sources"] = [{"document_id": "doc-x", "page_number": 99}]
    processor = _processor(monkeypatch, payload=payload)
    answer = processor.process_question("question", "text", question_id="q-invalid")
    trace = processor.get_trusted_qa_traces()[0]

    assert trace["shadow_decision"]["decision"] == "ANSWER"
    assert trace["post_answer_enforcement"]["action"] == "FAIL_CLOSED"
    assert answer["final_answer"] == "N/A"
    assert answer["sources"] == []
    assert answer["relevant_sources"] == []


def test_off_shadow_and_enforce_have_distinct_response_behavior(monkeypatch):
    payload = deepcopy(FakeAnswerProcessor.payload)
    payload["relevant_sources"] = [{"document_id": "doc-x", "page_number": 99}]

    off = _processor(monkeypatch, mode="OFF", payload=payload)
    off_answer = off.process_question("question", "text", question_id="q-off")
    shadow = _processor(monkeypatch, mode="SHADOW", payload=payload)
    shadow_answer = shadow.process_question("question", "text", question_id="q-shadow")
    enforce = _processor(monkeypatch, mode="ENFORCE", payload=payload)
    enforce_answer = enforce.process_question("question", "text", question_id="q-enforce")

    assert off_answer["final_answer"] == "supported answer"
    assert shadow_answer["final_answer"] == "supported answer"
    assert enforce_answer["final_answer"] == "N/A"
    assert off.get_trusted_qa_traces() == []
    assert shadow.get_trusted_qa_traces()[0]["post_answer_enforcement"]["enforced"] is False
    assert enforce.get_trusted_qa_traces()[0]["post_answer_enforcement"]["enforced"] is True


def test_enforce_does_not_skip_generation_or_add_gate_llm_call(monkeypatch):
    processor = _processor(monkeypatch, scores=(0.44, 0.42, 0.40))
    processor.process_question("question", "text", question_id="q-low")
    trace = processor.get_trusted_qa_traces()[0]

    assert FakeAnswerProcessor.calls == 1
    assert trace["shadow_decision"]["decision"] == "UNCERTAIN"
    assert trace["post_answer_enforcement"]["extra_llm_calls"] == 0
    assert trace["post_answer_enforcement"]["pre_generation_enforcement"] is False
    assert trace["post_answer_enforcement"]["post_answer_enforcement"] is True


def test_policy_version_reason_codes_and_original_output_are_recorded(monkeypatch):
    payload = deepcopy(FakeAnswerProcessor.payload)
    payload["relevant_sources"] = [{"document_id": "doc-x", "page_number": 99}]
    processor = _processor(monkeypatch, payload=payload)
    answer = processor.process_question("question", "text", question_id="q-audit")
    trace = processor.get_trusted_qa_traces()[0]
    enforcement = trace["post_answer_enforcement"]

    assert enforcement["policy_version"] == "trusted_qa_post_answer_v1"
    assert enforcement["reason_codes"] == ["CITATION_MEMBERSHIP_INVALID"]
    assert trace["original_pipeline_result"]["final_answer"] == "supported answer"
    assert trace["original_pipeline_result"]["relevant_sources"] == payload["relevant_sources"]
    assert trace["final_pipeline_result"]["final_answer"] == "N/A"
    assert trace["post_answer_audit"]["citation_membership_valid"] is False
    assert set(answer) == {
        "step_by_step_analysis",
        "reasoning_summary",
        "relevant_pages",
        "relevant_sources",
        "final_answer",
        "sources",
    }


def test_structured_output_error_is_fail_closed_only_in_enforce(monkeypatch):
    processor = _processor(
        monkeypatch, mode="ENFORCE", error=ValueError("invalid structured response")
    )
    answer = processor.process_question("question", "text", question_id="q-structure")
    assert answer["final_answer"] == "N/A"
    assert answer["sources"] == []
    assert processor.get_trusted_qa_traces()[0]["post_answer_enforcement"]["reason_codes"] == [
        "STRUCTURED_OUTPUT_INVALID"
    ]

    shadow = _processor(
        monkeypatch, mode="SHADOW", error=ValueError("invalid structured response")
    )
    with pytest.raises(ValueError, match="invalid structured response"):
        shadow.process_question("question", "text", question_id="q-shadow-structure")


def test_citation_membership_validator_semantics_are_unchanged(monkeypatch):
    processor = _processor(monkeypatch, mode="OFF")
    retrieved = [_result(page=1)]
    claims = [
        {"document_id": "doc-a", "page_number": 1},
        {"document_id": "doc-x", "page_number": 1},
    ]
    assert processor._validate_source_references(claims, retrieved) == [
        {
            "document_id": "doc-a",
            "document_title": "Policy",
            "page_number": 1,
            "source": "policy.pdf",
            "source_url": "https://example.test/policy",
        }
    ]


def test_legacy_mode_and_metadata_contracts_remain_compatible(monkeypatch):
    FakeRetriever.calls = 0
    FakeRetriever.scores = (0.9,)
    FakeAnswerProcessor.calls = 0
    FakeAnswerProcessor.error = None
    FakeAnswerProcessor.payload = {
        "step_by_step_analysis": "analysis",
        "reasoning_summary": "summary",
        "relevant_pages": [],
        "final_answer": "legacy answer",
    }
    monkeypatch.setattr(questions_processing, "VectorRetriever", FakeRetriever)
    monkeypatch.setattr(questions_processing, "APIProcessor", FakeAnswerProcessor)
    processor = QuestionsProcessor(
        routing_mode="legacy_company", trusted_qa_mode="ENFORCE"
    )
    answer = processor.process_question('What applies to "Acme"?', "text")

    assert answer["final_answer"] == "legacy answer"
    assert "trusted_qa" not in answer
    assert processor.get_trusted_qa_traces()[0]["post_answer_enforcement"]["action"] == "PASS"
    assert "trusted_qa_mode" not in DocumentMetadata.model_fields
    assert "trusted_qa_mode" not in CandidatePackageMetadata.model_fields


@pytest.mark.parametrize("scope", ["PRE_GENERATION", "FULL", "UNSUPPORTED"])
def test_unsupported_enforcement_scope_is_rejected(monkeypatch, scope):
    monkeypatch.setattr(questions_processing, "VectorRetriever", FakeRetriever)
    monkeypatch.setattr(questions_processing, "APIProcessor", FakeAnswerProcessor)
    with pytest.raises(NotImplementedError, match="POST_ANSWER_ONLY"):
        QuestionsProcessor(
            routing_mode="generic",
            trusted_qa_mode="ENFORCE",
            trusted_qa_enforcement_scope=scope,
        )
    with pytest.raises(NotImplementedError, match="POST_ANSWER_ONLY"):
        RunConfig(
            routing_mode="generic",
            trusted_qa_mode="ENFORCE",
            trusted_qa_enforcement_scope=scope,
        )


def test_saved_phase2_failures_are_intercepted_without_false_fail_closed():
    replay, metrics = build_replay()

    assert replay["answer_llm_called"] is False
    assert replay["gate_extra_llm_calls"] == 0
    assert metrics["known_invalid_intercepted_count"] == 2
    assert metrics["citation_membership_failure_intercepted_count"] == 2
    assert metrics["known_valid_answer_preserved_count"] == 2
    assert metrics["valid_abstention_preserved_count"] == 5
    assert metrics["false_fail_closed_count"] == 0
    assert metrics["retrieval_miss_remains_limitation"] is True
