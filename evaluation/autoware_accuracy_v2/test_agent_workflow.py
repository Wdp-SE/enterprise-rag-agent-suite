from run_agent_workflow import effective_language_mode, to_agent_evaluation_row


def test_workflow_baseline_preserves_evidence_without_claiming_agent_impacts():
    case = {"case_id": "case-1"}
    review = {
        "retrieved_results": [{
            "document_id": "docs-main:zh:guide/a", "version": "docs-main",
            "language": "zh", "document_relationships": [{
                "verification_status": "candidate",
            }],
        }],
        "coverage": {
            "required_check_count": 2, "covered_check_count": 1,
            "attempted_languages": ["zh", "en"], "covered_languages": ["zh"],
            "complete": False,
        },
        "retrieval_trace": {"queries": [{"language": "zh"}, {"language": "en"}], "model_status": "GENERATION_NOT_CONFIGURED"},
        "evidence_gap_details": [{"gap_type": "UNVERIFIED_TRANSLATION"}],
        "scope_status": "IN_SCOPE",
    }

    result = to_agent_evaluation_row(case, review, latency_ms=18.5)

    assert result["retrieved_source_ids"] == ["docs-main:zh:guide/a"]
    assert result["relation_states"] == {"docs-main:zh:guide/a": "candidate"}
    assert result["gap_types"] == ["UNVERIFIED_TRANSLATION"]
    assert result["coverage"]["complete"] is False
    assert result["model_status"] == "NOT_CALLED"
    assert result["impact_candidates"] == []
    assert result["abstention_evaluated"] is False
    assert result["latency_ms"] == 18.5


def test_scope_guard_not_called_status_is_a_deterministic_abstention():
    case = {"case_id": "private-scope"}
    review = {
        "retrieved_results": [], "coverage": {"complete": False},
        "retrieval_trace": {"queries": [], "model_status": "NOT_CALLED_OUT_OF_SCOPE"},
        "evidence_gap_details": [{"gap_type": "OUT_OF_SCOPE_PUBLIC_CORPUS"}],
        "scope_status": "OUT_OF_SCOPE",
    }

    result = to_agent_evaluation_row(case, review, latency_ms=1.2)

    assert result["model_status"] == "NOT_CALLED"
    assert result["abstained"] is True
    assert result["abstention_evaluated"] is True


def test_agent_workflow_can_compare_language_modes_without_mutating_case_labels():
    case = {"language": "bilingual"}

    assert effective_language_mode(case, None) == "bilingual"
    assert effective_language_mode(case, "zh") == "zh"
    assert case["language"] == "bilingual"
