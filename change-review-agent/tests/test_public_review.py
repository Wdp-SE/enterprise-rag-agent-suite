from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from app.public_review import PublicReviewAgent, _official_hit, _select_request_evidence


CORPUS = Path(__file__).resolve().parents[2] / "versioned-rag-service" / "public_corpus"
CHUNKS = json.loads((CORPUS / "chunks.json").read_text(encoding="utf-8"))
AUTOWARE_REPOSITORY = "autowarefoundation/autoware_universe"


class Gateway:
    def __init__(self):
        self.calls = []

    def workspace(self):
        return {"current_version": "3.4.3", "repository": "apache/dolphinscheduler"}

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
    summary = "将全局参数调整为最高优先级。"

    result = PublicReviewAgent(gateway).analyze_request(summary, language_mode="en")

    assert [row[0] for row in gateway.calls] == ["search", "review_advice"]
    assert gateway.calls[0] == ("search", "3.4.3", "en", 5)
    assert result["request_mode"] == "natural_language"
    assert result["request_summary"] == summary
    assert result["request_plan"]["change_type"] == "parameter_config"
    assert result["request_plan"]["classification_source"] == "rule_inferred"
    assert result["retrieval_trace"]["query_limit"] == 4
    assert len(result["retrieval_trace"]["queries"]) <= 4
    assert result["review_advice"]["status"] == "OK"
    assert result["review_advice"]["review"]["review_status"] == "REQUIRES_HUMAN_REVIEW"
    assert result["stage_status"] == {
        "planning": "OK", "retrieval": "OK", "generation": "OK",
    }
    assert result["impacts"][0]["reason"] == "该章节解释当前参数优先级。"
    assert result["impacts"][0]["suggested_action"] == "检查示例和相关版本说明是否同步。"
    cited = result["review_advice"]["sources"][0]["chunk_id"]
    assert result["impacts"][0]["evidence"]["chunk_id"] == cited
    assert result["sandbox_only"] is True
    assert result["public_baseline_written"] is False
    assert "patch_candidate" not in result


def test_natural_language_review_searches_both_languages_and_reports_clause_coverage():
    chinese = next(row for row in CHUNKS if row["document_key"] == "guide/parameter/priority" and row["language"] == "zh" and row["version"] == "3.4.3")
    english = next(row for row in CHUNKS if row["document_key"] == "guide/parameter/priority" and row["language"] == "en" and row["version"] == "3.4.3")

    class BilingualGateway(Gateway):
        def search(self, question, *, version, language, top_k=5):
            self.calls.append(("search", question, version, language, top_k))
            return {"results": [chinese if language == "zh" else english]}

    gateway = BilingualGateway()
    result = PublicReviewAgent(gateway).analyze_request("调整参数优先级。", language_mode="bilingual")

    traces = result["retrieval_trace"]["queries"]
    assert {(row["language"], row["status"]) for row in traces} == {
        ("zh", "candidate_found"), ("en", "candidate_found"),
    }
    assert {call[3] for call in gateway.calls if call[0] == "search"} == {"zh", "en"}
    assert {key: value for key, value in result["coverage"].items() if key != "incomplete_reason"} == {
        "required_check_count": 1, "covered_check_count": 1,
        "attempted_languages": ["zh", "en"], "covered_languages": ["en", "zh"],
        "search_failure_count": 0, "evidence_budget": 8, "selected_evidence_count": 2,
        "complete": True,
    }
    assert result["request_plan"]["checklist_items"]


def test_partial_bilingual_review_surfaces_search_failure_and_is_not_complete():
    chinese = next(row for row in CHUNKS if row["document_key"] == "guide/parameter/priority" and row["language"] == "zh" and row["version"] == "3.4.3")

    class OneLanguageUnavailable(Gateway):
        def search(self, question, *, version, language, top_k=5):
            self.calls.append(("search", question, version, language, top_k))
            if language == "en":
                raise ConnectionError("temporary retrieval failure")
            return {"results": [chinese]}

    result = PublicReviewAgent(OneLanguageUnavailable()).analyze_request("调整参数优先级。", language_mode="bilingual")

    assert result["coverage"]["complete"] is False
    assert result["coverage"]["search_failure_count"] == 1
    assert result["retrieved_results"]
    assert "不能据此判定无影响" in result["coverage"]["incomplete_reason"]
    assert any("检索服务未完成" in gap for gap in result["evidence_gaps"])


def test_natural_language_review_accepts_current_autoware_sources_from_manifest_repository():
    commit = "a" * 40
    evidence = {
        "chunk_id": "autoware-0.52-planning-validator-1",
        "document_id": "0.51.0:en:planning/planning_validator/design",
        "document_key": "planning/planning_validator/design",
        "version": "0.51.0", "language": "en", "locale": "en-US",
        "heading": "Trajectory validation", "content": "The planning validator checks trajectory feasibility.",
        "retrieval_score": 1.4, "repository": AUTOWARE_REPOSITORY,
        "commit": "d4d260983d357e1b2b34291d91933f9f4b53bf94",
        "source_url": f"https://github.com/{AUTOWARE_REPOSITORY}/blob/d4d260983d357e1b2b34291d91933f9f4b53bf94/planning/planning_validator/README.md",
    }

    class AutowareGateway:
        def __init__(self):
            self.calls = []

        def workspace(self):
            return {
                "workspace": "Autoware", "repository": AUTOWARE_REPOSITORY,
                "current_version": "0.52.0", "available_versions": ["0.51.0", "0.52.0"],
            }

        def search(self, question, *, version, language, top_k=5):
            self.calls.append(("search", version, language, top_k))
            return {"retrieval_policy": "bm25", "results": [evidence]}

        def review_advice(self, summary, evidence_chunk_ids):
            self.calls.append(("review_advice", summary, evidence_chunk_ids))
            return {
                "status": "OK", "answer": "Review trajectory feasibility.",
                "sources": [evidence],
                "review": {
                    "change_interpretation": "The change may affect trajectory validation.",
                    "impact_candidates": [{
                        "evidence_chunk_id": evidence["chunk_id"],
                        "reason": "The source defines trajectory validation behavior.",
                        "suggested_action": "Manually verify validator behavior and parameters.",
                    }],
                    "evidence_gaps": [], "version_ambiguities": [],
                    "reviewer_actions": ["Compare the pinned source."],
                    "review_status": "REQUIRES_HUMAN_REVIEW",
                },
            }

        def review_advice_for_version(self, summary, evidence_chunk_ids, *, version):
            self.calls.append(("review_advice_for_version", version))
            return self.review_advice(summary, evidence_chunk_ids)

    gateway = AutowareGateway()
    result = PublicReviewAgent(gateway).analyze_request(
        "Update the trajectory validation behavior in the planning validator.",
        target_version="0.51.0", objective="Catch invalid trajectories before handoff",
        constraints="Keep the planning output interface stable", language_mode="en",
    )

    assert _official_hit(evidence, "0.51.0", AUTOWARE_REPOSITORY)
    assert result["retrieved_results"] == [evidence]
    assert result["review_advice"]["status"] == "OK"
    assert result["impacts"][0]["evidence"]["repository"] == AUTOWARE_REPOSITORY
    assert gateway.calls[0] == ("search", "0.51.0", "en", 5)
    assert gateway.calls[-2] == ("review_advice_for_version", "0.51.0")
    assert result["request_context"]["objective"] == "Catch invalid trajectories before handoff"
    assert result["request_context"]["validation_plan"] is None
    assert "validation_plan" in result["request_context"]["missing_fields"]


def test_private_company_request_is_stopped_before_rag_or_model_calls():
    gateway = Gateway()

    result = PublicReviewAgent(gateway).analyze_request(
        "查询公司内部 Jira 审批人的手机号和私有工单权限"
    )

    assert gateway.calls == []
    assert result["scope_status"] == "OUT_OF_SCOPE"
    assert result["retrieved_results"] == []
    assert result["review_advice"]["status"] == "OUT_OF_SCOPE"
    assert result["retrieval_trace"]["model_status"] == "NOT_CALLED_OUT_OF_SCOPE"
    assert result["retrieval_trace"]["queries"] == []
    assert result["evidence_gap_details"][0]["gap_type"] == "OUT_OF_SCOPE_PUBLIC_CORPUS"


def test_evidence_selection_diversifies_documents_across_query_clauses():
    def row(chunk_id, document_key):
        return {"chunk_id": chunk_id, "document_key": document_key}

    searches = [
        ({"query": "full", "search_query": "full"}, [row(f"a-{n}", "doc-a") for n in range(1, 6)]),
        ({"query": "clause-a", "search_query": "SubWorkflow task"}, [
            row("a-1", "guide/task/conditions"),
            row("b-1", "guide/task/sub-workflow"),
        ]),
        ({"query": "clause-b", "search_query": "other"}, [row("c-1", "doc-c")]),
    ]

    selected = _select_request_evidence(searches)

    assert {item["document_key"] for item in selected} >= {
        "doc-a", "guide/task/sub-workflow", "doc-c"
    }
    assert len(selected) <= 8


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

    first = PublicReviewAgent(gateway).analyze_request(summary, language_mode="zh")
    second = PublicReviewAgent(gateway).analyze_request(summary, language_mode="zh")

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
    result = PublicReviewAgent(gateway).analyze_request("核对未收录的恢复策略", language_mode="zh")

    assert result["retrieved_results"] == []
    assert result["review_advice"]["status"] == "NO_EVIDENCE"
    assert result["retrieval_trace"]["queries"][0]["status"] == "no_retrieval_match"
    assert result["retrieval_trace"]["uncovered_queries"] == ["核对未收录的恢复策略"]
    assert "核对未收录的恢复策略" in result["evidence_gaps"][0]
    assert result["evidence_gap_details"][0]["gap_type"] == "NO_REQUIRED_SOURCE"
    assert result["evidence_gap_details"][0]["legacy_gap_code"] == "NO_MATCH"
    assert result["evidence_gap_details"][0]["missing_source_type"]
    assert result["evidence_gap_details"][0]["expected_version"] == "3.4.3"
    assert result["evidence_gap_details"][0]["suggested_query"] == "核对未收录的恢复策略"
    assert result["evidence_gap_details"][0]["requires_human_review"] is True
    assert [row[0] for row in gateway.calls] == ["search"]


def test_missing_subquery_keeps_other_candidates_and_reports_partial_coverage():
    gateway = Gateway()
    parameter = next(row for row in CHUNKS if row["document_key"] == "guide/parameter/priority" and row["language"] == "zh" and row["version"] == "3.4.3")
    summary = "调整参数优先级。核对不存在的自动恢复功能。"

    def search(question, *, version, language, top_k=5):
        gateway.calls.append(("search", question, version, language, top_k))
        return {"results": [] if "不存在" in question and question != summary else [{**parameter, "retrieval_score": 2.0}]}

    gateway.search = search
    result = PublicReviewAgent(gateway).analyze_request(summary, language_mode="zh")

    assert result["retrieved_results"][0]["chunk_id"] == parameter["chunk_id"]
    assert result["retrieval_trace"]["uncovered_queries"] == ["核对不存在的自动恢复功能"]
    assert result["retrieval_trace"]["queries"][2]["status"] == "no_retrieval_match"
    assert "核对不存在的自动恢复功能" in result["evidence_gaps"][0]


def test_unavailable_search_is_reported_separately_from_missing_evidence():
    gateway = Gateway()
    gateway.search = lambda *_args, **_kwargs: (_ for _ in ()).throw(ConnectionError("backend unavailable"))

    result = PublicReviewAgent(gateway).analyze_request("核对恢复策略", language_mode="zh")

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

    result = PublicReviewAgent(gateway).analyze_request("调整故障恢复策略", language_mode="en")

    assert result["review_advice"]["status"] == "ABSTAINED"
    assert result["review_advice"]["sources"] == []
    assert result["review_advice"]["review"]["impact_candidates"] == []
    assert result["review_advice"]["review"]["version_ambiguities"] == ["尚未核对历史版本。"]
    assert result["evidence_gaps"] == ["缺少下游节点恢复行为说明。", "尚未核对历史版本。"]
    assert any(row["gap_type"] == "VERSION_AMBIGUITY" for row in result["evidence_gap_details"])
    assert result["impacts"] == []
    assert result["retrieved_results"]
    assert result["retrieval_trace"]["model_status"] == "ABSTAINED"


def test_natural_language_review_abstains_when_rag_has_no_current_evidence():
    gateway = Gateway()
    def no_hits(question, *, version, language, top_k=5):
        gateway.calls.append(("search", version, language, top_k))
        return {"results": []}

    gateway.search = no_hits

    result = PublicReviewAgent(gateway).analyze_request("核对一个未收录的假设变更", language_mode="zh")

    assert result["review_advice"]["status"] == "NO_EVIDENCE"
    assert result["impacts"] == []
    assert result["retrieved_results"] == []
    assert [row[0] for row in gateway.calls] == ["search"]


def test_natural_language_review_keeps_candidates_when_model_is_unavailable():
    gateway = Gateway()
    gateway.review_advice = lambda *_args: {
        "status": "GENERATION_PROVIDER_UNAVAILABLE", "answer": "N/A", "sources": [],
    }

    result = PublicReviewAgent(gateway).analyze_request("核对全局参数变化的影响", language_mode="en")

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


def test_structured_change_context_is_searchable_and_kept_in_the_plan():
    gateway = Gateway()
    original_search = gateway.search
    observed_queries = []

    def search(query, *, version, language, top_k=5):
        observed_queries.append(query)
        return original_search(query, version=version, language=language, top_k=top_k)

    gateway.search = search
    result = PublicReviewAgent(gateway).analyze_request(
        "增加任务状态响应字段；核对工作流调用方。",
        change_type="interface_compatibility",
        impact_scope="任务状态 API",
        language_mode="zh",
    )

    assert result["request_plan"]["change_type"] == "interface_compatibility"
    assert result["request_plan"]["classification_source"] == "user_selected"
    assert result["request_plan"]["impact_scope"] == "任务状态 API"
    assert observed_queries[0].startswith("任务状态 API API 契约、字段、调用方与兼容性")
    assert len(result["retrieval_trace"]["queries"]) <= 4


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


def test_invalid_model_citation_is_removed_without_discarding_valid_candidates():
    gateway = Gateway()
    evidence = gateway.search("调整参数", version="3.4.3", language="zh_preferred")["results"][0]
    gateway.review_advice = lambda *_args: {
        "status": "OK", "answer": "请核对引用证据。", "sources": [evidence],
        "review": {
            "change_interpretation": "核对参数行为。",
            "impact_candidates": [
                {"evidence_chunk_id": evidence["chunk_id"], "reason": "有效来源。", "suggested_action": "对照原文。"},
                {"evidence_chunk_id": "invented-chunk", "reason": "不存在来源。", "suggested_action": "不要直接采纳。"},
            ],
            "evidence_gaps": [], "version_ambiguities": [],
            "reviewer_actions": ["人工核对。"], "review_status": "REQUIRES_HUMAN_REVIEW",
        },
    }

    result = PublicReviewAgent(gateway).analyze_request("调整参数")

    assert result["review_advice"]["status"] == "OK"
    assert [row["evidence"]["chunk_id"] for row in result["impacts"]] == [evidence["chunk_id"]]
    assert [row["evidence_chunk_id"] for row in result["review_advice"]["review"]["impact_candidates"]] == [evidence["chunk_id"]]
    invalid = next(row for row in result["evidence_gap_details"] if row["gap_type"] == "INVALID_CITATION")
    assert invalid["missing_source_type"] == "本次检索证据中的有效引用 ID"
    assert "invented-chunk" not in invalid["message"]


def test_unverified_translation_relation_is_a_review_gap_not_a_drift_conclusion():
    gateway = Gateway()
    source = next(
        row for row in CHUNKS
        if row["document_key"] == "guide/parameter/priority"
        and row["language"] == "zh" and row["version"] == "3.4.3"
    )
    source_id = source["document_id"]
    target_id = source_id.replace(":zh:", ":en:")
    candidate = {
        **source,
        "document_relationships": [{
            "relation_type": "translation_of", "verification_status": "candidate",
            "source_document_id": source_id, "target_document_id": target_id,
        }],
    }
    gateway.search = lambda *_args, **_kwargs: {"results": [candidate], "retrieval_policy": "bm25"}

    result = PublicReviewAgent(gateway).analyze_request("核对参数优先级变更是否需要同步")

    gap = next(row for row in result["evidence_gap_details"] if row["gap_type"] == "UNVERIFIED_TRANSLATION")
    assert gap["expected_version"] == "3.4.3"
    assert target_id in gap["suggested_query"]
    assert "对应关系待核验" in gap["description"]
    assert not any(row["gap_type"] == "LANGUAGE_DRIFT" for row in result["evidence_gap_details"])


def test_latest_composite_accepts_only_declared_component_versions_and_repositories():
    official = {
        "chunk_id": "docs-main:en:planning/example:1",
        "document_id": "docs-main:en:planning/example", "document_key": "planning/example",
        "version": "docs-main", "language": "en", "locale": "en-US",
        "heading": "Planning example", "content": "Official documentation evidence.",
        "retrieval_score": 3.0, "repository": "autowarefoundation/autoware-documentation",
        "commit": "a" * 40,
        "source_url": "https://github.com/autowarefoundation/autoware-documentation/blob/" + "a" * 40 + "/planning/example.md",
    }
    community = {
        **official,
        "chunk_id": "docs-main:zh:planning/example:1",
        "document_id": "docs-main:zh:planning/example", "language": "zh", "locale": "zh-CN",
        "content": "社区中文译本证据。", "repository": "tomato-ros/autoware-documentation-cn",
        "source_type": "community_translation", "commit": "b" * 40,
        "source_url": "https://github.com/tomato-ros/autoware-documentation-cn/blob/" + "b" * 40 + "/planning/example.md",
        "document_relationships": [{
            "relation_type": "translation_of", "verification_status": "candidate",
            "source_document_id": "docs-main:zh:planning/example",
            "target_document_id": "docs-main:en:planning/example",
        }],
    }
    historical = {**official, "chunk_id": "0.51.0:en:planning/example:1", "version": "0.51.0"}

    class CompositeGateway(Gateway):
        def workspace(self):
            return {
                "workspace": "Autoware", "repository": "autowarefoundation/autoware_universe",
                "repositories": [
                    "autowarefoundation/autoware-documentation",
                    "autowarefoundation/autoware_universe",
                    "tomato-ros/autoware-documentation-cn",
                ],
                "current_version": "latest", "available_versions": ["latest", "docs-main", "0.52.0", "0.51.0"],
                "version_scopes": {"latest": {"versions": ["docs-main", "0.52.0"]}},
            }

        def search(self, question, *, version, language, top_k=5):
            self.calls.append(("search", version, language, top_k))
            return {"retrieval_policy": "bm25_figure_ocr", "results": [official, community, historical]}

        def review_advice_for_version(self, summary, evidence_chunk_ids, *, version):
            self.calls.append(("review_advice_for_version", version, evidence_chunk_ids))
            return {
                "status": "ABSTAINED", "answer": "N/A", "sources": [],
                "review": {
                    "change_interpretation": "需人工核查。", "impact_candidates": [],
                    "evidence_gaps": [], "version_ambiguities": [], "reviewer_actions": [],
                    "review_status": "REQUIRES_HUMAN_REVIEW",
                },
            }

    gateway = CompositeGateway()
    result = PublicReviewAgent(gateway).analyze_request("Check the planning changes in the current release")

    assert {row["version"] for row in result["retrieved_results"]} == {"docs-main"}
    assert {row["repository"] for row in result["retrieved_results"]} == {
        "autowarefoundation/autoware-documentation", "tomato-ros/autoware-documentation-cn",
    }
    assert not any(row["version"] == "0.51.0" for row in result["retrieved_results"])
    assert gateway.calls[-1][1] == "latest"
    assert any(row["gap_type"] == "UNVERIFIED_TRANSLATION" for row in result["evidence_gap_details"])


def test_community_translation_without_registry_row_is_not_claimed_as_aligned():
    gateway = Gateway()
    source = next(
        row for row in CHUNKS
        if row["document_key"] == "guide/parameter/priority"
        and row["language"] == "zh" and row["version"] == "3.4.3"
    )
    community_translation = {
        **source, "source_type": "community_translation", "document_relationships": [],
        "repository": "community/docs-zh",
        "source_url": "https://github.com/community/docs-zh/blob/" + "c" * 40 + "/parameter.md",
        "commit": "c" * 40,
    }
    gateway.workspace = lambda: {
        "workspace": "Autoware", "repository": "apache/dolphinscheduler",
        "repositories": ["apache/dolphinscheduler", "community/docs-zh"],
        "current_version": "3.4.3", "available_versions": ["3.4.3"],
    }
    gateway.search = lambda *_args, **_kwargs: {"results": [community_translation]}

    result = PublicReviewAgent(gateway).analyze_request("Review this change against the current Chinese guide")

    gap = next(row for row in result["evidence_gap_details"] if row["gap_type"] == "UNVERIFIED_TRANSLATION")
    assert "尚无经人工核实的英文对应关系" in gap["description"]
    assert "内容同步或漂移" in gap["description"]
    assert "对应英文官方资料" in gap["suggested_query"]


def test_exact_review_reports_search_failure_instead_of_a_false_no_match():
    gateway = Gateway()
    selected = next(
        row for row in CHUNKS
        if row["document_key"] == "guide/parameter/priority"
        and row["language"] == "zh" and row["version"] == "3.4.3"
    )
    gateway.search = lambda *_args, **_kwargs: (_ for _ in ()).throw(ConnectionError("offline"))

    result = PublicReviewAgent(gateway).analyze(selected, selected["content"] + " proposed change")

    assert result["stage_status"]["retrieval"] == "FAILED"
    assert result["retrieval_trace"]["queries"][0]["status"] == "search_unavailable"
    assert result["evidence_gap_details"][0]["gap_type"] == "RETRIEVAL_FAILED"
    assert "未完成" in result["evidence_gap_details"][0]["description"]


def test_stage_status_distinguishes_retrieval_empty_failure_and_generation_failure():
    no_hits = Gateway()
    no_hits.search = lambda *_args, **_kwargs: {"results": []}
    no_evidence_result = PublicReviewAgent(no_hits).analyze_request("未收录参数行为")
    assert no_evidence_result["stage_status"] == {
        "planning": "OK", "retrieval": "EMPTY", "generation": "SKIPPED",
    }

    unavailable = Gateway()
    unavailable.search = lambda *_args, **_kwargs: (_ for _ in ()).throw(ConnectionError())
    unavailable_result = PublicReviewAgent(unavailable).analyze_request("检查参数行为")
    assert unavailable_result["stage_status"] == {
        "planning": "OK", "retrieval": "FAILED", "generation": "SKIPPED",
    }

    provider_failure = Gateway()
    provider_failure.review_advice = lambda *_args: {
        "status": "GENERATION_PROVIDER_TIMEOUT", "answer": "N/A", "sources": [],
    }
    failed_generation = PublicReviewAgent(provider_failure).analyze_request("检查参数行为")
    assert failed_generation["stage_status"] == {
        "planning": "OK", "retrieval": "OK", "generation": "FAILED",
    }
    assert failed_generation["retrieved_results"]
