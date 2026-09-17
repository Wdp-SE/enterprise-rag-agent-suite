from scripts.run_rd_v2_real_retrieval_validation import evaluate_case, metric_block


def test_dense_page_metrics_treat_multiple_expected_pages_as_relevant():
    item = {
        "question_id": "rdq-test",
        "question_type": "cross_section",
        "expected_document_id": "doc-a",
        "expected_pages": [2, 4],
        "expected_section_sources": ["WORD_OUTLINE"],
    }
    ranked = [
        {"document_id": "doc-a", "page_number": 4},
        {"document_id": "doc-b", "page_number": 1},
        {"document_id": "doc-a", "page_number": 2},
        {"document_id": "doc-b", "page_number": 2},
        {"document_id": "doc-b", "page_number": 3},
    ]

    result = evaluate_case(item, ranked)

    assert result["hit_at_k"] == {"1": 1, "3": 1, "5": 1}
    assert result["recall_at_k"] == {"1": 0.5, "3": 1.0, "5": 1.0}
    assert result["reciprocal_rank"] == 1.0


def test_empty_section_source_metric_is_explicitly_not_applicable():
    result = metric_block([])

    assert result["evaluated_questions"] == 0
    assert result["hit_at_k"] == {"1": None, "3": None, "5": None}
    assert result["recall_at_k"] == {"1": None, "3": None, "5": None}
    assert result["mrr"] is None
