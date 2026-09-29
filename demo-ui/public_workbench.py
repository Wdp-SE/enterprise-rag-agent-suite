"""Public knowledge and hypothetical change-review workbench."""

from __future__ import annotations

import json
import hashlib
import os
import re
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path
from html import escape
from urllib.parse import urljoin, urlsplit

import streamlit as st

from components.public_theme import PUBLIC_CSS
from services.public_knowledge_client import PublicKnowledgeClient
from services.rag_client import ServiceError


CSS = PUBLIC_CSS


def _module_heading(label: str) -> None:
    st.markdown(f'<span class="module-label">{escape(label)}</span>', unsafe_allow_html=True)


def _setting(name: str, fallback: str) -> str:
    value = os.environ.get(name)
    if value is not None:
        return value
    try:
        return str(st.secrets.get(name, fallback))
    except Exception:
        return fallback


def _published_versions(workspace: dict | None) -> list[str]:
    """Offer only versions the connected, published corpus declares."""
    if not workspace:
        return ["3.4.3", "3.4.2"]
    versions = list(dict.fromkeys(
        str(version) for version in (workspace.get("current_version"), workspace.get("baseline_version"))
        if version
    ))
    return versions or ["3.4.3", "3.4.2"]


def _confirmed_current_version(workspace: dict | None) -> str | None:
    if not workspace:
        return None
    version = workspace.get("current_version")
    return str(version).strip() if version else None


def _sync_workspace_version(workspace: dict | None) -> str | None:
    """Follow a newly published workspace version while preserving user scope otherwise."""
    current = _confirmed_current_version(workspace)
    for widget_key in ("official_version", "source_version"):
        default_key = f"{widget_key}_default"
        confirmed_key = f"{default_key}_confirmed"
        previous = st.session_state.get(default_key)
        previous_confirmed = st.session_state.get(confirmed_key, False)
        if current and (current != previous or not previous_confirmed):
            st.session_state[widget_key] = current
        if current:
            st.session_state[default_key] = current
        st.session_state[confirmed_key] = bool(current)
    st.session_state["official_current_version"] = current
    return current


def _version_option_label(version: str, workspace: dict | None) -> str:
    current = _confirmed_current_version(workspace)
    if version == "all":
        return "全部已收录版本"
    if not current:
        return f"{version} · 离线回退配置（未确认）"
    if version == current:
        return f"{version} · 最新已收录"
    if version == workspace.get("baseline_version"):
        return f"{version} · 历史基线"
    return f"{version} · 历史版本"


def _format_snapshot_timestamp(value: object) -> str | None:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")


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


def _replace_markdown_images(content: str) -> str:
    """State the image evidence boundary without pretending alt text is OCR."""
    def figure_notice(label: str) -> str:
        return f"（原文配图「{label}」，图中文字未纳入检索；可在固定来源查看）"

    content = re.sub(
        r"!\[([^\]]*)\]\([^)]*\)",
        lambda match: figure_notice(match.group(1).strip() or "未命名配图"),
        content,
    )
    def describe_html_image(match: re.Match[str]) -> str:
        alt = re.search(r"\balt\s*=\s*(['\"])(.*?)\1", match.group(0), flags=re.I | re.S)
        return figure_notice(alt.group(2).strip() if alt and alt.group(2).strip() else "未命名配图")

    content = re.sub(r"<img\b[^>]*>", describe_html_image, content, flags=re.I)
    return re.sub(r"<p\b[^>]*>\s*(（原文配图「[^<]+?）)\s*</p>", r"\1", content, flags=re.I)


def _rewrite_relative_source_links(content: str, source_url: str) -> str:
    """Keep Markdown navigation on the same pinned official GitHub commit."""
    source = urlsplit(source_url)
    pinned_prefix = re.match(
        r"^/apache/dolphinscheduler/blob/[0-9a-f]{40}/", source.path
    )
    if source.scheme != "https" or source.netloc != "github.com" or not pinned_prefix:
        return content
    pinned_root = f"https://github.com{pinned_prefix.group(0)}"

    def replace(match: re.Match[str]) -> str:
        destination = match.group(2).strip()
        parsed = urlsplit(destination)
        if (
            not destination or any(char.isspace() for char in destination)
            or parsed.scheme or parsed.netloc or parsed.path.startswith("/")
        ):
            return match.group(0)
        resolved = urljoin(source_url, destination)
        if not resolved.startswith(pinned_root):
            return match.group(1)
        return f"[{match.group(1)}]({resolved})"

    return re.sub(r"(?<!!)\[([^\]]+)\]\(([^)]+)\)", replace, content)


def _source_card(row: dict, *, index: int, key_prefix: str = "evidence") -> None:
    section = row.get("heading") or "正文"
    document_title = st.session_state.get("official_document_titles", {}).get(row.get("document_id")) or row.get("document_key") or "官方资料"
    version = row.get("version", "")
    current_version = st.session_state.get("official_current_version")
    version_label = (
        "最新已收录版本" if current_version and version == current_version
        else "历史版本" if current_version else "版本状态未确认"
    )
    source_label = {
        "official_documentation": "官方文档",
        "github_release": "官方 Release",
        "github_issue": "官方 Issue",
        "github_pull_request": "官方 PR",
    }.get(row.get("source_type"), "官方公开资料")
    with st.container(border=True, key=f"source_card_{key_prefix}_{index}"):
        st.markdown(f"**[{index}] {document_title}**")
        st.caption(f"章节：{section}　｜　{version_label} {version}　｜　{row.get('locale', '')}　｜　{source_label}")
        content = _replace_markdown_images(row.get("content", ""))
        content = _rewrite_relative_source_links(content, row.get("source_url", ""))
        st.write(content)
        if row.get("source_url"):
            st.markdown(f"[在 GitHub 查看固定版本来源]({row['source_url']})")
        with st.expander("技术详情"):
            st.code(f"document_key={row.get('document_key', '')}\nchunk_id={row.get('chunk_id', '')}\npolicy={row.get('retrieval_policy', '')}")
            if "retrieval_score" in row:
                st.caption(f"候选排序分数：{row['retrieval_score']:.4f}。该分数仅用于当前检索策略下的结果排序，不代表事实正确性。")


def _evidence(hits: list[dict], *, heading: str = "引用依据") -> None:
    st.subheader(heading)
    if not hits:
        st.info("当前范围内未找到可直接支持答案的官方资料。请调整问题或检索范围。")
        return
    key_prefix = re.sub(r"[^\w-]+", "_", heading)
    for index, row in enumerate(hits[:3], 1):
        _source_card(row, index=index, key_prefix=key_prefix)
    if len(hits) > 3:
        with st.expander(f"查看更多结果（{len(hits) - 3}）"):
            for index, row in enumerate(hits[3:], 4):
                _source_card(row, index=index, key_prefix=key_prefix)


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
                    f"- [{source.get('version', '版本未标注')} · {source.get('locale', '语言未标注')} · 固定来源（GitHub）]"
                    f"({source.get('source_url', '')})"
                )


NAV_GROUPS = (
    ("知识服务", ("总览", "版本检索与问答", "版本与历史", "资料与来源")),
    ("变更审查", ("新建变更审查", "可能相关资料", "修改前后对照", "人工审核")),
    ("系统说明", ("检索评测", "已知限制", "系统说明")),
)
NAV_GROUP_LABELS = {
    "知识服务": "版本化知识服务",
    "变更审查": "变更影响审查",
    "系统说明": "系统说明",
}
NAV_PAGE_LABELS = {
    "总览": "总览",
    "版本检索与问答": "版本化知识检索",
    "版本与历史": "版本与历史",
    "资料与来源": "资料来源",
    "新建变更审查": "发起变更审查",
    "可能相关资料": "影响候选",
    "修改前后对照": "修改建议对照",
    "人工审核": "人工审核",
    "检索评测": "检索评测",
    "已知限制": "已知限制",
    "系统说明": "系统说明",
}
SECTION_LABELS = {
    "知识检索": "版本化知识服务",
    "知识服务": "版本化知识服务",
    "变更审查": "变更影响审查",
    "系统说明": "系统说明",
}
NAV_PAGES = frozenset(page for _, pages in NAV_GROUPS for page in pages)
PAGE_PARENTS = {
    "可能相关资料": "新建变更审查",
    "修改前后对照": "新建变更审查",
    "人工审核": "新建变更审查",
}
SECTION_ROUTES = {
    "知识检索": "版本检索与问答",
    "知识服务": "版本检索与问答",
    "变更审查": "新建变更审查",
    "系统说明": "系统说明",
}


def _navigate(destination: str) -> None:
    destination = destination if destination in NAV_PAGES else "总览"
    current = st.session_state.get("official_nav", "总览")
    if current not in NAV_PAGES:
        current = "总览"
    if current != destination:
        history = [page for page in st.session_state.get("official_nav_history", []) if page in NAV_PAGES]
        history.append(current)
        st.session_state["official_nav_history"] = history[-24:]
    st.session_state["official_nav"] = destination


def _navigate_back() -> None:
    current = st.session_state.get("official_nav", "总览")
    history = [page for page in st.session_state.get("official_nav_history", []) if page in NAV_PAGES]
    while history:
        previous = history.pop()
        if previous != current:
            st.session_state["official_nav_history"] = history
            st.session_state["official_nav"] = previous
            return
    st.session_state["official_nav_history"] = history
    st.session_state["official_nav"] = PAGE_PARENTS.get(current, "总览")


def _page_header(section: str, title: str, *, page_key: str, parent: str | None = None) -> None:
    with st.container(key=f"page_header_{page_key}"):
        back, trail = st.columns([.22, 4.2], gap="small")
        with back:
            st.button("←", key=f"nav_back_{page_key}", help="返回上一个操作模块",
                      on_click=_navigate_back)
        with trail:
            home, first_separator, group, second_separator, current = st.columns(
                [.65, .12, 1.05, .12, 1.75], gap="small"
            )
            with home:
                st.button("首页", key=f"breadcrumb_home_{page_key}", help="跳转到工作台总览",
                          on_click=_navigate, args=("总览",))
            with first_separator:
                st.markdown('<div class="breadcrumb-separator">›</div>', unsafe_allow_html=True)
            with group:
                st.button(SECTION_LABELS.get(section, section), key=f"breadcrumb_section_{page_key}",
                          on_click=_navigate, args=(SECTION_ROUTES.get(section, parent or "总览"),))
            if section != title:
                with second_separator:
                    st.markdown('<div class="breadcrumb-separator">›</div>', unsafe_allow_html=True)
                with current:
                    st.markdown(
                        f'<div class="breadcrumbs-current" aria-current="page">{escape(title)}</div>',
                        unsafe_allow_html=True,
                    )
    st.title(title)


def _home(ready: bool, workspace: dict | None) -> None:
    baseline = workspace.get("baseline_version", "3.4.2") if workspace else "3.4.2"
    current = _confirmed_current_version(workspace)
    version_range = f"{baseline} → {current}" if current else "服务未连接，无法确认"
    st.markdown('<div class="masthead"><span class="kicker">公开研发资料 / 版本化知识空间</span></div>', unsafe_allow_html=True)
    st.title("研发知识版本服务与变更影响审查")
    st.write("基于 Apache DolphinScheduler 官方公开资料，提供按版本检索与引用溯源，并协助审查资料变更的潜在影响。")
    st.markdown(
        '<div class="public-note">独立工程演示，并非 Apache 官方产品。假设变更仅保留在当前会话，不修改上游项目或公共资料。</div>',
        unsafe_allow_html=True,
    )
    state = "已连接" if ready else "等待连接"
    status = [
        ("知识空间", "Apache DolphinScheduler"),
        ("资料性质", "官方公开资料"),
        ("历史基线 → 最新已收录", version_range),
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
            _module_heading("版本化研发知识服务 · RAG")
            st.markdown("### 版本化知识检索与问答")
            st.write("按产品版本检索官方资料，查看原文与引用依据，了解不同版本之间的资料差异。")
            st.caption("版本范围 · 资料检索 · 引用溯源 · 版本差异")
            st.button("进入知识检索", type="primary", use_container_width=True,
                      on_click=_navigate, args=("版本检索与问答",))
    with right:
        with st.container(border=True, key="public_agent_module"):
            _module_heading("Agent · 研发资料变更审查")
            st.markdown("### 研发资料变更影响审查")
            st.write("基于输入的假设变更发现待核对资料、汇集证据并提供修改建议，由人工确认。")
            st.caption("影响候选 · 引用依据 · 修改建议 · 人工审核")
            st.button("发起变更审查", type="primary", use_container_width=True,
                      on_click=_navigate, args=("新建变更审查",))
    st.markdown('<div class="section-rule">业务流程</div>', unsafe_allow_html=True)
    st.markdown(
        '<div class="flow-track"><span>研发资料</span><span>版本化检索</span>'
        '<span>引用溯源</span><span>资料变更</span><span>影响候选</span>'
        '<span>修改建议</span><span>人工审核</span></div>',
        unsafe_allow_html=True,
    )
    if workspace:
        st.markdown(
            f'<div class="home-snapshot">当前快照：{escape(str(workspace["source_count"]))} 份官方资料、'
            f'{escape(str(workspace["chunk_count"]))} 个检索片段；检索策略以真实评测结果为准。</div>',
            unsafe_allow_html=True,
        )


def _use_example() -> None:
    st.session_state["official_question"] = st.session_state["official_example"]


def _knowledge(client: PublicKnowledgeClient, ready: bool, workspace: dict | None) -> None:
    _page_header("知识服务", "版本化知识检索与问答", page_key="knowledge")
    st.caption("先确定资料范围，再提出问题；回答下方始终保留可核对的官方来源。")
    versions = _published_versions(workspace)
    current = _confirmed_current_version(workspace)
    default_policy = str(workspace.get("retrieval_policy", "由服务配置") if workspace else "由服务配置").upper()
    default_version_label = f"{current} · 最新已收录版本" if current else "无法确认最新已收录版本"
    st.markdown(
        f'<div class="context-strip"><span><strong>知识空间</strong> Apache DolphinScheduler</span>'
        f'<span><strong>资料</strong> 官方公开资料</span>'
        f'<span><strong>默认版本</strong> {escape(default_version_label)}</span>'
        f'<span><strong>默认检索</strong> {escape(default_policy)}</span></div>',
        unsafe_allow_html=True,
    )
    if current:
        latest_source_time = _format_snapshot_timestamp(
            workspace.get("latest_source_retrieval_timestamp") if workspace else None
        )
        st.caption(
            f"默认跟随知识服务声明的最新已收录版本 {current}；只覆盖已纳入知识库的资料，"
            "上游新版本需同步入库后才可检索。"
        )
        if latest_source_time:
            st.caption(f"最近收录资料：{latest_source_time}。")
    else:
        st.caption(
            "无法确认最新已收录版本；下拉框中的版本只是离线回退配置，并不代表当前知识库的最新版本。"
        )
    with st.container(border=True, key="knowledge_scope"):
        a, b, c = st.columns([1, 1, .9], gap="medium")
        with a:
            version = st.selectbox(
                "版本范围", [*versions, "all"],
                format_func=lambda x: _version_option_label(x, workspace),
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
            st.caption("范围受已收录版本与语言限定")
    example_version = current or versions[0]
    examples = [
        "DolphinScheduler 参数优先级从高到低是什么？",
        f"{example_version} 的 missed_fire_policy 对旧 schedule 默认什么？",
        "What is the API server health-check endpoint?",
    ]
    with st.expander("从官方资料选择示例问题"):
        st.selectbox("示例问题", examples, key="official_example", on_change=_use_example)
    st.markdown('<div class="section-rule">提出问题</div>', unsafe_allow_html=True)
    question = st.text_area(
        "你的问题", value="", placeholder=examples[0], height=100, key="official_question"
    )
    submitted_question = question.strip() or examples[0]
    generate_col, search_col = st.columns([1.65, 1], gap="medium")
    with generate_col:
        ask_now = st.button("生成带引用回答", type="primary", key="knowledge_generate",
                            disabled=not ready,
                            use_container_width=True)
    with search_col:
        with st.expander("只想核对原文？"):
            st.caption("直接查看 BM25 检索命中的官方资料，不调用生成模型。")
            search_now = st.button("仅查看检索原文", key="knowledge_search",
                                   disabled=not ready, use_container_width=True)
    st.caption("应用未设置固定生成次数上限；模型服务商的限流与计费规则仍适用。")
    if ask_now:
        with st.spinner("正在检索官方资料并核对引用……"):
            payload = _request(lambda: client.query_official(submitted_question, version=version, language=language), fallback="知识问答暂不可用。")
        if payload:
            st.session_state["official_result"] = ("query", submitted_question, version, language, payload)
    if search_now:
        with st.spinner("正在检索官方资料……"):
            payload = _request(lambda: client.search(submitted_question, version=version, language=language), fallback="资料检索暂不可用。")
        if payload:
            st.session_state["official_result"] = ("search", submitted_question, version, language, payload)
    result = st.session_state.get("official_result")
    if result and result[1:4] == (submitted_question, version, language):
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
                    st.caption("当前仅展示检索证据；RAG 后端尚未启用在线生成。")
                    st.caption(
                        "本地可配置 DASHSCOPE_API_KEY，或选择 DeepSeek 并配置 DEEPSEEK_API_KEY；"
                        "DeepSeek 需在启动前设置 RD_V2_GENERATION_PROVIDER=deepseek。"
                        "随后使用 start_prototype.ps1 -EnableGeneration 启动。"
                        "公网请在 Render 的 RAG 后端配置所选模型的密钥并启用生成开关。"
                        "不要把密钥填入 Streamlit。"
                    )
                elif payload.get("status") == "GENERATION_PROVIDER_UNAVAILABLE":
                    st.caption(
                        "RAG 后端无法连接模型服务；请检查运行后端的网络或 HTTPS 代理配置。"
                        "检索证据仍可用，修复连接后可重新生成。"
                    )
                elif payload.get("status") == "GENERATION_PROVIDER_TIMEOUT":
                    st.caption("模型服务响应超时；本次检索证据已保留。请稍后重试，并用下方请求编号排查后端日志。")
                elif payload.get("status") == "GENERATION_RATE_LIMITED":
                    st.caption("模型服务当前限流；检索证据已保留，请稍后重试。此状态不表示应用内生成次数用完。")
                elif payload.get("status") == "GENERATION_BILLING_REQUIRED":
                    st.caption("模型服务返回计费或余额限制；检索证据已保留。请检查模型服务账户状态。")
                elif payload.get("status") == "GENERATION_AUTH_FAILED":
                    st.caption("模型服务鉴权失败；检索证据已保留。请检查 RAG 后端的模型密钥与访问权限。")
                elif payload.get("status") == "GENERATION_PROVIDER_REJECTED":
                    st.caption(
                        "模型服务拒绝了请求；请检查模型名称、API Key 状态和账户调用权限。"
                        "检索证据仍保留，可在配置修正后重新生成。"
                    )
                elif payload.get("status") == "GENERATION_RESPONSE_INVALID":
                    st.caption(
                        "模型返回内容未满足引用回答要求，本次答案已隐藏；检索证据仍保留。"
                    )
                elif payload.get("status") == "GENERATION_RESPONSE_TRUNCATED":
                    st.caption("模型回复因输出长度截断，未形成可核验的完整回答；检索证据仍保留。")
                else:
                    st.caption(
                        "在线生成未完成或未通过引用核验；下方只展示检索证据。"
                        "请检查 RAG 后端出网连接、模型密钥和生成配置。"
                    )
            primary = sources[0] if sources else None
            _consistency(payload.get("consistency_notes", []), primary=primary)
            st.caption("引用可追溯到原文，但不代表回答中的每句话自动正确。")
            if payload.get("status") == "OK" and sources:
                _evidence(sources, heading="引用依据")
                cited_ids = {row.get("chunk_id") for row in sources}
                remaining = [
                    row for row in payload.get("evidence", [])
                    if row.get("chunk_id") not in cited_ids
                ]
                if remaining:
                    with st.expander(f"查看其余检索结果（{len(remaining)}）"):
                        _evidence(remaining, heading="其他相关官方资料")
            else:
                _evidence(payload.get("evidence", []), heading="检索到的官方资料")
        else:
            st.caption("以下内容按真实检索顺序排列；请通过版本、章节与官方原文核对。")
            _consistency(payload.get("consistency_notes", []))
            _evidence(payload.get("results", []), heading="检索到的官方资料")
        with st.expander("本次检索技术详情"):
            st.write(f"检索范围：{version} · 语言：{language} · 默认策略：{payload.get('retrieval_policy', '由服务配置')}")
            st.caption("候选排序分数只用于同一检索策略内的排序，不代表事实正确性。")
            generation = payload.get("generation") if mode == "query" else None
            if isinstance(generation, dict):
                st.caption(
                    f"生成请求：{generation.get('request_id') or '未返回'} · "
                    f"服务商：{generation.get('provider') or '未确认'} · "
                    f"请求模型：{generation.get('requested_model') or '未确认'} · "
                    f"实际模型：{generation.get('returned_model') or '未返回'}"
                )
                st.caption(
                    f"结束原因：{generation.get('finish_reason') or '未返回'} · "
                    f"生成耗时：{generation.get('latency_ms') if generation.get('latency_ms') is not None else '未记录'} ms · "
                    f"Token 用量：{generation.get('usage') or '未返回'}"
                )
    if not ready:
        st.info("知识服务可能正在冷启动；资料范围会在连接恢复后显示，请稍后刷新。")


def _analyze_hypothetical(client: PublicKnowledgeClient, selected: dict, proposed: str) -> dict:
    agent_root = Path(__file__).resolve().parents[1] / "change-review-agent"
    if str(agent_root) not in sys.path:
        sys.path.insert(0, str(agent_root))
    from app.public_review import PublicReviewAgent
    return PublicReviewAgent(client).analyze(selected, proposed)


def _analyze_change_request(
    client: PublicKnowledgeClient,
    change_summary: str,
    change_type: str | None = None,
    impact_scope: str | None = None,
) -> dict:
    agent_root = Path(__file__).resolve().parents[1] / "change-review-agent"
    if str(agent_root) not in sys.path:
        sys.path.insert(0, str(agent_root))
    from app.public_review import PublicReviewAgent
    return PublicReviewAgent(client).analyze_request(
        change_summary, change_type=change_type, impact_scope=impact_scope,
    )


def _review_steps(stage: int) -> None:
    labels = ("变更已提交", "证据已检索", "等待人工审核")
    cells = "".join(
        f'<span class="{"done" if i < stage else "current" if i == stage else ""}">'
        f'{i + 1}. {escape(label)}</span>'
        for i, label in enumerate(labels)
    )
    st.markdown(f'<div class="review-steps">{cells}</div>', unsafe_allow_html=True)


def _impact_panel(result: dict) -> None:
    st.subheader("影响候选")
    st.caption("以下资料由检索发现，表示需要进一步核对，不代表已确认实际影响。")
    references = result.get("confirmed_relations", [])
    if references:
        st.subheader("已确认文档关联")
        st.caption("官方 PR 明确引用 DSIP，仅确认两份文档有关联；不证明所选段落受影响。")
        for reference in references:
            with st.container(border=True):
                st.markdown("**官方实现 PR #18464 → DSIP #18454**")
                st.caption(f"明确引用所在章节：{reference['source_heading']}")
                excerpt = _rewrite_relative_source_links(
                    _replace_markdown_images(reference["source_excerpt"]), reference.get("source_url", "")
                )
                st.write(excerpt[:300] + ("…" if len(excerpt) > 300 else ""))
                st.markdown(f"[在 GitHub 查看固定版本来源]({reference['source_url']})")
                if len(excerpt) > 300:
                    with st.expander("查看完整引用原文"):
                        st.write(excerpt)
    impacts = result.get("impacts", [])
    if not impacts:
        st.info("未检索到足够相关的其他资料；仍可人工审核当前段落。")
        return
    for index, item in enumerate(impacts):
        evidence = item["evidence"]
        with st.container(border=True, key=f"impact_row_{index}"):
            st.markdown(f"**待核对资料 · {evidence.get('heading') or evidence.get('document_key')}**")
            st.caption(f"{evidence.get('version', '')}　｜　{evidence.get('locale', '')}　｜　可能受影响")
            st.write(item.get("reason", "请核对官方原文与显式引用。"))
            content = _rewrite_relative_source_links(
                _replace_markdown_images(evidence.get("content", "")), evidence.get("source_url", "")
            )
            st.write(content[:300] + ("…" if len(content) > 300 else ""))
            st.markdown(f"[在 GitHub 查看固定版本来源]({evidence['source_url']})")
            if len(content) > 300:
                with st.expander("查看完整相关片段"):
                    st.write(content)


def _review_evidence_panel(result: dict) -> None:
    st.subheader("引用依据")
    st.caption("以下是本次假设变更的官方原文起点；其他可能相关资料列在相应页面。")
    _source_card(result["selected_source"], index=1, key_prefix="selected_source")


def _review_advice_panel(result: dict, *, context: str = "review") -> None:
    advice = result.get("review_advice", {})
    if advice.get("status") == "OK" and advice.get("sources"):
        review = advice.get("review") or {}
        interpretation = review.get("change_interpretation") or advice.get("answer", "N/A")
        candidates = review.get("impact_candidates", [])
        source_numbers = {
            row.get("chunk_id"): number
            for number, row in enumerate(advice["sources"], start=1)
        }
        if context == "变更分析":
            st.subheader("模型辅助核对建议")
            st.markdown(
                '<div class="agent-review-summary">'
                '<div class="agent-review-summary-heading"><strong>本次分析结论</strong>'
                '<span>等待人工审核</span></div>'
                f'<p>{escape(str(interpretation))}</p></div>',
                unsafe_allow_html=True,
            )
            st.caption(
                f"模型依据 {len(advice['sources'])} 条当前检索证据整理；"
                f"以下 {len(candidates)} 条是待核对候选，不代表已确认影响。"
            )
            st.caption("同一片段只展示一次；候选与引用依据逐条对应，完整原文按需展开。")
            st.subheader("优先核对的影响候选")
            if candidates:
                sources_by_id = {
                    row.get("chunk_id"): row for row in advice["sources"] if row.get("chunk_id")
                }
                for number, candidate in enumerate(candidates, start=1):
                    evidence_id = candidate.get("evidence_chunk_id")
                    source = sources_by_id.get(evidence_id)
                    heading = (source or {}).get("heading") or (source or {}).get("document_key") or "待核对资料"
                    with st.container(key=f"review_candidate_{number}"):
                        st.markdown(
                            '<div class="agent-candidate-heading">'
                            f'<span>优先级 {number}</span><strong>{escape(str(heading))}</strong>'
                            '</div>',
                            unsafe_allow_html=True,
                        )
                        st.markdown('<div class="agent-field-label">影响判断</div>', unsafe_allow_html=True)
                        st.markdown(escape(str(candidate.get("reason") or "需要人工核对该资料。")))
                        st.markdown('<div class="agent-field-label">建议核对动作</div>', unsafe_allow_html=True)
                        st.markdown(escape(str(candidate.get("suggested_action") or "对照官方原文确认是否需要同步。")))
                        if source:
                            evidence_number = source_numbers.get(evidence_id)
                            st.markdown(
                                '<div class="agent-evidence-heading">'
                                f'引用证据 [{evidence_number}] · {escape(str(heading))}'
                                '</div>',
                                unsafe_allow_html=True,
                            )
                            st.caption(
                                f"{source.get('version', '版本未标注')}　｜　"
                                f"{source.get('locale', '语言未标注')}　｜　官方资料"
                            )
                            content = _rewrite_relative_source_links(
                                _replace_markdown_images(source.get("content", "")),
                                source.get("source_url", ""),
                            )
                            if content:
                                excerpt = content.strip()
                                st.markdown(escape(excerpt[:360] + ("…" if len(excerpt) > 360 else "")))
                            source_url = source.get("source_url")
                            if source_url:
                                st.markdown(f"[打开官方原文]({escape(str(source_url), quote=True)})")
                            if content:
                                with st.expander(f"展开完整引用原文 [{evidence_number}]"):
                                    st.write(content)
                        else:
                            st.caption("此候选未匹配到有效引用，须先人工查证，不能视为证据支持的影响结论。")
            else:
                st.info("模型没有形成可引用的影响候选；下方检索命中仅供人工筛查。")
        else:
            st.subheader("模型辅助核对建议")
            st.markdown("**变更理解**")
            st.write(interpretation)
            st.caption("具体候选、原文和修改前后对照见下方；所有建议仍需人工确认。")
        follow_up = []
        follow_up.extend(("证据缺口", value) for value in (review.get("evidence_gaps") or []))
        follow_up.extend(("版本或语言歧义", value) for value in (review.get("version_ambiguities") or []))
        follow_up.extend(("人工检查", value) for value in (review.get("reviewer_actions") or []))
        if follow_up:
            with st.expander(f"未解决事项与人工检查（{len(follow_up)}）"):
                for label, item in follow_up:
                    st.markdown(f"**{label}**")
                    st.write(item)
        st.caption("模型建议仅使用本次检索证据；人工确认前不会修改公共资料。")
    elif advice.get("status") == "GENERATION_NOT_CONFIGURED":
        st.subheader("模型辅助核对建议")
        st.caption("当前环境未启用模型建议；影响候选与原文仍可继续人工核对。")
    elif advice.get("status") == "GENERATION_PROVIDER_UNAVAILABLE":
        st.subheader("模型辅助核对建议")
        st.caption("模型服务暂不可用；本次检索候选与原文仍保留，建议人工核对。")
    elif advice.get("status") == "GENERATION_PROVIDER_TIMEOUT":
        st.subheader("模型辅助核对建议")
        st.caption("模型建议请求超时；检索候选与原文已保留，可稍后重试或人工核对。")
    elif advice.get("status") == "GENERATION_RATE_LIMITED":
        st.subheader("模型辅助核对建议")
        st.caption("模型服务当前限流；检索候选与原文已保留，可稍后重试。")
    elif advice.get("status") == "GENERATION_BILLING_REQUIRED":
        st.subheader("模型辅助核对建议")
        st.caption("模型服务返回计费或余额限制；请检查模型账户，当前候选仍可人工核对。")
    elif advice.get("status") == "GENERATION_AUTH_FAILED":
        st.subheader("模型辅助核对建议")
        st.caption("模型服务鉴权失败；请检查后端密钥与权限，当前候选和原文仍可人工核对。")
    elif advice.get("status") == "GENERATION_RESPONSE_TRUNCATED":
        st.subheader("模型辅助核对建议")
        st.caption("模型建议回复被截断，未作为有效建议展示；请依据已保留的候选原文人工核对。")
    elif advice.get("status") == "GENERATION_PROVIDER_REJECTED":
        st.subheader("模型辅助核对建议")
        st.caption("模型服务未接受本次建议请求；请检查后端模型配置，当前候选和原文仍可人工核对。")
    elif advice.get("status") == "ABSTAINED":
        st.subheader("模型辅助核对建议")
        st.info("模型提示待核对：当前证据不足以形成带有效引用的影响候选；以下缺口和动作尚未确认。")
        review = advice.get("review") if isinstance(advice.get("review"), dict) else {}
        if review.get("evidence_gaps"):
            st.caption("待补证据：" + "；".join(review["evidence_gaps"]))
        if review.get("version_ambiguities"):
            st.caption("版本或语言歧义：" + "；".join(review["version_ambiguities"]))
        if review.get("reviewer_actions"):
            st.caption("建议人工核对：" + "；".join(review["reviewer_actions"]))
    elif advice.get("status") == "NO_EVIDENCE":
        st.subheader("模型辅助核对建议")
        st.caption("没有找到可供模型引用的其他资料；请人工检查原文和变更草案。")
    else:
        st.subheader("模型辅助核对建议")
        st.caption("当前证据不足以形成带有效引用的模型建议；请按原文和候选资料人工核对。")

def _patch_panel(result: dict) -> None:
    st.subheader("修改建议对照")
    st.caption("右侧是你输入的会话内假设草案，不是自动生成或已批准的修改。官方原文不会被覆盖。")
    before, after = result["patch_candidate"]["before"], result["patch_candidate"]["proposed_after"]
    left, right = st.columns(2, gap="medium")
    with left:
        with st.container(border=True, key="before_panel"):
            st.markdown("**当前官方原文**")
            st.write(before[:450] + ("…" if len(before) > 450 else ""))
    with right:
        with st.container(border=True, key="after_panel"):
            st.markdown("**会话内假设草案**")
            st.write(after[:450] + ("…" if len(after) > 450 else ""))
    if len(before) > 450 or len(after) > 450:
        with st.expander("查看完整修改前后内容"):
            st.markdown("**当前官方原文**")
            st.write(before)
            st.markdown("**会话内假设草案**")
            st.write(after)


def _review_target_id(result: dict) -> str:
    task_id = result.get("task_id")
    if isinstance(task_id, str) and task_id:
        return task_id
    payload = json.dumps(result, ensure_ascii=False, sort_keys=True, default=str)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:24]


def _review_decision_for(result: dict) -> str | None:
    if st.session_state.get("official_review_decision_target") != _review_target_id(result):
        return None
    return st.session_state.get("official_review_decision")


def _set_review_decision(decision: str, target_id: str) -> None:
    st.session_state["official_review_decision"] = decision
    st.session_state["official_review_decision_target"] = target_id
    st.session_state["official_review_decision_at"] = datetime.now(timezone.utc).isoformat()


def _review_report(result: dict, decision: str, decided_at: str) -> dict:
    """Export a session decision with evidence IDs and draft hashes for review."""
    source_rows = [result.get("selected_source") or {}]
    source_rows.extend(result.get("retrieved_results") or [])
    source_rows.extend(result.get("review_advice", {}).get("sources") or [])
    sources = list({
        row["chunk_id"]: {"chunk_id": row["chunk_id"], "source_url": row.get("source_url")}
        for row in source_rows if row.get("chunk_id")
    }.values())
    patch = result.get("patch_candidate") or {}
    def content_hash(value: str | None) -> str | None:
        return hashlib.sha256(value.encode("utf-8")).hexdigest() if isinstance(value, str) else None

    return {
        "schema_version": 2,
        "record_scope": "session_export_only",
        "task_id": _review_target_id(result),
        "request_fingerprint": result.get("request_fingerprint"),
        "request_mode": result.get("request_mode"),
        "request_summary": result.get("request_summary"),
        "request_plan": result.get("request_plan"),
        "selected_source_id": (result.get("selected_source") or {}).get("chunk_id"),
        "before_sha256": content_hash(patch.get("before")),
        "proposed_after_sha256": content_hash(patch.get("proposed_after")),
        "retrieval_policy": result.get("retrieval_policy"),
        "retrieval_trace": result.get("retrieval_trace"),
        "evidence_gaps": result.get("evidence_gaps", []),
        "evidence_gap_details": result.get("evidence_gap_details", []),
        "evidence_sources": sources,
        "model_status": result.get("review_advice", {}).get("status"),
        "model_review": result.get("review_advice", {}).get("review"),
        "human_decision": decision,
        "decided_at_utc": decided_at,
        "public_baseline_written": result.get("public_baseline_written"),
    }


def _clear_stale_review() -> None:
    st.session_state.pop("official_review", None)
    st.session_state.pop("official_review_decision", None)
    st.session_state.pop("official_review_decision_target", None)
    st.session_state.pop("official_review_decision_at", None)


def _save_review_draft() -> None:
    st.session_state["official_review_draft"] = st.session_state.get(
        "official_proposed_text", ""
    )
    _clear_stale_review()


def _review_panel(result: dict) -> None:
    st.subheader("人工审核")
    st.caption("审核只记录本次会话的决定，不创建公开候选版本，也不修改公共资料。")
    request_only = result.get("request_mode") == "natural_language"
    review_target = "本次影响分析" if request_only else "会话草案"
    target_id = _review_target_id(result)
    approve, reject = st.columns(2)
    approve.button(f"确认已审阅{review_target}", use_container_width=True,
                   on_click=_set_review_decision, args=("reviewed", target_id))
    reject.button(f"退回{review_target}", use_container_width=True,
                  on_click=_set_review_decision, args=("rejected", target_id))
    decision = _review_decision_for(result)
    if decision == "reviewed":
        st.success(f"已记录本次会话对{review_target}的审核结果。未创建候选版本，公共基线未修改。")
    elif decision == "rejected":
        st.info(f"{review_target}已退回。公共基线未修改。")
    if decision:
        report = _review_report(result, decision, st.session_state.get("official_review_decision_at", ""))
        safe_id = re.sub(r"[^a-zA-Z0-9_-]", "", target_id)[:24] or "session"
        st.download_button(
            "下载本次审查记录（JSON）",
            data=json.dumps(report, ensure_ascii=False, indent=2),
            file_name=f"review-{safe_id}.json", mime="application/json",
            key=f"review_export_{safe_id}",
        )
        st.caption("审查记录只在当前会话保留；下载文件可用于人工留档，不代表已写入审批系统。")


def _request_candidates_panel(result: dict, *, standalone: bool = False) -> None:
    advice_sources = result.get("review_advice", {}).get("sources", [])
    retrieved = result.get("retrieved_results", [])
    advice_source_ids = {row.get("chunk_id") for row in advice_sources if row.get("chunk_id")}
    if standalone:
        st.subheader("可能相关资料")
        st.caption("检索和模型引用均表示待核对线索，不代表已经确认实际影响。")
        if advice_sources:
            _evidence(advice_sources, heading="模型引用的官方片段")
        elif retrieved:
            _evidence(retrieved, heading="RAG 检索命中（供人工筛查）")
        else:
            st.info("当前没有可供人工筛查的检索资料。")
        remaining = [row for row in retrieved if row.get("chunk_id") not in advice_source_ids]
        if remaining:
            with st.expander(f"其他 RAG 检索命中（{len(remaining)}）"):
                _evidence(remaining, heading="尚未被模型引用的检索资料")
        return

    if not advice_sources:
        if retrieved:
            st.subheader("RAG 检索命中（供人工筛查）")
            st.caption("模型没有给出带有效引用的影响判断；以下结果只是检索线索。")
            _evidence(retrieved, heading="知识库检索结果")
        else:
            st.info("没有检索到可供核对的官方资料。")
        return

    review = result.get("review_advice", {}).get("review") or {}
    paired_ids = {
        candidate.get("evidence_chunk_id")
        for candidate in review.get("impact_candidates", [])
        if candidate.get("evidence_chunk_id")
    }
    unpaired_sources = [row for row in advice_sources if row.get("chunk_id") not in paired_ids]
    remaining_retrieval = [row for row in retrieved if row.get("chunk_id") not in advice_source_ids]
    if unpaired_sources:
        with st.expander(f"其他模型引用证据（{len(unpaired_sources)}）"):
            _evidence(unpaired_sources, heading="尚未配对到优先候选的引用")
    if remaining_retrieval:
        with st.expander(f"其他未被模型引用的检索命中（{len(remaining_retrieval)}）"):
            _evidence(remaining_retrieval, heading="RAG 检索补充结果")

def _retrieval_trace_panel(result: dict) -> None:
    trace = result.get("retrieval_trace")
    if not isinstance(trace, dict):
        return
    model_gaps = set((result.get("review_advice", {}).get("review") or {}).get("evidence_gaps") or [])
    retrieval_gaps = [gap for gap in result.get("evidence_gaps", []) if gap not in model_gaps]
    if retrieval_gaps:
        st.caption("尚需补充检索证据：" + "；".join(retrieval_gaps))
    gap_details = result.get("evidence_gap_details") or []
    if gap_details:
        with st.expander(f"结构化证据缺口（{len(gap_details)}）"):
            for gap in gap_details:
                st.markdown(f"**{gap.get('gap_type', 'REVIEW_REQUIRED')}** · {gap.get('message', '')}")
                if gap.get("expected_materials"):
                    st.caption(f"建议补查资料：{gap['expected_materials']}")
                if gap.get("suggested_action"):
                    st.write(gap["suggested_action"])
    with st.expander("检索过程与覆盖范围"):
        st.caption(f"任务编号：{result.get('task_id', '当前会话')} · 模型建议状态：{trace.get('model_status', '未调用')}")
        labels = {
            "candidate_found": "已纳入证据",
            "no_retrieval_match": "未检索到匹配",
            "candidate_outside_evidence_budget": "候选超出证据上限",
            "search_unavailable": "检索服务未完成",
        }
        for index, row in enumerate(trace.get("queries", []), 1):
            st.markdown(f"{index}. **{labels.get(row.get('status'), '待核对')}** · {row.get('query', '')}")
            st.caption(f"命中 {len(row.get('top_chunk_ids', []))} 条；纳入模型证据 {len(row.get('selected_chunk_ids', []))} 条。")


def _clear_change_request_results() -> None:
    st.session_state.pop("official_request_review", None)
    st.session_state.pop("official_review", None)
    st.session_state.pop("official_review_decision", None)
    st.session_state.pop("official_review_decision_target", None)
    st.session_state.pop("official_review_decision_at", None)


def _change_request_context_changed() -> None:
    _clear_change_request_results()


def _save_change_request() -> None:
    st.session_state["official_change_request_draft"] = st.session_state.get(
        "official_change_request", ""
    )
    _clear_change_request_results()


def _agent(client: PublicKnowledgeClient, ready: bool, docs: list[dict]) -> None:
    _page_header("变更审查", "研发资料变更影响审查", page_key="agent")
    current_version = st.session_state.get("official_current_version")
    version_scope = f"知识库最新已收录版本 {current_version}" if current_version else "当前已收录资料"
    st.caption(f"用自然语言描述研发变更；Agent 调用 RAG 检索{version_scope}，再整理待核对的影响候选和建议。")
    st.info("本次分析仅保留在当前会话，不自动修改 Apache DolphinScheduler 上游项目或公共资料。")
    _remember_document_titles(docs)
    if "official_change_request" not in st.session_state:
        st.session_state["official_change_request"] = st.session_state.get(
            "official_change_request_draft", ""
        )
    summary = st.text_area(
        "描述研发变更", height=120,
        placeholder="例如：计划将全局参数优先级调整为最高，请找出需要核对的官方资料。",
        key="official_change_request", on_change=_save_change_request,
    )
    type_options = {
        "自动识别": None,
        "参数 / 配置变更": "parameter_config",
        "接口 / 兼容性变更": "interface_compatibility",
        "工作流 / 行为变更": "workflow_behavior",
        "数据 / 存储变更": "data_storage",
        "安全 / 权限变更": "security_permission",
        "其他 / 待识别": "general",
    }
    with st.expander("可选：补充结构化变更信息"):
        selected_type = st.selectbox(
            "变更类型", list(type_options), key="official_change_type",
            on_change=_change_request_context_changed,
        )
        impact_scope = st.text_input(
            "影响范围（模块、项目或对象）", max_chars=160,
            placeholder="例如：DAG 调度、API 任务状态字段",
            key="official_impact_scope", on_change=_change_request_context_changed,
        )
        st.caption("留空时由规则从原始描述识别；结构化字段只辅助检索规划，不替代原始描述或人工审核。")
    st.caption("Agent 保留原始描述，并在最多 4 次 RAG 查询内覆盖完整请求与拆分子问题；最多选取 5 条最新已收录资料供模型分析。")
    if st.button("检索资料并分析影响", type="primary", disabled=not ready or not summary.strip()):
        with st.spinner("正在检索当前版本官方资料并整理影响建议……"):
            result = _request(
                lambda: _analyze_change_request(
                    client, summary, type_options[selected_type], impact_scope,
                ),
                fallback="变更影响分析暂未完成。",
            )
        if result:
            st.session_state["official_request_review"] = result
            st.session_state.pop("official_review", None)
            st.session_state["official_review_decision"] = None
            st.rerun()

    request_result = st.session_state.get("official_request_review")
    request_plan = (request_result or {}).get("request_plan") or {}
    selected_type_code = type_options.get(st.session_state.get("official_change_type", "自动识别"))
    context_matches = (
        request_plan.get("impact_scope", "") == st.session_state.get("official_impact_scope", "").strip()
        and (
            request_plan.get("change_type") == selected_type_code
            and request_plan.get("classification_source") == "user_selected"
            if selected_type_code else request_plan.get("classification_source") != "user_selected"
        )
    )
    active_request = (
        request_result if request_result
        and request_result.get("request_summary") == summary.strip()
        and context_matches else None
    )
    if active_request:
        stage = 3 if _review_decision_for(active_request) else 2
        _review_steps(stage)
        plan = active_request.get("request_plan") or {}
        st.caption(
            f"变更类型：{plan.get('change_type_label', '待识别')} · "
            f"识别方式：{'人工选择' if plan.get('classification_source') == 'user_selected' else '规则识别'} · "
            f"检索关注点：{plan.get('retrieval_focus', '按原始描述检索')}"
        )
        st.markdown('<div class="section-rule">本次变更分析</div>', unsafe_allow_html=True)
        _review_advice_panel(active_request, context="变更分析")
        _request_candidates_panel(active_request)
        _retrieval_trace_panel(active_request)
        _review_panel(active_request)

        candidates = active_request.get("retrieved_results", [])
        if candidates:
            with st.expander("可选：针对候选资料制作修改草案"):
                st.caption("只有需要对具体段落准备前后对照时，才选择候选资料；草案仍只保留在当前会话。")
                documents_by_id = {row["document_id"]: row for row in docs if row.get("document_id")}
                candidate_document_ids = list(dict.fromkeys(row["document_id"] for row in candidates))
                for row in candidates:
                    documents_by_id.setdefault(row["document_id"], row)
                if st.session_state.get("official_change_document") not in candidate_document_ids:
                    st.session_state["official_change_document"] = candidate_document_ids[0]
                document_id = st.selectbox(
                    "聚焦一份检索候选资料", candidate_document_ids,
                    key="official_change_document",
                    format_func=lambda key: (
                        f"{documents_by_id[key].get('title') or documents_by_id[key].get('document_key')} · "
                        f"{documents_by_id[key].get('version', '')} · {documents_by_id[key].get('locale', '')}"
                    ),
                )
                chunks = _request(lambda: client.document(document_id), fallback="所选候选资料暂未加载。") if ready else None
                if chunks:
                    by_id = {row["chunk_id"]: row for row in chunks}
                    if st.session_state.get("official_change_chunk") not in by_id:
                        preferred = next((row["chunk_id"] for row in candidates if row["document_id"] == document_id), None)
                        st.session_state["official_change_chunk"] = preferred if preferred in by_id else next(iter(by_id))
                    chunk_id = st.selectbox(
                        "聚焦段落（可选）", list(by_id), key="official_change_chunk",
                        format_func=lambda key: f"{by_id[key].get('heading') or '正文'} · 第 {list(by_id).index(key)+1} 段",
                    )
                    selected = by_id[chunk_id]
                    if st.session_state.get("official_draft_source_id") != chunk_id:
                        st.session_state["official_draft_source_id"] = chunk_id
                        st.session_state["official_review_draft"] = selected["content"]
                        st.session_state["official_proposed_text"] = selected["content"]
                        _clear_stale_review()
                    elif "official_proposed_text" not in st.session_state:
                        st.session_state["official_proposed_text"] = st.session_state.get(
                            "official_review_draft", selected["content"]
                        )
                    with st.expander("查看所选官方原文"):
                        st.write(_rewrite_relative_source_links(
                            _replace_markdown_images(selected["content"]), selected.get("source_url", "")
                        ))
                        st.markdown(f"[在 GitHub 查看固定版本来源]({selected['source_url']})")
                    proposed = st.text_area(
                        "目标段落草案", height=170, key="official_proposed_text",
                        on_change=_save_review_draft,
                    )
                    st.caption("描述目标版本的段落内容；不会写入官方资料或上游项目。")
                    if st.button(
                        "生成修改前后对照", type="secondary", key="official_create_patch",
                        disabled=not ready or proposed.strip() == selected["content"].strip(),
                    ):
                        with st.spinner("正在核对段落差异、关联资料与引用依据……"):
                            result = _request(
                                lambda: _analyze_hypothetical(client, selected, proposed),
                                fallback="具体草案核对暂未完成。",
                            )
                        if result:
                            st.session_state["official_review"] = result
                            st.session_state["official_review_decision"] = None
                            st.rerun()
        exact_result = st.session_state.get("official_review")
        active_exact = exact_result if exact_result and exact_result.get("selected_source", {}).get("chunk_id") == st.session_state.get("official_change_chunk") else None
        if active_exact:
            st.markdown('<div class="section-rule">具体段落草案核对</div>', unsafe_allow_html=True)
            _review_advice_panel(active_exact, context="草案核对")
            _impact_panel(active_exact)
            _review_evidence_panel(active_exact)
            _patch_panel(active_exact)
            _retrieval_trace_panel(active_exact)
            _review_panel(active_exact)
    else:
        _review_steps(0)
        if not ready:
            st.info("知识服务正在启动或暂不可用；连接恢复后可直接提交自然语言变更描述。")


def _review_subpage(choice: str) -> None:
    _page_header("变更审查", NAV_PAGE_LABELS[choice], page_key="review", parent=PAGE_PARENTS[choice])
    result = st.session_state.get("official_review") or st.session_state.get("official_request_review")
    if not result:
        st.info("当前会话还没有变更分析结果。请先用自然语言描述变更并检索官方资料。")
        return
    st.caption("以下内容仅属于当前会话；已确认引用关系与检索建议会明确区分。")
    if choice == "可能相关资料":
        if result.get("request_mode") == "natural_language":
            _request_candidates_panel(result, standalone=True)
        else:
            _impact_panel(result)
    elif choice == "修改前后对照":
        if result.get("patch_candidate"):
            _patch_panel(result)
        elif result.get("request_mode") == "natural_language":
            _review_advice_panel(result)
            st.info("尚未为具体段落制作修改草案。返回“新建变更审查”，可从检索候选中选择资料继续。")
    else:
        _review_panel(result)


def _versions(client: PublicKnowledgeClient, ready: bool, workspace: dict | None) -> None:
    _page_header("知识服务", "版本与历史", page_key="versions")
    st.write("默认检索使用知识服务声明的最新已收录版本；页面仅展示已经同步到知识库的官方资料。")
    if not ready:
        st.info("知识服务暂不可用，连接恢复后可查看各版本的真实资料。")
        return
    docs = _request(client.documents, fallback="版本资料目录暂不可用。") or []
    baseline = workspace.get("baseline_version", "3.4.2") if workspace else "3.4.2"
    current = _confirmed_current_version(workspace)
    latest_source_time = _format_snapshot_timestamp(
        workspace.get("latest_source_retrieval_timestamp") if workspace else None
    )
    if latest_source_time:
        st.caption(f"最近收录资料：{latest_source_time}。官方上游的新版本需要同步入库后才会成为默认版本。")
    first, second = st.columns(2, gap="medium")
    for column, version, label in ((first, baseline, "历史基线"), (second, current, "最新已收录")):
        if not version:
            continue
        with column:
            with st.container(border=True):
                st.markdown(f"### {version}　{label}")
                matching = [row for row in docs if row.get("version") == version]
                st.write(f"知识库收录 {len(matching)} 份该版本资料。")
                for row in matching[:5]:
                    st.markdown(
                        f"- {row.get('title') or row['document_key']} · "
                        f"[固定版本来源（GitHub）]({row['source_url']})"
                    )
                if len(matching) > 5:
                    with st.expander(f"查看其余 {len(matching)-5} 份资料"):
                        for row in matching[5:]:
                            st.markdown(
                                f"- {row.get('title') or row['document_key']} · "
                                f"[固定版本来源（GitHub）]({row['source_url']})"
                            )
    st.info("需要对照版本内容时，在版本化知识检索中选择“全部已收录版本”；版本差异提醒只报告可核验的文字差异。")
    st.button("进入知识检索", on_click=_navigate, args=("版本检索与问答",))


def _sources(client: PublicKnowledgeClient, ready: bool, workspace: dict | None) -> None:
    _page_header("知识服务", "资料来源", page_key="sources")
    st.write("本工作台使用 Apache DolphinScheduler 官方公开资料；每条结果均保留版本信息与原文链接。")
    st.caption("独立工程演示，并非 Apache 官方产品；英文官方资料不会被自动翻译成中文原文。")
    if not ready:
        st.info("知识服务暂不可用，资料目录将在连接恢复后显示。")
        return
    docs = _request(client.documents, fallback="官方资料目录暂不可用。") or []
    version = st.selectbox("资料版本", [*_published_versions(workspace), "all"], format_func=lambda x: _version_option_label(x, workspace), key="source_version")
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
    for index, row in enumerate(filtered[:12]):
        with st.container(border=True, key=f"source_row_{index}"):
            st.markdown(f"**{row.get('title') or row['document_key']}**")
            st.caption(f"{row.get('version', '')}　｜　{row.get('locale', '')}　｜　{kind.get(row.get('source_type'), '官方资料')}")
            st.markdown(f"[在 GitHub 查看固定版本来源]({row['source_url']})")
    if len(filtered) > 12:
        with st.expander(f"查看其余 {len(filtered)-12} 份资料"):
            for row in filtered[12:]:
                st.markdown(
                    f"- {row.get('title') or row['document_key']} · "
                    f"[固定版本来源（GitHub）]({row['source_url']})"
                )


def _benchmark(workspace: dict | None) -> None:
    _page_header("系统说明", "检索评测", page_key="benchmark")
    st.subheader("技术选型依据")
    st.write("检索策略依据有版本记录的 Benchmark 选择；语料变更后必须重新评测。")
    policy = str(workspace.get("retrieval_policy", "由服务配置") if workspace else "由服务配置").upper()
    st.markdown(f"**当前默认：{policy}**。Dense 是字符哈希向量基线，不是神经语义 Embedding；Hybrid 在旧语料选型中未超过 BM25。")
    release = workspace.get("retrieval_evaluation") if workspace and workspace.get("retrieval_evaluation_status") == "v3_validated" else None
    if isinstance(release, dict) and release.get("name") == "quality_v3" and release.get("policy", "").upper() == policy:
        st.markdown("**V3 当前扩充语料（后端语料、策略与索引指纹已匹配）**")
        st.caption("132 份官方固定来源、1322 个片段；DEV 选型后仅对 BM25 打开一次 HOLDOUT。Top-5 来源与原文锚点指标，分母只含可回答题；无答案题另作检索诊断。")
        st.caption("当前服务核对语料、默认检索策略与片段索引指纹；选型和 DEV/HOLDOUT 结果哈希由仓库测试核验。以下是离线检索评测，不是线上实时质量监控。")
        fields = (
            ("source_hit_at_5", "来源 Hit@5"),
            ("source_recall_at_5_macro", "来源 Recall@5（宏）"),
            ("mrr", "来源 MRR"),
        )
        rows = ["| 切分 | 题数（可答/无答案） | " + " | ".join(label for _, label in fields) + " | 完整来源 | 多来源完整 | 原文锚点 | warm P95 |",
                "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |"]
        for split, label in (("dev", "DEV"), ("holdout", "HOLDOUT")):
            values = release.get(split, {})
            rows.append(
                f"| {label} | {values['question_count']}（{values['answerable_count']}/{values['no_answer_count']}） | "
                + " | ".join(f"{values[key]:.4f}" for key, _ in fields)
                + f" | {values['complete_source_count']}/{values['answerable_count']}"
                + f" | {values['complete_multi_source_count']}/{values['multi_source_question_count']}"
                + f" | {values['evidence_marker_found']}/{values['evidence_marker_count']}"
                + f" | {values['warm_search_p95_ms']:.2f} ms |"
            )
        st.markdown("\n".join(rows))
        st.caption("HOLDOUT 多来源完整命中仅 4/8，跨资料与跨版本核对仍是短板。本机 warm 检索时间不含公网、冷启动和模型生成；这些指标也不能代表答案正确率或幻觉率。")
    else:
        st.caption("当前后端尚未匹配 V3 扩充语料评测的发布指纹；可能仍运行旧服务或语料、策略已变化。不能把仓库内 V3 指标当作当前后端成绩。")
    st.caption("Rerank：NOT EVALUATED。尚未完成符合轻量部署条件的可重复双语评测，当前不进入默认链路。")
    st.markdown("**历史选型（旧语料）**")
    st.caption("以下冻结实验只用于说明最初选择 BM25 的依据；语料范围较小，不能作为当前 132 份资料的检索质量。")
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
    _page_header("系统说明", "已知限制", page_key="limits")
    for index, (title, detail) in enumerate((
        ("资料范围", "当前知识库是 DolphinScheduler 官方公开资料的有限子集，不能覆盖全部功能。"),
        ("检索与回答", "检索候选不等于最终答案；无答案问题仍可能返回看似相关的片段。"),
        ("引用", "引用能帮助定位来源，不保证回答中的每句话事实必然正确。"),
        ("相关资料", "没有官方显式链接时，Agent 只列出建议人工核对的可能相关资料。"),
        ("会话边界", "公网假设变更和人工审核不修改上游项目或公共资料。"),
        ("Rerank", "尚未完成可重复的双语 Rerank 评测，因此未进入默认检索链路。"),
    )):
        with st.container(border=True, key=f"limit_row_{index}"):
            st.markdown(f"**{title}**")
            st.write(detail)


def _about(workspace: dict | None) -> None:
    _page_header("系统说明", "系统说明", page_key="about")
    st.write("版本化知识服务按版本查找资料并提供原文依据；变更审查 Agent 汇总影响候选与修改建议，由人工确认。")
    st.markdown('<div class="flow-track"><span>研发资料</span><span>版本检索</span><span>引用溯源</span><span>资料变更</span><span>影响候选</span><span>人工审核</span></div>', unsafe_allow_html=True)
    st.info("本工作台是独立工程演示，不代表 Apache DolphinScheduler 官方或内部系统。")
    if workspace:
        st.caption(f"历史基线 {workspace['baseline_version']} → 最新已收录 {workspace['current_version']}；资料 {workspace['source_count']} 份；当前默认策略 {workspace.get('retrieval_policy', '由服务配置')}。")
    st.markdown("[Apache DolphinScheduler 官方仓库](https://github.com/apache/dolphinscheduler)　·　[官方 Releases](https://github.com/apache/dolphinscheduler/releases)")


def render() -> None:
    st.markdown(CSS, unsafe_allow_html=True)
    choice = st.session_state.setdefault("official_nav", "总览")
    st.session_state.setdefault("official_nav_history", [])
    if choice not in NAV_PAGES:
        choice = "总览"
        st.session_state["official_nav"] = choice
        st.session_state["official_nav_history"] = [
            page for page in st.session_state["official_nav_history"] if page in NAV_PAGES
        ]
    client = _client()
    workspace = _request(client.workspace, fallback="知识服务暂未连接，页面仍可浏览。")
    ready = bool(workspace)
    _sync_workspace_version(workspace)
    with st.sidebar:
        st.markdown('<div class="sidebar-mark">工作台导航</div>', unsafe_allow_html=True)
        st.caption("选择要查看的功能页面")
        st.caption("Apache DolphinScheduler 官方公开资料")
        for group, pages in NAV_GROUPS:
            st.markdown(f'<div class="nav-heading">{escape(NAV_GROUP_LABELS.get(group, group))}</div>', unsafe_allow_html=True)
            for page in pages:
                st.button(NAV_PAGE_LABELS.get(page, page), key="nav_" + page,
                          type="primary" if choice == page else "secondary",
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
        _sources(client, ready, workspace)
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
