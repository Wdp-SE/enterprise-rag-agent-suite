from __future__ import annotations

import pytest

from main import build_parser
from src.answer_generation import StructuredAnswerGenerator
from src.context_expansion import SectionContextExpander
from src.rd_v2_runtime import (
    FINAL_DENSE_REPRESENTATION,
    FINAL_RETRIEVAL_POLICY,
    validate_citation_membership,
)
from src.trusted_qa import (
    TrustedQAMode,
    VersionResolutionStatus,
    build_answer_evidence_audit,
    collect_retrieval_signals,
    decide_post_answer_enforcement,
)


def test_formal_retrieval_policy_is_fixed() -> None:
    assert FINAL_RETRIEVAL_POLICY == "DENSE_ONLY"
    assert FINAL_DENSE_REPRESENTATION == "SECTION_PATH"


def test_structured_answer_schema_is_strict() -> None:
    value = StructuredAnswerGenerator._decode(
        '{"final_answer":"应执行降级流程","relevant_sources":'
        '[{"document_id":"DESIGN-001","page_number":3}]}'
    )
    assert value["final_answer"] == "应执行降级流程"
    with pytest.raises(ValueError):
        StructuredAnswerGenerator._decode(
            {
                "final_answer": "未经约束的答案",
                "relevant_sources": [],
                "confidence": 0.9,
            }
        )


def test_context_expansion_stays_inside_document_version_section() -> None:
    chunks = [
        {
            "chunk_id": "v1-1",
            "document_id": "DOC-1",
            "version_id": "V1",
            "section_id": "S1",
            "page_number": 1,
            "text": "章节开头",
            "position": 0,
        },
        {
            "chunk_id": "v1-2",
            "document_id": "DOC-1",
            "version_id": "V1",
            "section_id": "S1",
            "page_number": 2,
            "text": "章节正文",
            "position": 1,
        },
        {
            "chunk_id": "v2-1",
            "document_id": "DOC-1",
            "version_id": "V2",
            "section_id": "S1",
            "page_number": 1,
            "text": "新版本内容",
            "position": 0,
        },
    ]
    expander = SectionContextExpander.from_chunks(chunks, neighbor_children=1)
    output = expander.expand(
        [
            {
                **chunks[1],
                "distance": 0.82,
                "dense_score": 0.82,
                "retrieval_rank": 1,
                "bm25_score": 99,
                "rrf_score": 88,
                "relevance_score": 77,
            }
        ]
    )
    assert {item["chunk_id"] for item in output} == {"v1-1", "v1-2"}
    assert all(item["retrieval_sources"] == ["dense"] for item in output)
    assert all(
        not ({"bm25_score", "rrf_score", "relevance_score"} & set(item))
        for item in output
    )


def test_dense_signals_have_formal_version_governance() -> None:
    snapshot = collect_retrieval_signals(
        question_id="q-1",
        retrieval_results=[
            {
                "document_id": "DOC-1",
                "page_number": 2,
                "dense_score": 0.81,
                "relevance_score": 100,
            }
        ],
        version_governance_enabled=True,
        version_resolution_status=VersionResolutionStatus.RESOLVED,
        eligible_document_count=1,
    )
    assert snapshot.top1_score == 0.81
    assert snapshot.version_resolution_status == VersionResolutionStatus.RESOLVED
    assert "rerank_score" not in snapshot.model_fields


def test_forged_citation_is_removed_and_answer_fails_closed() -> None:
    evidence = [{"document_id": "DOC-1", "page_number": 2}]
    claimed = [{"document_id": "DOC-OTHER", "page_number": 99}]
    assert validate_citation_membership(claimed, evidence) == []
    audit = build_answer_evidence_audit(
        generation_performed=True,
        structured_output_valid=True,
        final_answer="一个没有有效引用的回答",
        claimed_citations=claimed,
        validated_citations=[],
        citation_membership_checked=True,
    )
    decision = decide_post_answer_enforcement(audit, mode=TrustedQAMode.ENFORCE)
    assert decision.enforced is True


def test_cli_exposes_only_formal_business_commands() -> None:
    parser = build_parser()
    commands = set(parser._subparsers._group_actions[0].choices)
    assert commands == {
        "serve",
        "validate-artifacts",
        "ingest-version",
        "activate-version",
        "diff",
        "catalog",
    }
