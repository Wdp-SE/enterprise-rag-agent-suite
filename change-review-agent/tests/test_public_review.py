from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from app.public_review import PublicReviewAgent


CORPUS = Path(__file__).resolve().parents[2] / "versioned-rag-service" / "public_corpus"
CHUNKS = json.loads((CORPUS / "chunks.json").read_text(encoding="utf-8"))


class Gateway:
    def __init__(self):
        self.calls = []

    def workspace(self):
        return {"current_version": "3.4.3"}

    def document(self, document_id):
        self.calls.append(("document", document_id))
        return [row for row in CHUNKS if row["document_id"] == document_id]

    def search(self, question, *, version, language, top_k=5):
        self.calls.append(("search", version, language, top_k))
        rows = [
            row for row in CHUNKS
            if row["version"] == version
            and row["document_key"] == "guide/upgrade/incompatible"
        ]
        return {"results": rows[:top_k]}

    def engineering_diff(self, old_items, new_items):
        self.calls.append(("diff", old_items, new_items))
        assert old_items[0]["content_hash"] != new_items[0]["content_hash"]
        return {"changes": [{
            "change_type": "MODIFIED", "external_identifier": old_items[0]["external_identifier"],
            "old_content": old_items[0]["content"], "new_content": new_items[0]["content"],
        }]}

    def engineering_impacts(self, payload):
        self.calls.append(("impact", payload))
        confirmed = {row["target_item_id"] for row in payload["trace_links"]}
        return {"impacts": [
            {"impacted_item_id": item_id,
             "review_status": "CONFIRMED" if item_id in confirmed else "SUGGESTED"}
            for item_id in payload["dense_item_ids"]
        ]}

    def review_advice(self, change_summary, evidence_chunk_ids):
        self.calls.append(("review_advice", change_summary, evidence_chunk_ids))
        evidence = next(row for row in CHUNKS if row["chunk_id"] == evidence_chunk_ids[0])
        return {
            "status": "OK",
            "answer": "请核对该参数在相关版本说明中的优先级。",
            "sources": [evidence],
            "review": {
                "change_interpretation": "将参数优先级调整为最高。",
                "impact_candidates": [{
                    "evidence_chunk_id": evidence["chunk_id"],
                    "reason": "该章节解释当前参数优先级。",
                    "suggested_action": "检查示例和相关版本说明是否同步。",
                }],
                "evidence_gaps": ["尚未核对英文版。"],
                "version_ambiguities": [],
                "reviewer_actions": ["逐版本核实配置行为。"],
                "review_status": "REQUIRES_HUMAN_REVIEW",
            },
        }


def test_official_change_calls_rag_http_diff_search_impact_without_baseline_write():
    gateway = Gateway()
    selected = next(row for row in CHUNKS if row["document_key"] == "guide/parameter/priority" and row["language"] == "zh" and row["version"] == "3.4.3")
    before = hashlib.sha256((CORPUS / "corpus_manifest.json").read_bytes()).hexdigest()
    result = PublicReviewAgent(gateway).analyze(selected, selected["content"] + " 假设性更新。")
    assert result["change"]["change_type"] == "MODIFIED"
    assert result["sandbox_only"] and not result["public_baseline_written"]
    assert result["patch_candidate"]["status"] == "REQUIRES_HUMAN_REVIEW"
    assert all(row["relation"] == "suggested" for row in result["impacts"])
    assert [row[0] for row in gateway.calls] == ["diff", "search", "impact", "review_advice"]
    advice_call = gateway.calls[-1]
    assert "假设性更新" in advice_call[1]
    assert set(advice_call[2]) == {row["evidence"]["chunk_id"] for row in result["impacts"]}
    assert result["review_advice"]["status"] == "OK"
    assert result["review_advice"]["sources"][0]["chunk_id"] in advice_call[2]
    assert result["impacts"][0]["reason"] == "该章节解释当前参数优先级。"
    assert result["impacts"][0]["suggested_action"] == "检查示例和相关版本说明是否同步。"
    assert result["review_advice"]["review"]["evidence_gaps"] == ["尚未核对英文版。"]
    assert result["review_advice"]["review"]["review_status"] == "REQUIRES_HUMAN_REVIEW"
    assert hashlib.sha256((CORPUS / "corpus_manifest.json").read_bytes()).hexdigest() == before


def test_natural_language_review_searches_current_corpus_before_grounded_advice():
    gateway = Gateway()
    summary = "将全局参数调整为最高优先级，并检查需要同步的资料。"

    result = PublicReviewAgent(gateway).analyze_request(summary)

    assert [row[0] for row in gateway.calls] == ["search", "review_advice"]
    assert gateway.calls[0] == ("search", "3.4.3", "zh_preferred", 5)
    assert result["request_mode"] == "natural_language"
    assert result["request_summary"] == summary
    assert result["review_advice"]["status"] == "OK"
    assert result["review_advice"]["review"]["review_status"] == "REQUIRES_HUMAN_REVIEW"
    assert result["impacts"][0]["reason"] == "该章节解释当前参数优先级。"
    assert result["impacts"][0]["suggested_action"] == "检查示例和相关版本说明是否同步。"
    cited = result["review_advice"]["sources"][0]["chunk_id"]
    assert result["impacts"][0]["evidence"]["chunk_id"] == cited
    assert result["sandbox_only"] is True
    assert result["public_baseline_written"] is False
    assert "patch_candidate" not in result


def test_multi_part_request_keeps_evidence_from_each_part_with_auditable_trace():
    gateway = Gateway()
    parameter = next(row for row in CHUNKS if row["document_key"] == "guide/parameter/priority" and row["language"] == "zh" and row["version"] == "3.4.3")
    upgrade = next(row for row in CHUNKS if row["document_key"] == "guide/upgrade/incompatible" and row["language"] == "zh" and row["version"] == "3.4.3")
    summary = "调整参数优先级。核对升级文档的兼容性。"

    def search(question, *, version, language, top_k=5):
        gateway.calls.append(("search", question, version, language, top_k))
        if question == summary:
            return {"results": [{**parameter, "retrieval_score": 4.0}]}
        if "兼容性" in question:
            return {"results": [{**upgrade, "retrieval_score": 2.0}]}
        return {"results": [{**parameter, "retrieval_score": 3.0}]}

    gateway.search = search
    gateway.review_advice = lambda _summary, evidence_ids: {
        "status": "OK", "answer": "应核对两类资料。",
        "review": {
            "impact_candidates": [{
                "evidence_chunk_id": evidence_ids[-1],
                "reason": "升级资料涉及兼容性。",
                "suggested_action": "人工核对兼容差异。",
            }],
            "evidence_gaps": [],
            "review_status": "REQUIRES_HUMAN_REVIEW",
        },
    }

    first = PublicReviewAgent(gateway).analyze_request(summary)
    second = PublicReviewAgent(gateway).analyze_request(summary)

    assert {row["chunk_id"] for row in first["retrieved_results"]} == {parameter["chunk_id"], upgrade["chunk_id"]}
    assert [row[0] for row in gateway.calls[:3]] == ["search", "search", "search"]
    assert gateway.calls[0][1] == summary
    assert gateway.calls[1][1] == "调整参数优先级"
    assert gateway.calls[2][1] == "核对升级文档的兼容性"
    assert first["task_id"] != second["task_id"]
    assert first["request_fingerprint"] == second["request_fingerprint"]
    assert first["retrieval_trace"]["queries"][2]["selected_chunk_ids"] == [upgrade["chunk_id"]]
    assert first["retrieval_trace"]["model_status"] == "OK"
    assert first["evidence_gaps"] == []
    assert first["public_baseline_written"] is False


def test_no_retrieval_match_reports_gap_and_skips_model():
    gateway = Gateway()

    def search(question, *, version, language, top_k=5):
        gateway.calls.append(("search", question, version, language, top_k))
        return {"results": [{**CHUNKS[0], "retrieval_score": 0.0}]}

    gateway.search = search
    result = PublicReviewAgent(gateway).analyze_request("核对未收录的恢复策略")

    assert result["retrieved_results"] == []
    assert result["review_advice"]["status"] == "NO_EVIDENCE"
    assert result["retrieval_trace"]["queries"][0]["status"] == "no_retrieval_match"
    assert result["retrieval_trace"]["uncovered_queries"] == ["核对未收录的恢复策略"]
    assert "核对未收录的恢复策略" in result["evidence_gaps"][0]
    assert [row[0] for row in gateway.calls] == ["search"]


def test_missing_subquery_keeps_other_candidates_and_reports_partial_coverage():
    gateway = Gateway()
    parameter = next(row for row in CHUNKS if row["document_key"] == "guide/parameter/priority" and row["language"] == "zh" and row["version"] == "3.4.3")
    summary = "调整参数优先级。核对不存在的自动恢复功能。"

    def search(question, *, version, language, top_k=5):
        gateway.calls.append(("search", question, version, language, top_k))
        return {"results": [] if "不存在" in question and question != summary else [{**parameter, "retrieval_score": 2.0}]}

    gateway.search = search
    result = PublicReviewAgent(gateway).analyze_request(summary)

    assert result["retrieved_results"][0]["chunk_id"] == parameter["chunk_id"]
    assert result["retrieval_trace"]["uncovered_queries"] == ["核对不存在的自动恢复功能"]
    assert result["retrieval_trace"]["queries"][2]["status"] == "no_retrieval_match"
    assert "核对不存在的自动恢复功能" in result["evidence_gaps"][0]


def test_unavailable_search_is_reported_separately_from_missing_evidence():
    gateway = Gateway()
    gateway.search = lambda *_args, **_kwargs: (_ for _ in ()).throw(ConnectionError("backend unavailable"))

    result = PublicReviewAgent(gateway).analyze_request("核对恢复策略")

    assert result["review_advice"]["status"] == "RETRIEVAL_UNAVAILABLE"
    assert result["retrieval_trace"]["queries"][0]["status"] == "search_unavailable"
    assert "检索服务" in result["evidence_gaps"][0]


def test_exact_review_has_task_identity_and_model_evidence_gap():
    gateway = Gateway()
    selected = next(row for row in CHUNKS if row["document_key"] == "guide/parameter/priority" and row["language"] == "zh" and row["version"] == "3.4.3")
    proposal = selected["content"] + " 假设性更新。"

    first = PublicReviewAgent(gateway).analyze(selected, proposal)
    second = PublicReviewAgent(gateway).analyze(selected, proposal)

    assert first["task_id"] != second["task_id"]
    assert first["request_fingerprint"] == second["request_fingerprint"]
    assert first["retrieval_trace"]["model_status"] == "OK"
    assert first["evidence_gaps"] == ["尚未核对英文版。"]


def test_exact_review_can_consider_other_sections_in_selected_document():
    gateway = Gateway()
    sections = [row for row in CHUNKS if row["document_key"] == "guide/parameter/priority" and row["language"] == "zh" and row["version"] == "3.4.3"]
    selected, sibling = sections[:2]

    def search(question, *, version, language, top_k=5):
        gateway.calls.append(("search", version, language, top_k))
        return {"results": [selected, sibling]}

    gateway.search = search
    result = PublicReviewAgent(gateway).analyze(selected, selected["content"] + " 假设性更新。")

    assert [row["evidence"]["chunk_id"] for row in result["impacts"]] == [sibling["chunk_id"]]
    assert result["retrieval_trace"]["queries"][0]["selected_chunk_ids"] == [sibling["chunk_id"]]


def test_natural_language_review_discards_model_candidates_outside_retrieved_evidence():
    gateway = Gateway()
    evidence = gateway.search("假设调整参数", version="3.4.3", language="zh_preferred")["results"][0]
    gateway.review_advice = lambda *_args: {
        "status": "OK", "answer": "请采纳",
        "sources": [evidence],
        "review": {
            "change_interpretation": "调整参数。",
            "impact_candidates": [{
                "evidence_chunk_id": "invented-chunk",
                "reason": "不在本次检索中。", "suggested_action": "不要采纳。",
            }],
            "evidence_gaps": [], "version_ambiguities": [],
            "reviewer_actions": ["人工确认。"],
            "review_status": "REQUIRES_HUMAN_REVIEW",
        },
    }

    result = PublicReviewAgent(gateway).analyze_request("假设调整参数")

    assert result["review_advice"]["status"] == "ABSTAINED"
    assert result["review_advice"]["sources"] == []
    assert result["impacts"] == []


def test_natural_language_review_keeps_model_gaps_when_it_abstains():
    gateway = Gateway()
    gateway.review_advice = lambda *_args: {
        "status": "ABSTAINED", "answer": "N/A", "sources": [],
        "review": {
            "change_interpretation": "仍需补充证据。",
            "impact_candidates": [],
            "evidence_gaps": ["缺少下游节点恢复行为说明。"],
            "version_ambiguities": ["尚未核对历史版本。"],
            "reviewer_actions": ["补充恢复策略来源后重新审查。"],
            "review_status": "REQUIRES_HUMAN_REVIEW",
        },
    }

    result = PublicReviewAgent(gateway).analyze_request("调整故障恢复策略")

    assert result["review_advice"]["status"] == "ABSTAINED"
    assert result["review_advice"]["sources"] == []
    assert result["review_advice"]["review"]["impact_candidates"] == []
    assert result["review_advice"]["review"]["version_ambiguities"] == ["尚未核对历史版本。"]
    assert result["evidence_gaps"] == ["缺少下游节点恢复行为说明。"]
    assert result["impacts"] == []
    assert result["retrieved_results"]
    assert result["retrieval_trace"]["model_status"] == "ABSTAINED"


def test_natural_language_review_abstains_when_rag_has_no_current_evidence():
    gateway = Gateway()
    def no_hits(question, *, version, language, top_k=5):
        gateway.calls.append(("search", version, language, top_k))
        return {"results": []}

    gateway.search = no_hits

    result = PublicReviewAgent(gateway).analyze_request("核对一个未收录的假设变更")

    assert result["review_advice"]["status"] == "NO_EVIDENCE"
    assert result["impacts"] == []
    assert result["retrieved_results"] == []
    assert [row[0] for row in gateway.calls] == ["search"]


def test_natural_language_review_keeps_candidates_when_model_is_unavailable():
    gateway = Gateway()
    gateway.review_advice = lambda *_args: {
        "status": "GENERATION_PROVIDER_UNAVAILABLE", "answer": "N/A", "sources": [],
    }

    result = PublicReviewAgent(gateway).analyze_request("核对全局参数变化的影响")

    assert result["retrieved_results"]
    assert result["review_advice"]["status"] == "GENERATION_PROVIDER_UNAVAILABLE"
    assert result["impacts"] == []
    assert result["public_baseline_written"] is False


def test_natural_language_review_rejects_empty_or_oversized_change_request():
    agent = PublicReviewAgent(Gateway())

    with pytest.raises(ValueError, match="1 到 4000"):
        agent.analyze_request("   ")
    with pytest.raises(ValueError, match="1 到 4000"):
        agent.analyze_request("a" * 4001)


def test_dsip_reference_confirms_documents_without_confirming_unrelated_paragraph_impact():
    gateway = Gateway()
    selected = next(
        row for row in CHUNKS
        if row["document_key"] == "proposals/dsip-107-proposal"
        and row["heading"] == "Code of Conduct"
    )
    result = PublicReviewAgent(gateway).analyze(selected, selected["content"] + " Hypothetical review change.")
    assert result["confirmed_relations"] == [{
        "relation_type": "DOCUMENT_REFERENCE",
        "source_document_id": "3.4.3:en:proposals/dsip-107-implementation",
        "target_document_id": "3.4.3:en:proposals/dsip-107-proposal",
        "source_chunk_id": "3.4.3:en:proposals/dsip-107-implementation:2",
        "source_heading": "Purpose of the pull request",
        "source_url": "https://github.com/apache/dolphinscheduler/pull/18464",
        "source_excerpt": next(
            row["content"] for row in CHUNKS
            if row["chunk_id"] == "3.4.3:en:proposals/dsip-107-implementation:2"
        ),
    }]
    assert "independent part of DSIP #18454" in result["confirmed_relations"][0]["source_excerpt"]
    assert result["impacts"]
    assert all(row["relation"] == "suggested" for row in result["impacts"])
    assert all(
        row["evidence"]["chunk_id"] != "3.4.3:en:proposals/dsip-107-implementation:2"
        for row in result["impacts"]
    )


def test_rejects_history_unknown_source_and_unchanged_content():
    gateway = Gateway()
    selected = next(row for row in CHUNKS if row["document_key"] == "guide/parameter/priority" and row["language"] == "zh" and row["version"] == "3.4.3")
    with pytest.raises(ValueError, match="相同"):
        PublicReviewAgent(gateway).analyze(selected, selected["content"])
    with pytest.raises(ValueError, match="官方"):
        PublicReviewAgent(gateway).analyze({**selected, "source_url": "https://example.com"}, "new")
    with pytest.raises(ValueError, match="当前"):
        PublicReviewAgent(gateway).analyze({**selected, "version": "3.4.2"}, "new")
