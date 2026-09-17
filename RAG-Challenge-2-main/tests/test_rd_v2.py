import json

import pytest

from src.questions_processing import QuestionsProcessor
from src.rd_retrieval import (
    BM25Retriever,
    RDHybridRetriever,
    RDRetrievalConfig,
    SectionContextExpander,
    reciprocal_rank_fusion,
)
from src.sectioning import SectionAwareTextSplitter, detect_heading


@pytest.mark.parametrize(
    ("line", "level"),
    [
        ("第1章 总则", 1),
        ("第一节 接口", 2),
        ("一、范围", 1),
        ("（一）输入", 2),
        ("## Parser supplied heading", 2),
    ],
)
def test_section_detection_supports_common_engineering_headings(line, level):
    assert detect_heading(line).level == level


def _report(*pages):
    return {
        "metainfo": {
            "document_id": "rd-spec",
            "title": "R&D specification",
            "source": "rd-spec.pdf",
        },
        "content": {
            "pages": [
                {"page": index, "text": text}
                for index, text in enumerate(pages, start=1)
            ]
        },
    }


def test_section_child_parent_mapping_and_page_provenance():
    splitter = SectionAwareTextSplitter(child_chunk_size=30, child_chunk_overlap=0)
    result = splitter._split_report(
        _report(
            "# Overview\nRD-DATA-01 normalizes source records.",
            "## Interface\nPOST /api/v2/ingest accepts source_uri.",
        )
    )

    assert result["content"]["section_detection"]["mode"] == "pdf_heuristic"
    sections = {
        section["section_id"]: section for section in result["content"]["sections"]
    }
    chunks = result["content"]["chunks"]
    assert chunks
    for chunk in chunks:
        assert chunk["parent_id"] == chunk["section_id"]
        assert chunk["chunk_id"] in sections[chunk["section_id"]]["child_chunk_ids"]
        assert chunk["page_number"] == chunk["page"]
        assert chunk["document_id"] == "rd-spec"


def test_section_detection_failure_falls_back_to_legacy_chunks():
    result = SectionAwareTextSplitter()._split_report(
        _report("Plain body text without a heading marker.")
    )
    assert result["content"]["section_detection"]["mode"] == "legacy_fallback"
    assert result["content"]["chunks"]


def test_bm25_finds_interface_and_field_exact_terms():
    retriever = BM25Retriever().build(
        [
            {
                "chunk_id": "a:0",
                "document_id": "a",
                "page": 1,
                "text": "The status endpoint reports general health.",
            },
            {
                "chunk_id": "a:1",
                "document_id": "a",
                "page": 2,
                "text": "POST /api/v2/ingest requires the source_uri field.",
            },
        ]
    )
    assert retriever.search("/api/v2/ingest", top_k=1)[0]["chunk_id"] == "a:1"
    assert retriever.search("source_uri", top_k=1)[0]["chunk_id"] == "a:1"


def test_rrf_merges_and_deduplicates_dense_and_bm25():
    dense = [
        {"chunk_id": "a:0", "document_id": "a", "page": 1, "text": "A", "distance": 0.9},
        {"chunk_id": "a:1", "document_id": "a", "page": 2, "text": "B", "distance": 0.8},
    ]
    sparse = [
        {"chunk_id": "a:1", "document_id": "a", "page": 2, "text": "B", "distance": 4.2},
        {"chunk_id": "a:2", "document_id": "a", "page": 3, "text": "C", "distance": 3.0},
        {"chunk_id": "a:2", "document_id": "a", "page": 3, "text": "C", "distance": 2.0},
    ]
    fused = reciprocal_rank_fusion(dense, sparse, rrf_k=60)
    assert [item["chunk_id"] for item in fused] == ["a:1", "a:0", "a:2"]
    assert fused[0]["retrieval_sources"] == ["dense", "bm25"]


def test_context_expansion_is_bounded_and_traceable(tmp_path):
    document_dir = tmp_path / "documents"
    document_dir.mkdir()
    chunks = [
        {
            "id": index,
            "chunk_id": f"rd:{index}",
            "document_id": "rd",
            "page": index + 1,
            "page_number": index + 1,
            "section_id": "rd:section:1",
            "parent_id": "rd:section:1",
            "length_tokens": 2,
            "text": f"child {index}",
        }
        for index in range(3)
    ]
    (document_dir / "rd.json").write_text(
        json.dumps(
            {
                "metainfo": {
                    "document_id": "rd",
                    "title": "Spec",
                    "source": "spec.pdf",
                },
                "content": {"pages": [], "chunks": chunks},
            }
        ),
        encoding="utf-8",
    )
    expander = SectionContextExpander(
        [document_dir], neighbor_children=2, max_tokens=5
    )
    expanded = expander.expand([{**chunks[1], "distance": 0.5}])
    assert len(expanded) == 2
    assert sum(item["length_tokens"] for item in expanded) <= 5
    assert {(item["document_id"], item["page"]) for item in expanded} == {
        ("rd", 2),
        ("rd", 1),
    }
    assert {item["context_role"] for item in expanded} == {"hit", "parent_anchor"}


def test_rd_hybrid_runs_rrf_and_existing_reranker(tmp_path):
    class FakeDense:
        document_ids = ["rd"]

        def retrieve(self, **kwargs):
            return [
                {
                    "chunk_id": "rd:0",
                    "document_id": "rd",
                    "document_title": "Spec",
                    "page": 1,
                    "text": "semantic",
                    "distance": 0.8,
                }
            ]

    class FakeSparse:
        def search(self, *args, **kwargs):
            return [
                {
                    "chunk_id": "rd:1",
                    "document_id": "rd",
                    "document_title": "Spec",
                    "page": 2,
                    "text": "exact timeout_ms",
                    "bm25_score": 3.0,
                    "distance": 3.0,
                }
            ]

    class FakeReranker:
        called = False

        def rerank_documents(self, query, documents, **kwargs):
            self.called = True
            return list(reversed(documents))

    fake_reranker = FakeReranker()
    retriever = RDHybridRetriever(
        tmp_path,
        tmp_path,
        config=RDRetrievalConfig(fusion_top_k=2, rerank_top_k=2),
        vector_retriever=FakeDense(),
        bm25_retriever=FakeSparse(),
        reranker=fake_reranker,
    )
    results = retriever.retrieve("timeout_ms", top_n=2, expand_context=False)
    assert fake_reranker.called is True
    assert [item["chunk_id"] for item in results] == ["rd:1", "rd:0"]


def test_expanded_child_evidence_remains_citation_compatible():
    processor = QuestionsProcessor(questions_file_path=None)
    retrieval_results = [
        {
            "document_id": "rd-spec",
            "document_title": "Spec",
            "source": "spec.pdf",
            "page": 4,
            "page_number": 4,
            "chunk_id": "rd-spec:7",
            "section_id": "rd-spec:section:2",
            "text": "timeout_ms defaults to 30000.",
        }
    ]
    validated = processor._validate_source_references(
        [{"document_id": "rd-spec", "page_number": 4}], retrieval_results
    )
    assert [(item["document_id"], item["page_number"]) for item in validated] == [
        ("rd-spec", 4)
    ]
