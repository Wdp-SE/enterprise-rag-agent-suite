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
from services.review_audit import SQLiteReviewAudit
from services.rag_client import ServiceError
from services.public_workspace_profile import public_workspace_mismatch, workspace_snapshot


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


def _workspace_name(workspace: dict | None) -> str:
    return str((workspace or {}).get("workspace") or "公开研发知识空间")


def _published_versions(workspace: dict | None) -> list[str]:
    """Offer only versions the connected, published corpus declares."""
    if not workspace:
        return ["等待连接"]
    declared = workspace.get("available_versions")
    versions = list(dict.fromkeys(str(version) for version in declared or [] if version))
    current = workspace.get("current_version")
    if current:
        versions = [str(current), *[version for version in versions if version != str(current)]]
    if not versions:
        versions = list(dict.fromkeys(
            str(version) for version in (current, workspace.get("baseline_version")) if version
        ))
    return versions or ["等待连接"]


def _confirmed_current_version(workspace: dict | None) -> str | None:
    if not workspace:
        return None
    version = workspace.get("current_version")
    return str(version).strip() if version else None


def _review_version_selector(workspace: dict | None) -> tuple[list[str], int]:
    versions = _published_versions(workspace)
    current = _confirmed_current_version(workspace)
    if not current or current not in versions:
        raise ValueError("知识空间当前版本不在可检索版本列表中")
    return versions, versions.index(current)


def _request_context_matches(
    result: dict | None, *, summary: str, target_version: str,
    objective: str, constraints: str, validation_plan: str,
    selected_type_code: str | None, impact_scope: str,
) -> bool:
    """Avoid stale results while keeping pre-RAG scope rejections visible."""
    if not result or result.get("request_summary") != summary.strip():
        return False
    plan = result.get("request_plan") or {}
    if result.get("scope_status") == "OUT_OF_SCOPE":
        return True
    context = result.get("request_context") or {}
    return (
        (plan.get("target_version") or context.get("target_version")) == target_version
        and context.get("objective") == (objective.strip() or None)
        and context.get("constraints") == (constraints.strip() or None)
        and context.get("validation_plan") == (validation_plan.strip() or None)
        and plan.get("impact_scope", "") == impact_scope.strip()
        and (
            plan.get("change_type") == selected_type_code
            and plan.get("classification_source") == "user_selected"
            if selected_type_code else plan.get("classification_source") != "user_selected"
        )
    )


def _published_language_options(workspace: dict | None) -> list[tuple[str, str]]:
    locales = set((workspace or {}).get("languages") or [])
    options = []
    if "zh-CN" in locales:
        options.extend((("zh_preferred", "中文优先"), ("zh", "中文")))
    if "en-US" in locales:
        options.append(("en", "English"))
    if len(locales) > 1:
        options.insert(1 if options and options[0][0] == "zh_preferred" else 0, ("all", "全部已收录语言"))
    if not options:
        options = [("all", "语言元数据未声明")]
    elif len(options) > 1 and not any(value == "all" for value, _ in options):
        options.insert(0, ("all", "全部已收录语言"))
    return options


def _sync_workspace_version(workspace: dict | None) -> str | None:
    """Follow a newly published workspace version while preserving user scope otherwise."""
    current = _confirmed_current_version(workspace)
    st.session_state["official_workspace"] = workspace or {}
    for widget_key in ("official_version", "source_version", "agent_target_version"):
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
    labels = (workspace or {}).get("version_labels") or {}
    if version in labels:
        return str(labels[version])
    if not current:
        return f"{version} · 离线回退配置（未确认）"
    if version == current:
        return f"{version} · 最新已收录"
    if version == workspace.get("baseline_version"):
        return f"{version} · 历史基线"
    return f"{version} · 历史版本"


def _scope_members(version: str, workspace: dict | None) -> set[str] | None:
    if version == "all":
        return None
    scopes = (workspace or {}).get("version_scopes") or {}
    definition = scopes.get(version) if isinstance(scopes, dict) else None
    members = definition.get("versions") if isinstance(definition, dict) else None
    return set(members) if isinstance(members, list) else {version}


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


def _source_coverage_text(workspace: dict | None) -> str | None:
    if not workspace:
        return None
    rows = workspace.get("source_breakdown") or []
    counts = {
        (str(row.get("version", "")), str(row.get("locale", "")), str(row.get("source_type", ""))): int(row.get("count", 0))
        for row in rows if isinstance(row, dict)
    }
    english_main = counts.get(("docs-main", "en-US", "official_documentation"), 0)
    english_release = counts.get(("1.9.0", "en-US", "official_documentation"), 0)
    chinese = counts.get(("docs-main", "zh-CN", "community_translation"), 0)
    universe_latest = counts.get(("0.52.0", "en-US", "official_documentation"), 0)
    universe_baseline = counts.get(("0.51.0", "en-US", "official_documentation"), 0)
    alignment = workspace.get("translation_alignment") or {}
    matched = int(alignment.get("path_matched_to_official_main", 0))
    unverified = int(alignment.get("source_path_not_found_in_official_main", 0))
    if not any((english_main, english_release, chinese, universe_latest, universe_baseline)):
        return None
    return (
        f"资料覆盖：官方 Documentation 英文 main {english_main} 页、release 1.9.0 {english_release} 页；"
        f"Universe Planning 英文 0.52.0 / 0.51.0 各 {universe_latest} / {universe_baseline} 份；"
        f"另收录社区中文译文 {chinese} 页，其中 {matched} 页按路径匹配到官方 main，"
        f"{unverified} 页当前未匹配到同路径英文原文，均保留为独立社区快照。"
    )


def _client() -> PublicKnowledgeClient:
    session_id = st.session_state.setdefault("official_session_id", uuid.uuid4().hex)
    return PublicKnowledgeClient(
        _setting("RAG_API_BASE_URL", "http://127.0.0.1:8765"),
        timeout=float(_setting("DEMO_REQUEST_TIMEOUT_SECONDS", "45")),
        session_id=session_id,
        retry_limit=int(_setting("RAG_RETRY_LIMIT", "1")),
    )


def _audit_repository() -> SQLiteReviewAudit:
    configured_path = _setting("DEMO_AUDIT_DB_PATH", "").strip()
    if configured_path:
        database_path = Path(configured_path).expanduser()
    else:
        runtime_root = Path(_setting(
            "DEMO_RUNTIME_ROOT", str(Path(__file__).resolve().parent / "runtime")
        )).expanduser()
        database_path = runtime_root / "review_audit.sqlite3"
    return SQLiteReviewAudit(database_path)


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
        r"^/([A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+)/blob/([0-9a-f]{40})/", source.path
    )
    if source.scheme != "https" or source.netloc != "github.com" or not pinned_prefix:
        return content
    pinned_root = f"https://github.com{pinned_prefix.group(1)}/blob/{pinned_prefix.group(2)}/"

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
    latest_members = _scope_members(current_version or "", st.session_state.get("official_workspace")) if current_version else set()
    version_label = (
        "最新资料范围" if current_version and version in (latest_members or set())
        else "历史资料快照" if current_version else "版本状态未确认"
    )
    source_label = {
        "official_documentation": "官方文档",
        "community_translation": "社区中文译文",
        "github_release": "官方 Release",
        "github_issue": "官方 Issue",
        "github_pull_request": "官方 PR",
    }.get(row.get("source_type"), "官方公开资料")
    if row.get("modality") == "image_ocr" and not _verified_image_citation(row):
        st.warning(f"[{index}] 截图证据未通过来源校验，已隐藏识别文本。")
        return
    with st.container(border=True, key=f"source_card_{key_prefix}_{index}"):
        is_image = row.get("modality") == "image_ocr"
        if is_image:
            st.markdown(f"**[{index}] 截图 OCR 证据 · {document_title}**")
            st.caption(f"章节：{section}　｜　派生证据　｜　{version_label} {version}　｜　{row.get('locale', '')}")
            st.info("截图 OCR 文字 · 经目视校对的派生证据，需对照原图；不等同于官方文档正文。")
            st.write(row.get("content", ""))
            st.markdown(f"[查看原图]({row['raw_url']})")
        else:
            st.markdown(f"**[{index}] {document_title}**")
            st.caption(f"章节：{section}　｜　{version_label}　｜　{_version_option_label(version, st.session_state.get('official_workspace'))}　｜　{row.get('locale', '')}　｜　{source_label}")
            content = _replace_markdown_images(row.get("content", ""))
            content = _rewrite_relative_source_links(content, row.get("source_url", ""))
            st.write(content)
            if row.get("source_type") == "community_translation":
                if row.get("translation_alignment_status") == "path_matched_to_official_main":
                    st.caption("社区维护的中文译文；此页按固定 canonical 路径匹配到官方 main 快照，不代表官方中文译文。")
                else:
                    st.caption("社区维护的中文译文；当前官方 main 快照中未找到同路径英文原文，版本对应关系未核实。")
                if row.get("rendered_url"):
                    st.markdown(f"[阅读社区中文页面（在线版本）]({row['rendered_url']})")
                if row.get("english_source_url"):
                    st.markdown(f"[查看对应英文原文]({row['english_source_url']})")
                elif row.get("canonical_url"):
                    st.markdown(f"[查看译文标注的官方页面]({row['canonical_url']})")
        if row.get("source_url"):
            st.markdown(f"[查看固定提交来源]({row['source_url']})")
        with st.expander("技术详情"):
            st.code(f"document_key={row.get('document_key', '')}\nchunk_id={row.get('chunk_id', '')}\npolicy={row.get('retrieval_policy', '')}")
            if is_image:
                st.code(f"figure_id={row.get('figure_id', '')}\ncommit={row.get('commit', '')}\nsha256={row.get('sha256', '')}")
            if "retrieval_score" in row:
                st.caption(f"候选排序分数：{row['retrieval_score']:.4f}。该分数仅用于当前检索策略下的结果排序，不代表事实正确性。")


def _verified_image_citation(row: dict) -> bool:
    commit = row.get("commit", "")
    sha = row.get("sha256", "")
    repository = str(row.get("repository") or "")
    if row.get("review_status") != "approved" or not re.fullmatch(r"[0-9a-f]{40}", commit):
        return False
    if not re.fullmatch(r"[0-9a-f]{64}", sha) or not str(row.get("content", "")).strip():
        return False
    if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repository):
        return False
    raw_prefix = f"https://raw.githubusercontent.com/{repository}/{commit}/"
    source_prefix = f"https://github.com/{repository}/blob/{commit}/"
    return str(row.get("raw_url", "")).startswith(raw_prefix) and str(row.get("source_url", "")).startswith(source_prefix)


def _evidence(hits: list[dict], *, heading: str = "引用依据") -> None:
    st.subheader(heading)
    if not hits:
        st.info("当前范围内未找到可直接支持答案的资料。请调整问题或检索范围。")
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
    current = _confirmed_current_version(workspace)
    version_range = _version_option_label(current, workspace) if current else "服务未连接，无法确认"
    name = _workspace_name(workspace)
    locales = (workspace or {}).get("languages") or []
    language_label = " / ".join("中文" if value == "zh-CN" else "English" if value == "en-US" else value for value in locales) or "服务连接后确认"
    st.markdown('<div class="masthead"><span class="kicker">公开研发资料 / 版本化知识空间</span></div>', unsafe_allow_html=True)
    st.title("研发知识版本服务与变更影响审查")
    st.write(f"基于 {name} 官方英文资料与社区中文译本，提供按版本检索、引用溯源和研发资料变更影响审查。")
    st.markdown(
        '<div class="public-note">独立工程演示，并非上游官方产品。假设变更仅保留在当前会话，不修改上游项目或公共资料。</div>',
        unsafe_allow_html=True,
    )
    state = "已连接" if ready else "等待连接"
    status = [
        ("知识空间", name),
        ("资料性质", "官方英文资料 + 社区中文译本"),
        ("默认检索范围", version_range),
        ("语言", language_label),
        ("服务状态", state),
    ]
    cells = "".join(
        f'<div class="status-cell"><span class="status-label">{escape(label)}</span>'
        f'<span class="status-value">{escape(value)}</span></div>'
        for label, value in status
    )
    st.markdown(f'<div class="status-grid">{cells}</div>', unsafe_allow_html=True)
    if workspace and workspace.get("corpus_scope"):
        st.caption(str(workspace["corpus_scope"]))
    coverage = _source_coverage_text(workspace)
    if coverage:
        st.caption(coverage)
    left, right = st.columns(2, gap="medium")
    with left:
        with st.container(border=True, key="public_rag_module"):
            _module_heading("版本化研发知识服务 · RAG")
            st.markdown("### 版本化知识检索与问答")
            st.write("按版本与语言范围检索研发资料，查看固定来源和引用依据，核对不同快照间的资料差异。")
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
            f'<div class="home-snapshot">{escape(workspace_snapshot(workspace))}</div>',
            unsafe_allow_html=True,
        )


def _use_example() -> None:
    st.session_state["official_question"] = st.session_state["official_example"]


def _knowledge(client: PublicKnowledgeClient, ready: bool, workspace: dict | None) -> None:
    _page_header("知识服务", "版本化知识检索与问答", page_key="knowledge")
    st.caption("先确定资料范围，再提出问题；回答下方始终保留可核对的官方来源。")
    versions = _published_versions(workspace)
    current = _confirmed_current_version(workspace)
    name = _workspace_name(workspace)
    default_policy = str(workspace.get("retrieval_policy", "由服务配置") if workspace else "由服务配置").upper()
    default_version_label = _version_option_label(current, workspace) if current else "无法确认最新已收录版本"
    st.markdown(
        f'<div class="context-strip"><span><strong>知识空间</strong> {escape(name)}</span>'
        f'<span><strong>资料</strong> 官方英文资料 / 社区中文译本</span>'
        f'<span><strong>默认版本</strong> {escape(default_version_label)}</span>'
        f'<span><strong>默认检索</strong> {escape(default_policy)}</span></div>',
        unsafe_allow_html=True,
    )
    if current:
        latest_source_time = _format_snapshot_timestamp(
            workspace.get("latest_source_retrieval_timestamp") if workspace else None
        )
        st.caption(
            f"默认使用 {default_version_label}；该范围只覆盖已固定快照，并非单一软件发行版本。"
            "上游更新需同步入库后才可检索。"
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
            language_options = _published_language_options(workspace)
            language_values = [value for value, _label in language_options]
            language = st.selectbox(
                "资料语言", language_values,
                format_func=lambda x: dict(language_options)[x],
                key="official_language",
            )
        with c:
            st.markdown("**资料类型**")
            st.caption("官方文档 / 发布说明 / 配置 / 验证资料")
            st.caption("范围受已收录版本与语言限定")
    if str((workspace or {}).get("repository", "")).casefold() == "autowarefoundation/autoware_universe":
        examples = [
            "如何启动 Autoware 并通过命令行参数启用或禁用模块？",
            "如何使用 ROS 2 日志调试 Autoware？",
            "Autoware 规划模块由哪些部分组成？",
            "How does the start planner decide when to generate a pull-out path?",
            "What does the planning validator check before publishing a trajectory?",
            "Which parameters configure the planning validator?",
        ]
    else:
        examples = [
            f"{name} 中某个功能或参数是如何设计的？",
            "哪些公开资料描述了这个变更的相关模块与验证方式？",
            "What does the selected version's official documentation say about this feature?",
        ]
    with st.expander("从已收录资料选择示例问题"):
        st.selectbox("示例问题", examples, key="official_example", on_change=_use_example)
    st.markdown('<div class="section-rule">提出问题</div>', unsafe_allow_html=True)
    question = st.text_area("你的问题", value="", placeholder=examples[0], height=100, key="official_question")
    submitted_question = question.strip() or examples[0]
    generate_col, search_col = st.columns([1.65, 1], gap="medium")
    with generate_col:
        ask_now = st.button("生成带引用回答", type="primary", key="knowledge_generate",
                            disabled=not ready,
                            use_container_width=True)
    with search_col:
        with st.expander("只想核对原文？"):
            st.caption("直接查看 BM25 检索命中的资料，不调用生成模型。")
            search_now = st.button("仅查看检索原文", key="knowledge_search",
                                   disabled=not ready, use_container_width=True)
    st.caption("应用未设置固定生成次数上限；模型服务商的限流与计费规则仍适用。")
    if ask_now:
        with st.spinner("正在检索资料并核对引用……"):
            payload = _request(lambda: client.query_official(submitted_question, version=version, language=language), fallback="知识问答暂不可用。")
        if payload:
            st.session_state["official_result"] = ("query", submitted_question, version, language, payload)
    if search_now:
        with st.spinner("正在检索资料……"):
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
                    st.caption("当前版本与语言范围内没有正分检索命中；请检查检索范围，或改用资料中的关键术语后重试。")
                elif payload.get("status") == "ABSTAINED":
                    diagnostic = payload.get("generation") or {}
                    reason = diagnostic.get("failure_reason")
                    if reason == "MODEL_NO_SUPPORTED_ANSWER":
                        candidate_count = diagnostic.get("candidate_count", len(payload.get("evidence") or []))
                        st.caption(
                            f"模型服务已正常响应，但没有从本次检索证据形成可引用答案；系统已安全拒答。"
                            f"本次 RAG 召回 {candidate_count} 条候选。"
                        )
                        coverage = diagnostic.get("evidence_coverage") or {}
                        missing_terms = coverage.get("missing_terms") or []
                        if missing_terms:
                            missing_label = "、".join(str(term) for term in missing_terms[:6])
                            st.caption(
                                f"候选证据未覆盖问题关键词：{missing_label}。更像是检索证据没有覆盖问题重点，"
                                "不是网络或 API Key 故障。请核对下方候选，改写关键词或缩小问题后重试。"
                            )
                        else:
                            st.caption(
                                "候选片段命中了问题中的词面关键词，但这不代表内容足以回答问题；"
                                "模型仍未给出可核验结论。请核对下方原文是否包含所需接口路径或参数值。"
                                "这是模型未形成受证据支持的回答，不是网络或 API Key 故障。"
                            )
                    elif reason == "NO_VALID_EVIDENCE_CITATIONS":
                        claimed = diagnostic.get("claimed_citation_count", 0)
                        valid = diagnostic.get("valid_citation_count", 0)
                        st.caption(
                            f"模型已返回答案，但引用未能匹配本次检索证据（有效引用 {valid}/{claimed}）；"
                            "系统已隐藏答案。这是引用校验失败，不是网络或 API Key 故障。"
                        )
                    else:
                        st.caption(
                            f"回答因证据校验未通过而被隐藏（原因码：{reason or '未返回'}）；"
                            "请核对下方检索原文及本次检索技术详情。"
                        )
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
                    diagnostic = payload.get("generation") or {}
                    request_id = diagnostic.get("request_id") or "未返回"
                    st.caption(
                        f"RAG 后端返回未分类状态：{payload.get('status', 'UNKNOWN')}；下方保留了检索证据。"
                        f"仅凭该状态不能判断为网络或密钥故障。请求编号：{request_id}，可据此查后端日志。"
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
                        _evidence(remaining, heading="其他相关资料")
            else:
                _evidence(payload.get("evidence", []), heading="检索到的资料")
        else:
            st.caption("以下内容按真实检索顺序排列；请通过版本、章节与官方原文核对。")
            _consistency(payload.get("consistency_notes", []))
            _evidence(payload.get("results", []), heading="检索到的资料")
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
    *,
    target_version: str | None = None,
    objective: str | None = None,
    constraints: str | None = None,
    validation_plan: str | None = None,
) -> dict:
    agent_root = Path(__file__).resolve().parents[1] / "change-review-agent"
    if str(agent_root) not in sys.path:
        sys.path.insert(0, str(agent_root))
    from app.public_review import PublicReviewAgent
    return PublicReviewAgent(client).analyze_request(
        change_summary, change_type=change_type, impact_scope=impact_scope,
        target_version=target_version, objective=objective,
        constraints=constraints, validation_plan=validation_plan,
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
                                f"{source.get('locale', '语言未标注')}　｜　公开来源资料"
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
    elif advice.get("status") == "OUT_OF_SCOPE":
        st.subheader("当前资料范围不支持此请求")
        st.warning(advice.get(
            "message",
            "当前公开知识空间中没有适用于此请求的资料；未执行检索或模型生成。",
        ))
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


def _set_review_decision(
    decision: str, target_id: str, result: dict, session_id: str,
) -> None:
    st.session_state["official_review_decision"] = decision
    st.session_state["official_review_decision_target"] = target_id
    decided_at = datetime.now(timezone.utc).isoformat()
    st.session_state["official_review_decision_at"] = decided_at
    st.session_state.pop("official_review_audit_event_id", None)
    st.session_state.pop("official_review_audit_persisted_at", None)
    st.session_state.pop("official_review_audit_error", None)
    try:
        report = _review_report(result, decision, decided_at)
        event = _audit_repository().record(report, session_id=session_id)
        st.session_state["official_review_audit_event_id"] = event["event_id"]
        st.session_state["official_review_audit_persisted_at"] = event["persisted_at_utc"]
    except Exception:
        # Keep the exportable decision visible, but never claim it was persisted.
        st.session_state["official_review_audit_error"] = "审核结果未能写入本地审查记录。"


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
        "schema_version": 3,
        "record_scope": "review_decision_export",
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
    st.session_state.pop("official_review_audit_event_id", None)
    st.session_state.pop("official_review_audit_persisted_at", None)
    st.session_state.pop("official_review_audit_error", None)


def _save_review_draft() -> None:
    st.session_state["official_review_draft"] = st.session_state.get(
        "official_proposed_text", ""
    )
    _clear_stale_review()


def _review_panel(result: dict) -> None:
    st.subheader("人工审核")
    st.caption(
        "审核决定会追加写入本地 SQLite，并按匿名浏览器会话隔离查询；不创建公开候选版本，也不修改公共资料。"
    )
    st.info(
        "这是演示审计记录，不是企业审批系统：当前没有登录身份或权限控制；公网托管实例的临时磁盘可能在重启/重新部署后清空。"
        "请勿输入企业机密或个人敏感信息。"
    )
    request_only = result.get("request_mode") == "natural_language"
    review_target = "本次影响分析" if request_only else "会话草案"
    target_id = _review_target_id(result)
    session_id = st.session_state.setdefault("official_session_id", uuid.uuid4().hex)
    approve, reject = st.columns(2)
    approve.button(f"确认已审阅{review_target}", use_container_width=True,
                   on_click=_set_review_decision, args=("reviewed", target_id, result, session_id))
    reject.button(f"退回{review_target}", use_container_width=True,
                  on_click=_set_review_decision, args=("rejected", target_id, result, session_id))
    decision = _review_decision_for(result)
    if decision == "reviewed":
        if st.session_state.get("official_review_audit_event_id"):
            st.success(f"审核结果已写入本地审查记录。未创建候选版本，公共基线未修改。")
        else:
            st.warning(st.session_state.get("official_review_audit_error", "审核结果尚未确认持久化。"))
    elif decision == "rejected":
        if st.session_state.get("official_review_audit_event_id"):
            st.info(f"{review_target}已退回，决定已写入本地审查记录。公共基线未修改。")
        else:
            st.warning(st.session_state.get("official_review_audit_error", "退回决定尚未确认持久化。"))
    if decision:
        report = _review_report(result, decision, st.session_state.get("official_review_decision_at", ""))
        audit_event_id = st.session_state.get("official_review_audit_event_id")
        report["persisted_to_demo_sqlite"] = bool(audit_event_id)
        if audit_event_id:
            report["audit_event_id"] = audit_event_id
            report["persisted_at_utc"] = st.session_state.get("official_review_audit_persisted_at")
        safe_id = re.sub(r"[^a-zA-Z0-9_-]", "", target_id)[:24] or "session"
        st.download_button(
            "下载本次审查记录（JSON）",
            data=json.dumps(report, ensure_ascii=False, indent=2),
            file_name=f"review-{safe_id}.json", mime="application/json",
            key=f"review_export_{safe_id}",
        )
        st.caption("下载内容是本次决定的 JSON 副本；本地 SQLite 只用于此演示实例留存，不等于企业审批系统。")

    with st.expander("本匿名会话最近的审核记录"):
        try:
            history = _audit_repository().list_recent(session_id=session_id, limit=10)
            if history:
                st.table([
                    {
                        "时间（UTC）": event.get("decided_at_utc", ""),
                        "决定": "已审阅" if event.get("human_decision") == "reviewed" else "已退回",
                        "审查内容": (event.get("request_summary") or "").replace("\n", " ")[:100],
                        "证据数": len(event.get("evidence_sources") or []),
                    }
                    for event in history
                ])
            else:
                st.caption("该会话还没有持久化的审核决定。")
        except Exception:
            st.warning("暂时无法读取本地审核记录；当前页面结果仍可下载为 JSON。")


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
            st.info("没有检索到可供核对的资料。")
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
    st.session_state.pop("official_review_audit_event_id", None)
    st.session_state.pop("official_review_audit_persisted_at", None)
    st.session_state.pop("official_review_audit_error", None)


def _change_request_context_changed() -> None:
    _clear_change_request_results()


def _save_change_request() -> None:
    st.session_state["official_change_request_draft"] = st.session_state.get(
        "official_change_request", ""
    )
    _clear_change_request_results()


def _agent(
    client: PublicKnowledgeClient, ready: bool, docs: list[dict], workspace: dict | None = None,
) -> None:
    _page_header("变更审查", "研发资料变更影响审查", page_key="agent")
    current_version = st.session_state.get("official_current_version")
    version_scope = (
        f"知识库{_version_option_label(current_version, workspace)}"
        if current_version else "当前已收录资料"
    )
    if workspace:
        versions, default_version_index = _review_version_selector(workspace)
    else:
        versions, default_version_index = _published_versions(workspace), 0
    name = _workspace_name(workspace)
    st.caption(f"用自然语言描述研发变更；Agent 调用 RAG 检索{version_scope}，再整理待核对的影响候选和建议。")
    st.info(f"本次分析仅保留在当前会话，不自动修改 {name} 上游项目或公共资料。")
    _remember_document_titles(docs)
    if "official_change_request" not in st.session_state:
        st.session_state["official_change_request"] = st.session_state.get(
            "official_change_request_draft", ""
        )
    summary = st.text_area(
        "描述研发变更", height=120,
        placeholder=(
            "例如：计划调整行为路径规划的 pull-out 判断条件，请检查相关参数、模块说明与验证资料。"
            if str((workspace or {}).get("repository", "")).casefold()
            == "autowarefoundation/autoware_universe"
            else "例如：计划调整某个已收录功能的行为，请检查相关模块、参数和验证资料。"
        ),
        key="official_change_request", on_change=_save_change_request,
    )
    type_options = {
        "自动识别": None,
        "参数 / 配置变更": "parameter_config",
        "接口 / 兼容性变更": "interface_compatibility",
        "工作流 / 行为变更": "workflow_behavior",
        "规划 / 轨迹行为变更": "planning_behavior",
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
            placeholder=(
                "例如：行为路径规划、规划验证器"
                if str((workspace or {}).get("repository", "")).casefold()
                == "autowarefoundation/autoware_universe"
                else "例如：目标模块、接口或配置项"
            ),
            key="official_impact_scope", on_change=_change_request_context_changed,
        )
        target_version = st.selectbox(
            "审查目标版本", versions, index=default_version_index,
            format_func=lambda value: _version_option_label(value, workspace),
            key="agent_target_version", on_change=_change_request_context_changed,
        )
        objective = st.text_input(
            "变更目标（选填）", max_chars=800,
            placeholder="这次变更希望解决什么问题？", key="official_change_objective",
            on_change=_change_request_context_changed,
        )
        constraints = st.text_input(
            "约束条件（选填）", max_chars=800,
            placeholder="例如：保持现有接口兼容", key="official_change_constraints",
            on_change=_change_request_context_changed,
        )
        validation_plan = st.text_input(
            "验证计划（选填）", max_chars=800,
            placeholder="例如：运行规划验证器回归测试", key="official_change_validation_plan",
            on_change=_change_request_context_changed,
        )
        st.caption("未填写的目标、约束或验证计划会明确标为待补充；Agent 不会代替你推断事实。")
    st.caption(f"Agent 保留原始描述，并在最多 4 次 RAG 查询内覆盖完整请求与拆分子问题；最多选取 5 条 {target_version} 版本证据供模型分析。")
    if st.button("检索资料并分析影响", type="primary", disabled=not ready or not summary.strip()):
        with st.spinner(f"正在检索 {name} {target_version} 版本资料并整理影响建议……"):
            result = _request(
                lambda: _analyze_change_request(
                    client, summary, type_options[selected_type], impact_scope,
                    target_version=target_version, objective=objective,
                    constraints=constraints, validation_plan=validation_plan,
                ),
                fallback="变更影响分析暂未完成。",
            )
        if result:
            st.session_state["official_request_review"] = result
            st.session_state.pop("official_review", None)
            st.session_state["official_review_decision"] = None
            st.rerun()

    request_result = st.session_state.get("official_request_review")
    selected_type_code = type_options.get(st.session_state.get("official_change_type", "自动识别"))
    active_request = request_result if _request_context_matches(
        request_result, summary=summary, target_version=target_version,
        objective=objective, constraints=constraints, validation_plan=validation_plan,
        selected_type_code=selected_type_code,
        impact_scope=st.session_state.get("official_impact_scope", ""),
    ) else None
    if active_request:
        stage = 3 if _review_decision_for(active_request) else 2
        _review_steps(stage)
        plan = active_request.get("request_plan") or {}
        st.caption(
            f"变更类型：{plan.get('change_type_label', '待识别')} · "
            f"识别方式：{'人工选择' if plan.get('classification_source') == 'user_selected' else '规则识别'} · "
            f"检索关注点：{plan.get('retrieval_focus', '按原始描述检索')}"
        )
        context = active_request.get("request_context") or {}
        context_labels = {
            "objective": "变更目标", "constraints": "约束条件",
            "validation_plan": "验证计划",
        }
        st.markdown("**提案上下文**")
        context_cells = [
            ("审查目标版本", context.get("target_version") or plan.get("target_version") or target_version),
            *[
                (label, context.get(key) or value.strip() or "待补充")
                for key, label, value in (
                    ("objective", context_labels["objective"], objective),
                    ("constraints", context_labels["constraints"], constraints),
                    ("validation_plan", context_labels["validation_plan"], validation_plan),
                )
            ],
        ]
        st.dataframe(
            [{"字段": label, "当前内容": value} for label, value in context_cells],
            hide_index=True, use_container_width=True,
        )
        if context.get("missing_fields"):
            missing_labels = [context_labels.get(key, key) for key in context["missing_fields"]]
            st.caption("尚待补充：" + "、".join(missing_labels) + "。这些内容不会由 Agent 推断。")
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
                    st.caption("描述目标版本的段落内容；不会写入当前语料或上游项目。")
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
        st.info("当前会话还没有变更分析结果。请先用自然语言描述变更并检索相关资料。")
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
    st.write("页面展示已固定提交的公开资料快照。默认范围是 Documentation main 与 Universe 0.52.0 的组合，不代表单一软件发行版本。")
    if not ready:
        st.info("知识服务暂不可用，连接恢复后可查看各版本的真实资料。")
        return
    docs = _request(client.documents, fallback="版本资料目录暂不可用。") or []
    baseline = workspace.get("baseline_version") if workspace else None
    current = _confirmed_current_version(workspace)
    latest_source_time = _format_snapshot_timestamp(
        workspace.get("latest_source_retrieval_timestamp") if workspace else None
    )
    if latest_source_time:
        st.caption(f"最近收录资料：{latest_source_time}。上游新内容只有固定提交并同步入库后才会进入检索范围。")
    first, second = st.columns(2, gap="medium")
    for column, version, label in (
        (first, baseline, _version_option_label(baseline, workspace) if baseline else "历史基线"),
        (second, current, _version_option_label(current, workspace) if current else "最新已收录"),
    ):
        if not version:
            continue
        with column:
            with st.container(border=True):
                st.markdown(f"### {version}　{label}")
                members = _scope_members(version, workspace)
                matching = [row for row in docs if members is None or row.get("version") in members]
                st.write(f"知识库收录 {len(matching)} 份该版本资料。")
                for row in matching[:5]:
                    st.markdown(
                        f"- {row.get('title') or row['document_key']} · "
                        f"[固定版本来源（GitHub）]({row['source_url']})"
                    )
                    if row.get("rendered_url"):
                        st.markdown(f"  [阅读社区中文页面]({row['rendered_url']})")
                if len(matching) > 5:
                    with st.expander(f"查看其余 {len(matching)-5} 份资料"):
                        for row in matching[5:]:
                            st.markdown(
                                f"- {row.get('title') or row['document_key']} · "
                                f"[固定版本来源（GitHub）]({row['source_url']})"
                            )
                            if row.get("rendered_url"):
                                st.markdown(f"  [阅读社区中文页面]({row['rendered_url']})")
    st.info("需要对照版本内容时，在版本化知识检索中选择“全部已收录版本”；版本差异提醒只报告可核验的文字差异。")
    st.button("进入知识检索", on_click=_navigate, args=("版本检索与问答",))


def _sources(client: PublicKnowledgeClient, ready: bool, workspace: dict | None) -> None:
    _page_header("知识服务", "资料来源", page_key="sources")
    name = _workspace_name(workspace)
    st.write(f"本工作台使用 {name} 固定提交的公开资料；每条结果均保留版本信息与来源链接。")
    st.caption("英文资料来自 Autoware 官方文档仓库；中文资料来自 Tomato ROS 社区译本，不代表官方翻译，页面会显示来源对应关系是否核验。")
    coverage = _source_coverage_text(workspace)
    if coverage:
        st.info(coverage)
    if not ready:
        st.info("知识服务暂不可用，资料目录将在连接恢复后显示。")
        return
    docs = _request(client.documents, fallback="官方资料目录暂不可用。") or []
    version = st.selectbox("资料版本", [*_published_versions(workspace), "all"], format_func=lambda x: _version_option_label(x, workspace), key="source_version")
    term = st.text_input("按资料名称或工程标识筛选", key="source_filter")
    filtered = [
        row for row in docs
        if (version == "all" or row.get("version") in (_scope_members(version, workspace) or set()))
        and term.casefold() in (row.get("title", "") + " " + row.get("document_key", "")).casefold()
    ]
    st.caption(f"当前条件下有 {len(filtered)} 份固定来源资料。")
    kind = {
        "official_documentation": "官方文档",
        "community_translation": "社区中文译文",
        "github_release": "官方 Release",
        "github_issue": "官方 Issue",
        "github_pull_request": "官方 PR",
    }
    for index, row in enumerate(filtered[:12]):
        with st.container(border=True, key=f"source_row_{index}"):
            st.markdown(f"**{row.get('title') or row['document_key']}**")
            st.caption(f"{_version_option_label(row.get('version', ''), workspace)}　｜　{row.get('locale', '')}　｜　{kind.get(row.get('source_type'), '公开资料')}")
            st.markdown(f"[查看固定提交来源]({row['source_url']})")
            if row.get("rendered_url"):
                st.markdown(f"[阅读社区中文页面（网页为在线版本）]({row['rendered_url']})")
            if row.get("translation_alignment_status") == "path_matched_to_official_main":
                st.caption("译文 canonical 路径与本项目固定的官方 Documentation main 快照路径匹配；这不等于逐句翻译校验。")
            elif row.get("source_type") == "community_translation":
                st.caption("未在固定的官方 main 快照中找到同路径英文原文，版本和内容对应关系未核验。")
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
    release_status = workspace.get("retrieval_evaluation_status") if workspace else None
    release = workspace.get("retrieval_evaluation") if workspace and release_status in (
        "autoware_retrieval_v3_validated", "autoware_retrieval_v1_validated", "v4_bm25_validated", "v3_validated",
    ) else None
    experiment = workspace.get("retrieval_experiment") if workspace else None
    if isinstance(release, dict) and release.get("name") == "autoware_retrieval_v3" and release.get("policy", "").upper() == policy:
        st.markdown("**Autoware 当前检索策略评测（冻结题集，Top-5）**")
        st.caption(
            f"{workspace.get('source_count', '—')} 份固定提交官方资料、{workspace.get('chunk_count', '—')} 个文本片段，"
            "另含 2 条经人工复核并绑定原图 SHA 的图中文字证据；评测含 43 道手工问题（DEV 32 / HOLDOUT 11），"
            "仅衡量检索，不代表答案正确率、幻觉率或公网延迟。"
        )
        fields = (
            ("complete_required_sources_at_5", "完整来源@5"),
            ("required_source_recall_at_5", "来源召回@5"),
            ("image_evidence_hit_at_5", "图片证据命中@5"),
            ("no_answer_nonempty_candidate_rate", "无答案仍召回候选"),
        )
        rows = ["| 切分 / 策略 | 题数 | " + " | ".join(label for _, label in fields) + " | 错版本 | warm P95 |",
                "| --- | ---: | " + " | ".join("---:" for _ in fields) + " | ---: | ---: |"]
        for split_name, label, baseline_key in (
            ("dev", "DEV", "bm25_dev"), ("holdout", "HOLDOUT", "bm25_holdout"),
        ):
            baseline = release[baseline_key]
            selected = release[split_name]
            for strategy, values in (("BM25", baseline), ("BM25 + 图片文字", selected)):
                rows.append(
                    f"| {label} / {strategy} | {values['query_count']} | "
                    + " | ".join(f"{values[key] * 100:.1f}%" for key, _ in fields)
                    + f" | {values['version_mismatch_count']} | {values['search_p95_ms']:.2f} ms |"
                )
        st.markdown("\n".join(rows))
        st.caption(
            "图片文字候选只在至少两个图中文字词命中且不挤掉 Top-5 内唯一来源时加入；"
            "本题集 DEV 来源指标与 BM25 持平，图片证据命中由 0/4 升至 3/4；HOLDOUT 来源指标持平，图片命中由 0/2 升至 2/2。"
        )
        if release["holdout"].get("complete_required_sources_at_5", 1) < 1:
            st.warning(
                "HOLDOUT 有跨资料问题未找齐全部必需来源；这说明跨模块召回仍有缺口。"
                "查看冻结评测说明中的失败案例，后续改进应使用新评测版本验证。"
            )
            st.markdown(
                "[查看 Autoware V3 评测与失败案例]("
                "(https://github.com/Wdp-SE/enterprise-rag-agent-suite/blob/main/"
                "evaluation/autoware_retrieval_v3/README.md)"
            )
        if release["holdout"]["no_answer_nonempty_candidate_rate"] > 0:
            st.warning(
                "Holdout 无答案问题仍返回了候选（1/1）。检索命中不等于问题可回答；"
                "下一步要扩充无答案题并评估拒答阈值，不能把这个结果解释为生成准确率。"
            )
    elif isinstance(release, dict) and release.get("name") == "quality_v4" and release.get("policy", "").upper() == policy:
        st.markdown("**V4 当前 BM25 基线（索引与评测指纹已匹配）**")
        st.caption("132 份官方固定来源、1322 个文本片段，并使用 30 条人工复核截图 OCR 证据进行独立策略实验。当前线上仍使用 BM25；下面是冻结题集的离线结果，不是生成答案准确率、幻觉率或公网延迟。")
        fields = (
            ("complete_source_at_5", "完整来源@5"),
            ("anchor_recall_at_5", "原文锚点召回@5"),
            ("image_hit_at_5", "图片命中@5"),
            ("no_answer_nonempty_candidate_rate", "无答案仍召回候选"),
        )
        rows = ["| 切分 | 题数 | " + " | ".join(label for _, label in fields) + " | 错版本 | warm P95 |",
                "| --- | ---: | " + " | ".join("---:" for _ in fields) + " | ---: | ---: |"]
        for split, label in (("dev", "DEV"), ("holdout", "HOLDOUT")):
            values = release.get(split, {})
            rows.append(
                f"| {label} | {values['question_count']} | "
                + " | ".join(f"{values[key] * 100:.1f}%" for key, _ in fields)
                + f" | {values['version_mismatch_count']} | {values['warm_p95_ms']:.2f} ms |"
            )
        st.markdown("\n".join(rows))
        if isinstance(experiment, dict) and experiment.get("status") == "candidate_not_promoted":
            ocr = experiment["holdout_candidate"]
            # The baseline and candidate are shown side by side to make the trade-off explicit.
            baseline_metrics = release.get("holdout", {})
            fields = (("complete_source_at_5", "完整来源@5"), ("anchor_recall_at_5", "原文锚点召回@5"),
                      ("image_hit_at_5", "图片命中@5"), ("warm_p95_ms", "warm P95"))
            comparison_rows = ["| HOLDOUT 策略 | " + " | ".join(label for _, label in fields) + " |",
                               "| --- | " + " | ".join("---:" for _ in fields) + " |"]
            comparison_rows.append("| BM25（线上默认） | " + " | ".join(
                f"{baseline_metrics[key] * 100:.1f}%" if key != "warm_p95_ms" else f"{baseline_metrics[key]:.2f} ms"
                for key, _ in fields
            ) + " |")
            comparison_rows.append("| BM25 + 图片 OCR（实验候选） | " + " | ".join(
                f"{ocr[key] * 100:.1f}%" if key != "warm_p95_ms" else f"{ocr[key]:.2f} ms"
                for key, _ in fields
            ) + " |")
            st.markdown("**图片 OCR 候选未晋级**")
            st.markdown("\n".join(comparison_rows))
            st.caption(experiment.get("decision_reason", "候选未达到预先设定的非劣化门槛。"))
            st.caption("无答案题仍有检索候选，说明需要另做相关性阈值与拒答评测；这不等于模型产生了幻觉。图片 OCR 为派生证据，需核对固定版本原图。")
    elif isinstance(release, dict) and release.get("name") == "quality_v3" and release.get("policy", "").upper() == policy:
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
    elif workspace and workspace.get("retrieval_evaluation_status") == "expanded_corpus_pending_rebenchmark":
        st.warning(
            "语料刚扩展为英文官方文档、社区中文译文和 Autoware Universe Planning 的多快照集合；"
            "旧 43 题 V3 结果与当前语料指纹不匹配，不能作为当前成绩。BM25 仅作可解释基线，"
            "双语冻结评测尚未完成，目前没有可报告的当前语料准确率或最优策略。"
        )
    else:
        st.caption("当前后端尚未匹配已发布评测的语料与策略指纹；可能仍运行旧服务、候选策略或不同语料。不能把仓库内离线指标当作当前后端成绩。")
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
        ("资料范围", "当前知识库只包含来源清单中登记的公开资料，不覆盖上游项目的全部功能。"),
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
    name = _workspace_name(workspace)
    st.info(f"本工作台是独立工程演示，不代表 {name} 官方或任何企业内部系统。")
    if workspace:
        baseline = workspace.get("baseline_version") or "未配置"
        current = workspace.get("current_version") or "未配置"
        st.caption(
            f"历史基线 {_version_option_label(baseline, workspace)}；默认范围 {_version_option_label(current, workspace)}。"
            f"资料 {workspace.get('source_count', '未知')} 份；"
            f"当前默认策略 {workspace.get('retrieval_policy', '由服务配置')}。"
        )
    repositories = (workspace or {}).get("repositories") or [(workspace or {}).get("repository")]
    repository_links = [
        f"[{repository}](https://github.com/{repository})"
        for repository in repositories
        if isinstance(repository, str) and re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repository)
    ]
    if repository_links:
        st.markdown("公开来源仓库：" + " · ".join(repository_links))
    st.caption("提案字段和人工审核流程参考成熟工程变更治理实践；KEP 仅作流程设计启发，不是本知识库语料或兼容性声明。")


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
        st.caption(f"{_workspace_name(workspace)} 官方英文资料 / 社区中文译本")
        if workspace and workspace.get("corpus_scope"):
            st.caption("精选资料范围，不代表上游项目全量")
        for group, pages in NAV_GROUPS:
            st.markdown(f'<div class="nav-heading">{escape(NAV_GROUP_LABELS.get(group, group))}</div>', unsafe_allow_html=True)
            for page in pages:
                st.button(NAV_PAGE_LABELS.get(page, page), key="nav_" + page,
                          type="primary" if choice == page else "secondary",
                          on_click=_navigate, args=(page,), use_container_width=True)
        st.divider()
        st.caption(f"知识空间：{_workspace_name(workspace)}　｜　{'已连接' if ready else '等待连接'}")
    mismatch = public_workspace_mismatch(
        workspace, public_demo=_setting("APP_ENV", "local").strip().casefold() == "public_demo",
    )
    if mismatch:
        st.warning(mismatch)
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
        _agent(client, ready, docs or [], workspace)
    elif choice in ("可能相关资料", "修改前后对照", "人工审核"):
        _review_subpage(choice)
    elif choice == "检索评测":
        _benchmark(workspace)
    elif choice == "已知限制":
        _limits()
    else:
        _about(workspace)
