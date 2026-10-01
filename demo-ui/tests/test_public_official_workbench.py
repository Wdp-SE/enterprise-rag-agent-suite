from __future__ import annotations

import json
from pathlib import Path

from streamlit.testing.v1 import AppTest


APP = Path(__file__).parents[1] / "app.py"
CHUNK = {
    "chunk_id": "3.4.3:zh:guide/parameter/priority:1",
    "document_id": "3.4.3:zh:guide/parameter/priority",
    "document_key": "guide/parameter/priority",
    "version": "3.4.3", "locale": "zh-CN", "language": "zh",
    "heading": "参数优先级", "content": "上游参数优先于启动参数。",
    "source_type": "official_documentation",
    "source_url": "https://github.com/apache/dolphinscheduler/blob/verified/docs/docs/zh/guide/parameter/priority.md",
    "retrieval_score": 12.0, "retrieval_policy": "bm25",
}


def _mock_client(monkeypatch):
    from services.public_knowledge_client import PublicKnowledgeClient
    import public_workbench

    monkeypatch.setenv("DEMO_LEGACY_FIXTURES", "false")
    monkeypatch.setattr(PublicKnowledgeClient, "workspace", lambda self: {
        "workspace": "Apache DolphinScheduler", "baseline_version": "3.4.2",
        "current_version": "3.4.3", "source_count": 52, "chunk_count": 659,
        "languages": ["zh-CN", "en-US"], "repository": "apache/dolphinscheduler",
    })
    monkeypatch.setattr(PublicKnowledgeClient, "documents", lambda self: [{
        "document_id": CHUNK["document_id"], "document_key": CHUNK["document_key"],
        "title": "参数优先级", "version": "3.4.3", "locale": "zh-CN",
        "source_type": "official_documentation", "source_url": CHUNK["source_url"],
    }])
    monkeypatch.setattr(PublicKnowledgeClient, "document", lambda self, document_id: [dict(CHUNK)])
    monkeypatch.setattr(PublicKnowledgeClient, "search", lambda self, question, **scope: {
        "query": question, "results": [dict(CHUNK)], "retrieval_policy": "bm25",
        "consistency_notes": [],
    })


    monkeypatch.setattr(PublicKnowledgeClient, "query_official", lambda self, question, **scope: {
        "answer": "上游参数优先于启动参数。", "sources": [dict(CHUNK)],
        "claims": [{"text": "上游参数优先于启动参数。", "source_indexes": [1]}],
        "evidence": [dict(CHUNK)], "status": "OK", "consistency_notes": [],
        "evidence_support": {
            "level": "partial", "label": "一般",
            "summary": "引用覆盖了部分问题关键词；该提示不代表答案正确率。",
        },
    })
    monkeypatch.setattr(PublicKnowledgeClient, "review_advice", lambda self, change_summary, evidence_chunk_ids: {
        "status": "OK", "answer": "依据引用片段，建议核对相关资料中的参数顺序。",
        "sources": [dict(CHUNK)] if CHUNK["chunk_id"] in evidence_chunk_ids else [],
        "evidence": [dict(CHUNK)] if CHUNK["chunk_id"] in evidence_chunk_ids else [],
        "review": {
            "change_interpretation": "依据引用片段，建议核对相关资料中的参数顺序。",
            "impact_candidates": [{
                "evidence_chunk_id": CHUNK["chunk_id"],
                "reason": "该章节说明参数优先级。",
                "suggested_action": "核对示例与运维说明是否同步。",
            }],
            "evidence_gaps": ["尚未检查英文资料。"],
            "version_ambiguities": [],
            "reviewer_actions": ["逐版本确认变更影响。"],
            "review_status": "REQUIRES_HUMAN_REVIEW",
        },
    })
    monkeypatch.setattr(
        PublicKnowledgeClient, "review_advice_for_version",
        lambda self, change_summary, evidence_chunk_ids, *, version:
            self.review_advice(change_summary, evidence_chunk_ids),
    )
    monkeypatch.setattr(public_workbench, "_analyze_hypothetical", lambda client, selected, proposed_text: {
        "change": {"change_type": "MODIFIED"}, "selected_source": dict(CHUNK),
        "impacts": [{"relation": "suggested", "status": "SUGGESTED", "reason": "主题相关，需人工核验。", "evidence": dict(CHUNK)}],
        "confirmed_relations": [], "patch_candidate": {
            "before": CHUNK["content"], "proposed_after": proposed_text,
            "status": "REQUIRES_HUMAN_REVIEW",
        }, "sandbox_only": True, "public_baseline_written": False,
        "review_advice": {
            "status": "OK", "answer": "依据本次官方片段，建议核对相关资料中的参数顺序。",
            "sources": [dict(CHUNK)],
            "review": {
                "change_interpretation": "依据本次官方片段，建议核对相关资料中的参数顺序。",
                "impact_candidates": [{
                    "evidence_chunk_id": CHUNK["chunk_id"],
                    "reason": "该章节说明参数优先级。",
                    "suggested_action": "核对示例与运维说明是否同步。",
                }],
                "evidence_gaps": ["尚未检查英文资料。"],
                "version_ambiguities": [],
                "reviewer_actions": ["逐版本确认变更影响。"],
                "review_status": "REQUIRES_HUMAN_REVIEW",
            },
        },
    })


def test_workspace_scoped_selectors_follow_the_latest_manifest_version():
    import public_workbench

    workspace = {
        "workspace": "Autoware", "repository": "autowarefoundation/autoware_universe",
        "baseline_version": "0.51.0", "current_version": "0.52.0",
        "available_versions": ["0.51.0", "0.52.0"], "languages": ["en-US"],
    }

    assert public_workbench._published_versions(workspace) == ["0.52.0", "0.51.0"]
    assert public_workbench._review_version_selector(workspace) == (["0.52.0", "0.51.0"], 0)
    assert public_workbench._published_language_options(workspace) == [("en", "English")]
    assert public_workbench._published_language_options({"languages": []}) == [("all", "语言元数据未声明")]


def test_bilingual_language_options_default_to_chinese_priority_before_all_languages():
    import public_workbench

    options = public_workbench._published_language_options({"languages": ["en-US", "zh-CN"]})

    assert options == [
        ("zh_preferred", "中文优先"),
        ("all", "全部已收录语言"),
        ("zh", "中文"),
        ("en", "English"),
    ]


def test_relationship_labels_keep_path_candidates_distinct_from_confirmed_translation():
    import public_workbench

    candidate = public_workbench._document_relationship_caption({
        "document_relationships": [{
            "relation_type": "translation_of", "verification_status": "candidate",
        }],
    })
    verified = public_workbench._document_relationship_caption({
        "document_relationships": [{
            "relation_type": "translation_of", "verification_status": "verified",
        }],
    })
    localized = public_workbench._document_relationship_caption({
        "document_relationships": [{
            "relation_type": "localized_variant_of", "verification_status": "verified",
        }],
    })

    assert "待核验" in candidate
    assert "不据此判断同步差异" in candidate
    assert "已核验" in verified
    assert "译文" not in localized


def test_autoware_source_coverage_summary_calls_out_unverified_community_pages():
    import public_workbench

    summary = public_workbench._source_coverage_text({
        "source_breakdown": [
            {"version": "docs-main", "locale": "en-US", "source_type": "official_documentation", "count": 431},
            {"version": "1.9.0", "locale": "en-US", "source_type": "official_documentation", "count": 431},
            {"version": "docs-main", "locale": "zh-CN", "source_type": "community_translation", "count": 260},
            {"version": "0.52.0", "locale": "en-US", "source_type": "official_documentation", "count": 13},
            {"version": "0.51.0", "locale": "en-US", "source_type": "official_documentation", "count": 13},
        ],
        "translation_alignment": {
            "path_matched_to_official_main": 44,
            "source_path_not_found_in_official_main": 216,
        },
    })

    assert summary is not None
    assert "官方 Documentation 英文 main 431 页" in summary
    assert "中文社区资料 260 页" in summary
    assert "44 页仅有路径匹配候选（内容和版本关系未核验）" in summary
    assert "216 页未找到同路径英文资料" in summary
    assert "仅核验通过的关联用于同步差异检查" in summary


def test_workbench_warns_when_connected_public_rag_workspace_is_not_autoware(monkeypatch):
    _mock_client(monkeypatch)
    from services.public_knowledge_client import PublicKnowledgeClient
    monkeypatch.setenv("APP_ENV", "public_demo")

    monkeypatch.setattr(PublicKnowledgeClient, "workspace", lambda self: {
        "workspace": "Apache DolphinScheduler",
        "repository": "apache/dolphinscheduler",
        "baseline_version": "0.51.0", "current_version": "0.52.0",
        "languages": ["zh-CN", "en-US"],
    })

    app = AppTest.from_file(APP, default_timeout=40).run()

    assert not app.exception
    warning = "\n".join(item.value for item in app.warning)
    assert "Autoware 工作台不匹配" in warning
    assert "RAG_API_BASE_URL" not in warning
    assert "public_corpus_autoware" not in warning


def test_home_hides_operational_and_corpus_detail_copy(monkeypatch):
    _mock_client(monkeypatch)
    from services.public_knowledge_client import PublicKnowledgeClient
    original_workspace = PublicKnowledgeClient.workspace
    monkeypatch.setattr(PublicKnowledgeClient, "workspace", lambda self: {
        **original_workspace(self),
        "corpus_scope": "Detailed corpus paths, repositories and version matching notes",
    })
    app = AppTest.from_file(APP, default_timeout=40).run()

    assert not app.exception
    visible = "\n".join(
        item.value
        for group in (app.markdown, app.caption, app.info, app.warning)
        for item in group
    )
    assert "选择要查看的功能页面" not in visible
    assert "精选资料范围，不代表上游项目全量" not in visible
    assert "独立工程演示，并非上游官方产品" not in visible
    assert "community Chinese translation snapshot" not in visible
    assert "Detailed corpus paths" not in visible
    assert "进入知识检索" in "\n".join(item.label for item in app.button)


def test_agent_context_filter_keeps_scope_guard_and_rejects_stale_results():
    import public_workbench

    args = {
        "summary": "change the planner behavior",
        "target_version": "0.52.0",
        "objective": "reduce false pull-out",
        "constraints": "keep interface stable",
        "validation_plan": "run planner tests",
        "selected_type_code": "workflow_behavior",
        "impact_scope": "behavior path planner",
    }
    assert public_workbench._request_context_matches({
        "request_summary": args["summary"], "scope_status": "OUT_OF_SCOPE",
    }, **args)

    valid = {
        "request_summary": args["summary"],
        "request_plan": {
            "target_version": "0.52.0", "impact_scope": "behavior path planner",
            "change_type": "workflow_behavior", "classification_source": "user_selected",
        },
        "request_context": {
            "target_version": "0.52.0", "objective": args["objective"],
            "constraints": args["constraints"], "validation_plan": args["validation_plan"],
        },
    }
    assert public_workbench._request_context_matches(valid, **args)
    assert not public_workbench._request_context_matches(
        valid, **{**args, "target_version": "0.51.0"}
    )


def _state_get(session_state, key, default=None):
    try:
        return session_state[key]
    except KeyError:
        return default


def _start_agent_request(app, summary="假设调整全局参数优先级，并找出需要核对的资料。"):
    if _state_get(app.session_state, "official_nav") != "新建变更审查":
        next(button for button in app.button if button.label == "发起变更审查").click().run()
    app.text_area(key="official_change_request").set_value(summary).run()
    next(button for button in app.button if button.label == "检索资料并分析影响").click().run()
    return app


def test_public_home_has_two_chinese_modules_and_no_case_labels(monkeypatch):
    _mock_client(monkeypatch)
    from services.public_knowledge_client import PublicKnowledgeClient
    monkeypatch.setattr(PublicKnowledgeClient, "workspace", lambda self: {
        "workspace": "Autoware", "repository": "autowarefoundation/autoware_universe",
        "baseline_version": "0.51.0", "current_version": "latest",
        "available_versions": ["latest", "docs-main", "1.9.0", "0.52.0", "0.51.0"],
        "languages": ["en-US", "zh-CN"],
        "source_breakdown": [
            {"version": "docs-main", "locale": "en-US", "source_type": "official_documentation", "count": 431},
            {"version": "1.9.0", "locale": "en-US", "source_type": "official_documentation", "count": 431},
            {"version": "docs-main", "locale": "zh-CN", "source_type": "community_translation", "count": 260},
            {"version": "0.52.0", "locale": "en-US", "source_type": "official_documentation", "count": 13},
            {"version": "0.51.0", "locale": "en-US", "source_type": "official_documentation", "count": 13},
        ],
        "translation_alignment": {
            "path_matched_to_official_main": 44,
            "source_path_not_found_in_official_main": 216,
        },
    })
    app = AppTest.from_file(APP, default_timeout=40).run()
    assert not app.exception
    assert [item.value for item in app.title] == ["研发知识版本服务与变更影响审查"]
    text = "\n".join(item.value for item in list(app.markdown) + list(app.caption))
    assert "Autoware" in text
    assert "版本化研发知识服务 · RAG" in text
    assert "Agent · 研发资料变更审查" in text
    assert "研发资料变更影响审查" in text
    assert "中文社区资料" in text
    assert "仅对核验通过的文档关系开展同步差异审查" in text
    assert "官方英文资料 + 社区中文译本" not in text
    assert "中英文资料按来源独立收录" in text
    assert "进入知识检索" in {button.label for button in app.button}
    assert "发起变更审查" in {button.label for button in app.button}
    assert "Case A" not in text and "演示案例 A" not in text
    assert "Case B" not in text and "演示案例 B" not in text
    assert app.session_state["official_nav"] == "总览"
    assert "总览" in {button.label for button in app.button}


def test_public_rag_keeps_answer_before_real_cited_source(monkeypatch):
    _mock_client(monkeypatch)
    app = AppTest.from_file(APP, default_timeout=40).run()
    next(button for button in app.button if button.label == "版本化知识检索").click().run()
    assert not app.exception
    assert app.selectbox(key="official_language").value == "zh_preferred"
    assert app.selectbox(key="official_version").value == "3.4.3"
    next(button for button in app.button if button.label == "生成带引用回答").click().run()
    assert not app.exception
    text = "\n".join(item.value for item in list(app.markdown) + list(app.caption))
    assert {item.value for item in app.subheader} >= {"回答", "引用依据"}
    assert "查看固定提交来源" in text
    assert "[1] 参数优先级" in text
    assert "引用编号对应本次检索片段" in text
    assert "证据支撑度：一般" not in text
    assert "不代表答案正确率" in text
    assert "证据可信度" not in text


def test_rag_renders_approved_image_ocr_as_derived_evidence(monkeypatch):
    _mock_client(monkeypatch)
    import public_workbench

    image = {
        **CHUNK,
        "chunk_id": "3.4.3:zh:guide/parameter/context:figure:1",
        "document_key": "guide/parameter/context",
        "document_id": "3.4.3:zh:guide/parameter/context",
        "heading": "参数上下文 / 查看运行结果",
        "content": "Node_A 日志截图显示输出 100 和 66。",
        "modality": "image_ocr", "figure_id": "64bd324feb4e55a2",
        "review_status": "approved", "sha256": "a" * 64,
        "commit": "a190201acffa03d199d4ca216288734a6513de3d",
        "raw_url": "https://raw.githubusercontent.com/apache/dolphinscheduler/a190201acffa03d199d4ca216288734a6513de3d/docs/img/example.png",
        "source_url": "https://github.com/apache/dolphinscheduler/blob/a190201acffa03d199d4ca216288734a6513de3d/docs/docs/zh/guide/parameter/context.md",
    }
    from services.public_knowledge_client import PublicKnowledgeClient
    monkeypatch.setattr(PublicKnowledgeClient, "search", lambda self, question, **scope: {
        "query": question, "results": [dict(image)], "retrieval_policy": "bm25_figure_ocr",
    })

    app = AppTest.from_file(APP, default_timeout=40).run()
    next(button for button in app.button if button.label == "版本化知识检索").click().run()
    next(button for button in app.button if button.label == "仅查看检索原文").click().run()

    assert not app.exception
    text = "\n".join(item.value for item in list(app.markdown) + list(app.caption) + list(app.info))
    assert "截图 OCR 文字" in text
    assert "需对照原图" in text
    assert "[查看原图]" in text
    assert "在 GitHub 查看固定版本来源" in text


def test_rag_hides_image_ocr_when_approval_or_pinned_image_url_is_invalid(monkeypatch):
    _mock_client(monkeypatch)
    from services.public_knowledge_client import PublicKnowledgeClient

    image = {
        **CHUNK,
        "modality": "image_ocr", "figure_id": "untrusted-figure",
        "review_status": "pending", "sha256": "bad-hash",
        "raw_url": "https://example.com/image.png",
        "content": "untrusted screenshot text",
    }
    monkeypatch.setattr(PublicKnowledgeClient, "search", lambda self, question, **scope: {
        "query": question, "results": [dict(image)], "retrieval_policy": "bm25_figure_ocr",
    })

    app = AppTest.from_file(APP, default_timeout=40).run()
    next(button for button in app.button if button.label == "版本化知识检索").click().run()
    next(button for button in app.button if button.label == "仅查看检索原文").click().run()

    assert not app.exception
    text = "\n".join(item.value for item in list(app.markdown) + list(app.caption) + list(app.info) + list(app.warning))
    assert "截图证据未通过来源校验，已隐藏" in text
    assert "untrusted screenshot text" not in text


def test_version_selector_uses_latest_published_workspace_version(monkeypatch):
    _mock_client(monkeypatch)
    from services.public_knowledge_client import PublicKnowledgeClient

    monkeypatch.setattr(PublicKnowledgeClient, "workspace", lambda self: {
        "workspace": "Apache DolphinScheduler", "baseline_version": "3.4.3",
        "current_version": "3.5.0", "source_count": 70, "chunk_count": 800,
    })
    app = AppTest.from_file(APP, default_timeout=40).run()
    next(button for button in app.button if button.label == "版本化知识检索").click().run()

    assert not app.exception
    assert app.selectbox(key="official_version").value == "3.5.0"
    labels = app.selectbox(key="official_version").options
    assert labels[0].startswith("3.5.0") and labels[1].startswith("3.4.3")
    assert labels[2] == "全部已收录版本"


def test_version_selector_tracks_new_latest_release_after_manual_old_selection(monkeypatch):
    _mock_client(monkeypatch)
    from services.public_knowledge_client import PublicKnowledgeClient

    workspace = {
        "workspace": "Apache DolphinScheduler", "baseline_version": "3.4.2",
        "current_version": "3.4.3", "source_count": 52, "chunk_count": 659,
        "latest_source_retrieval_timestamp": "2026-09-27T16:48:07.391969+00:00",
    }
    monkeypatch.setattr(PublicKnowledgeClient, "workspace", lambda self: dict(workspace))
    app = AppTest.from_file(APP, default_timeout=40).run()
    next(button for button in app.button if button.label == "版本化知识检索").click().run()
    assert app.selectbox(key="official_version").value == "3.4.3"

    workspace.update(
        baseline_version="3.4.3", current_version="3.5.0",
        latest_source_retrieval_timestamp="2026-09-28T09:15:00+00:00",
    )
    app.run()

    assert not app.exception
    assert app.selectbox(key="official_version").value == "3.5.0"
    app.selectbox(key="official_version").set_value("3.4.3").run()
    assert app.selectbox(key="official_version").value == "3.4.3"
    visible = "\n".join(item.value for item in list(app.markdown) + list(app.caption))
    assert "最新已收录版本" in visible
    assert "最近收录资料" in visible and "2026-09-28 09:15 UTC" in visible


def test_offline_version_fallback_is_not_presented_as_latest(monkeypatch):
    _mock_client(monkeypatch)
    from services.public_knowledge_client import PublicKnowledgeClient

    monkeypatch.setattr(PublicKnowledgeClient, "workspace", lambda self: None)
    app = AppTest.from_file(APP, default_timeout=40).run()
    next(button for button in app.button if button.label == "版本化知识检索").click().run()

    assert not app.exception
    assert app.selectbox(key="official_version").value == "3.4.3"
    visible = "\n".join(item.value for item in list(app.markdown) + list(app.caption))
    assert "无法确认最新已收录版本" in visible
    assert "离线回退配置" in visible


def test_agent_result_prioritizes_analysis_and_pairs_actions_with_evidence(monkeypatch):
    _mock_client(monkeypatch)
    app = AppTest.from_file(APP, default_timeout=40).run()
    _start_agent_request(app)

    assert not app.exception
    visible = "\n".join(
        item.value for collection in (app.markdown, app.caption, app.subheader, app.info)
        for item in collection
    )
    assert "本次分析结论" in visible
    assert "优先核对的影响候选" in visible
    assert "建议核对动作" in visible
    assert "引用证据" in visible
    assert "等待人工审核" in visible
    source_links = [item.value for item in app.markdown if "[打开官方原文]" in item.value]
    assert len(source_links) == 1
    assert "可能相关资料" not in {item.value for item in app.subheader}


def test_review_decision_cannot_approve_a_different_analysis(monkeypatch):
    _mock_client(monkeypatch)
    app = AppTest.from_file(APP, default_timeout=40).run()
    _start_agent_request(app)
    next(button for button in app.button if button.label == "确认已审阅本次影响分析").click().run()
    request_target = app.session_state["official_review_decision_target"]

    app.session_state["official_review"] = {
        "request_mode": "selected_source",
        "selected_source": {"chunk_id": "another-source"},
        "patch_candidate": {"proposed_after": "另一个会话草案"},
    }
    next(button for button in app.button if button.label == "人工审核").click().run()

    assert not app.exception
    assert not any("已记录本次会话对会话草案" in item.value for item in app.success)
    next(button for button in app.button if button.label == "确认已审阅会话草案").click().run()
    assert app.session_state["official_review_decision_target"] != request_target


def test_agent_shows_retrieval_trace_and_uncovered_change_clause(monkeypatch):
    _mock_client(monkeypatch)
    from services.public_knowledge_client import PublicKnowledgeClient

    def search(self, question, **scope):
        rows = [] if question.startswith("待排查") else [dict(CHUNK)]
        return {"query": question, "results": rows, "retrieval_policy": "bm25"}

    monkeypatch.setattr(PublicKnowledgeClient, "search", search)
    app = AppTest.from_file(APP, default_timeout=40).run()
    _start_agent_request(app, "调整参数优先级；待排查调度失败恢复说明。")

    assert not app.exception
    assert app.session_state["official_request_review"]["retrieval_trace"]["uncovered_queries"]
    visible = "\n".join(item.value for item in list(app.markdown) + list(app.caption))
    assert "检索过程与覆盖范围" in {item.label for item in app.expander}
    assert "待排查调度失败恢复说明" in visible


def test_agent_surfaces_stage_status_and_unverified_translation_check(monkeypatch):
    _mock_client(monkeypatch)
    from services.public_knowledge_client import PublicKnowledgeClient

    related = {
        "gap_type": "UNVERIFIED_TRANSLATION",
        "message": "中英文对应关系待核验；不能据此判定内容不一致。",
        "description": "中英文对应关系待核验；不能据此判定内容不一致。",
        "missing_source_type": "经人工确认的中英文对应关系",
        "expected_version": "0.52.0",
        "suggested_query": "核验对应语种资料：docs-main:en:planning/example",
        "suggested_action": "先确认两份资料确为同一范围，再检查更新时间。",
    }
    original_search = PublicKnowledgeClient.search

    def search(self, question, **scope):
        result = original_search(self, question, **scope)
        result["results"] = [{
            **result["results"][0],
            "document_relationships": [{
                "relation_type": "translation_of", "verification_status": "candidate",
            }],
        }]
        return result

    monkeypatch.setattr(PublicKnowledgeClient, "search", search)
    app = AppTest.from_file(APP, default_timeout=40).run()
    _start_agent_request(app)

    assert not app.exception
    result = app.session_state["official_request_review"]
    result["stage_status"] = {"planning": "OK", "retrieval": "OK", "generation": "OK"}
    result["evidence_gap_details"] = [related]
    app.session_state["official_request_review"] = result
    app.run()

    assert not app.exception
    visible = "\n".join(item.value for item in list(app.markdown) + list(app.caption) + list(app.info))
    assert "流程状态" in visible
    assert "对应关系待核验" in visible
    assert "0.52.0" in visible
    assert "核验对应语种资料" in visible
    assert "待补充核查" in {item.value for item in app.subheader}


def test_agent_shows_model_abstention_gaps_as_unconfirmed_prompts(monkeypatch):
    _mock_client(monkeypatch)
    from services.public_knowledge_client import PublicKnowledgeClient

    monkeypatch.setattr(PublicKnowledgeClient, "review_advice", lambda self, change_summary, evidence_chunk_ids: {
        "status": "ABSTAINED", "answer": "N/A", "sources": [],
        "evidence": [dict(CHUNK)],
        "review": {
            "change_interpretation": "需要进一步核对。",
            "impact_candidates": [],
            "evidence_gaps": ["缺少下游节点恢复行为说明。"],
            "version_ambiguities": ["尚未核对历史版本。"],
            "reviewer_actions": ["补充恢复策略来源后重新审查。"],
            "review_status": "REQUIRES_HUMAN_REVIEW",
        },
    })
    app = AppTest.from_file(APP, default_timeout=40).run()
    _start_agent_request(app, "调整故障恢复策略")

    assert not app.exception
    result = app.session_state["official_request_review"]
    assert result["impacts"] == []
    visible = "\n".join(item.value for item in list(app.markdown) + list(app.caption) + list(app.info))
    assert "模型提示待核对" in visible
    assert "缺少下游节点恢复行为说明" in visible
    assert "尚未核对历史版本" in visible
    assert "补充恢复策略来源后重新审查" in visible


def test_review_export_records_task_evidence_and_human_decision_without_raw_draft():
    from public_workbench import _review_report

    result = {
        "task_id": "task-123", "request_fingerprint": "request-sha", "request_mode": "selected_source",
        "selected_source": {"chunk_id": "3.4.3:zh:guide/test:1", "source_url": "https://github.com/apache/dolphinscheduler/example"},
        "patch_candidate": {"before": "official text", "proposed_after": "private proposed text"},
        "retrieved_results": [], "review_advice": {"status": "OK", "review": {"impact_candidates": []}},
        "retrieval_trace": {"queries": []}, "evidence_gaps": [], "public_baseline_written": False,
    }

    report = _review_report(result, "reviewed", "2026-09-28T00:00:00+00:00")

    assert report["task_id"] == "task-123"
    assert report["human_decision"] == "reviewed"
    assert report["selected_source_id"] == "3.4.3:zh:guide/test:1"
    assert report["public_baseline_written"] is False
    assert report["proposed_after_sha256"]
    assert report["schema_version"] == 2
    assert "private proposed text" not in json.dumps(report, ensure_ascii=False)


def test_generation_rate_limit_keeps_evidence_and_explains_retry(monkeypatch):
    _mock_client(monkeypatch)
    from services.public_knowledge_client import PublicKnowledgeClient

    monkeypatch.setattr(PublicKnowledgeClient, "query_official", lambda self, question, **scope: {
        "answer": "N/A", "sources": [], "evidence": [dict(CHUNK)],
        "status": "GENERATION_RATE_LIMITED", "consistency_notes": [],
        "generation": {
            "request_id": "test-request-1", "provider": "deepseek",
            "requested_model": "deepseek-chat", "returned_model": None,
            "finish_reason": None, "usage": None, "latency_ms": 1480,
        },
    })
    app = AppTest.from_file(APP, default_timeout=40).run()
    next(button for button in app.button if button.label == "版本化知识检索").click().run()
    next(button for button in app.button if button.label == "生成带引用回答").click().run()

    assert not app.exception
    visible = "\n".join(item.value for item in list(app.markdown) + list(app.caption))
    assert "限流" in visible and "稍后重试" in visible
    assert "[1] 参数优先级" in visible
    assert "test-request-1" in visible


def test_long_hit_fragment_is_complete_once_and_names_github_as_snapshot(monkeypatch):
    _mock_client(monkeypatch)
    from services.public_knowledge_client import PublicKnowledgeClient

    long_hit = {**CHUNK, "content": "命中证据。" * 200}
    monkeypatch.setattr(PublicKnowledgeClient, "query_official", lambda self, question, **scope: {
        "answer": "检索证据支持的回答。", "sources": [long_hit], "evidence": [long_hit],
        "status": "OK", "consistency_notes": [],
    })
    app = AppTest.from_file(APP, default_timeout=40).run()
    next(button for button in app.button if button.label == "版本化知识检索").click().run()
    next(button for button in app.button if button.label == "生成带引用回答").click().run()

    assert not app.exception
    visible = "\n".join(item.value for item in app.markdown)
    assert visible.count("命中证据。") == 200
    assert all("完整命中片段" not in item.label for item in app.expander)
    assert "在 GitHub 查看固定版本来源" in visible


def test_generated_answer_shows_cited_evidence_first_and_collapses_other_hits(monkeypatch):
    _mock_client(monkeypatch)
    from services.public_knowledge_client import PublicKnowledgeClient

    other = {**CHUNK, "chunk_id": "3.4.3:zh:guide/parameter/local:2", "heading": "本地参数"}
    monkeypatch.setattr(PublicKnowledgeClient, "query_official", lambda self, question, **scope: {
        "answer": "启动参数优先于本地参数。", "sources": [dict(CHUNK)],
        "evidence": [dict(CHUNK), other], "status": "OK", "consistency_notes": [],
    })
    app = AppTest.from_file(APP, default_timeout=40).run()
    next(button for button in app.button if button.label == "版本化知识检索").click().run()
    next(button for button in app.button if button.label == "生成带引用回答").click().run()

    assert not app.exception
    assert "引用依据" in {item.value for item in app.subheader}
    assert any(item.label == "查看其余检索结果（1）" for item in app.expander)
    assert "只想核对原文？" in {item.label for item in app.expander}


def test_generated_answer_renders_claim_level_references_without_confidence_grade(monkeypatch):
    _mock_client(monkeypatch)
    from services.public_knowledge_client import PublicKnowledgeClient

    monkeypatch.setattr(PublicKnowledgeClient, "query_official", lambda self, question, **scope: {
        "answer": "当前片段记录上游参数优先。", "sources": [dict(CHUNK)],
        "claims": [{"text": "当前片段记录上游参数优先。", "source_indexes": [1]}],
        "evidence": [dict(CHUNK)], "status": "OK", "consistency_notes": [],
    })
    app = AppTest.from_file(APP, default_timeout=40).run()
    next(button for button in app.button if button.label == "版本化知识检索").click().run()
    next(button for button in app.button if button.label == "生成带引用回答").click().run()

    visible = "\n".join(item.value for item in list(app.markdown) + list(app.caption))
    assert "当前片段记录上游参数优先" in visible
    assert "[1]" in visible
    assert "引用编号对应本次检索片段" in visible
    assert "证据支撑度：" not in visible


def test_agent_starts_with_natural_language_and_uses_rag_to_find_candidates(monkeypatch):
    _mock_client(monkeypatch)
    from services.public_knowledge_client import PublicKnowledgeClient

    calls = []
    def search(self, question, *, version, language, top_k=5):
        calls.append((question, version, language, top_k))
        return {"query": question, "results": [dict(CHUNK)], "retrieval_policy": "bm25"}

    monkeypatch.setattr(PublicKnowledgeClient, "search", search)
    app = AppTest.from_file(APP, default_timeout=40).run()
    next(button for button in app.button if button.label == "发起变更审查").click().run()

    assert app.text_area(key="official_change_request").label == "描述研发变更"
    assert not any(box.label == "选择真实研发资料" for box in app.selectbox)
    change_request = "计划将全局参数优先级调整为最高，请找出需要核对的研发资料。"
    app.text_area(key="official_change_request").set_value(change_request).run()
    next(button for button in app.button if button.label == "检索资料并分析影响").click().run()

    assert not app.exception
    assert calls == [
        (f"{change_request} global parameter", "3.4.3", "zh", 5),
        (f"{change_request} global parameter", "3.4.3", "en", 5),
    ]
    assert app.session_state["official_request_review"]["request_summary"] == change_request
    assert app.session_state["official_request_review"]["impacts"][0]["evidence"]["chunk_id"] == CHUNK["chunk_id"]
    headings = [item.value for item in app.subheader]
    assert headings.index("模型辅助核对建议") < headings.index("优先核对的影响候选")
    assert "建议引用的官方片段（变更分析）" not in headings
    evidence_ids = [item["chunk_id"] for item in app.session_state["official_request_review"]["retrieved_results"]]
    assert len(evidence_ids) == len(set(evidence_ids))
    assert "检索覆盖不完整" in "\n".join(item.value for item in app.warning)


def test_rag_suggested_question_is_muted_placeholder_and_used_when_submitted_blank(monkeypatch):
    _mock_client(monkeypatch)
    from services.public_knowledge_client import PublicKnowledgeClient

    monkeypatch.setattr(PublicKnowledgeClient, "workspace", lambda self: {
        "workspace": "Autoware", "repository": "autowarefoundation/autoware_universe",
        "baseline_version": "0.51.0", "current_version": "0.52.0",
        "available_versions": ["0.51.0", "0.52.0"], "languages": ["en-US"],
    })

    submitted = []
    monkeypatch.setattr(PublicKnowledgeClient, "query_official", lambda self, question, **scope: (
        submitted.append(question) or {
            "answer": "依据官方资料生成的回答。", "sources": [dict(CHUNK)],
            "evidence": [dict(CHUNK)], "status": "OK", "consistency_notes": [],
        }
    ))
    app = AppTest.from_file(APP, default_timeout=40).run()
    next(button for button in app.button if button.label == "版本化知识检索").click().run()

    question = app.text_area(key="official_question")
    assert question.value == ""
    assert question.placeholder == "How does the start planner decide when to generate a pull-out path?"
    next(button for button in app.button if button.label == "生成带引用回答").click().run()

    assert not app.exception
    assert submitted == ["How does the start planner decide when to generate a pull-out path?"]
    assert "依据官方资料生成的回答。" in "\n".join(item.value for item in app.markdown)


def test_rag_generation_uses_user_edited_question(monkeypatch):
    _mock_client(monkeypatch)
    from services.public_knowledge_client import PublicKnowledgeClient

    submitted = []
    monkeypatch.setattr(PublicKnowledgeClient, "query_official", lambda self, question, **scope: (
        submitted.append(question) or {
            "answer": "依据官方资料生成的回答。", "sources": [dict(CHUNK)],
            "evidence": [dict(CHUNK)], "status": "OK", "consistency_notes": [],
        }
    ))
    app = AppTest.from_file(APP, default_timeout=40).run()
    next(button for button in app.button if button.label == "版本化知识检索").click().run()
    app.text_area(key="official_question").set_value("Which parameters configure the planning validator?").run()
    next(button for button in app.button if button.label == "生成带引用回答").click().run()

    assert not app.exception
    assert submitted == ["Which parameters configure the planning validator?"]


def test_suggested_questions_match_current_autoware_corpus(monkeypatch):
    _mock_client(monkeypatch)
    from services.public_knowledge_client import PublicKnowledgeClient
    monkeypatch.setattr(PublicKnowledgeClient, "workspace", lambda self: {
        "workspace": "Autoware", "repository": "autowarefoundation/autoware_universe",
        "baseline_version": "0.51.0", "current_version": "0.52.0",
        "available_versions": ["0.51.0", "0.52.0"], "languages": ["en-US"],
    })
    app = AppTest.from_file(APP, default_timeout=40).run()
    next(button for button in app.button if button.label == "版本化知识检索").click().run()

    example_picker = app.selectbox(key="official_example")
    options = example_picker.options
    assert "Which parameters configure the planning validator?" in options
    assert "How does the start planner decide when to generate a pull-out path?" in options
    assert "What does the planning validator check before publishing a trajectory?" in options
    assert not any("DolphinScheduler" in question or "API server" in question for question in options)
    assert not any(item.label == "从已收录资料选择示例问题" for item in app.expander)
    assert example_picker.label == "示例问题（选择后可编辑）"

    selected_question = "Which parameters configure the planning validator?"
    example_picker.set_value(selected_question).run()
    assert app.text_area(key="official_question").value == selected_question


def test_evidence_image_markdown_uses_text_placeholder_instead_of_missing_asset(monkeypatch):
    _mock_client(monkeypatch)
    from services.public_knowledge_client import PublicKnowledgeClient

    image_chunk = {
        **CHUNK,
        "content": "Dependencies support execution tracking.\n\n"
                   "![Apache DolphinScheduler](../../../img/introduction_ui.png)",
    }
    monkeypatch.setattr(PublicKnowledgeClient, "search", lambda self, question, **scope: {
        "query": question, "results": [dict(image_chunk)], "retrieval_policy": "bm25",
        "consistency_notes": [],
    })
    app = AppTest.from_file(APP, default_timeout=40).run()
    next(button for button in app.button if button.label == "版本化知识检索").click().run()
    next(button for button in app.button if button.label == "仅查看检索原文").click().run()

    assert not app.exception
    rendered = "\n".join(item.value for item in app.markdown)
    assert "原文配图「Apache DolphinScheduler」" in rendered
    assert "![Apache DolphinScheduler]" not in rendered


def test_agent_original_source_uses_placeholder_for_missing_markdown_images(monkeypatch):
    _mock_client(monkeypatch)
    from services.public_knowledge_client import PublicKnowledgeClient

    image_chunk = {
        **CHUNK,
        "content": "Apache DolphinScheduler guide.\n\n"
                   "![Apache DolphinScheduler](../../../img/introduction_ui.png)",
    }
    monkeypatch.setattr(PublicKnowledgeClient, "document", lambda self, document_id: [dict(image_chunk)])

    app = AppTest.from_file(APP, default_timeout=40).run()
    next(button for button in app.button if button.label == "发起变更审查").click().run()
    _start_agent_request(app)

    assert not app.exception
    rendered = "\n".join(item.value for item in app.markdown)
    assert "原文配图「Apache DolphinScheduler」" in rendered
    assert "![Apache DolphinScheduler]" not in rendered


def test_public_rag_without_generation_shows_compact_evidence_fallback(monkeypatch):
    _mock_client(monkeypatch)
    from services.public_knowledge_client import PublicKnowledgeClient

    monkeypatch.setattr(PublicKnowledgeClient, "query_official", lambda self, question, **scope: {
        "answer": "N/A", "sources": [], "evidence": [dict(CHUNK)],
        "status": "GENERATION_NOT_CONFIGURED", "consistency_notes": [],
    })
    app = AppTest.from_file(APP, default_timeout=40).run()
    next(button for button in app.button if button.label == "版本化知识检索").click().run()
    next(button for button in app.button if button.label == "生成带引用回答").click().run()

    assert not app.exception
    visible = "\n".join(item.value for item in list(app.markdown) + list(app.caption) + list(app.info))
    assert "检索证据仍可查看" in visible
    assert "模型生成尚未启用" in visible
    assert "API_KEY" not in visible
    assert "start_prototype.ps1" not in visible
    assert "[1] 参数优先级" in visible
    assert "检索候选" not in visible
    assert "只想核对原文？" in {item.label for item in app.expander}
    assert "仅查看检索原文" in {button.label for button in app.button}


def test_public_rag_generation_failure_explains_backend_fallback(monkeypatch):
    _mock_client(monkeypatch)
    from services.public_knowledge_client import PublicKnowledgeClient

    monkeypatch.setattr(PublicKnowledgeClient, "query_official", lambda self, question, **scope: {
        "answer": "N/A", "sources": [], "evidence": [dict(CHUNK)],
        "status": "FAIL_CLOSED", "consistency_notes": [],
    })
    app = AppTest.from_file(APP, default_timeout=40).run()
    next(button for button in app.button if button.label == "版本化知识检索").click().run()
    next(button for button in app.button if button.label == "生成带引用回答").click().run()

    visible = "\n".join(item.value for item in list(app.markdown) + list(app.caption) + list(app.info))
    assert "生成未完成（FAIL_CLOSED）" in visible
    assert "联系维护者时请提供请求编号" in visible
    assert "[1] 参数优先级" in visible


def test_abstained_answer_explains_missing_retrieval_terms(monkeypatch):
    _mock_client(monkeypatch)
    from services.public_knowledge_client import PublicKnowledgeClient

    monkeypatch.setattr(PublicKnowledgeClient, "query_official", lambda self, question, **scope: {
        "answer": "N/A", "sources": [], "evidence": [dict(CHUNK)],
        "status": "ABSTAINED", "consistency_notes": [],
        "generation": {
            "failure_reason": "MODEL_NO_SUPPORTED_ANSWER",
            "candidate_count": 5,
            "evidence_coverage": {"matched_terms": ["api", "server"], "missing_terms": ["health", "check", "endpoint"]},
            "request_id": "request-abstained-test",
        },
    })
    app = AppTest.from_file(APP, default_timeout=40).run()
    next(button for button in app.button if button.label == "版本化知识检索").click().run()
    next(button for button in app.button if button.label == "生成带引用回答").click().run()

    visible = "\n".join(item.value for item in list(app.markdown) + list(app.caption) + list(app.info))
    assert "模型服务正常" in visible
    assert "health、check、endpoint" in visible
    assert "未覆盖关键词" in visible
    assert "不是网络或 API Key 故障" not in visible
    assert "[1] 参数优先级" in visible


def test_abstained_answer_distinguishes_keyword_match_from_supported_answer(monkeypatch):
    _mock_client(monkeypatch)
    from services.public_knowledge_client import PublicKnowledgeClient

    monkeypatch.setattr(PublicKnowledgeClient, "query_official", lambda self, question, **scope: {
        "answer": "N/A", "sources": [], "evidence": [dict(CHUNK)],
        "status": "ABSTAINED", "consistency_notes": [],
        "generation": {
            "failure_reason": "MODEL_NO_SUPPORTED_ANSWER",
            "candidate_count": 5,
            "evidence_coverage": {
                "matched_terms": ["api", "server", "health", "check", "endpoint"],
                "missing_terms": [],
            },
        },
    })
    app = AppTest.from_file(APP, default_timeout=40).run()
    next(button for button in app.button if button.label == "版本化知识检索").click().run()
    next(button for button in app.button if button.label == "生成带引用回答").click().run()

    visible = "\n".join(item.value for item in list(app.markdown) + list(app.caption) + list(app.info))
    assert "没有找到可支持答案的原文" in visible
    assert "这是证据不足导致的拒答，不是网络或 API Key 故障" in visible
    assert "当前证据覆盖了部分问题关键词" not in visible


def test_public_rag_has_no_fixed_generation_count_limit(monkeypatch):
    _mock_client(monkeypatch)
    monkeypatch.setenv("MAX_LLM_CALLS_PER_SESSION", "10")
    app = AppTest.from_file(APP, default_timeout=40).run()
    next(button for button in app.button if button.label == "版本化知识检索").click().run()
    app.session_state["official_generation_calls"] = 1000
    app.run()

    assert app.button(key="knowledge_generate").disabled is False
    captions = [item.value for item in app.caption]
    assert not any("剩余生成次数" in caption or "生成额度已用完" in caption for caption in captions)
    assert any("应用不设固定生成次数上限" in caption for caption in captions)


def test_provider_connection_failure_explains_proxy_or_network(monkeypatch):
    _mock_client(monkeypatch)
    from services.public_knowledge_client import PublicKnowledgeClient

    monkeypatch.setattr(PublicKnowledgeClient, "query_official", lambda self, question, **scope: {
        "answer": "N/A", "sources": [], "evidence": [dict(CHUNK)],
        "status": "GENERATION_PROVIDER_UNAVAILABLE", "consistency_notes": [],
    })
    app = AppTest.from_file(APP, default_timeout=40).run()
    next(button for button in app.button if button.label == "版本化知识检索").click().run()
    next(button for button in app.button if button.label == "生成带引用回答").click().run()

    visible = "\n".join(item.value for item in list(app.markdown) + list(app.caption) + list(app.info))
    assert "后端无法连接模型服务" in visible
    assert "检索证据已保留" in visible
    assert "[1] 参数优先级" in visible


def test_provider_rejection_and_invalid_response_explain_safe_fallback(monkeypatch):
    _mock_client(monkeypatch)
    from services.public_knowledge_client import PublicKnowledgeClient

    statuses = iter(("GENERATION_PROVIDER_REJECTED", "GENERATION_RESPONSE_INVALID"))
    monkeypatch.setattr(PublicKnowledgeClient, "query_official", lambda self, question, **scope: {
        "answer": "N/A", "sources": [], "evidence": [dict(CHUNK)],
        "status": next(statuses), "consistency_notes": [],
    })
    app = AppTest.from_file(APP, default_timeout=40).run()
    next(button for button in app.button if button.label == "版本化知识检索").click().run()
    next(button for button in app.button if button.label == "生成带引用回答").click().run()
    visible = "\n".join(item.value for item in list(app.markdown) + list(app.caption))
    assert "模型服务拒绝了请求" in visible
    assert "检索证据已保留" in visible

    next(button for button in app.button if button.label == "生成带引用回答").click().run()
    visible = "\n".join(item.value for item in list(app.markdown) + list(app.caption))
    assert "模型返回内容未满足引用要求" in visible
    assert "检索证据已保留" in visible


def test_generated_answer_typography_is_large_and_readable():
    from components.public_theme import PUBLIC_CSS

    assert '.st-key-generated_answer [data-testid="stMarkdownContainer"] p {' in PUBLIC_CSS
    assert "font-size:1.3rem!important;line-height:1.75!important;" in PUBLIC_CSS
    assert "font-size:1.3rem!important;line-height:1.75!important;" in PUBLIC_CSS


def test_breadcrumbs_are_clickable_and_back_returns_to_previous_module(monkeypatch):
    _mock_client(monkeypatch)
    app = AppTest.from_file(APP, default_timeout=40).run()

    next(button for button in app.button if button.label == "版本化知识检索").click().run()
    labels = {button.label for button in app.button}
    assert {"←", "首页", "版本化知识服务"} <= labels
    assert "返回首页" not in labels
    assert any(
        'class="breadcrumbs-current"' in item.value
        and 'aria-current="page"' in item.value
        and "版本化知识检索与问答" in item.value
        for item in app.markdown
    )

    next(button for button in app.button if button.label == "发起变更审查").click().run()
    next(button for button in app.button if button.label == "←").click().run()
    assert app.session_state["official_nav"] == "版本检索与问答"

    next(button for button in app.button if button.label == "首页").click().run()
    assert app.session_state["official_nav"] == "总览"

    next(button for button in app.button if button.label == "发起变更审查").click().run()
    next(button for button in app.button if button.label == "变更影响审查").click().run()
    assert app.session_state["official_nav"] == "新建变更审查"
    next(button for button in app.button if button.label == "首页").click().run()
    assert app.session_state["official_nav"] == "总览"


def test_review_subpage_breadcrumb_and_back_history(monkeypatch):
    _mock_client(monkeypatch)
    app = AppTest.from_file(APP, default_timeout=40).run()
    _start_agent_request(app)

    next(button for button in app.button if button.label == "人工审核").click().run()
    assert app.session_state["official_nav"] == "人工审核"
    assert {"←", "首页", "变更影响审查"} <= {button.label for button in app.button}
    assert "返回审查" not in {button.label for button in app.button}

    next(button for button in app.button if button.label == "变更影响审查").click().run()
    assert app.session_state["official_nav"] == "新建变更审查"
    assert app.session_state["official_request_review"]["sandbox_only"] is True

    next(button for button in app.button if button.label == "←").click().run()
    assert app.session_state["official_nav"] == "人工审核"


def test_rag_actions_alerts_and_typography_use_neutral_accessible_styles(monkeypatch):
    _mock_client(monkeypatch)
    app = AppTest.from_file(APP, default_timeout=40).run()
    next(button for button in app.button if button.label == "版本化知识检索").click().run()
    assert app.button(key="knowledge_generate")
    assert app.button(key="knowledge_search")

    from components.public_theme import PUBLIC_CSS

    assert ".st-key-knowledge_generate button" in PUBLIC_CSS
    assert ".st-key-knowledge_search button" in PUBLIC_CSS
    assert "[data-testid=\"stAlert\"]" in PUBLIC_CSS
    assert "background:var(--paper)!important" in PUBLIC_CSS
    assert "[data-testid=\"stMarkdownContainer\"] p" in PUBLIC_CSS
    assert "font-size:clamp(1.14rem,1.06rem + .2vw,1.3rem)!important;" in PUBLIC_CSS


def test_streamlit_alert_inner_layers_cannot_restore_blue_backgrounds():
    from components.public_theme import PUBLIC_CSS

    assert '[data-testid="stAlert"] *' in PUBLIC_CSS
    assert '[role="alert"] *' in PUBLIC_CSS
    assert "background-image:none!important;" in PUBLIC_CSS
    assert "background-color:transparent!important;" in PUBLIC_CSS


def test_legacy_ui_theme_has_no_blue_tinted_surfaces():
    app_source = APP.read_text(encoding="utf-8")

    for color in ("#f4f7fb", "#f7f9fc", "#eaf0f7", "#f5f9ff", "#edf4fb", "#eef4fa"):
        assert color not in app_source


def test_workbench_theme_keeps_neutral_base_and_equal_home_cards():
    from components.public_theme import PUBLIC_CSS, _frame_data_uri

    assert "--canvas:#f5f5f5" in PUBLIC_CSS
    assert "--ink:#171717" in PUBLIC_CSS
    assert "--quiet:#f7f7f7" in PUBLIC_CSS
    assert "--blue:" not in PUBLIC_CSS
    assert "background:var(--ink)!important" not in PUBLIC_CSS
    assert ".st-key-public_rag_module,.st-key-public_agent_module {" in PUBLIC_CSS
    assert "background:var(--paper)!important;color:var(--ink);" in PUBLIC_CSS
    assert '[data-testid="stSelectbox"] .react-aria-ComboBox [role="group"] {' in PUBLIC_CSS
    assert "min-height:25rem;padding:4.2rem clamp(3.5rem,4.6vw,4.5rem) 3.7rem!important;" in PUBLIC_CSS
    assert "grid-template-columns:repeat(5,minmax(0,1fr))" in PUBLIC_CSS
    assert '[data-testid="stHorizontalBlock"]:has(.st-key-public_rag_module) {flex-direction:column!important;' in PUBLIC_CSS
    assert '.st-key-public_rag_module::before {background-image:url("' + _frame_data_uri("rag-book-frame.svg") + '");}' in PUBLIC_CSS
    assert '.st-key-public_agent_module::before {background-image:url("' + _frame_data_uri("agent-robot-frame.svg") + '");}' in PUBLIC_CSS
    assert ".flow-track span:not(:last-child)::after" in PUBLIC_CSS
    assert "[class*=\"st-key-source_card_\"]" in PUBLIC_CSS
    assert ".st-key-generated_answer {" in PUBLIC_CSS
    assert "border-left:3px solid var(--ink)!important;border-radius:0!important;" in PUBLIC_CSS


def test_home_module_action_clearance_and_readable_text_scale_are_preserved():
    """Keep the book action above its inner page seam and ordinary UI copy legible."""
    from components.public_theme import PUBLIC_CSS

    book_frame = (APP.parent / "assets" / "rag-book-frame.svg").read_text(encoding="utf-8")

    assert "v368" in book_frame
    assert "M320 381v32" in book_frame
    assert "min-height:25rem;padding:4.2rem clamp(3.5rem,4.6vw,4.5rem) 3.7rem!important;" in PUBLIC_CSS
    assert "p,li {font-size:clamp(1.14rem,1.06rem + .2vw,1.3rem);line-height:1.65;color:var(--body);}" in PUBLIC_CSS
    assert "[data-testid=\"stButton\"] button {min-height:3rem;border-radius:4px;font-size:clamp(1.12rem,1.05rem + .15vw,1.24rem);" in PUBLIC_CSS


def test_workbench_typography_overrides_streamlit_default_small_text_nodes():
    from components.public_theme import PUBLIC_CSS

    assert '[data-testid="stMarkdownContainer"] p,' in PUBLIC_CSS
    assert '[data-testid="stMarkdownContainer"] li {font-size:clamp(1.14rem,1.06rem + .2vw,1.3rem)!important;' in PUBLIC_CSS
    assert '[data-testid="stButton"] button [data-testid="stMarkdownContainer"] p {color:inherit!important;font-size:clamp(1.12rem,1.05rem + .15vw,1.24rem)!important;line-height:1.25!important;}' in PUBLIC_CSS
    assert '[data-testid="stWidgetLabel"] p {font-size:1.12rem!important;line-height:1.45!important;}' in PUBLIC_CSS
    assert '[data-testid="stExpander"] summary p {font-size:1.14rem!important;' in PUBLIC_CSS
    assert '.home-snapshot {color:var(--muted);font-size:1.18rem;line-height:1.55;}' in PUBLIC_CSS


def test_corpus_image_references_have_readable_local_descriptions():
    from public_workbench import _replace_markdown_images

    content = '前文 ![流程图](../flow.png) <p align="center"><img src="../step.png" alt="执行步骤"/></p>'
    rendered = _replace_markdown_images(content)
    assert "原文配图「流程图」" in rendered
    assert "原文配图「执行步骤」" in rendered
    assert "图中文字未纳入检索" in rendered
    assert "<img" not in rendered and "<p align" not in rendered


def test_relative_corpus_links_point_to_the_pinned_official_source():
    from public_workbench import _rewrite_relative_source_links

    source_url = (
        "https://github.com/apache/dolphinscheduler/blob/"
        "a190201acffa03d199d4ca216288734a6513de3d/"
        "docs/docs/zh/guide/parameter/priority.md"
    )
    content = (
        "[内置参数](built-in.md) [本章](#priority) "
        "[官方发布](https://github.com/apache/dolphinscheduler/releases)"
    )
    rendered = _rewrite_relative_source_links(content, source_url)

    assert (
        "[内置参数](https://github.com/apache/dolphinscheduler/blob/"
        "a190201acffa03d199d4ca216288734a6513de3d/"
        "docs/docs/zh/guide/parameter/built-in.md)"
    ) in rendered
    assert f"[本章]({source_url}#priority)" in rendered
    assert "[官方发布](https://github.com/apache/dolphinscheduler/releases)" in rendered


def test_wide_layout_uses_full_main_column_and_unframed_back_arrow():
    from components.public_theme import PUBLIC_CSS

    assert "max-width:none!important;width:100%!important;margin:0!important;" in PUBLIC_CSS
    assert ".block-container {background:var(--paper);" in PUBLIC_CSS
    assert '[data-testid="stHeader"] {background:var(--paper);}' in PUBLIC_CSS
    assert '[data-testid="stSidebar"][aria-expanded="true"]' in PUBLIC_CSS
    assert "width:clamp(260px,17vw,330px)!important;" in PUBLIC_CSS
    assert '[data-testid="stSidebar"][aria-expanded="false"]' in PUBLIC_CSS
    assert "flex:0 0 0!important;" in PUBLIC_CSS
    assert '[class*="st-key-page_header_"] [data-testid="stColumn"] > [data-testid="stVerticalBlock"] {' in PUBLIC_CSS
    assert "min-height:2.35rem;display:flex;align-items:center;justify-content:center;" in PUBLIC_CSS
    assert '[class*="st-key-page_header_"] [data-testid="stMarkdownContainer"] {overflow:visible;display:flex;align-items:center;min-height:2.35rem;margin:0!important;' in PUBLIC_CSS
    assert '[class*="st-key-page_header_"] [data-testid="stMarkdownContainer"] p {margin:0!important;' in PUBLIC_CSS
    assert ".breadcrumb-separator {height:2.35rem;box-sizing:border-box;display:flex;align-items:center;justify-content:center;" in PUBLIC_CSS
    assert "font-size:clamp(1.14rem,1.06rem + .2vw,1.3rem);line-height:1.65" in PUBLIC_CSS
    assert "font-size:clamp(1.12rem,1.05rem + .15vw,1.24rem);font-weight:640" in PUBLIC_CSS
    assert "font-size:1.3rem;font-weight:560" in PUBLIC_CSS
    assert "grid-template-columns:repeat(5,minmax(0,1fr))" in PUBLIC_CSS
    assert ".status-cell {display:flex;flex-direction:column;justify-content:center;min-height:6.1rem;" in PUBLIC_CSS
    assert "background:transparent!important;color:var(--ink)!important;border:0!important;box-shadow:none!important;" in PUBLIC_CSS


def test_workbench_navigation_is_larger_and_content_has_no_forced_empty_viewport_height():
    from components.public_theme import PUBLIC_CSS

    assert ".breadcrumbs {font-size:1.2rem;" in PUBLIC_CSS
    assert ".breadcrumbs-current {height:2.35rem;" in PUBLIC_CSS
    assert "color:var(--ink);font-size:1.2rem;font-weight:740" in PUBLIC_CSS
    assert "[data-testid=\"stSidebar\"] [data-testid=\"stButton\"] button" in PUBLIC_CSS
    assert "font-size:1.3rem;font-weight:560" in PUBLIC_CSS
    assert '[data-testid="stWidgetLabel"] p {font-size:1.12rem!important;line-height:1.45!important;}' in PUBLIC_CSS
    assert 'width:100%!important;max-width:100%!important;flex-wrap:wrap!important;' in PUBLIC_CSS
    assert '.breadcrumbs-current {height:auto;min-height:2.35rem;}' in PUBLIC_CSS
    assert "margin:1.7rem 0 .85rem" in PUBLIC_CSS
    assert "[data-testid=\"stMainBlockContainer\"] > [data-testid=\"stVerticalBlock\"] {min-height:calc(100vh" not in PUBLIC_CSS
    assert ".block-container {background:var(--paper);max-width:none!important;width:100%!important;margin:0!important;box-sizing:border-box;\n  padding:3rem 1.25rem 1.5rem;overflow:visible;}" in PUBLIC_CSS
    assert "textarea::placeholder" in PUBLIC_CSS


def test_home_snapshot_follows_content_with_consistent_spacing(monkeypatch):
    _mock_client(monkeypatch)
    app = AppTest.from_file(APP, default_timeout=40).run()

    assert not app.exception
    assert any('class="home-snapshot"' in item.value for item in app.markdown)

    from components.public_theme import PUBLIC_CSS

    assert '[data-testid="stMainBlockContainer"] > [data-testid="stVerticalBlock"] {min-height:calc(100vh - 4.5rem);' not in PUBLIC_CSS
    assert '[data-testid="stMainBlockContainer"] > [data-testid="stVerticalBlock"] > [data-testid="stElementContainer"]:has(.home-snapshot) {' in PUBLIC_CSS
    assert "margin-top:1.15rem!important;border-top:1px solid var(--line);" in PUBLIC_CSS
    assert '[data-testid="stElementContainer"]:has(.home-snapshot) {\n  margin-top:auto!important' not in PUBLIC_CSS
    assert "@media (max-width:600px) {.status-grid {grid-template-columns:minmax(0,1fr);}" in PUBLIC_CSS
    assert ('[data-testid="stElementContainer"]:has(.home-snapshot) [data-testid="stMarkdownContainer"] {\n'
            '  margin:0!important;') in PUBLIC_CSS


def test_stale_navigation_state_recovers_to_home(monkeypatch):
    _mock_client(monkeypatch)
    app = AppTest.from_file(APP, default_timeout=40).run()
    app.session_state["official_nav"] = "removed page"
    app.run()

    assert not app.exception
    assert app.session_state["official_nav"] == "总览"
    assert [item.value for item in app.title] == ["研发知识版本服务与变更影响审查"]


def test_public_agent_change_and_review_are_session_local(monkeypatch):
    _mock_client(monkeypatch)
    first = AppTest.from_file(APP, default_timeout=40).run()
    _start_agent_request(first, "计划将全局参数优先级调整为最高，并找出要同步的资料。")
    assert not first.exception
    assert first.session_state["official_request_review"]["sandbox_only"] is True
    assert first.session_state["official_request_review"]["public_baseline_written"] is False
    assert "模型辅助核对建议" in {item.value for item in first.subheader}
    assert "依据引用片段，建议核对相关资料中的参数顺序。" in "\n".join(
        item.value for item in first.markdown
    )
    visible = "\n".join(item.value for item in list(first.markdown) + list(first.caption))
    assert "该章节说明参数优先级。" in visible
    assert "核对示例与运维说明是否同步。" in visible
    assert "尚未检查英文资料。" in visible
    assert "等待人工审核" in visible
    headings = [item.value for item in first.subheader]
    assert headings.index("模型辅助核对建议") < headings.index("优先核对的影响候选")
    next(button for button in first.button if button.label == "确认已审阅本次影响分析").click().run()
    assert first.session_state["official_review_decision"] == "reviewed"

    second = AppTest.from_file(APP, default_timeout=40).run()
    next(button for button in second.button if button.label == "发起变更审查").click().run()
    assert "official_request_review" not in second.session_state
    assert "official_review_decision" not in second.session_state


def test_agent_draft_survives_navigation_away_and_back(monkeypatch):
    _mock_client(monkeypatch)
    app = AppTest.from_file(APP, default_timeout=40).run()
    next(button for button in app.button if button.label == "发起变更审查").click().run()
    request = "把全局参数调整为最高优先级，并检查需要同步的资料。"
    app.text_area(key="official_change_request").set_value(request).run()
    next(button for button in app.button if button.label == "总览").click().run()
    next(button for button in app.button if button.label == "发起变更审查").click().run()

    assert not app.exception
    assert app.text_area(key="official_change_request").value == request

def test_public_agent_shows_explicit_document_reference_without_confirming_paragraph_impact(monkeypatch):
    _mock_client(monkeypatch)
    import public_workbench

    analyze = public_workbench._analyze_hypothetical

    def with_document_reference(client, selected, proposed):
        result = analyze(client, selected, proposed)
        result["confirmed_relations"] = [{
            "relation_type": "DOCUMENT_REFERENCE",
            "source_document_id": "3.4.3:en:proposals/dsip-107-implementation",
            "target_document_id": "3.4.3:en:proposals/dsip-107-proposal",
            "source_chunk_id": "3.4.3:en:proposals/dsip-107-implementation:2",
            "source_heading": "Purpose of the pull request",
            "source_url": "https://github.com/apache/dolphinscheduler/pull/18464",
            "source_excerpt": "This pull request is an independent part of DSIP #18454.",
        }]
        return result

    monkeypatch.setattr(public_workbench, "_analyze_hypothetical", with_document_reference)
    app = AppTest.from_file(APP, default_timeout=40).run()
    _start_agent_request(app)
    app.text_area(key="official_proposed_text").set_value("假设将启动参数提高到第一优先级。").run()
    next(button for button in app.button if button.label == "生成修改前后对照").click().run()
    assert not app.exception
    assert "已确认文档关联" in {item.value for item in app.subheader}
    visible = "\n".join(item.value for item in list(app.markdown) + list(app.caption))
    assert "independent part of DSIP #18454" in visible
    assert "https://github.com/apache/dolphinscheduler/pull/18464" in visible
    assert "不证明所选段落受影响" in visible
    assert "待核对资料" in visible
    assert "已确认关系" not in visible


def test_public_navigation_exposes_versions_sources_evaluation_and_limits(monkeypatch):
    _mock_client(monkeypatch)
    app = AppTest.from_file(APP, default_timeout=40).run()
    labels = {button.label for button in app.button}
    assert {"总览", "版本化知识检索", "版本与历史", "资料来源", "发起变更审查", "影响候选", "修改建议对照", "检索评测", "已知限制"} <= labels
    next(button for button in app.button if button.label == "检索评测").click().run()
    assert not app.exception
    visible = "\n".join(item.value for item in list(app.markdown) + list(app.caption) + list(app.subheader))
    assert "技术选型依据" in visible
    assert "字符哈希向量基线" in visible
    assert "BM25" in visible
    assert "Rerank" in visible
    assert "43 条可回答" in visible
    assert "双来源" in visible and "0/4" in visible


def test_benchmark_prefers_server_verified_v3_and_labels_old_numbers_historical(monkeypatch):
    _mock_client(monkeypatch)
    from services.public_knowledge_client import PublicKnowledgeClient

    monkeypatch.setattr(PublicKnowledgeClient, "workspace", lambda self: {
        "workspace": "Apache DolphinScheduler", "baseline_version": "3.4.2",
        "current_version": "3.4.3", "source_count": 132, "chunk_count": 1322,
        "retrieval_policy": "bm25", "retrieval_evaluation_status": "v3_validated",
        "retrieval_evaluation": {
            "name": "quality_v3", "policy": "bm25", "top_k": 5,
            "dev": {
                "question_count": 36, "answerable_count": 32, "no_answer_count": 4,
                "complete_source_count": 30, "multi_source_question_count": 8,
                "complete_multi_source_count": 6, "evidence_marker_found": 44,
                "evidence_marker_count": 48, "source_hit_at_5": 0.96875,
                "source_recall_at_5_macro": 0.953125, "mrr": 0.921875,
                "warm_search_p95_ms": 7.52,
            },
            "holdout": {
                "question_count": 36, "answerable_count": 32, "no_answer_count": 4,
                "complete_source_count": 27, "multi_source_question_count": 8,
                "complete_multi_source_count": 4, "evidence_marker_found": 37,
                "evidence_marker_count": 49, "source_hit_at_5": 0.875,
                "source_recall_at_5_macro": 0.859375, "mrr": 0.7604167,
                "warm_search_p95_ms": 7.02,
            },
        },
    })
    app = AppTest.from_file(APP, default_timeout=40).run()
    next(button for button in app.button if button.label == "检索评测").click().run()

    assert not app.exception
    visible = "\n".join(item.value for item in list(app.markdown) + list(app.caption) + list(app.subheader))
    assert "V3 当前扩充语料" in visible
    assert "27/32" in visible and "4/8" in visible and "37/49" in visible
    assert "历史选型（旧语料）" in visible
    assert "正在单独复评" not in visible


def test_benchmark_does_not_present_local_v3_as_current_without_matching_backend_release(monkeypatch):
    _mock_client(monkeypatch)
    app = AppTest.from_file(APP, default_timeout=40).run()
    next(button for button in app.button if button.label == "检索评测").click().run()
    visible = "\n".join(item.value for item in list(app.markdown) + list(app.caption) + list(app.subheader))

    assert not app.exception
    assert "V3 当前扩充语料" not in visible
    assert "历史选型（旧语料）" in visible


def test_verified_autoware_v3_exposes_cross_source_holdout_gap(monkeypatch):
    _mock_client(monkeypatch)
    from services.public_knowledge_client import PublicKnowledgeClient

    metrics = {
        "query_count": 11,
        "complete_required_sources_at_5": 0.9,
        "required_source_recall_at_5": 0.9167,
        "image_evidence_hit_at_5": 1.0,
        "image_evidence_hits": "2/2",
        "version_mismatch_count": 0,
        "no_answer_nonempty_candidate_rate": 1.0,
        "no_answer_cases": 1,
        "search_p95_ms": 3.6,
    }
    baseline = {**metrics, "image_evidence_hit_at_5": 0.0, "image_evidence_hits": "0/2"}
    monkeypatch.setattr(PublicKnowledgeClient, "workspace", lambda self: {
        "workspace": "Autoware", "repository": "autowarefoundation/autoware_universe",
        "current_version": "0.52.0", "source_count": 26, "chunk_count": 562,
        "retrieval_policy": "bm25_figure_ocr",
        "retrieval_evaluation_status": "autoware_retrieval_v3_validated",
        "retrieval_evaluation": {
            "name": "autoware_retrieval_v3", "policy": "bm25_figure_ocr", "top_k": 5,
            "metric_scope": "retrieval only; no LLM answer quality or hallucination claim",
            "dev": {**metrics, "query_count": 32, "complete_required_sources_at_5": 1.0,
                    "required_source_recall_at_5": 1.0, "image_evidence_hits": "3/4"},
            "holdout": metrics, "bm25_dev": baseline, "bm25_holdout": baseline,
        },
    })
    app = AppTest.from_file(APP, default_timeout=40).run()
    next(button for button in app.button if button.label == "检索评测").click().run()

    assert not app.exception
    assert any("跨资料问题未找齐全部必需来源" in item.value for item in app.warning)
    assert any("无答案问题仍返回了候选" in item.value for item in app.warning)
    assert any("Autoware V3 评测与失败案例" in item.value for item in app.markdown)


def test_quality_v1_benchmark_displays_current_bilingual_and_image_limits(monkeypatch):
    _mock_client(monkeypatch)
    from services.public_knowledge_client import PublicKnowledgeClient

    baseline = {
        "query_count": 31, "required_source_recall_at_5": 0.9143,
        "complete_required_sources_at_5": 0.8929, "mrr_at_5": 0.7319,
        "ndcg_at_5": 0.8071, "image_evidence_hit_at_5": 0.0,
        "image_evidence_hits": "0/3", "version_mismatch_count": 0,
        "no_answer_nonempty_candidate_rate": 1.0,
        "no_answer_nonempty_candidates": "3/3", "search_p95_ms": 46.687,
    }
    selected = {**baseline, "image_evidence_hit_at_5": 0.6667,
                "image_evidence_hits": "2/3", "search_p95_ms": 49.893,
                "mean_retrieval_operations_per_query": 2}
    monkeypatch.setattr(PublicKnowledgeClient, "workspace", lambda self: {
        "workspace": "Autoware", "repository": "autowarefoundation/autoware_universe",
        "current_version": "latest", "source_count": 1148, "chunk_count": 7927,
        "retrieval_policy": "bm25_figure_ocr",
        "retrieval_evaluation_status": "autoware_quality_v1_validated",
        "retrieval_evaluation": {
            "name": "autoware_quality_v1", "policy": "bm25_figure_ocr", "top_k": 5,
            "case_count": 82, "case_split_counts": {"dev": 51, "holdout": 31},
            "category_counts": {"single_fact": 46, "image_evidence": 6},
            "metric_scope": "retrieval candidate coverage only",
            "dev": {**baseline, "query_count": 51},
            "holdout": selected, "bm25_dev": {**baseline, "query_count": 51},
            "bm25_holdout": baseline,
        },
    })
    app = AppTest.from_file(APP, default_timeout=40).run()
    next(button for button in app.button if button.label == "检索评测").click().run()

    assert not app.exception
    visible = "\n".join(item.value for item in list(app.markdown) + list(app.caption) + list(app.subheader))
    assert "冻结双语题集" in visible
    assert "0/3" in visible and "2/3" in visible
    assert "不是模型误答率" in visible
    assert "不代表答案准确率" in visible
    assert "autoware_retrieval_v3_validated" not in visible


def test_accuracy_v2_benchmark_shows_current_strategy_and_rejected_candidate(monkeypatch):
    _mock_client(monkeypatch)
    from services.public_knowledge_client import PublicKnowledgeClient

    current = {
        "required_source_recall_at_5": 0.4,
        "complete_required_sources_at_5": 0.3,
        "required_source_recall_at_20": 0.58,
        "mrr_at_5": 0.2596,
        "ndcg_at_5": 0.3079,
        "explicit_version_mismatch_count": 0,
        "search_p95_ms": 52.779,
        "query_count": 45,
        "image_hit_count": 6,
        "image_case_count": 6,
        "answer_accuracy": None,
        "unanswerable_candidate_rate": 1.0,
    }
    candidate = {
        **current,
        "required_source_recall_at_5": 0.38,
        "required_source_recall_at_20": 0.5,
        "mrr_at_5": 0.2196,
        "ndcg_at_5": 0.2737,
        "search_p95_ms": 55.852,
    }
    monkeypatch.setattr(PublicKnowledgeClient, "workspace", lambda self: {
        "workspace": "Autoware", "repository": "autowarefoundation/autoware_universe",
        "current_version": "latest", "source_count": 1148, "chunk_count": 7927,
        "retrieval_policy": "bm25_figure_ocr",
        "retrieval_evaluation_status": "autoware_accuracy_v2_validated",
        "retrieval_evaluation": {
            "name": "autoware_accuracy_v2", "policy": "bm25_figure_ocr", "top_k": 5,
            "case_count": 90, "case_split_counts": {"dev": 45, "holdout": 45},
            "metric_scope": "retrieval source recall and ranking only",
            "dev": current, "holdout": current, "bm25_dev": current, "bm25_holdout": current,
            "candidate": {"policy": "hybrid_figure_ocr", "dev": candidate,
                          "holdout": candidate, "decision": "not_promoted",
                          "decision_reason": "候选跨语方向回退。"},
            "candidate_decision": "not_promoted",
            "interpretation": "not answer accuracy or production latency",
        },
        "change_review_evaluation": {
            "name": "autoware_accuracy_v2_agent", "case_count": 57,
            "holdout": {
                "bilingual": {"case_count": 28, "evidence_source_recall": 0.6364,
                              "complete_evidence_source_rate": 0.5652,
                              "retrieval_check_coverage_rate": 0.8161,
                              "retrieval_language_coverage_rate": 0.9107,
                              "complete_retrieval_case_rate": 0.7143,
                              "search_calls_mean": 6.0, "latency_p95_ms": 341.352},
                "zh": {"case_count": 28, "evidence_source_recall": 0.2727,
                       "complete_evidence_source_rate": 0.2609,
                       "retrieval_check_coverage_rate": 0.8621,
                       "retrieval_language_coverage_rate": 0.8571,
                       "complete_retrieval_case_rate": 0.8571,
                       "search_calls_mean": 3.0, "latency_p95_ms": 171.422},
            },
        },
    })
    app = AppTest.from_file(APP, default_timeout=40).run()
    next(button for button in app.button if button.label == "检索评测").click().run()
    visible = "\n".join(item.value for item in list(app.markdown) + list(app.caption) + list(app.subheader))

    assert not app.exception
    assert "当前 RAG 检索策略评测" in visible
    assert "BM25 + 已校对图片文字" in visible
    assert "Hybrid + 图片 OCR 候选未晋级" in visible
    assert "Agent 变更审查检索策略对比" in visible
    assert "来源标签是从 RAG 题集转移的检索锚点" in visible
    assert "约翻倍" in visible
    assert "不代表生成答案准确率" in visible
    assert "52.78 ms" in visible


def test_benchmark_shows_v4_bm25_and_rejected_image_candidate_tradeoff(monkeypatch):
    _mock_client(monkeypatch)
    from services.public_knowledge_client import PublicKnowledgeClient

    monkeypatch.setattr(PublicKnowledgeClient, "workspace", lambda self: {
        "workspace": "Apache DolphinScheduler", "current_version": "3.4.3",
        "source_count": 132, "chunk_count": 1322, "retrieval_policy": "bm25",
        "retrieval_evaluation_status": "v4_bm25_validated",
        "retrieval_evaluation": {
            "name": "quality_v4", "policy": "bm25", "top_k": 5,
            "interpretation": "Retrieval only.",
            "dev": {"question_count": 51, "complete_source_at_5": 0.7436,
                     "anchor_recall_at_5": 0.5510, "image_hit_at_5": 0.0,
                     "version_mismatch_count": 0, "no_answer_nonempty_candidate_rate": 1.0,
                     "warm_p95_ms": 9.83},
            "holdout": {"question_count": 53, "complete_source_at_5": 0.8571,
                         "anchor_recall_at_5": 0.7925, "image_hit_at_5": 0.0,
                         "version_mismatch_count": 0, "no_answer_nonempty_candidate_rate": 1.0,
                         "warm_p95_ms": 6.20},
        },
        "retrieval_experiment": {
            "name": "quality_v4_image_ocr_candidate", "status": "candidate_not_promoted",
            "candidate_policy": "bm25_figure_ocr",
            "decision_reason": "原文锚点召回下降 9.4 个百分点，超过 5 个百分点门槛。",
            "holdout_candidate": {"question_count": 53, "complete_source_at_5": 0.9184,
                                  "anchor_recall_at_5": 0.6981, "image_hit_at_5": 1.0,
                                  "warm_p95_ms": 8.33},
            "promotion_comparison": {"passed": False},
        },
    })

    app = AppTest.from_file(APP, default_timeout=40).run()
    next(button for button in app.button if button.label == "检索评测").click().run()
    visible = "\n".join(item.value for item in list(app.markdown) + list(app.caption) + list(app.subheader))

    assert not app.exception
    assert "V4 当前 BM25 基线" in visible
    assert "图片 OCR 候选未晋级" in visible
    assert "BM25（线上默认）" in visible
    assert "BM25 + 图片 OCR（实验候选）" in visible
    assert "原文锚点召回下降 9.4 个百分点" in visible


def test_relative_official_link_stays_on_commit_or_becomes_plain_text():
    from public_workbench import _rewrite_relative_source_links

    source = "https://github.com/apache/dolphinscheduler/blob/" + "a" * 40 + "/docs/docs/zh/guide/parameter/context.md"
    raw = "[安全章节](./global.md) [越界章节](../../../../../../../../another-repo/README.md) [外部](https://example.com/x)"
    visible = _rewrite_relative_source_links(raw, source)

    assert "[安全章节](https://github.com/apache/dolphinscheduler/blob/" in visible
    assert "越界章节" in visible
    assert "[越界章节](" not in visible
    assert "[外部](https://example.com/x)" in visible


def test_verified_consistency_notice_names_primary_basis_and_both_versions(monkeypatch):
    _mock_client(monkeypatch)
    from services.public_knowledge_client import PublicKnowledgeClient
    old = {**CHUNK, "version": "3.4.2", "source_url": "https://github.com/apache/dolphinscheduler/releases/tag/3.4.2"}
    note = {
        "kind": "verified_literal_value_difference", "document_key": CHUNK["document_key"],
        "heading": CHUNK["heading"], "parameter": "worker.threads", "values": ["1000", "500"],
        "message": "同一章节中有不同的明确值。", "sources": [
            {"version": "3.4.3", "locale": "zh-CN", "source_url": CHUNK["source_url"]},
            {"version": "3.4.2", "locale": "zh-CN", "source_url": old["source_url"]},
        ],
    }
    monkeypatch.setattr(PublicKnowledgeClient, "query_official", lambda self, question, **scope: {
        "answer": "当前片段记录 1000。", "sources": [dict(CHUNK)],
        "evidence": [dict(CHUNK), old], "status": "OK", "consistency_notes": [note],
    })
    app = AppTest.from_file(APP, default_timeout=40).run()
    next(button for button in app.button if button.label == "版本化知识检索").click().run()
    next(button for button in app.button if button.label == "生成带引用回答").click().run()
    assert not app.exception
    visible = "\n".join(item.value for item in list(app.markdown) + list(app.caption) + list(app.warning))
    assert "版本差异提醒" in visible
    assert "引用依据之一" in visible
    assert "3.4.2" in visible and "3.4.3" in visible
    assert "概率" not in visible


def test_agent_review_sections_remain_session_bound_after_navigation(monkeypatch):
    _mock_client(monkeypatch)
    app = AppTest.from_file(APP, default_timeout=40).run()
    _start_agent_request(app)
    assert not app.exception
    next(button for button in app.button if button.label == "影响候选").click().run()
    visible = "\n".join(item.value for item in list(app.markdown) + list(app.caption))
    assert "可能相关资料" in visible or "在 GitHub 查看固定版本来源" in visible
    next(button for button in app.button if button.label == "人工审核").click().run()
    assert app.session_state["official_request_review"]["sandbox_only"] is True
    next(button for button in app.button if button.label == "确认已审阅本次影响分析").click().run()
    assert app.session_state["official_review_decision"] == "reviewed"


def test_agent_stepper_marks_human_review_after_analysis(monkeypatch):
    _mock_client(monkeypatch)
    app = AppTest.from_file(APP, default_timeout=40).run()
    _start_agent_request(app)
    tracks = [item.value for item in app.markdown if 'review-steps' in item.value]
    assert any('class="current">3. 等待人工审核' in track for track in tracks)
    next(button for button in app.button if button.label == "确认已审阅本次影响分析").click().run()
    tracks = [item.value for item in app.markdown if 'review-steps' in item.value]
    assert any('class="done">3. 等待人工审核' in track for track in tracks)


def test_switching_source_resets_previous_unsent_draft(monkeypatch):
    _mock_client(monkeypatch)
    from services.public_knowledge_client import PublicKnowledgeClient
    second = {**CHUNK, "chunk_id": "3.4.3:zh:guide/parameter/priority:2",
              "heading": "启动参数", "content": "启动参数是第二优先级。"}
    monkeypatch.setattr(PublicKnowledgeClient, "document",
                        lambda self, document_id: [dict(CHUNK), second])
    app = AppTest.from_file(APP, default_timeout=40).run()
    _start_agent_request(app)
    app.text_area(key="official_proposed_text").set_value("上一个段落的未提交草案").run()
    app.selectbox(key="official_change_chunk").set_value(second["chunk_id"]).run()
    assert not app.exception
    assert app.text_area(key="official_proposed_text").value == second["content"]
    assert _state_get(app.session_state, "official_review_decision") is None


def test_about_page_exposes_separate_frontend_backend_and_asset_fingerprints(monkeypatch):
    _mock_client(monkeypatch)
    import public_workbench

    monkeypatch.setattr(public_workbench, "ui_build_revision", lambda: "a" * 40)
    from services.public_knowledge_client import PublicKnowledgeClient
    monkeypatch.setattr(PublicKnowledgeClient, "workspace", lambda self: {
        "workspace": "Autoware", "repository": "autowarefoundation/autoware_universe",
        "repositories": ["autowarefoundation/autoware_universe"],
        "build_revision": "b" * 40,
        "corpus_fingerprint": {"fingerprint_sha256": "c" * 64},
        "retrieval_config_fingerprint": "d" * 64,
        "evaluation_fingerprint": "e" * 64,
    })
    app = AppTest.from_file(APP, default_timeout=40).run()
    next(button for button in app.button if button.label == "系统说明").click().run()
    assert not app.exception
    assert any(item.label == "运行版本与资料指纹" for item in app.expander)
