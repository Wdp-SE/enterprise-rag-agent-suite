from __future__ import annotations

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
        "evidence": [dict(CHUNK)], "status": "OK", "consistency_notes": [],
    })
    monkeypatch.setattr(public_workbench, "_analyze_hypothetical", lambda client, selected, proposed_text: {
        "change": {"change_type": "MODIFIED"}, "selected_source": dict(CHUNK),
        "impacts": [{"relation": "suggested", "status": "SUGGESTED", "reason": "主题相关，需人工核验。", "evidence": dict(CHUNK)}],
        "confirmed_relations": [], "patch_candidate": {
            "before": CHUNK["content"], "proposed_after": proposed_text,
            "status": "REQUIRES_HUMAN_REVIEW",
        }, "sandbox_only": True, "public_baseline_written": False,
    })


def test_public_home_has_two_chinese_modules_and_no_case_labels(monkeypatch):
    _mock_client(monkeypatch)
    app = AppTest.from_file(APP, default_timeout=40).run()
    assert not app.exception
    assert [item.value for item in app.title] == ["版本可信研发知识与变更审查系统"]
    text = "\n".join(item.value for item in list(app.markdown) + list(app.caption))
    assert "Apache DolphinScheduler" in text
    assert "研发知识 RAG" in text and "变更审查 Agent" in text
    assert "Case A" not in text and "演示案例 A" not in text
    assert "Case B" not in text and "演示案例 B" not in text
    assert app.session_state["official_nav"] == "总览"
    assert "总览" in {button.label for button in app.button}


def test_public_rag_keeps_answer_before_real_cited_source(monkeypatch):
    _mock_client(monkeypatch)
    app = AppTest.from_file(APP, default_timeout=40).run()
    next(button for button in app.button if button.label == "版本检索与问答").click().run()
    assert not app.exception
    assert app.selectbox(key="official_language").value == "zh_preferred"
    assert app.selectbox(key="official_version").value == "3.4.3"
    next(button for button in app.button if button.label == "生成带引用回答").click().run()
    assert not app.exception
    text = "\n".join(item.value for item in list(app.markdown) + list(app.caption))
    assert {item.value for item in app.subheader} >= {"回答", "引用依据"}
    assert "查看官方原文" in text
    assert "[1] 参数优先级" in text
    assert "引用编号：[1]" in text
    assert "证据可信度" not in text


def test_public_rag_without_generation_shows_compact_evidence_fallback(monkeypatch):
    _mock_client(monkeypatch)
    from services.public_knowledge_client import PublicKnowledgeClient

    monkeypatch.setattr(PublicKnowledgeClient, "query_official", lambda self, question, **scope: {
        "answer": "N/A", "sources": [], "evidence": [dict(CHUNK)],
        "status": "GENERATION_NOT_CONFIGURED", "consistency_notes": [],
    })
    app = AppTest.from_file(APP, default_timeout=40).run()
    next(button for button in app.button if button.label == "版本检索与问答").click().run()
    next(button for button in app.button if button.label == "生成带引用回答").click().run()

    assert not app.exception
    visible = "\n".join(item.value for item in list(app.markdown) + list(app.caption) + list(app.info))
    assert "当前仅展示检索证据" in visible
    assert "[1] 参数优先级" in visible
    assert "检索候选" not in visible
    assert "仅查看检索证据" in {button.label for button in app.button}


def test_rag_and_agent_pages_offer_return_home_navigation(monkeypatch):
    _mock_client(monkeypatch)
    app = AppTest.from_file(APP, default_timeout=40).run()

    next(button for button in app.button if button.label == "版本检索与问答").click().run()
    assert "返回首页" in {button.label for button in app.button}
    next(button for button in app.button if button.label == "返回首页").click().run()
    assert app.session_state["official_nav"] == "总览"

    next(button for button in app.button if button.label == "新建变更审查").click().run()
    assert "返回首页" in {button.label for button in app.button}
    next(button for button in app.button if button.label == "返回首页").click().run()
    assert app.session_state["official_nav"] == "总览"


def test_review_subpage_returns_to_agent_then_home(monkeypatch):
    _mock_client(monkeypatch)
    app = AppTest.from_file(APP, default_timeout=40).run()
    next(button for button in app.button if button.label == "新建变更审查").click().run()
    app.text_area(key="official_proposed_text").set_value("假设将启动参数提高到第一优先级。").run()
    next(button for button in app.button if button.label == "开始变更审查").click().run()

    next(button for button in app.button if button.label == "人工审核").click().run()
    assert app.session_state["official_nav"] == "人工审核"
    assert "返回审查" in {button.label for button in app.button}
    assert "返回首页" in {button.label for button in app.button}

    next(button for button in app.button if button.label == "返回审查").click().run()
    assert app.session_state["official_nav"] == "新建变更审查"
    assert app.session_state["official_review"]["sandbox_only"] is True

    next(button for button in app.button if button.label == "返回首页").click().run()
    assert app.session_state["official_nav"] == "总览"


def test_workbench_theme_keeps_neutral_base_and_equal_home_cards():
    from components.public_theme import PUBLIC_CSS

    assert "--canvas:#f4f5f6" in PUBLIC_CSS
    assert "--ink:#171b20" in PUBLIC_CSS
    assert "background:var(--ink)!important" not in PUBLIC_CSS
    assert ".st-key-public_rag_module,.st-key-public_agent_module {" in PUBLIC_CSS
    assert "background:var(--paper)!important;color:var(--ink);" in PUBLIC_CSS
    assert "border:1px solid var(--line-strong)!important;border-radius:5px!important;" in PUBLIC_CSS
    assert ".st-key-generated_answer {" in PUBLIC_CSS


def test_stale_navigation_state_recovers_to_home(monkeypatch):
    _mock_client(monkeypatch)
    app = AppTest.from_file(APP, default_timeout=40).run()
    app.session_state["official_nav"] = "removed page"
    app.run()

    assert not app.exception
    assert app.session_state["official_nav"] == "总览"
    assert [item.value for item in app.title] == ["版本可信研发知识与变更审查系统"]


def test_public_agent_change_and_review_are_session_local(monkeypatch):
    _mock_client(monkeypatch)
    first = AppTest.from_file(APP, default_timeout=40).run()
    next(button for button in first.button if button.label == "新建变更审查").click().run()
    first.text_area(key="official_proposed_text").set_value("假设将启动参数提高到第一优先级。").run()
    next(button for button in first.button if button.label == "开始变更审查").click().run()
    assert not first.exception
    assert first.session_state["official_review"]["sandbox_only"] is True
    assert first.session_state["official_review"]["public_baseline_written"] is False
    next(button for button in first.button if button.label == "确认已审阅会话草案").click().run()
    assert first.session_state["official_review_decision"] == "reviewed"

    second = AppTest.from_file(APP, default_timeout=40).run()
    next(button for button in second.button if button.label == "新建变更审查").click().run()
    assert "official_review" not in second.session_state
    assert "official_review_decision" not in second.session_state

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
    next(button for button in app.button if button.label == "新建变更审查").click().run()
    app.text_area(key="official_proposed_text").set_value("假设将启动参数提高到第一优先级。").run()
    next(button for button in app.button if button.label == "开始变更审查").click().run()
    assert not app.exception
    assert "已确认文档关联" in {item.value for item in app.subheader}
    visible = "\n".join(item.value for item in list(app.markdown) + list(app.caption))
    assert "independent part of DSIP #18454" in visible
    assert "https://github.com/apache/dolphinscheduler/pull/18464" in visible
    assert "不证明所选段落受影响" in visible
    assert "建议核对" in visible
    assert "已确认关系" not in visible


def test_public_navigation_exposes_versions_sources_evaluation_and_limits(monkeypatch):
    _mock_client(monkeypatch)
    app = AppTest.from_file(APP, default_timeout=40).run()
    labels = {button.label for button in app.button}
    assert {"总览", "版本检索与问答", "版本与历史", "资料与来源", "新建变更审查", "可能相关资料", "修改前后对照", "检索评测", "已知限制"} <= labels
    next(button for button in app.button if button.label == "检索评测").click().run()
    assert not app.exception
    visible = "\n".join(item.value for item in list(app.markdown) + list(app.caption) + list(app.subheader))
    assert "技术选型依据" in visible
    assert "字符哈希向量基线" in visible
    assert "BM25" in visible
    assert "Rerank" in visible
    assert "43 条可回答" in visible
    assert "双来源" in visible and "0/4" in visible


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
    next(button for button in app.button if button.label == "版本检索与问答").click().run()
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
    next(button for button in app.button if button.label == "新建变更审查").click().run()
    app.text_area(key="official_proposed_text").set_value("假设将启动参数提高到第一优先级。").run()
    next(button for button in app.button if button.label == "开始变更审查").click().run()
    assert not app.exception
    next(button for button in app.button if button.label == "可能相关资料").click().run()
    visible = "\n".join(item.value for item in list(app.markdown) + list(app.caption))
    assert "建议核对" in visible or "可能相关" in visible
    next(button for button in app.button if button.label == "人工审核").click().run()
    assert app.session_state["official_review"]["sandbox_only"] is True
    next(button for button in app.button if button.label == "确认已审阅会话草案").click().run()
    assert app.session_state["official_review_decision"] == "reviewed"


def test_agent_stepper_marks_human_review_after_analysis(monkeypatch):
    _mock_client(monkeypatch)
    app = AppTest.from_file(APP, default_timeout=40).run()
    next(button for button in app.button if button.label == "新建变更审查").click().run()
    app.text_area(key="official_proposed_text").set_value("假设将启动参数提高到第一优先级。").run()
    next(button for button in app.button if button.label == "开始变更审查").click().run()
    tracks = [item.value for item in app.markdown if 'review-steps' in item.value]
    assert any('class="current">5. 人工审核' in track for track in tracks)
    next(button for button in app.button if button.label == "确认已审阅会话草案").click().run()
    tracks = [item.value for item in app.markdown if 'review-steps' in item.value]
    assert any('class="done">5. 人工审核' in track for track in tracks)


def test_switching_source_resets_previous_unsent_draft(monkeypatch):
    _mock_client(monkeypatch)
    from services.public_knowledge_client import PublicKnowledgeClient
    second = {**CHUNK, "chunk_id": "3.4.3:zh:guide/parameter/priority:2",
              "heading": "启动参数", "content": "启动参数是第二优先级。"}
    monkeypatch.setattr(PublicKnowledgeClient, "document",
                        lambda self, document_id: [dict(CHUNK), second])
    app = AppTest.from_file(APP, default_timeout=40).run()
    next(button for button in app.button if button.label == "新建变更审查").click().run()
    app.text_area(key="official_proposed_text").set_value("上一个段落的未提交草案").run()
    app.selectbox(key="official_change_chunk").set_value(second["chunk_id"]).run()
    assert not app.exception
    assert app.text_area(key="official_proposed_text").value == second["content"]
    assert app.session_state.get("official_review_decision") is None
