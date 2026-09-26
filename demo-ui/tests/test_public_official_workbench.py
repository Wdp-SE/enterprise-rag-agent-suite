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
    monkeypatch.setattr(PublicKnowledgeClient, "review_advice", lambda self, change_summary, evidence_chunk_ids: {
        "status": "OK", "answer": "依据引用片段，建议核对相关资料中的参数顺序。",
        "sources": [dict(CHUNK)] if CHUNK["chunk_id"] in evidence_chunk_ids else [],
        "evidence": [dict(CHUNK)] if CHUNK["chunk_id"] in evidence_chunk_ids else [],
    })
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
        },
    })


def _start_agent_request(app, summary="假设调整全局参数优先级，并找出需要核对的资料。"):
    if app.session_state.get("official_nav") != "新建变更审查":
        next(button for button in app.button if button.label == "发起变更审查").click().run()
    app.text_area(key="official_change_request").set_value(summary).run()
    next(button for button in app.button if button.label == "检索资料并分析影响").click().run()
    return app


def test_public_home_has_two_chinese_modules_and_no_case_labels(monkeypatch):
    _mock_client(monkeypatch)
    app = AppTest.from_file(APP, default_timeout=40).run()
    assert not app.exception
    assert [item.value for item in app.title] == ["研发知识版本服务与变更影响审查"]
    text = "\n".join(item.value for item in list(app.markdown) + list(app.caption))
    assert "Apache DolphinScheduler" in text
    assert "版本化研发知识服务 · RAG" in text
    assert "Agent · 研发资料变更审查" in text
    assert "研发资料变更影响审查" in text
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
    assert "查看官方原文" in text
    assert "[1] 参数优先级" in text
    assert "引用编号：[1]" in text
    assert "证据可信度" not in text


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
    assert calls == [(change_request, "3.4.3", "zh_preferred", 5)]
    assert app.session_state["official_request_review"]["request_summary"] == change_request
    assert app.session_state["official_request_review"]["impacts"][0]["evidence"]["chunk_id"] == CHUNK["chunk_id"]
    headings = [item.value for item in app.subheader]
    assert headings.index("模型辅助核对建议") < headings.index("可能相关资料")


def test_rag_suggested_question_is_muted_placeholder_and_used_when_submitted_blank(monkeypatch):
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

    question = app.text_area(key="official_question")
    assert question.value == ""
    assert question.placeholder == "DolphinScheduler 参数优先级从高到低是什么？"
    next(button for button in app.button if button.label == "生成带引用回答").click().run()

    assert not app.exception
    assert submitted == ["DolphinScheduler 参数优先级从高到低是什么？"]
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
    app.text_area(key="official_question").set_value("DolphinScheduler 健康检查接口是什么？").run()
    next(button for button in app.button if button.label == "生成带引用回答").click().run()

    assert not app.exception
    assert submitted == ["DolphinScheduler 健康检查接口是什么？"]


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
    assert "[图片：Apache DolphinScheduler]" in rendered
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
    assert "[图片：Apache DolphinScheduler]" in rendered
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
    assert "当前仅展示检索证据" in visible
    assert "start_prototype.ps1 -EnableGeneration" in visible
    assert "DASHSCOPE_API_KEY" in visible
    assert "DEEPSEEK_API_KEY" in visible
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
    assert "在线生成未完成或未通过引用核验" in visible
    assert "RAG 后端出网连接" in visible
    assert "[1] 参数优先级" in visible


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
    assert any("未设置固定生成次数上限" in caption for caption in captions)


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
    assert "RAG 后端无法连接模型服务" in visible
    assert "HTTPS 代理配置" in visible
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
    assert "检索证据仍保留" in visible

    next(button for button in app.button if button.label == "生成带引用回答").click().run()
    visible = "\n".join(item.value for item in list(app.markdown) + list(app.caption))
    assert "模型返回内容未满足引用回答要求" in visible
    assert "检索证据仍保留" in visible


def test_generated_answer_typography_is_large_and_readable():
    from components.public_theme import PUBLIC_CSS

    assert '.st-key-generated_answer [data-testid="stMarkdownContainer"] p {' in PUBLIC_CSS
    assert "font-size:1.3rem!important;line-height:1.75!important;" in PUBLIC_CSS
    assert ".st-key-generated_answer .citation-index {font-size:1.08rem!important;" in PUBLIC_CSS


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
    assert "font-size:clamp(1.08rem,1rem + .18vw,1.24rem);line-height:1.65" in PUBLIC_CSS


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
    assert "min-height:20.75rem;padding:3.8rem clamp(4rem,5vw,4.5rem) 3.25rem!important;" in PUBLIC_CSS
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
    assert "min-height:20.75rem;padding:3.8rem clamp(4rem,5vw,4.5rem) 3.25rem!important;" in PUBLIC_CSS
    assert "p,li {font-size:clamp(1.08rem,1rem + .18vw,1.24rem);line-height:1.65;color:var(--body);}" in PUBLIC_CSS
    assert "[data-testid=\"stButton\"] button {min-height:3rem;border-radius:4px;font-size:clamp(1.08rem,1rem + .15vw,1.2rem);" in PUBLIC_CSS


def test_corpus_image_references_have_readable_local_descriptions():
    from public_workbench import _replace_markdown_images

    content = '前文 ![流程图](../flow.png) <p align="center"><img src="../step.png" alt="执行步骤"/></p>'
    rendered = _replace_markdown_images(content)
    assert "[图片：流程图]" in rendered
    assert "[图片：执行步骤]" in rendered
    assert "<img" not in rendered and "<p align" not in rendered


def test_wide_layout_uses_full_main_column_and_unframed_back_arrow():
    from components.public_theme import PUBLIC_CSS

    assert "max-width:none!important;width:100%!important;margin:0!important;" in PUBLIC_CSS
    assert ".block-container {background:var(--paper);" in PUBLIC_CSS
    assert '[data-testid="stHeader"] {background:var(--paper);}' in PUBLIC_CSS
    assert '[data-testid="stSidebar"][aria-expanded="true"]' in PUBLIC_CSS
    assert "width:clamp(280px,19vw,360px)!important;" in PUBLIC_CSS
    assert '[data-testid="stSidebar"][aria-expanded="false"]' in PUBLIC_CSS
    assert "flex:0 0 0!important;" in PUBLIC_CSS
    assert '[class*="st-key-page_header_"] [data-testid="stColumn"] > [data-testid="stVerticalBlock"] {' in PUBLIC_CSS
    assert "min-height:2.35rem;display:flex;align-items:center;justify-content:center;" in PUBLIC_CSS
    assert '[class*="st-key-page_header_"] [data-testid="stMarkdownContainer"] {overflow:visible;display:flex;align-items:center;min-height:2.35rem;margin:0!important;' in PUBLIC_CSS
    assert '[class*="st-key-page_header_"] [data-testid="stMarkdownContainer"] p {margin:0!important;' in PUBLIC_CSS
    assert ".breadcrumb-separator {height:2.35rem;box-sizing:border-box;display:flex;align-items:center;justify-content:center;" in PUBLIC_CSS
    assert "font-size:clamp(1.08rem,1rem + .18vw,1.24rem);line-height:1.65" in PUBLIC_CSS
    assert "font-size:clamp(1.08rem,1rem + .15vw,1.2rem);font-weight:640" in PUBLIC_CSS
    assert "font-size:1.25rem;font-weight:560" in PUBLIC_CSS
    assert "grid-template-columns:1.3fr 1.05fr 1.1fr 1.2fr .95fr" in PUBLIC_CSS
    assert "background:transparent!important;color:var(--ink)!important;border:0!important;box-shadow:none!important;" in PUBLIC_CSS


def test_workbench_navigation_is_larger_and_content_has_no_forced_empty_viewport_height():
    from components.public_theme import PUBLIC_CSS

    assert ".breadcrumbs {font-size:1.2rem;" in PUBLIC_CSS
    assert ".breadcrumbs-current {height:2.35rem;" in PUBLIC_CSS
    assert "color:var(--ink);font-size:1.2rem;font-weight:740" in PUBLIC_CSS
    assert "[data-testid=\"stSidebar\"] [data-testid=\"stButton\"] button" in PUBLIC_CSS
    assert "font-size:1.25rem;font-weight:560" in PUBLIC_CSS
    assert 'width:100%!important;max-width:100%!important;flex-wrap:wrap!important;' in PUBLIC_CSS
    assert '.breadcrumbs-current {height:auto;min-height:2.35rem;}' in PUBLIC_CSS
    assert "margin:1.7rem 0 .85rem" in PUBLIC_CSS
    assert "[data-testid=\"stMainBlockContainer\"] > [data-testid=\"stVerticalBlock\"] {min-height:calc(100vh" not in PUBLIC_CSS
    assert ".block-container {background:var(--paper);max-width:none!important;width:100%!important;margin:0!important;box-sizing:border-box;\n  padding:3rem 1.65rem 1.5rem;overflow:visible;}" in PUBLIC_CSS
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
    headings = [item.value for item in first.subheader]
    assert headings.index("模型辅助核对建议") < headings.index("可能相关资料")
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
    assert "可能相关资料" in visible or "官方原文" in visible
    next(button for button in app.button if button.label == "人工审核").click().run()
    assert app.session_state["official_request_review"]["sandbox_only"] is True
    next(button for button in app.button if button.label == "确认已审阅本次影响分析").click().run()
    assert app.session_state["official_review_decision"] == "reviewed"


def test_agent_stepper_marks_human_review_after_analysis(monkeypatch):
    _mock_client(monkeypatch)
    app = AppTest.from_file(APP, default_timeout=40).run()
    _start_agent_request(app)
    tracks = [item.value for item in app.markdown if 'review-steps' in item.value]
    assert any('class="current">5. 人工审核' in track for track in tracks)
    next(button for button in app.button if button.label == "确认已审阅本次影响分析").click().run()
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
    _start_agent_request(app)
    app.text_area(key="official_proposed_text").set_value("上一个段落的未提交草案").run()
    app.selectbox(key="official_change_chunk").set_value(second["chunk_id"]).run()
    assert not app.exception
    assert app.text_area(key="official_proposed_text").value == second["content"]
    assert app.session_state.get("official_review_decision") is None
