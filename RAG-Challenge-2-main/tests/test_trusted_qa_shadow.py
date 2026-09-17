from types import SimpleNamespace

import pytest

import src.questions_processing as questions_processing
from src.candidate_knowledge import CandidatePackageMetadata
from src.document_metadata import DocumentMetadata
from src.questions_processing import QuestionsProcessor
from src.trusted_qa import (
    DecisionState,
    PostValidationStatus,
    ReasonCode,
    ShadowPolicyProfile,
    TrustedQAMode,
    VersionResolutionStatus,
    build_answer_evidence_audit,
    collect_retrieval_signals,
    decide_evidence_sufficiency,
    evaluate_shadow_decisions,
)


def _result(score=0.9, *, document_id="doc-a", page=1, rerank=None):
    result = {
        "document_id": document_id,
        "document_title": "Policy",
        "document_type": "policy",
        "source": "policy.pdf",
        "source_url": "https://example.test/policy",
        "category": "safety",
        "tags": [],
        "chunk_id": f"{document_id}:{page}",
        "page": page,
        "text": "Evidence text.",
        "distance": score,
    }
    if rerank is not None:
        result["relevance_score"] = rerank
    return result


def _snapshot(scores=(0.9, 0.82, 0.78), **kwargs):
    results = [
        _result(score, page=index + 1)
        for index, score in enumerate(scores)
    ]
    return collect_retrieval_signals(
        question_id="q-1", retrieval_results=results, **kwargs
    )


def _fake_version_plan(*, eligible=("doc-a",), ambiguous=False, issues=()):
    return SimpleNamespace(
        eligible_document_ids=list(eligible),
        issues=list(issues),
        context=SimpleNamespace(
            intent=SimpleNamespace(value="TEMPORAL_DATE"),
            temporal_ambiguity=ambiguous,
        ),
    )


def test_signal_snapshot_serialization_and_observation_fields():
    snapshot = collect_retrieval_signals(
        question_id="q-1",
        retrieval_results=[
            _result(0.91, document_id="doc-a", page=1, rerank=0.8),
            _result(0.83, document_id="doc-a", page=2, rerank=0.6),
            _result(0.75, document_id="doc-b", page=1, rerank=0.2),
        ],
    )
    payload = snapshot.model_dump(mode="json")

    assert payload["top1_score"] == 0.91
    assert payload["top1_top2_margin"] == 0.08
    assert payload["retrieved_document_count"] == 2
    assert payload["retrieved_page_count"] == 3
    assert payload["citation_candidates_available"] is True
    assert payload["rerank_available"] is True
    assert payload["rerank_score"] == 0.8
    assert payload["version_resolution_status"] == "DISABLED"
    assert "confidence_score" not in payload
    assert "should_reject" not in payload


def test_no_retrieval_is_hard_reject():
    snapshot = collect_retrieval_signals(
        question_id="empty", retrieval_results=[]
    )
    decision = decide_evidence_sufficiency(snapshot)

    assert decision.decision == DecisionState.REJECT
    assert decision.reason_codes == [ReasonCode.NO_RETRIEVAL_RESULT]


def test_no_eligible_document_is_hard_reject():
    snapshot = collect_retrieval_signals(
        question_id="q-version",
        retrieval_results=[_result()],
        version_governance_enabled=True,
        version_plan=_fake_version_plan(eligible=()),
    )
    decision = decide_evidence_sufficiency(snapshot)

    assert decision.decision == DecisionState.REJECT
    assert ReasonCode.NO_ELIGIBLE_DOCUMENT in decision.reason_codes


def test_version_ambiguity_is_uncertain_not_silent_answer():
    snapshot = collect_retrieval_signals(
        question_id="q-version",
        retrieval_results=[_result()],
        version_governance_enabled=True,
        version_plan=_fake_version_plan(ambiguous=True),
    )
    decision = decide_evidence_sufficiency(snapshot)

    assert snapshot.version_resolution_status == VersionResolutionStatus.AMBIGUOUS
    assert decision.decision == DecisionState.UNCERTAIN
    assert decision.reason_codes == [ReasonCode.VERSION_AMBIGUITY]


def test_version_resolution_failure_is_hard_reject():
    snapshot = collect_retrieval_signals(
        question_id="q-version",
        retrieval_results=[_result()],
        version_governance_enabled=True,
        version_plan=_fake_version_plan(issues=("INDEX_ASSET_MISSING:doc-old",)),
    )
    decision = decide_evidence_sufficiency(snapshot)

    assert snapshot.version_resolution_status == VersionResolutionStatus.FAILED
    assert ReasonCode.VERSION_RESOLUTION_FAILED in decision.reason_codes


def test_invalid_retrieval_state_is_hard_reject():
    invalid = _result()
    invalid.pop("page")
    snapshot = collect_retrieval_signals(
        question_id="q-invalid-retrieval", retrieval_results=[invalid]
    )
    decision = decide_evidence_sufficiency(snapshot)

    assert snapshot.retrieval_state_valid is False
    assert decision.decision == DecisionState.REJECT
    assert ReasonCode.INVALID_RETRIEVAL_STATE in decision.reason_codes


def test_ordinary_strong_retrieval_can_receive_shadow_answer():
    decision = decide_evidence_sufficiency(_snapshot())
    assert decision.decision == DecisionState.ANSWER
    assert decision.reason_codes == []


def test_cosine_alone_does_not_hard_reject_low_score_answerable_case():
    decision = decide_evidence_sufficiency(_snapshot((0.44, 0.42, 0.40)))
    assert decision.decision == DecisionState.UNCERTAIN
    assert decision.decision != DecisionState.REJECT
    assert decision.reason_codes == [ReasonCode.WEAK_RETRIEVAL_SIGNAL]


def test_high_top1_alone_does_not_automatically_answer():
    decision = decide_evidence_sufficiency(_snapshot((0.95, 0.2, 0.1)))
    assert decision.decision == DecisionState.UNCERTAIN
    assert decision.reason_codes == [ReasonCode.AMBIGUOUS_RETRIEVAL_SIGNAL]


def test_middle_region_is_uncertain():
    decision = decide_evidence_sufficiency(_snapshot((0.68, 0.64, 0.61)))
    assert decision.decision == DecisionState.UNCERTAIN


def test_shadow_decision_is_deterministic():
    snapshot = _snapshot((0.68, 0.64, 0.61))
    first = decide_evidence_sufficiency(snapshot)
    second = decide_evidence_sufficiency(snapshot)
    assert first == second


def test_reason_codes_and_policy_version_are_stable():
    assert ReasonCode.NO_RETRIEVAL_RESULT.value == "NO_RETRIEVAL_RESULT"
    decision = decide_evidence_sufficiency(_snapshot())
    assert decision.policy_version == "trusted_qa_shadow_v0_1"
    assert decision.shadow_mode is True


def test_off_mode_returns_no_decision_and_enforce_keeps_pre_generation_shadow_only():
    snapshot = _snapshot()
    assert decide_evidence_sufficiency(
        snapshot, mode=TrustedQAMode.OFF
    ) is None
    enforce_observation = decide_evidence_sufficiency(
        snapshot, mode=TrustedQAMode.ENFORCE
    )
    assert enforce_observation.decision == DecisionState.ANSWER
    assert enforce_observation.shadow_mode is True


def test_policy_ablation_profiles_are_distinct_and_deterministic():
    snapshot = _snapshot((0.8, 0.76, 0.72))
    hard = decide_evidence_sufficiency(
        snapshot, profile=ShadowPolicyProfile.HARD_ONLY
    )
    soft = decide_evidence_sufficiency(
        snapshot, profile=ShadowPolicyProfile.HARD_PLUS_SOFT
    )
    agreement = decide_evidence_sufficiency(
        snapshot, profile=ShadowPolicyProfile.HARD_SOFT_AGREEMENT
    )

    assert hard.policy_version == "trusted_qa_shadow_v0_1_hard"
    assert soft.policy_version == "trusted_qa_shadow_v0_1"
    assert agreement.policy_version == "trusted_qa_shadow_v0_1_agreement"


def test_citation_candidate_signal_is_membership_availability_only():
    snapshot = _snapshot()
    assert snapshot.citation_candidates_available is True
    assert snapshot.citation_candidate_count == 3
    assert not hasattr(snapshot, "semantic_support_verified")


def test_answer_audit_keeps_membership_separate_from_entailment():
    audit = build_answer_evidence_audit(
        generation_performed=True,
        structured_output_valid=True,
        final_answer="A supported-looking answer",
        claimed_citations=[{"document_id": "doc-a", "page_number": 1}],
        validated_citations=[{"document_id": "doc-a", "page_number": 1}],
        citation_membership_checked=True,
    )

    assert audit.citation_membership_valid is True
    assert audit.semantic_support_verified is None
    assert audit.post_validation_status == PostValidationStatus.VALID


def test_answer_audit_records_filtered_and_empty_citations():
    filtered = build_answer_evidence_audit(
        generation_performed=True,
        structured_output_valid=True,
        final_answer="answer",
        claimed_citations=[{"page": 1}, {"page": 99}],
        validated_citations=[{"page": 1}],
        citation_membership_checked=True,
    )
    empty = build_answer_evidence_audit(
        generation_performed=True,
        structured_output_valid=True,
        final_answer="answer",
        claimed_citations=[],
        validated_citations=[],
        citation_membership_checked=True,
    )

    assert filtered.post_answer_shadow_decision == DecisionState.UNCERTAIN
    assert filtered.reason_codes == [ReasonCode.CITATION_MEMBERSHIP_FAILED]
    assert empty.post_answer_shadow_decision == DecisionState.REJECT
    assert empty.reason_codes == [ReasonCode.ANSWER_WITHOUT_VALID_CITATION]


def test_structured_output_failure_and_na_are_audited():
    invalid = build_answer_evidence_audit(
        generation_performed=True,
        structured_output_valid=False,
        citation_membership_checked=False,
        generation_error_type="ValidationError",
    )
    na = build_answer_evidence_audit(
        generation_performed=True,
        structured_output_valid=True,
        final_answer="N/A",
        claimed_citations=[],
        validated_citations=[],
        citation_membership_checked=True,
    )

    assert invalid.post_validation_status == PostValidationStatus.STRUCTURED_OUTPUT_INVALID
    assert invalid.post_answer_shadow_decision == DecisionState.REJECT
    assert na.answer_is_na is True
    assert na.post_validation_status == PostValidationStatus.ANSWER_IS_NA


class FakeRetriever:
    calls = 0

    def __init__(self, *args, **kwargs):
        pass

    def retrieve(self, **kwargs):
        type(self).calls += 1
        return [
            _result(0.91, page=1),
            _result(0.84, page=2),
            _result(0.78, page=3),
        ]


class FakeAnswerProcessor:
    calls = 0
    response_data = {"model": "fake-local", "input_tokens": 1, "output_tokens": 1}

    def __init__(self, *args, **kwargs):
        pass

    def get_answer_from_rag_context(self, **kwargs):
        type(self).calls += 1
        return {
            "step_by_step_analysis": "analysis",
            "reasoning_summary": "summary",
            "relevant_pages": [],
            "relevant_sources": [{"document_id": "doc-a", "page_number": 1}],
            "final_answer": "answer",
        }


def _processor(monkeypatch, mode):
    FakeRetriever.calls = 0
    FakeAnswerProcessor.calls = 0
    monkeypatch.setattr(questions_processing, "VectorRetriever", FakeRetriever)
    monkeypatch.setattr(questions_processing, "APIProcessor", FakeAnswerProcessor)
    return QuestionsProcessor(routing_mode="generic", trusted_qa_mode=mode)


def test_questions_processor_off_mode_has_no_trace(monkeypatch):
    processor = _processor(monkeypatch, "OFF")
    answer = processor.process_question("question", "text", question_id="q-off")

    assert answer["final_answer"] == "answer"
    assert processor.get_trusted_qa_traces() == []


def test_shadow_mode_does_not_change_response_or_skip_generation(monkeypatch):
    off = _processor(monkeypatch, "OFF")
    off_answer = off.process_question("question", "text", question_id="q-off")
    shadow = _processor(monkeypatch, "SHADOW")
    shadow_answer = shadow.process_question(
        "question", "text", question_id="q-shadow"
    )

    assert shadow_answer == off_answer
    assert set(shadow_answer) == set(off_answer)
    assert FakeRetriever.calls == 1
    assert FakeAnswerProcessor.calls == 1
    traces = shadow.get_trusted_qa_traces()
    assert len(traces) == 1
    assert traces[0]["shadow_decision"]["decision"] == "ANSWER"
    assert traces[0]["actual_pipeline_result"]["final_answer"] == "answer"


def test_shadow_trace_post_answer_citation_audit(monkeypatch):
    processor = _processor(monkeypatch, "SHADOW")
    processor.process_question("question", "text", question_id="q-citation")
    audit = processor.get_trusted_qa_traces()[0]["post_answer_audit"]

    assert audit["citation_count"] == 1
    assert audit["citation_membership_valid"] is True
    assert audit["semantic_support_verified"] is None


def test_shadow_records_structured_generation_failure_without_changing_error_flow(
    monkeypatch,
):
    class FailingAnswerProcessor(FakeAnswerProcessor):
        def get_answer_from_rag_context(self, **kwargs):
            raise ValueError("invalid structured response")

    monkeypatch.setattr(questions_processing, "VectorRetriever", FakeRetriever)
    monkeypatch.setattr(questions_processing, "APIProcessor", FailingAnswerProcessor)
    processor = QuestionsProcessor(routing_mode="generic", trusted_qa_mode="SHADOW")

    with pytest.raises(ValueError, match="invalid structured response"):
        processor.process_question("question", "text", question_id="q-invalid")
    audit = processor.get_trusted_qa_traces()[0]["post_answer_audit"]
    assert audit["structured_output_valid"] is False
    assert audit["post_validation_status"] == "STRUCTURED_OUTPUT_INVALID"


def test_enforce_mode_keeps_valid_generic_answer(monkeypatch):
    processor = _processor(monkeypatch, "ENFORCE")
    answer = processor.process_question("question", "text", question_id="q-enforce")

    assert answer["final_answer"] == "answer"
    assert FakeAnswerProcessor.calls == 1
    trace = processor.get_trusted_qa_traces()[0]
    assert trace["shadow_decision"]["shadow_mode"] is True
    assert trace["post_answer_enforcement"]["action"] == "PASS"
    assert trace["post_answer_enforcement"]["enforced"] is False


def test_legacy_mode_response_remains_compatible_in_shadow(monkeypatch):
    class LegacyRetriever(FakeRetriever):
        def retrieve_by_company_name(self, **kwargs):
            type(self).calls += 1
            return [_result(0.9, page=1)]

    monkeypatch.setattr(questions_processing, "VectorRetriever", LegacyRetriever)
    monkeypatch.setattr(questions_processing, "APIProcessor", FakeAnswerProcessor)
    processor = QuestionsProcessor(
        routing_mode="legacy_company", trusted_qa_mode="SHADOW"
    )
    answer = processor.process_question('What applies to "Acme"?', "text")

    assert answer["final_answer"] == "answer"
    assert "trusted_qa" not in answer
    assert len(processor.get_trusted_qa_traces()) == 1


def test_version_plan_is_observed_without_mutation():
    plan = _fake_version_plan(eligible=("doc-a",), issues=("NOTE",))
    before = (list(plan.eligible_document_ids), list(plan.issues), plan.context.temporal_ambiguity)
    collect_retrieval_signals(
        question_id="q-version",
        retrieval_results=[_result()],
        version_governance_enabled=True,
        version_plan=plan,
    )
    after = (list(plan.eligible_document_ids), list(plan.issues), plan.context.temporal_ambiguity)
    assert after == before


def test_candidate_and_document_metadata_contracts_are_unaffected():
    assert "trusted_qa_mode" not in DocumentMetadata.model_fields
    assert "trusted_qa_mode" not in CandidatePackageMetadata.model_fields


def test_shadow_metrics_are_counterfactual_and_handle_uncertain():
    metrics = evaluate_shadow_decisions(
        [
            {"ground_truth_answerable": True, "shadow_decision": "ANSWER"},
            {"ground_truth_answerable": True, "shadow_decision": "UNCERTAIN"},
            {"ground_truth_answerable": False, "shadow_decision": "REJECT"},
            {"ground_truth_answerable": False, "shadow_decision": "ANSWER"},
        ]
    )

    assert metrics["metric_scope"] == "counterfactual_shadow_only"
    assert metrics["shadow_false_reject_rate"] == 0.0
    assert metrics["shadow_false_accept_rate"] == 0.5
    assert metrics["shadow_uncertain_rate"] == 0.25
    assert metrics["production_accuracy"] is None
