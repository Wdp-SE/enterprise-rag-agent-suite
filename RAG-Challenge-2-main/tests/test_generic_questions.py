import src.questions_processing as questions_processing
from src.api_requests import APIProcessor
from src.questions_processing import QuestionsProcessor


class FakeRetriever:
    init_count = 0

    def __init__(self, *args, **kwargs):
        type(self).init_count += 1
        self.calls = []

    def retrieve(self, **kwargs):
        self.calls.append(kwargs)
        return [
            {
                "document_id": "policy-a",
                "document_title": "Safety Policy",
                "document_type": "policy",
                "source": "policy-a.pdf",
                "source_url": "https://example.test/policy-a",
                "category": "safety",
                "tags": [],
                "chunk_id": "policy-a:0",
                "page": 4,
                "text": "The responsible unit must establish a safety system.",
                "distance": 0.91,
            }
        ]


class FakeAnswerProcessor:
    response_data = {"model": "fake-local"}

    def __init__(self, *args, **kwargs):
        self.calls = []

    def get_answer_from_rag_context(self, **kwargs):
        self.calls.append(kwargs)
        return {
            "step_by_step_analysis": "analysis",
            "reasoning_summary": "summary",
            "relevant_pages": [],
            "relevant_sources": [
                {"document_id": "policy-a", "page_number": 4},
                {"document_id": "policy-a", "page_number": 99},
                {"document_id": "other-doc", "page_number": 4},
            ],
            "final_answer": "Establish a safety system.",
        }


def test_generic_mode_does_not_extract_company_and_reuses_retriever(monkeypatch):
    FakeRetriever.init_count = 0
    monkeypatch.setattr(questions_processing, "VectorRetriever", FakeRetriever)
    monkeypatch.setattr(questions_processing, "APIProcessor", FakeAnswerProcessor)
    processor = QuestionsProcessor(
        questions_file_path=None,
        routing_mode="generic",
        new_challenge_pipeline=True,
    )

    first = processor.process_question("What safety system is required?", "text")
    second = processor.process_question("Who is responsible?", "text")

    assert FakeRetriever.init_count == 1
    assert len(processor.retriever.calls) == 2
    assert first["sources"] == [
        {
            "document_id": "policy-a",
            "document_title": "Safety Policy",
            "page_number": 4,
            "source": "policy-a.pdf",
            "source_url": "https://example.test/policy-a",
        }
    ]
    assert second["final_answer"] == "Establish a safety system."
    assert processor.openai_processor.calls[0]["prompt_mode"] == "generic"


def test_generic_question_output_contains_sources_not_competition_references(monkeypatch):
    monkeypatch.setattr(questions_processing, "VectorRetriever", FakeRetriever)
    monkeypatch.setattr(questions_processing, "APIProcessor", FakeAnswerProcessor)
    processor = QuestionsProcessor(
        questions_file_path=None,
        routing_mode="generic",
        new_challenge_pipeline=True,
    )
    processor.answer_details = [None]

    result = processor._process_single_question(
        {"text": "What safety system is required?", "kind": "text", "_question_index": 0}
    )

    assert result["question"] == "What safety system is required?"
    assert "references" not in result
    assert result["sources"][0]["document_id"] == "policy-a"


def test_generic_prompt_is_not_annual_report_or_company_specific():
    processor = APIProcessor(provider="dashscope")

    system_prompt, response_format, _ = processor._build_rag_context_prompts(
        "boolean", prompt_mode="generic"
    )

    assert "公司年报" not in system_prompt
    assert "company_name" not in system_prompt
    assert response_format is not None


def test_generic_citation_validation_uses_document_and_page(monkeypatch):
    monkeypatch.setattr(questions_processing, "VectorRetriever", FakeRetriever)
    monkeypatch.setattr(questions_processing, "APIProcessor", FakeAnswerProcessor)
    processor = QuestionsProcessor(routing_mode="generic")
    retrieval_results = [
        {
            "document_id": "doc-a",
            "document_title": "A",
            "page": 1,
            "source": "a.pdf",
            "source_url": None,
        },
        {
            "document_id": "doc-b",
            "document_title": "B",
            "page": 1,
            "source": "b.pdf",
            "source_url": None,
        },
    ]

    sources = processor._validate_source_references(
        [
            {"document_id": "doc-b", "page_number": 1},
            {"document_id": "doc-c", "page_number": 1},
        ],
        retrieval_results,
    )

    assert [(source["document_id"], source["page_number"]) for source in sources] == [
        ("doc-b", 1)
    ]


def test_default_routing_mode_remains_legacy_company(monkeypatch):
    monkeypatch.setattr(questions_processing, "VectorRetriever", FakeRetriever)
    monkeypatch.setattr(questions_processing, "APIProcessor", FakeAnswerProcessor)

    assert QuestionsProcessor().routing_mode == "legacy_company"


def test_generic_full_context_is_disabled(monkeypatch):
    monkeypatch.setattr(questions_processing, "VectorRetriever", FakeRetriever)
    monkeypatch.setattr(questions_processing, "APIProcessor", FakeAnswerProcessor)

    try:
        QuestionsProcessor(routing_mode="generic", full_context=True)
    except ValueError as error:
        assert "full_context is disabled" in str(error)
    else:
        raise AssertionError("generic full_context should be rejected")
