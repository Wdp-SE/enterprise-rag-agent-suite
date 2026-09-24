"""Public knowledge and hypothetical change-review workbench."""

from __future__ import annotations

import json
import os
import sys
import uuid
from pathlib import Path
from html import escape

import streamlit as st

from components.public_theme import PUBLIC_CSS
from services.public_knowledge_client import PublicKnowledgeClient
from services.rag_client import ServiceError


CSS = PUBLIC_CSS


def _setting(name: str, fallback: str) -> str:
    value = os.environ.get(name)
    if value is not None:
        return value
    try:
        return str(st.secrets.get(name, fallback))
    except Exception:
        return fallback


def _client() -> PublicKnowledgeClient:
    session_id = st.session_state.setdefault("official_session_id", uuid.uuid4().hex)
    return PublicKnowledgeClient(
        _setting("RAG_API_BASE_URL", "http://127.0.0.1:8765"),
        timeout=float(_setting("DEMO_REQUEST_TIMEOUT_SECONDS", "45")),
        session_id=session_id,
        retry_limit=int(_setting("RAG_RETRY_LIMIT", "1")),
    )


def _request(call, *, fallback: str):
    try:
        return call()
    except ServiceError as exc:
        st.warning(f"{fallback} {exc.public_message}")
    except Exception:
        st.warning(fallback)
    return None


def _remember_document_titles(docs: list[dict]) -> None:
    titles = st.session_state.setdefault("official_document_titles", {})
    titles.update({row["document_id"]: row.get("title") or row.get("document_key", "")
                   for row in docs if row.get("document_id")})


def _source_card(row: dict, *, index: int) -> None:
    section = row.get("heading") or "正文"
    document_title = st.session_state.get("official_document_titles", {}).get(row.get("document_id")) or row.get("document_key") or "官方资料"
    version = row.get("version", "")
    version_label = "当前版本" if version == "3.4.3" else "历史版本"
    source_label = {
        "official_documentation": "官方文档",
        "github_release": "官方 Release",
        "github_issue": "官方 Issue",
        "github_pull_request": "官方 PR",
    }.get(row.get("source_type"), "官方公开资料")
    with st.container(border=True, key=f"source_card_{index}"):
        st.markdown(f"**[{index}] {document_title}**")
        st.caption(f"章节：{section}　｜　{version_label} {version}　｜　{row.get('locale', '')}　｜　{source_label}")
        content = row.get("content", "")
        st.write(content[:340] + ("…" if len(content) > 340 else ""))
        if row.get("source_url"):
            st.markdown(f"[查看官方原文]({row['source_url']})")
        if len(content) > 340:
            with st.expander("展开完整命中片段"):
                st.write(content)
        with st.expander("技术详情"):
            st.code(f"document_key={row.get('document_key', '')}\nchunk_id={row.get('chunk_id', '')}\npolicy={row.get('retrieval_policy', '')}")
            if "retrieval_score" in row:
                st.caption(f"候选排序分数：{row['retrieval_score']:.4f}。该分数仅用于当前检索策略下的结果排序，不代表事实正确性。")


def _evidence(hits: list[dict], *, heading: str = "引用依据") -> None:
    st.subheader(heading)
    if not hits:
        st.info("当前范围内未找到可直接支持答案的官方资料。请调整问题或检索范围。")
        return
    for index, row in enumerate(hits[:3], 1):
        _source_card(row, index=index)
    if len(hits) > 3:
        with st.expander(f"查看更多结果（{len(hits) - 3}）"):
            for index, row in enumerate(hits[3:], 4):
                _source_card(row, index=index)


def _consistency(notes: list[dict], *, primary: dict | None = None) -> None:
    if not notes:
        return
    st.caption("版本差异提醒")
    if primary:
        st.markdown(
            f"**当前回答引用依据之一：** {primary.get('heading') or primary.get('document_key')} "
            f"（{primary.get('version', '版本未标注')}，{primary.get('locale', '语言未标注')}）。"
        )
    else:
        st.caption("本次未生成可核验回答；下列差异只说明资料文字或明确参数值不同。")
    st.caption("资料差异不自动等于事实冲突；请对照来源版本，人工确认相关资料是否已同步。")
    for note in notes:
        with st.container(border=True):
            st.markdown(f"**{note.get('heading') or note.get('document_key')}**")
            st.write(note.get("message", "请核对固定版本的官方原文。"))
            if note.get("kind") == "verified_literal_value_difference":
                values = " / ".join(str(value) for value in note.get("values", []))
                st.markdown(f"明确字面值：`{note.get('parameter', '参数')}` → **{values}**")
            for source in note.get("sources", []):
                st.markdown(
                    f"- [{source.get('version', '版本未标注')} · {source.get('locale', '语言未标注')} · 查看官方来源]"
                    f"({source.get('source_url', '')})"
                )


def _navigate(destination: str) -> None:
    st.session_state["official_nav"] = destination


def _page_header(section: str, title: str, *, page_key: str) -> None:
    breadcrumb, home = st.columns([5, 1], gap="small")
    with breadcrumb:
        st.markdown(
            f'<div class="breadcrumbs">首页　/　<strong>{escape(section)}</strong></div>',
            unsafe_allow_html=True,
        )
    with home:
        st.button("返回首页", key=f"return_home_{page_key}", on_click=_navigate,
                  args=("总览",), use_container_width=True)
    st.title(title)


def _home(ready: bool, workspace: dict | None) -> None:
    baseline = workspace.get("baseline_version", "3.4.2") if workspace else "3.4.2"
    current = workspace.get("current_version", "3.4.3") if workspace else "3.4.3"
    st.markdown('<div class="masthead"><span class="kicker">公开研发资料 / 固定版本知识空间</span></div>', unsafe_allow_html=True)
    st.title("版本可信研发知识与变更审查系统")
    st.write("基于 Apache DolphinScheduler 官方公开资料，提供版本感知的研发知识检索、引用溯源与假设变更审查。")
    st.markdown(
        '<div class="public-note">独立工程演示，并非 Apache 官方产品。假设变更仅保留在当前会话，不修改上游项目或公共资料。</div>',
        unsafe_allow_html=True,
    )
    state = "已连接" if ready else "等待连接"
    status = [
        ("知识空间", "Apache DolphinScheduler"),
        ("资料性质", "官方公开资料"),
        ("固定版本", f"{baseline} → {current}"),
        ("语言", "中文优先 / English"),
        ("服务状态", state),
    ]
    cells = "".join(
        f'<div class="status-cell"><span class="status-label">{escape(label)}</span>'
        f'<span class="status-value">{escape(value)}</span></div>'
        for label, value in status
    )
    st.markdown(f'<div class="status-grid">{cells}</div>', unsafe_allow_html=True)
    left, right = st.columns(2, gap="medium")
    with left:
        with st.container(border=True, key="public_rag_module"):
            st.markdown('<span class="module-label">研发知识 RAG / 知识服务</span>', unsafe_allow_html=True)
            st.markdown("### 版本检索与问答")
            st.write("查当前与历史版本，核对中英文官方原文、引用依据与资料差异。")
            st.caption("版本范围 · 检索问答 · 原文溯源 · 版本差异")
            st.button("进入版本检索与问答", type="primary", use_container_width=True,
                      on_click=_navigate, args=("版本检索与问答",))
    with right:
        with st.container(border=True, key="public_agent_module"):
            st.markdown('<span class="module-label">变更审查 Agent / 人工决策辅助</span>', unsafe_allow_html=True)
            st.markdown("### 假设变更审查")
            st.write("从真实研发资料提出会话内假设变更，查找可能相关的资料并人工审核。")
            st.caption("输入假设 · 相关资料 · 引用依据 · 修改前后对照")
            st.button("新建变更审查", type="primary", use_container_width=True,
                      on_click=_navigate, args=("新建变更审查",))
    st.markdown('<div class="section-rule">从资料到人工审核</div>', unsafe_allow_html=True)
    st.markdown(
        '<div class="flow-track"><span>公开研发资料</span><span>检索与问答</span>'
        '<span>版本与引用核对</span><span>假设变更</span>'
        '<span>可能相关资料</span><span>人工审核</span></div>',
        unsafe_allow_html=True,
    )
    if workspace:
        st.caption(f"当前快照：{workspace['source_count']} 份官方资料、{workspace['chunk_count']} 个检索片段；检索策略以真实评测结果为准。")


def _use_example() -> None:
    st.session_state["official_question"] = st.session_state["official_example"]


def _knowledge(client: PublicKnowledgeClient, ready: bool, workspace: dict | None) -> None:
    _page_header("知识检索", "版本检索与问答", page_key="knowledge")
    st.caption("先确定资料范围，再提出问题；回答下方始终保留可核对的官方来源。")
    current = workspace.get("current_version", "3.4.3") if workspace else "3.4.3"
    default_policy = str(workspace.get("retrieval_policy", "由服务配置") if workspace else "由服务配置").upper()
    st.markdown(
        f'<div class="context-strip"><span><strong>知识空间</strong> Apache DolphinScheduler</span>'
        f'<span><strong>资料</strong> 官方公开资料</span>'
        f'<span><strong>默认版本</strong> {escape(current)}</span>'
        f'<span><strong>默认检索</strong> {escape(default_policy)}</span></div>',
        unsafe_allow_html=True,
    )
    with st.container(border=True, key="knowledge_scope"):
        a, b, c = st.columns([1, 1, .9], gap="medium")
        with a:
            version = st.selectbox(
                "版本范围", ["3.4.3", "3.4.2", "all"],
                format_func=lambda x: "全部固定版本" if x == "all" else f"{x} · {'当前版本' if x == '3.4.3' else '历史版本'}",
                key="official_version",
            )
        with b:
            language = st.selectbox(
                "资料语言", ["zh_preferred", "all", "zh", "en"],
                format_func=lambda x: {"zh_preferred": "中文优先", "all": "全部官方资料", "zh": "中文", "en": "English"}[x],
                key="official_language",
            )
        with c:
            st.markdown("**资料类型**")
            st.caption("官方文档 / Release / DSIP / PR")
            st.caption("范围由固定版本与语言共同限定")
    examples = [
        "DolphinScheduler 参数优先级从高到低是什么？",
        "3.4.3 的 missed_fire_policy 对旧 schedule 默认什么？",
        "What is the API server health-check endpoint?",
    ]
    with st.expander("从官方资料选择示例问题"):
        st.selectbox("示例问题", examples, key="official_example", on_change=_use_example)
    st.markdown('<div class="section-rule">提出问题</div>', unsafe_allow_html=True)
    question = st.text_area("你的问题", value=examples[0], height=100, key="official_question")
    generate_col, search_col = st.columns([1, 1], gap="small")
    with generate_col:
        ask_now = st.button("生成带引用回答", type="primary", disabled=not ready or not question.strip(), use_container_width=True)
    with search_col:
        search_now = st.button("仅查看检索证据", disabled=not ready or not question.strip(), use_container_width=True)
    budget_limit = int(_setting("MAX_LLM_CALLS_PER_SESSION", "3"))
    remaining = budget_limit - st.session_state.get("official_generation_calls", 0)
    if remaining <= 0:
        st.caption("本次会话的生成次数已用完，仍可继续检索官方资料。")
    if ask_now:
        if remaining <= 0:
            st.caption("本次会话的生成次数已用完；请使用“仅查看检索证据”。")
        else:
            with st.spinner("正在检索官方资料并核对引用……"):
                payload = _request(lambda: client.query_official(question, version=version, language=language), fallback="知识问答暂不可用。")
            if payload:
                if payload.get("status") not in ("GENERATION_NOT_CONFIGURED", "NO_EVIDENCE"):
                    st.session_state["official_generation_calls"] = budget_limit - remaining + 1
                st.session_state["official_result"] = ("query", question, version, language, payload)
    if search_now:
        with st.spinner("正在检索官方资料……"):
            payload = _request(lambda: client.search(question, version=version, language=language), fallback="资料检索暂不可用。")
        if payload:
            st.session_state["official_result"] = ("search", question, version, language, payload)
    result = st.session_state.get("official_result")
    if result and result[1:4] == (question, version, language):
        if ready and "official_document_titles" not in st.session_state:
            docs = _request(client.documents, fallback="来源目录暂不可用，仍可查看原文链接。")
            if docs is not None:
                _remember_document_titles(docs)
        mode, _, _, _, payload = result
        st.markdown('<div class="section-rule">结果与核验</div>', unsafe_allow_html=True)
        if mode == "query":
            st.subheader("回答")
            sources = payload.get("sources") or []
            if payload.get("status") == "OK" and sources:
                with st.container(border=True, key="generated_answer"):
                    st.write(payload["answer"])
                    citation_numbers = "　".join(f"[{index}]" for index in range(1, len(sources) + 1))
                    st.markdown(f'<span class="citation-index">引用编号：{citation_numbers}</span>', unsafe_allow_html=True)
            else:
                if payload.get("status") == "NO_EVIDENCE":
                    st.caption("当前范围内没有找到足够相关的资料；请调整问题或扩大版本范围。")
                elif payload.get("status") == "GENERATION_NOT_CONFIGURED":
                    st.caption("当前仅展示检索证据；此环境尚未配置在线生成。")
                else:
                    st.caption("未能生成通过引用校验的回答；下方只展示检索证据，请自行核对原文。")
            primary = sources[0] if sources else None
            _consistency(payload.get("consistency_notes", []), primary=primary)
            st.caption("引用可追溯到原文，但不代表回答中的每句话自动正确。")
            hits = sources if payload.get("status") == "OK" else payload.get("evidence", [])
            _evidence(hits, heading="引用依据" if payload.get("status") == "OK" else "检索到的官方资料")
        else:
            st.subheader("检索到的官方资料")
            st.caption("以下内容按真实检索顺序排列；请通过版本、章节与官方原文核对。")
            _consistency(payload.get("consistency_notes", []))
            _evidence(payload.get("results", []), heading="检索证据")
        with st.expander("本次检索技术详情"):
            st.write(f"固定版本范围：{version} · 语言：{language} · 默认策略：{payload.get('retrieval_policy', '由服务配置')}")
            st.caption("候选排序分数只用于同一检索策略内的排序，不代表事实正确性。")
    if not ready:
        st.info("知识服务可能正在冷启动；资料范围会在连接恢复后显示，请稍后刷新。")


def _analyze_hypothetical(client: PublicKnowledgeClient, selected: dict, proposed: str) -> dict:
    agent_root = Path(__file__).resolve().parents[1] / "OpenManus-rag"
    if str(agent_root) not in sys.path:
        sys.path.insert(0, str(agent_root))
    from app.public_review import PublicReviewAgent
    return PublicReviewAgent(client).analyze(selected, proposed)


def _review_steps(stage: int) -> None:
    labels = ("输入假设", "可能相关资料", "引用依据", "修改前后对照", "人工审核")
    cells = "".join(
        f'<span class="{"done" if i < stage else "current" if i == stage else ""}">'
        f'{i + 1}. {escape(label)}</span>'
        for i, label in enumerate(labels)
    )
    st.markdown(f'<div class="review-steps">{cells}</div>', unsafe_allow_html=True)


def _impact_panel(result: dict) -> None:
    st.subheader("可能相关资料")
    st.caption("这些资料由检索发现，仅供核对；当前没有自动确认实际影响。")
    references = result.get("confirmed_relations", [])
    if references:
        st.subheader("已确认文档关联")
        st.caption("官方 PR 明确引用 DSIP，仅确认两份文档有关联；不证明所选段落受影响。")
        for reference in references:
            with st.container(border=True):
                st.markdown("**官方实现 PR #18464 → DSIP #18454**")
                st.caption(f"明确引用所在章节：{reference['source_heading']}")
                excerpt = reference["source_excerpt"]
                st.write(excerpt[:300] + ("…" if len(excerpt) > 300 else ""))
                st.markdown(f"[查看明确引用的官方原文]({reference['source_url']})")
                if len(excerpt) > 300:
                    with st.expander("查看完整引用原文"):
                        st.write(excerpt)
    impacts = result.get("impacts", [])
    if not impacts:
        st.info("未检索到足够相关的其他资料；仍可人工审核当前段落。")
        return
    for item in impacts:
        evidence = item["evidence"]
        with st.container(border=True):
            st.markdown(f"**建议核对 · {evidence.get('heading') or evidence.get('document_key')}**")
            st.caption(f"{evidence.get('version', '')}　｜　{evidence.get('locale', '')}　｜　可能受影响")
            st.write(item.get("reason", "请核对官方原文与显式引用。"))
            content = evidence.get("content", "")
            st.write(content[:300] + ("…" if len(content) > 300 else ""))
            st.markdown(f"[查看官方原文]({evidence['source_url']})")
            if len(content) > 300:
                with st.expander("查看完整相关片段"):
                    st.write(content)


def _review_evidence_panel(result: dict) -> None:
    st.subheader("引用依据")
    st.caption("以下是本次假设变更的官方原文起点；其他可能相关资料列在相应页面。")
    _source_card(result["selected_source"], index=1)


def _patch_panel(result: dict) -> None:
    st.subheader("修改前后对照")
    st.caption("右侧是你输入的会话内假设草案，不是自动生成或已批准的修改。官方原文不会被覆盖。")
    before, after = result["patch_candidate"]["before"], result["patch_candidate"]["proposed_after"]
    left, right = st.columns(2, gap="medium")
    with left:
        with st.container(border=True):
            st.markdown("**当前官方原文**")
            st.write(before[:450] + ("…" if len(before) > 450 else ""))
    with right:
        with st.container(border=True):
            st.markdown("**会话内假设草案**")
            st.write(after[:450] + ("…" if len(after) > 450 else ""))
    if len(before) > 450 or len(after) > 450:
        with st.expander("查看完整修改前后内容"):
            st.markdown("**当前官方原文**")
            st.write(before)
            st.markdown("**会话内假设草案**")
            st.write(after)


def _set_review_decision(decision: str) -> None:
    st.session_state["official_review_decision"] = decision


def _clear_stale_review() -> None:
    st.session_state.pop("official_review", None)
    st.session_state.pop("official_review_decision", None)


def _review_panel(result: dict) -> None:
    st.subheader("人工审核")
    st.caption("审核只记录本次会话的决定，不创建公开候选版本，也不修改公共资料。")
    approve, reject = st.columns(2)
    approve.button("确认已审阅会话草案", use_container_width=True,
                   on_click=_set_review_decision, args=("reviewed",))
    reject.button("退回会话草案", use_container_width=True,
                  on_click=_set_review_decision, args=("rejected",))
    decision = st.session_state.get("official_review_decision")
    if decision == "reviewed":
        st.success("已记录本次会话的人工审核结果。未创建候选版本，公共基线未修改。")
    elif decision == "rejected":
        st.info("会话草案已退回。公共基线未修改。")


def _agent(client: PublicKnowledgeClient, ready: bool, docs: list[dict]) -> None:
    _page_header("变更审查", "假设变更审查", page_key="agent")
    st.caption("从真实官方资料提出局部假设，发现可能相关的资料，最终由人核对。")
    st.info("本次为会话内假设变更审查，不修改 Apache DolphinScheduler 上游项目或公共资料。")
    _remember_document_titles(docs)
    current_docs = [row for row in docs if row["version"] == "3.4.3"]
    if not current_docs:
        _review_steps(0)
        st.warning("当前官方资料目录尚未加载，请等待知识服务启动。")
        return
    options = {row["document_id"]: row for row in current_docs}
    left, right = st.columns(2, gap="medium")
    with left:
        document_id = st.selectbox(
            "选择真实研发资料", list(options), key="official_change_document",
            format_func=lambda key: (
                f"{options[key]['title']} · "
                f"{ {'github_issue': '官方 Issue', 'github_pull_request': '官方 PR', 'github_release': '官方 Release', 'official_documentation': '官方文档'}.get(options[key].get('source_type'), '官方资料')} · "
                f"{options[key]['locale']} · {options[key]['version']}"
            ),
        )
    chunks = _request(lambda: client.document(document_id), fallback="所选文档暂未加载。") if ready else None
    if not chunks:
        _review_steps(0)
        return
    by_id = {row["chunk_id"]: row for row in chunks}
    with right:
        chunk_id = st.selectbox(
            "选择要审查的段落", list(by_id), key="official_change_chunk",
            format_func=lambda key: f"{by_id[key]['heading'] or '正文'} · 第 {list(by_id).index(key)+1} 段",
        )
    selected = by_id[chunk_id]
    if st.session_state.get("official_draft_source_id") != chunk_id:
        st.session_state["official_draft_source_id"] = chunk_id
        st.session_state["official_proposed_text"] = selected["content"]
        _clear_stale_review()
    result = st.session_state.get("official_review")
    active_result = result if result and result["selected_source"]["chunk_id"] == chunk_id else None
    stage = 5 if st.session_state.get("official_review_decision") and active_result else 4 if active_result else 0
    _review_steps(stage)
    with st.expander("查看当前官方原文与固定来源"):
        st.write(selected["content"])
        st.markdown(f"[查看官方来源]({selected['source_url']})")
    proposed = st.text_area("假设修改后的内容", height=190,
                            key="official_proposed_text", on_change=_clear_stale_review)
    st.caption("可修改参数值、配置或行为描述；仅在当前会话内分析，不上传或覆盖官方资料。")
    if st.button("开始变更审查", type="primary", disabled=not ready or proposed.strip() == selected["content"].strip()):
        with st.spinner("正在比较变化并检索可能相关的官方资料……"):
            result = _request(lambda: _analyze_hypothetical(client, selected, proposed), fallback="变更分析暂未完成。")
        if result:
            st.session_state["official_review"] = result
            st.session_state["official_review_decision"] = None
            active_result = result
            st.rerun()
    if not active_result:
        return
    st.markdown('<div class="section-rule">会话审查结果</div>', unsafe_allow_html=True)
    _impact_panel(active_result)
    _review_evidence_panel(active_result)
    _patch_panel(active_result)
    _review_panel(active_result)


def _review_subpage(choice: str) -> None:
    _page_header("变更审查", choice, page_key=choice)
    result = st.session_state.get("official_review")
    if not result:
        st.info("当前会话还没有假设变更审查结果。请先选择真实资料并提交假设修改。")
        st.button("返回新建变更审查", on_click=_navigate, args=("新建变更审查",))
        return
    st.caption("以下内容仅属于当前会话；已确认引用关系与检索建议会明确区分。")
    if choice == "可能相关资料":
        _impact_panel(result)
    elif choice == "修改前后对照":
        _patch_panel(result)
    else:
        _review_panel(result)


def _versions(client: PublicKnowledgeClient, ready: bool, workspace: dict | None) -> None:
    st.markdown('<div class="masthead"><span class="kicker">知识服务 / 固定版本</span></div>', unsafe_allow_html=True)
    st.title("版本与历史")
    st.write("公开知识空间固定在相邻的官方发布版本。历史资料不会被当成当前版本静默引用。")
    if not ready:
        st.info("知识服务暂不可用，连接恢复后可查看各版本的真实资料。")
        return
    docs = _request(client.documents, fallback="版本资料目录暂不可用。") or []
    baseline = workspace.get("baseline_version", "3.4.2") if workspace else "3.4.2"
    current = workspace.get("current_version", "3.4.3") if workspace else "3.4.3"
    first, second = st.columns(2, gap="medium")
    for column, version, label in ((first, baseline, "历史基线"), (second, current, "当前版本")):
        with column:
            with st.container(border=True):
                st.markdown(f"### {version}　{label}")
                matching = [row for row in docs if row.get("version") == version]
                st.write(f"本工作台固定收录 {len(matching)} 份该版本资料。")
                for row in matching[:5]:
                    st.markdown(f"- [{row.get('title') or row['document_key']}]({row['source_url']})")
                if len(matching) > 5:
                    with st.expander(f"查看其余 {len(matching)-5} 份资料"):
                        for row in matching[5:]:
                            st.markdown(f"- [{row.get('title') or row['document_key']}]({row['source_url']})")
    st.info("需要对照两个版本的内容时，在“版本检索与问答”中选择“全部固定版本”；版本差异提醒只报告可核验的文字差异。")
    st.button("进入版本检索与问答", on_click=_navigate, args=("版本检索与问答",))


def _sources(client: PublicKnowledgeClient, ready: bool) -> None:
    st.markdown('<div class="masthead"><span class="kicker">知识服务 / 资料归属</span></div>', unsafe_allow_html=True)
    st.title("资料与来源")
    st.write("本工作台使用 Apache DolphinScheduler 官方公开资料；每条结果均保留固定版本与原文链接。")
    st.caption("独立工程演示，并非 Apache 官方产品；英文官方资料不会被自动翻译成中文原文。")
    if not ready:
        st.info("知识服务暂不可用，资料目录将在连接恢复后显示。")
        return
    docs = _request(client.documents, fallback="官方资料目录暂不可用。") or []
    version = st.selectbox("资料版本", ["all", "3.4.3", "3.4.2"], format_func=lambda x: "全部固定版本" if x == "all" else x, key="source_version")
    term = st.text_input("按资料名称或工程标识筛选", key="source_filter")
    filtered = [
        row for row in docs
        if (version == "all" or row.get("version") == version)
        and term.casefold() in (row.get("title", "") + " " + row.get("document_key", "")).casefold()
    ]
    st.caption(f"当前条件下有 {len(filtered)} 份固定来源资料。")
    kind = {
        "official_documentation": "官方文档",
        "github_release": "官方 Release",
        "github_issue": "官方 Issue",
        "github_pull_request": "官方 PR",
    }
    for row in filtered[:12]:
        with st.container(border=True):
            st.markdown(f"**{row.get('title') or row['document_key']}**")
            st.caption(f"{row.get('version', '')}　｜　{row.get('locale', '')}　｜　{kind.get(row.get('source_type'), '官方资料')}")
            st.markdown(f"[查看固定版本官方原文]({row['source_url']})")
    if len(filtered) > 12:
        with st.expander(f"查看其余 {len(filtered)-12} 份资料"):
            for row in filtered[12:]:
                st.markdown(f"- [{row.get('title') or row['document_key']}]({row['source_url']})")


def _benchmark(workspace: dict | None) -> None:
    st.markdown('<div class="masthead"><span class="kicker">系统说明 / 实测决策</span></div>', unsafe_allow_html=True)
    st.title("检索评测")
    st.subheader("技术选型依据")
    st.write("检索策略由真实 Benchmark 指标决定，而不是按照技术复杂度选择。")
    policy = str(workspace.get("retrieval_policy", "由服务配置") if workspace else "由服务配置").upper()
    st.markdown(f"**当前默认：{policy}**。Dense 是字符哈希向量基线，不是神经语义 Embedding；Hybrid 已评测但总体未超过 BM25。")
    st.caption("Rerank：NOT EVALUATED。尚未完成符合轻量部署条件的可重复双语评测，当前不进入默认链路。")
    path = Path(__file__).resolve().parents[1] / "evaluation" / "real_world_retrieval" / "results" / "benchmark_results.json"
    try:
        report = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        st.info("本地评测记录暂不可用。当前页面不展示推测指标，请查看仓库中的真实检索评测文件。")
        return
    bm25_overall = report["results"]["bm25"]["overall"]
    st.caption(
        f"{report['query_count']} 条经官方原文核验的问题，其中 {bm25_overall['answerable']} 条可回答、"
        f"{bm25_overall['no_answer_queries']} 条无答案探针；Hit/MRR 的分母为可回答题。"
        f"同一语料、版本范围与 Top-{report['top_k']}；延迟为本地进程内检索。"
    )
    names = {"dense": "Dense", "bm25": "BM25", "hybrid": "Hybrid"}
    fields = (("hit_at_1", "Hit@1"), ("hit_at_3", "Hit@3"), ("hit_at_5", "Hit@5"),
              ("mrr", "MRR"), ("ndcg_at_5", "nDCG@5"), ("p50_ms", "P50 ms"), ("p95_ms", "P95 ms"))
    header = "| 策略 | " + " | ".join(label for _, label in fields) + " |"
    rule = "| --- | " + " | ".join("---:" for _ in fields) + " |"
    rows = []
    for key in ("dense", "bm25", "hybrid"):
        metrics = report["results"][key]["overall"]
        rows.append("| " + names[key] + " | " + " | ".join(str(metrics[field]) for field, _ in fields) + " |")
    for key in ("Dense + Rerank", "Hybrid + Rerank"):
        rows.append("| " + key + " | NOT EVALUATED | " + " | ".join("—" for _ in fields[1:]) + " |")
    st.markdown("\n".join((header, rule, *rows)))
    st.info(f"这只代表所选官方资料子集与 {report['query_count']} 条查询。无答案问题也可能返回检索候选，候选不等于正确答案。")
    selected_results = report["results"].get(policy.lower(), report["results"]["bm25"])
    cross = selected_results["by_category"]["cross_document"]
    both_count = round(cross["cross_document_both_source_at_5"] * cross["queries"])
    st.caption(
        f"跨文档题的双来源 Top-5 完整命中：{both_count}/{cross['queries']}；"
        "表中 Hit@5 只要求命中任一来源，不能代表多来源答案已完整找到。"
    )


def _limits() -> None:
    st.markdown('<div class="masthead"><span class="kicker">系统说明 / 使用边界</span></div>', unsafe_allow_html=True)
    st.title("已知限制")
    for title, detail in (
        ("资料范围", "当前知识库是 DolphinScheduler 官方公开资料的有限子集，不能覆盖全部功能。"),
        ("检索与回答", "检索候选不等于最终答案；无答案问题仍可能返回看似相关的片段。"),
        ("引用", "引用能帮助定位来源，不保证回答中的每句话事实必然正确。"),
        ("相关资料", "没有官方显式链接时，Agent 只列出建议人工核对的可能相关资料。"),
        ("会话边界", "公网假设变更和人工审核不修改上游项目或公共资料。"),
        ("Rerank", "尚未完成可重复的双语 Rerank 评测，因此未进入默认检索链路。"),
    ):
        with st.container(border=True):
            st.markdown(f"**{title}**")
            st.write(detail)


def _about(workspace: dict | None) -> None:
    st.markdown('<div class="masthead"><span class="kicker">系统说明 / 资料与流程</span></div>', unsafe_allow_html=True)
    st.title("系统说明")
    st.write("RAG 负责查资料、看版本与引用并提醒可核验差异；Agent 负责协助用户审查一次会话内的假设变更。")
    st.markdown('<div class="flow-track"><span>官方公开资料</span><span>版本检索</span><span>引用核对</span><span>可能相关资料</span><span>人工审核</span></div>', unsafe_allow_html=True)
    st.info("本工作台是独立工程演示，不代表 Apache DolphinScheduler 官方或内部系统。")
    if workspace:
        st.caption(f"固定版本：{workspace['baseline_version']} → {workspace['current_version']}；资料 {workspace['source_count']} 份；当前默认策略 {workspace.get('retrieval_policy', '由服务配置')}。")
    st.markdown("[Apache DolphinScheduler 官方仓库](https://github.com/apache/dolphinscheduler)　·　[官方 Releases](https://github.com/apache/dolphinscheduler/releases)")


NAV_GROUPS = (
    ("知识服务", ("总览", "版本检索与问答", "版本与历史", "资料与来源")),
    ("变更审查", ("新建变更审查", "可能相关资料", "修改前后对照", "人工审核")),
    ("系统说明", ("检索评测", "已知限制", "系统说明")),
)


def render() -> None:
    st.markdown(CSS, unsafe_allow_html=True)
    choice = st.session_state.setdefault("official_nav", "总览")
    client = _client()
    workspace = _request(client.workspace, fallback="知识服务暂未连接，页面仍可浏览。")
    ready = bool(workspace)
    with st.sidebar:
        st.markdown('<div class="sidebar-mark">工作台导航</div>', unsafe_allow_html=True)
        st.caption("选择要查看的功能页面")
        st.caption("Apache DolphinScheduler 官方公开资料")
        for group, pages in NAV_GROUPS:
            st.markdown(f'<div class="nav-heading">{group}</div>', unsafe_allow_html=True)
            for page in pages:
                st.button(page, key="nav_" + page, type="primary" if choice == page else "secondary",
                          on_click=_navigate, args=(page,), use_container_width=True)
        st.divider()
        st.caption(f"知识空间：Apache DolphinScheduler　｜　{'已连接' if ready else '等待连接'}")
    if choice == "总览":
        _home(ready, workspace)
    elif choice == "版本检索与问答":
        _knowledge(client, ready, workspace)
    elif choice == "版本与历史":
        _versions(client, ready, workspace)
    elif choice == "资料与来源":
        _sources(client, ready)
    elif choice == "新建变更审查":
        docs = _request(client.documents, fallback="官方资料目录暂不可用。") if ready else []
        _agent(client, ready, docs or [])
    elif choice in ("可能相关资料", "修改前后对照", "人工审核"):
        _review_subpage(choice)
    elif choice == "检索评测":
        _benchmark(workspace)
    elif choice == "已知限制":
        _limits()
    else:
        _about(workspace)
