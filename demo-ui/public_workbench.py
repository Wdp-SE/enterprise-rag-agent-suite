"""Public knowledge and hypothetical change-review workbench."""

from __future__ import annotations

import json
import hashlib
import os
import posixpath
import re
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path
from html import escape
from urllib.parse import unquote, urljoin, urlsplit

import streamlit as st

from build_identity import ui_build_revision
from components.public_theme import PUBLIC_CSS
from services.public_knowledge_client import PublicKnowledgeClient
from services.review_audit import SQLiteReviewAudit
from services.rag_client import ServiceError
from services.public_workspace_profile import (
    public_workspace_mismatch,
    workspace_readiness_message,
    workspace_page_readiness_notice,
    workspace_snapshot,
    clear_workspace_bound_results,
)


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
    device_scope: dict[str, str | None] | None = None,
) -> bool:
    """Avoid stale results while keeping pre-RAG scope rejections visible."""
    if not result or result.get("request_summary") != summary.strip():
        return False
    plan = result.get("request_plan") or {}
    plan_scope = plan.get("device_scope") or {}
    if any(plan_scope.get(key) != value for key, value in (device_scope or {}).items()):
        return False
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
    if locales.intersection({"zh", "zh-CN", "zh-TW"}):
        return [("zh", "中文")]
    if locales.intersection({"en", "en-US", "en-GB"}):
        return [("en", "English")]
    return [("all", "语言元数据未声明")]


def _sync_workspace_version(workspace: dict | None) -> str | None:
    """Follow a newly published workspace version while preserving user scope otherwise."""
    current = _confirmed_current_version(workspace)
    clear_workspace_bound_results(st.session_state, workspace)
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
    counts = [row for row in rows if isinstance(row, dict) and int(row.get("count", 0)) > 0]
    if not counts:
        return None
    families = sorted({str(row.get("document_family", "工程资料")).replace("_", " ") for row in counts})
    source_count = int(workspace.get("source_count") or sum(int(row.get("count", 0)) for row in counts))
    snapshot = str(workspace.get("current_version") or "当前快照")
    return f"当前中文快照 {snapshot} 收录 {source_count} 份资料，覆盖：{'、'.join(families)}。"


_DEVICE_SCOPE_FIELDS = (
    ("device_model", "hardware_models", "设备型号"),
    ("module_sku", "module_skus", "模组 SKU"),
    ("carrier_board", "carrier_boards", "载板"),
    ("software_baseline", "software_baselines", "软件基线"),
)


def _device_scope_options(workspace: dict | None) -> dict[str, list[str]]:
    workspace = workspace or {}
    return {
        key: list(dict.fromkeys(str(value) for value in workspace.get(source, []) if value))
        for key, source, _label in _DEVICE_SCOPE_FIELDS
    }


def _device_scope_controls(workspace: dict | None, *, prefix: str) -> dict[str, str | None]:
    """Render manifest-backed hardware/software filters and return confirmed values."""
    options = _device_scope_options(workspace)
    selected = {key: None for key, _source, _label in _DEVICE_SCOPE_FIELDS}
    available = [field for field in _DEVICE_SCOPE_FIELDS if options[field[0]]]
    if not available:
        return selected
    with st.expander("可选：限定设备与软件环境", expanded=False):
        st.caption("选择后会作为硬过滤条件；未指定的维度不会被推断为兼容。")
        columns = st.columns(min(4, len(available)), gap="small")
        for index, (key, _source, label) in enumerate(available):
            widget_key = f"{prefix}_{key}"
            choices = ["不限定", *options[key]]
            if st.session_state.get(widget_key) not in choices:
                st.session_state[widget_key] = "不限定"
            with columns[index % len(columns)]:
                value = st.selectbox(label, choices, key=widget_key)
            selected[key] = value if value != "不限定" else None
    return selected


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


def _scroll_to_results() -> None:
    """Move the Streamlit page to the knowledge results after a request."""
    script = """
    <script>
    (() => {
      const scroll = () => {
        const target = document.getElementById("knowledge-results-anchor");
        if (target) target.scrollIntoView({ behavior: "smooth", block: "start" });
      };
      requestAnimationFrame(() => requestAnimationFrame(scroll));
    })();
    </script>
    """
    html_renderer = getattr(st, "html", None)
    if html_renderer is not None:
        html_renderer(script, unsafe_allow_javascript=True)
    else:
        st.components.v1.html(script, height=1, scrolling=False)


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
    """Resolve links only while they remain in the pinned repository or docs locale."""
    source = urlsplit(source_url)
    pinned_prefix = re.match(
        r"^/([A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+)/blob/([0-9a-f]{40})/", source.path
    )
    wiki_source = source.scheme == "https" and source.netloc == "wiki.seeedstudio.com"
    github_source = source.scheme == "https" and source.netloc == "github.com" and pinned_prefix
    if not wiki_source and not github_source:
        return content
    pinned_root = (
        f"https://github.com/{pinned_prefix.group(1)}/blob/{pinned_prefix.group(2)}/"
        if pinned_prefix else None
    )
    wiki_locale_root = None
    if wiki_source:
        locale = re.match(r"^/(cn|en)/", source.path)
        if locale:
            wiki_locale_root = f"https://{source.netloc}/{locale.group(1)}/"

    def replace(match: re.Match[str]) -> str:
        destination = match.group(2).strip()
        parsed = urlsplit(destination)
        if (
            not destination or any(char.isspace() for char in destination)
            or parsed.scheme or parsed.netloc
            or (not wiki_source and parsed.path.startswith("/"))
        ):
            return match.group(0)
        resolved = urljoin(source_url, destination)
        resolved_parts = urlsplit(resolved)
        if resolved_parts.scheme != "https" or resolved_parts.netloc != source.netloc:
            return match.group(0)
        if pinned_root and not resolved.startswith(pinned_root):
            return match.group(1)
        if wiki_locale_root:
            safe_root_path = urlsplit(wiki_locale_root).path
            resolved_path = posixpath.normpath(unquote(resolved_parts.path))
            normalized_root = posixpath.normpath(safe_root_path)
            if resolved_path != normalized_root and not resolved_path.startswith(f"{normalized_root}/"):
                return match.group(1)
        return f"[{match.group(1)}]({resolved})"

    return re.sub(r"(?<!!)\[([^\]]+)\]\(([^)]+)\)", replace, content)


def _document_relationship_caption(row: dict) -> str:
    relationships = row.get("document_relationships")
    if not isinstance(relationships, list):
        return ""
    labels = []
    for relation in relationships:
        if not isinstance(relation, dict):
            continue
        relation_type = relation.get("relation_type")
        state = relation.get("verification_status")
        if relation_type == "translation_of":
            label = (
                "中英文对应关系待核验（不据此判断同步差异）"
                if state != "verified" else "译文关系已核验"
            )
        elif relation_type == "localized_variant_of":
            label = "本地化变体待核验" if state != "verified" else "本地化变体关系已核验"
        elif relation_type == "references_or_depends_on":
            label = "显式工程关联已确认" if state == "verified" else "工程关联待核验"
        elif relation_type == "supersedes":
            label = "替代关系已确认" if state == "verified" else "替代关系待核验"
        else:
            continue
        if label not in labels:
            labels.append(label)
    return " · ".join(labels)


def _source_card(row: dict, *, index: int, key_prefix: str = "evidence") -> None:
    section = row.get("heading") or "正文"
    document_title = st.session_state.get("official_document_titles", {}).get(row.get("document_id")) or row.get("document_key") or "公开资料"
    version = row.get("version", "")
    current_version = st.session_state.get("official_current_version")
    latest_members = _scope_members(current_version or "", st.session_state.get("official_workspace")) if current_version else set()
    version_label = (
        "最新资料范围" if current_version and version in (latest_members or set())
        else "历史资料快照" if current_version else "版本状态未确认"
    )
    source_label = {
        "official_documentation": "官方文档",
        "community_translation": "中文社区译本",
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
            st.info("人工校对的 OCR 派生证据，请对照原图。")
            st.write(row.get("content", ""))
            st.markdown(f"[查看原图]({row['raw_url']})")
        else:
            st.markdown(f"**[{index}] {document_title}**")
            st.caption(f"章节：{section}　｜　{version_label}　｜　{_version_option_label(version, st.session_state.get('official_workspace'))}　｜　{row.get('locale', '')}　｜　{source_label}")
            relation_caption = _document_relationship_caption(row)
            if relation_caption:
                st.caption(relation_caption)
            content = _replace_markdown_images(row.get("content", ""))
            content = _rewrite_relative_source_links(content, row.get("source_url", ""))
            st.write(content)
            if row.get("source_type") == "community_translation":
                st.caption("社区维护的中文译本；关键参数请结合固定提交来源核对。")
                if row.get("rendered_url"):
                    st.markdown(f"[阅读中文社区资料]({row['rendered_url']})")
        if row.get("source_url"):
            st.markdown(f"[阅读原始页面]({row['source_url']})")
        with st.expander("技术详情"):
            st.code(f"document_key={row.get('document_key', '')}\nchunk_id={row.get('chunk_id', '')}\npolicy={row.get('retrieval_policy', '')}")
            if is_image:
                st.code(f"figure_id={row.get('figure_id', '')}\ncommit={row.get('commit', '')}\nsha256={row.get('sha256', '')}")


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
    workspace = st.session_state.get("official_workspace") or {}
    allowed_repositories = set(workspace.get("repositories") or [workspace.get("repository", "")])
    pinned_commits = {
        str(item.get("commit"))
        for item in [*(workspace.get("source_registry") or []), *(workspace.get("snapshots") or [])]
        if isinstance(item, dict) and item.get("commit")
    }
    if repository not in allowed_repositories or commit not in pinned_commits:
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
                    f"- [{source.get('version', '版本未标注')} · {source.get('locale', '语言未标注')} · 原始来源]"
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
    language_label = " / ".join(locales) if locales else "尚无已审核语料"
    st.markdown('<div class="masthead"><span class="kicker">单项目研发资料 / 版本化知识空间</span></div>', unsafe_allow_html=True)
    st.title("研发知识版本服务与变更影响审查")
    st.write(
        f"基于 {name} 的固定版本项目资料进行检索；变更审查整理同一项目内有来源支持的影响候选和证据缺口，最终由工程师确认。"
    )
    state = "已连接" if ready else (
        "许可待核实" if workspace and workspace.get("source_status") == "pending_redistribution_license"
        else "等待连接或语料激活"
    )
    status = [
        ("知识空间", name),
        ("资料来源", "单一项目固定版本公开资料"),
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
    left, right = st.columns(2, gap="medium")
    with left:
        with st.container(border=True, key="public_rag_module"):
            _module_heading("版本化研发知识服务 · RAG")
            st.markdown("### 版本化知识检索与问答")
            st.write("按资料快照、设备和软件环境检索工程资料，并保留原文出处。")
            st.button("进入知识检索", type="primary", use_container_width=True,
                      on_click=_navigate, args=("版本检索与问答",))
    with right:
        with st.container(border=True, key="public_agent_module"):
            _module_heading("Agent · 研发资料变更审查")
            st.markdown("### 研发资料变更影响审查")
            st.write("根据变更描述查找相关资料并整理修改建议，由人工确认。")
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
    versions = _published_versions(workspace)
    current = _confirmed_current_version(workspace)
    name = _workspace_name(workspace)
    default_policy = str(workspace.get("retrieval_policy", "由服务配置") if workspace else "由服务配置").upper()
    default_version_label = _version_option_label(current, workspace) if current else "无法确认最新已收录版本"
    st.markdown(
        f'<div class="context-strip"><span><strong>知识空间</strong> {escape(name)}</span>'
        f'<span><strong>资料</strong> 单一项目固定版本资料</span>'
        f'<span><strong>默认版本</strong> {escape(default_version_label)}</span>'
        f'<span><strong>默认检索</strong> {escape(default_policy)}</span></div>',
        unsafe_allow_html=True,
    )
    if current:
        latest_source_time = _format_snapshot_timestamp(
            workspace.get("latest_source_retrieval_timestamp") if workspace else None
        )
        if latest_source_time:
            st.caption(f"最近收录：{latest_source_time}")
    else:
        st.caption("暂未获取当前版本信息；请以可选范围为准。")
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
            families = sorted({
                str(row.get("document_family", "工程资料")).replace("_", " ")
                for row in (workspace or {}).get("source_breakdown", []) if isinstance(row, dict)
            })
            st.caption(" / ".join(families[:4]) if families else "当前公开工程资料")
    selected_scope = _device_scope_controls(workspace, prefix="official")
    filters = {key: value for key, value in selected_scope.items() if value is not None}
    profile = (workspace or {}).get("domain_profile") or {}
    examples = list(profile.get("example_queries") or [])
    examples = [str(item) for item in examples if isinstance(item, str) and item.strip()]
    if not examples:
        examples = [f"{name} 中某个功能或参数是如何设计的？"]
    example_key = "official_example"
    if st.session_state.get(example_key) not in examples:
        st.session_state[example_key] = examples[0]
    st.selectbox(
        "示例问题（选择后可编辑）", examples, key="official_example",
        on_change=_use_example,
    )
    st.markdown('<div class="section-rule">提出问题</div>', unsafe_allow_html=True)
    question = st.text_area("你的问题", value="", placeholder=examples[0], height=100, key="official_question")
    submitted_question = question.strip() or examples[0]
    generate_col, search_col = st.columns([1.65, 1], gap="medium")
    with generate_col:
        ask_now = st.button("生成带引用回答", type="primary", key="knowledge_generate",
                            disabled=not ready,
                            use_container_width=True)
    with search_col:
        top_k = st.slider(
            "证据条数（Top-K）", min_value=1, max_value=10, value=5,
            key="official_top_k",
            help="控制本次检索以及回答生成可使用的证据条数。版本和语言范围仍由服务端严格过滤。",
        )
        with st.expander("只想核对原文？"):
            st.caption("只显示检索原文，不生成回答。")
            search_now = st.button("仅查看检索原文", key="knowledge_search",
                                   disabled=not ready, use_container_width=True)
    st.caption("应用不设固定生成次数上限；费用和限流以服务商规则为准。")
    scroll_to_results = ask_now or search_now
    if scroll_to_results:
        st.markdown('<div id="knowledge-results-anchor"></div>', unsafe_allow_html=True)
    if ask_now:
        with st.spinner("正在检索资料并核对引用……"):
            payload = _request(
                lambda: client.query_official(
                    submitted_question, version=version, language=language, top_k=top_k,
                    **filters,
                ),
                fallback="知识问答暂不可用。",
            )
        if payload:
            st.session_state["official_result"] = ("query", submitted_question, version, language, selected_scope, payload)
            st.session_state["official_result_top_k"] = top_k
    if search_now:
        with st.spinner("正在检索资料……"):
            payload = _request(
                lambda: client.search(
                    submitted_question, version=version, language=language, top_k=top_k,
                    **filters,
                ),
                fallback="资料检索暂不可用。",
            )
        if payload:
            st.session_state["official_result"] = ("search", submitted_question, version, language, selected_scope, payload)
            st.session_state["official_result_top_k"] = top_k
    result = st.session_state.get("official_result")
    if (
        result
        and result[1:5] == (submitted_question, version, language, selected_scope)
        and st.session_state.get("official_result_top_k", 5) == top_k
    ):
        if ready and "official_document_titles" not in st.session_state:
            docs = _request(client.documents, fallback="来源目录暂不可用，仍可查看原文链接。")
            if docs is not None:
                _remember_document_titles(docs)
        mode, _, _, _, _filters, payload = result
        st.markdown('<div class="section-rule">结果与核验</div>', unsafe_allow_html=True)
        if mode == "query":
            st.subheader("回答")
            sources = payload.get("sources") or []
            if payload.get("status") == "OK" and sources:
                with st.container(border=True, key="generated_answer"):
                    claims = payload.get("claims") or []
                    if claims:
                        for claim_index, claim in enumerate(claims, 1):
                            source_indexes = claim.get("source_indexes") or []
                            citations = "　".join(f"[{index}]" for index in source_indexes)
                            st.markdown(f"**{claim_index}.** {claim.get('text', '')}　{citations}")
                    else:
                        st.write(payload["answer"])
                    st.caption("引用编号对应本次检索片段；系统已核对引用归属，仍需对照原文确认语义。")
            else:
                if payload.get("status") == "OUT_OF_SCOPE":
                    st.caption("问题涉及当前公开语料无法提供的企业内部信息；系统已停止检索与模型生成。")
                elif payload.get("status") == "NO_EVIDENCE":
                    st.caption("当前版本与语言范围内未找到匹配资料；请调整范围或改用原文术语。")
                elif payload.get("status") == "ABSTAINED":
                    diagnostic = payload.get("generation") or {}
                    reason = diagnostic.get("failure_reason")
                    if reason == "MODEL_NO_SUPPORTED_ANSWER":
                        candidate_count = diagnostic.get("candidate_count", len(payload.get("evidence") or []))
                        coverage = diagnostic.get("evidence_coverage") or {}
                        missing_terms = coverage.get("missing_terms") or []
                        if missing_terms:
                            missing_label = "、".join(str(term) for term in missing_terms[:6])
                            st.caption(
                                f"模型服务正常，但召回的 {candidate_count} 条资料未覆盖关键词：{missing_label}。"
                                "系统已拒答；请改用原文术语或缩小问题范围。"
                            )
                        else:
                            st.caption(
                                f"模型服务正常，已召回 {candidate_count} 条资料，但没有找到可支持答案的原文；"
                                "这是证据不足导致的拒答，不是网络或 API Key 故障。"
                            )
                    elif reason == "NO_VALID_EVIDENCE_CITATIONS":
                        claimed = diagnostic.get("claimed_citation_count", 0)
                        valid = diagnostic.get("valid_citation_count", 0)
                        st.caption(
                            f"答案引用未通过校验（有效引用 {valid}/{claimed}），已隐藏。请以检索原文为准。"
                        )
                    else:
                        st.caption(
                            f"回答因证据校验未通过而被隐藏（原因码：{reason or '未返回'}）；"
                            "请核对下方检索原文及本次检索技术详情。"
                        )
                elif payload.get("status") == "GENERATION_NOT_CONFIGURED":
                    st.caption("模型生成尚未启用；检索证据仍可查看。")
                elif payload.get("status") == "GENERATION_PROVIDER_UNAVAILABLE":
                    st.caption("后端无法连接模型服务；检索证据已保留，请稍后重试。")
                elif payload.get("status") == "GENERATION_PROVIDER_TIMEOUT":
                    st.caption("模型服务响应超时；检索证据已保留，请稍后重试。")
                elif payload.get("status") == "GENERATION_RATE_LIMITED":
                    st.caption("模型服务当前限流；检索证据已保留，请稍后重试。")
                elif payload.get("status") == "GENERATION_BILLING_REQUIRED":
                    st.caption("模型账户余额或计费状态受限；检索证据已保留。")
                elif payload.get("status") == "GENERATION_AUTH_FAILED":
                    st.caption("模型服务鉴权失败；检索证据已保留，请联系维护者。")
                elif payload.get("status") == "GENERATION_PROVIDER_REJECTED":
                    st.caption("模型服务拒绝了请求；检索证据已保留，请稍后重试。")
                elif payload.get("status") == "GENERATION_RESPONSE_INVALID":
                    st.caption(
                        "模型返回内容未满足引用要求，答案已隐藏；检索证据已保留。"
                    )
                elif payload.get("status") == "GENERATION_RESPONSE_TRUNCATED":
                    st.caption("模型回复被截断，未形成完整回答；检索证据已保留。")
                else:
                    diagnostic = payload.get("generation") or {}
                    request_id = diagnostic.get("request_id") or "未返回"
                    st.caption(
                        f"生成未完成（{payload.get('status', 'UNKNOWN')}）；检索证据已保留。"
                        f"联系维护者时请提供请求编号：{request_id}。"
                    )
            primary = sources[0] if sources else None
            _consistency(payload.get("consistency_notes", []), primary=primary)
            st.caption("请对照引用原文核验回答。")
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
            if payload.get("status") == "OUT_OF_SCOPE":
                st.caption("问题涉及当前公开语料无法提供的企业内部信息；系统已停止检索。")
            _consistency(payload.get("consistency_notes", []))
            _evidence(payload.get("results", []), heading="检索到的资料")
        with st.expander("本次检索技术详情"):
            st.write(
                f"检索范围：{version} · 语言：{language} · Top-K：{top_k} · "
                f"默认策略：{payload.get('retrieval_policy', '由服务配置')}"
            )
            selected_filters = [(label, selected_scope.get(key)) for key, _source, label in _DEVICE_SCOPE_FIELDS if selected_scope.get(key)]
            if selected_filters:
                st.caption("设备/软件范围：" + " · ".join(f"{label}：{value}" for label, value in selected_filters))
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
        notice = workspace_page_readiness_notice(
            workspace, "知识服务可能正在冷启动；连接恢复后可继续检索。",
        )
        if notice:
            st.info(notice)
    if scroll_to_results:
        _scroll_to_results()


def _analyze_hypothetical(
    client: PublicKnowledgeClient, selected: dict, proposed: str,
    *, device_scope: dict[str, str | None] | None = None,
) -> dict:
    agent_root = Path(__file__).resolve().parents[1] / "change-review-agent"
    if str(agent_root) not in sys.path:
        sys.path.insert(0, str(agent_root))
    from app.public_review import PublicReviewAgent
    return PublicReviewAgent(client).analyze(selected, proposed, **(device_scope or {}))


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
    language_mode: str = "zh",
    device_scope: dict[str, str | None] | None = None,
) -> dict:
    agent_root = Path(__file__).resolve().parents[1] / "change-review-agent"
    if str(agent_root) not in sys.path:
        sys.path.insert(0, str(agent_root))
    from app.public_review import PublicReviewAgent
    return PublicReviewAgent(client).analyze_request(
        change_summary, change_type=change_type, impact_scope=impact_scope,
        target_version=target_version, objective=objective,
        constraints=constraints, validation_plan=validation_plan,
        language_mode=language_mode, **(device_scope or {}),
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
    st.caption("以下为待核对线索，最终影响由人工确认。")
    references = result.get("confirmed_relations", [])
    if references:
        st.subheader("已确认文档关联")
        st.caption("该引用只确认文档关联，不代表所选段落受影响。")
        for reference in references:
            with st.container(border=True):
                relation_type = str(reference.get("relation_type") or "文档关联")
                st.markdown(f"**{escape(relation_type.replace('_', ' '))}**")
                st.caption(f"明确引用所在章节：{reference['source_heading']}")
                excerpt = _rewrite_relative_source_links(
                    _replace_markdown_images(reference["source_excerpt"]), reference.get("source_url", "")
                )
                st.write(excerpt[:300] + ("…" if len(excerpt) > 300 else ""))
                st.markdown(f"[阅读原始页面]({reference['source_url']})")
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
            st.caption(f"{evidence.get('version', '')}　｜　{evidence.get('locale', '')}")
            st.write(item.get("reason", "请核对官方原文与显式引用。"))
            content = _rewrite_relative_source_links(
                _replace_markdown_images(evidence.get("content", "")), evidence.get("source_url", "")
            )
            st.write(content[:300] + ("…" if len(content) > 300 else ""))
            st.markdown(f"[阅读原始页面]({evidence['source_url']})")
            if len(content) > 300:
                with st.expander("查看完整相关片段"):
                    st.write(content)


def _review_evidence_panel(result: dict) -> None:
    st.subheader("引用依据")
    _source_card(result["selected_source"], index=1, key_prefix="selected_source")


def _review_advice_panel(result: dict, *, context: str = "review") -> None:
    advice = result.get("review_advice", {})
    if advice.get("status") == "OK" and advice.get("sources"):
        review = advice.get("review") or {}
        interpretation = review.get("change_interpretation") or advice.get("answer", "N/A")
        coverage = result.get("coverage") or {}
        coverage_complete = coverage.get("complete", True)
        if context == "变更分析" and not coverage_complete:
            interpretation = "本次只整理已命中的证据；检索覆盖不完整，不能据此判定无影响。请先补齐语言和检查项缺口。"
        candidates = review.get("impact_candidates", [])
        source_numbers = {
            row.get("chunk_id"): number
            for number, row in enumerate(advice["sources"], start=1)
        }
        if context == "变更分析":
            st.subheader("模型辅助核对建议")
            if not coverage_complete:
                st.warning(
                    "检索覆盖不完整：当前结果只能作为已命中资料的核对线索，不能据此得出无影响结论。"
                )
            st.markdown(
                '<div class="agent-review-summary">'
                '<div class="agent-review-summary-heading"><strong>本次分析结论</strong>'
                '<span>等待人工审核</span></div>'
                f'<p>{escape(str(interpretation))}</p></div>',
                unsafe_allow_html=True,
            )
            st.caption(f"依据 {len(advice['sources'])} 条检索证据整理 · {len(candidates)} 项待核对")
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
                        st.markdown(escape(str(candidate.get("suggested_action") or "核对引用资料与变更范围后，由审核人决定后续动作。")))
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
        structured_gap_text = {
            str(row.get("message") or row.get("description") or "").strip()
            for row in result.get("evidence_gap_details") or []
        }
        follow_up = []
        follow_up.extend(
            ("证据缺口", value) for value in (review.get("evidence_gaps") or [])
            if str(value).strip() not in structured_gap_text
        )
        follow_up.extend(
            ("版本或语言歧义", value) for value in (review.get("version_ambiguities") or [])
            if str(value).strip() not in structured_gap_text
        )
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
    st.caption("草案仅用于本次审查，不会写回源资料。")
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
    st.info(
        "此处为匿名演示审核记录，可能随实例重启清空，不能替代正式审批；请勿提交敏感信息。"
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

    with st.expander("最近审核记录"):
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
        st.caption("检索与模型引用均为待核对线索。")
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
    stage_status = result.get("stage_status") or {}
    coverage = result.get("coverage") or {}
    if coverage:
        language_names = {"zh": "中文", "en": "英文"}
        attempted = "、".join(language_names.get(value, value) for value in coverage.get("attempted_languages", []))
        covered = "、".join(language_names.get(value, value) for value in coverage.get("covered_languages", [])) or "无"
        st.caption(
            f"检查项覆盖 {coverage.get('covered_check_count', 0)}/{coverage.get('required_check_count', 0)}"
            f" · 语言分支：{attempted or '未执行'} · 有命中：{covered} · "
            f"纳入证据 {coverage.get('selected_evidence_count', 0)}/{coverage.get('evidence_budget', 8)}"
        )
    if stage_status:
        stage_labels = {"planning": "问题拆解", "retrieval": "资料检索", "generation": "建议整理"}
        status_labels = {
            "OK": "完成", "EMPTY": "无结果", "FAILED": "失败",
            "SKIPPED": "未执行", "OUT_OF_SCOPE": "超出范围",
        }
        rendered = "　·　".join(
            f"{stage_labels.get(stage, stage)}：{status_labels.get(status, status)}"
            for stage, status in stage_status.items()
        )
        st.caption(f"流程状态　{rendered}")
    gap_details = result.get("evidence_gap_details") or []
    if gap_details:
        st.subheader("待补充核查")
        gap_labels = {
            "NO_REQUIRED_SOURCE": "缺少必要资料",
            "VERSION_AMBIGUITY": "版本适用性待确认",
            "IMAGE_NOT_REVIEWED": "图片证据待核验",
            "OUT_OF_SCOPE": "超出当前资料范围",
            "OUT_OF_SCOPE_PUBLIC_CORPUS": "超出当前资料范围",
            "RETRIEVAL_FAILED": "检索未完成",
            "INVALID_CITATION": "无效引用已移除",
            "MODEL_REPORTED": "模型提示待核验",
        }
        for gap in gap_details:
            gap_type = str(gap.get("gap_type") or "REVIEW_REQUIRED")
            description = str(gap.get("description") or gap.get("message") or "需要人工核查。")
            st.markdown(f"**{gap_labels.get(gap_type, '待核查事项')}** · {escape(description)}")
            missing_source = gap.get("missing_source_type") or gap.get("expected_materials")
            expected_version = gap.get("expected_version")
            metadata = []
            if missing_source:
                metadata.append(f"待补资料：{escape(str(missing_source))}")
            if expected_version:
                metadata.append(f"适用版本：{escape(str(expected_version))}")
            if metadata:
                st.caption("　｜　".join(metadata))
            suggested_query = gap.get("suggested_query")
            if suggested_query:
                st.caption(f"建议核查问题：{escape(str(suggested_query))}")
            action = gap.get("suggested_action")
            if action:
                st.markdown(escape(str(action)))
    with st.expander("检索过程与覆盖范围"):
        st.caption(f"任务编号：{result.get('task_id', '当前会话')} · 模型建议状态：{trace.get('model_status', '未调用')}")
        labels = {
            "candidate_found": "已纳入证据",
            "no_retrieval_match": "未检索到匹配",
            "candidate_outside_evidence_budget": "候选超出证据上限",
            "search_unavailable": "检索服务未完成",
        }
        for index, row in enumerate(trace.get("queries", []), 1):
            language_name = {"zh": "中文", "en": "英文"}.get(row.get("language"), row.get("language", ""))
            language_suffix = f" [{language_name}]" if language_name else ""
            st.markdown(f"{index}. **{labels.get(row.get('status'), '待核对')}**{language_suffix} · {row.get('query', '')}")
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
    profile = (workspace or {}).get("domain_profile") or {}
    example_queries = [
        str(value) for value in profile.get("example_queries", [])
        if isinstance(value, str) and value.strip()
    ]
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
            f"例如：{example_queries[0]}；请补充目标设备和软件基线，便于缩小核查范围。"
            if example_queries else "描述计划修改的设备、软件基线、部署或运维行为，并说明希望核对的资料。"
        ),
        key="official_change_request", on_change=_save_change_request,
    )
    type_options = {"自动识别": None}
    for change_type in profile.get("change_types", []):
        if not isinstance(change_type, dict):
            continue
        type_id = str(change_type.get("id") or "").strip()
        label = str(change_type.get("label") or type_id).strip()
        if type_id and label and type_id != "general":
            type_options[label] = type_id
    type_options["其他 / 待识别"] = "general"
    if st.session_state.get("official_change_type") not in type_options:
        st.session_state["official_change_type"] = "自动识别"
    with st.expander("可选：补充结构化变更信息"):
        selected_type = st.selectbox(
            "变更类型", list(type_options), key="official_change_type",
            on_change=_change_request_context_changed,
        )
        impact_scope = st.text_input(
            "影响范围（模块、项目或对象）", max_chars=160,
            placeholder="例如：设备型号、接口、刷写流程、推理部署或故障恢复步骤",
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
    device_scope = _device_scope_controls(workspace, prefix="agent")
    language_mode = "zh"
    st.caption(
        "Agent 保留原始描述，最多拆分 4 项检查；每项只检索中文资料，最多 4 次 RAG 查询，"
        f"最多选取 8 条 {target_version} 版本证据供模型分析。"
    )
    if st.button("检索资料并分析影响", type="primary", disabled=not ready or not summary.strip()):
        with st.spinner(f"正在检索 {name} {target_version} 版本资料并整理影响建议……"):
            result = _request(
                lambda: _analyze_change_request(
                    client, summary, type_options[selected_type], impact_scope,
                    target_version=target_version, objective=objective,
                    constraints=constraints, validation_plan=validation_plan,
                    language_mode=language_mode, device_scope=device_scope,
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
        device_scope=device_scope,
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
        for warning in plan.get("scope_warnings") or []:
            st.warning(warning)
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
                st.caption("需要形成段落建议时，可选择一份候选资料。")
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
                        st.markdown(f"[阅读原始页面]({selected['source_url']})")
                    proposed = st.text_area(
                        "目标段落草案", height=170, key="official_proposed_text",
                        on_change=_save_review_draft,
                    )
                    if st.button(
                        "生成修改前后对照", type="secondary", key="official_create_patch",
                        disabled=not ready or proposed.strip() == selected["content"].strip(),
                    ):
                        with st.spinner("正在核对段落差异、关联资料与引用依据……"):
                            result = _request(
                                lambda: _analyze_hypothetical(
                                    client, selected, proposed, device_scope=device_scope,
                                ),
                                fallback="具体草案核对暂未完成。",
                            )
                        if result:
                            st.session_state["official_review"] = result
                            st.session_state["official_exact_scope"] = device_scope.copy()
                            st.session_state["official_review_decision"] = None
                            st.rerun()
        exact_result = st.session_state.get("official_review")
        active_exact = (
            exact_result
            if exact_result
            and exact_result.get("selected_source", {}).get("chunk_id") == st.session_state.get("official_change_chunk")
            and st.session_state.get("official_exact_scope") == device_scope
            else None
        )
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
            notice = workspace_page_readiness_notice(
                workspace, "知识服务正在启动或暂不可用；连接恢复后可直接提交自然语言变更描述。",
            )
            if notice:
                st.info(notice)


def _review_subpage(choice: str) -> None:
    _page_header("变更审查", NAV_PAGE_LABELS[choice], page_key="review", parent=PAGE_PARENTS[choice])
    result = st.session_state.get("official_review") or st.session_state.get("official_request_review")
    if not result:
        st.info("当前会话还没有变更分析结果。请先用自然语言描述变更并检索相关资料。")
        return
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
    if not ready:
        notice = workspace_page_readiness_notice(
            workspace, "知识服务暂不可用，连接恢复后可查看各版本的真实资料。",
        )
        if notice:
            st.info(notice)
        return
    docs = _request(client.documents, fallback="版本资料目录暂不可用。") or []
    if (workspace or {}).get("workspace_id") == "edge_ai_device":
        st.write("资料快照记录语料的固定来源版本；JetPack/L4T 与设备型号是检索范围，不代表历史语料快照。")
        snapshots = (workspace or {}).get("snapshots") or []
        for index, snapshot in enumerate(snapshots):
            version = str(snapshot.get("version") or _confirmed_current_version(workspace) or "当前快照")
            with st.container(border=True, key=f"edge_snapshot_{index}"):
                st.markdown(f"### 当前固定中文资料快照 · `{version}`")
                details = [
                    f"资料数：{snapshot.get('source_count', len(docs))}",
                    f"仓库：{snapshot.get('repository') or (workspace or {}).get('repository', '未声明')}",
                    f"来源提交：`{snapshot.get('commit') or '未声明'}`",
                ]
                if snapshot.get("captured_at_date"):
                    details.append(f"固定日期：{snapshot['captured_at_date']}")
                st.caption("　·　".join(details))
        st.markdown("**资料中标注的设备与软件范围**")
        for key, label in (
            ("hardware_models", "设备型号"), ("module_skus", "模组 SKU"),
            ("carrier_boards", "载板"), ("software_baselines", "JetPack / L4T 基线"),
        ):
            values = (workspace or {}).get(key) or []
            if values:
                st.write(f"**{label}：** " + "、".join(str(value) for value in values))
        st.caption("这些是来源资料标注的适用范围；出现某个版本或型号不等于已验证兼容。")
        if docs:
            with st.expander(f"查看固定快照中的资料（{len(docs)}）"):
                for row in docs:
                    title = row.get("title") or row.get("document_key") or "公开资料"
                    st.markdown(f"- {title} · [阅读原始页面]({row['source_url']})")
        return
    st.write("仅展示已收录的公开资料快照；资料快照与软件发行版本分别管理。")
    baseline = workspace.get("baseline_version") if workspace else None
    current = _confirmed_current_version(workspace)
    latest_source_time = _format_snapshot_timestamp(
        workspace.get("latest_source_retrieval_timestamp") if workspace else None
    )
    if latest_source_time:
        st.caption(f"最近收录：{latest_source_time} · 新资料入库后即可检索。")
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
                        f"[阅读原始页面]({row['source_url']})"
                    )
                    if row.get("rendered_url"):
                        st.markdown(f"  [阅读排版页面]({row['rendered_url']})")
                if len(matching) > 5:
                    with st.expander(f"查看其余 {len(matching)-5} 份资料"):
                        for row in matching[5:]:
                            st.markdown(
                                f"- {row.get('title') or row['document_key']} · "
                                f"[阅读原始页面]({row['source_url']})"
                            )
                            if row.get("rendered_url"):
                                st.markdown(f"  [阅读排版页面]({row['rendered_url']})")
    st.info("版本对照请在知识检索中选择“全部已收录版本”。")
    st.button("进入知识检索", on_click=_navigate, args=("版本检索与问答",))


def _sources(client: PublicKnowledgeClient, ready: bool, workspace: dict | None) -> None:
    _page_header("知识服务", "资料来源", page_key="sources")
    name = _workspace_name(workspace)
    profile = (workspace or {}).get("domain_profile") or {}
    source_scope = profile.get("source_scope") or (workspace or {}).get("data_origin")
    st.write(source_scope or f"资料来自 {name} 的公开来源固定快照。")
    coverage = _source_coverage_text(workspace)
    if coverage:
        with st.expander("查看收录范围与语言对应情况"):
            st.write(coverage)
    if not ready:
        notice = workspace_page_readiness_notice(
            workspace, "知识服务暂不可用，资料目录将在连接恢复后显示。",
        )
        if notice:
            st.info(notice)
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
        "official_documentation": "公开工程文档",
        "community_translation": "中文社区译本",
        "github_release": "官方 Release",
        "github_issue": "官方 Issue",
        "github_pull_request": "官方 PR",
    }
    for index, row in enumerate(filtered[:12]):
        with st.container(border=True, key=f"source_row_{index}"):
            st.markdown(f"**{row.get('title') or row['document_key']}**")
            st.caption(f"{_version_option_label(row.get('version', ''), workspace)}　｜　{row.get('locale', '')}　｜　{kind.get(row.get('source_type'), '公开资料')}")
            st.markdown(f"[阅读原始页面]({row['source_url']})")
            if row.get("rendered_url"):
                st.markdown(f"[阅读排版页面]({row['rendered_url']})")
            if row.get("source_type") == "community_translation":
                st.caption("社区维护的中文译本；此链接固定到收录提交。")
    if len(filtered) > 12:
        with st.expander(f"查看其余 {len(filtered)-12} 份资料"):
            for row in filtered[12:]:
                st.markdown(
                    f"- {row.get('title') or row['document_key']} · "
                    f"[阅读原始页面]({row['source_url']})"
                )


def _benchmark(workspace: dict | None) -> None:
    _page_header("系统说明", "检索评测", page_key="benchmark")
    st.subheader("当前语料评测状态")
    if not workspace:
        st.info("知识服务尚未连接，当前无法确认语料与检索策略。")
        return

    status = str(workspace.get("retrieval_evaluation_status") or "pending")
    policy = str(workspace.get("retrieval_policy") or "由服务配置").upper()
    st.markdown(f"**当前策略：{policy}**")
    if status == "pending_project_evaluation" and workspace.get("source_status") == "pending_redistribution_license":
        st.warning("目标项目尚未获得可核实的内容再分发许可，目前没有可索引的项目正文，因此尚不能评测本项目 RAG 或 Agent 效果。历史其他语料的成绩不作为当前项目成绩。")
        return
    if status != "edge_ai_retrieval_v2_validated":
        st.warning(
            "当前项目尚未完成与活动语料指纹绑定的冻结评测；"
            "此前其他领域语料上的分数不适用于本知识空间，因此这里不展示为当前成绩。"
        )
    else:
        report = workspace.get("retrieval_evaluation")
        if not isinstance(report, dict) or report.get("name") != "edge_ai_retrieval_v2":
            st.warning("后端标记为已评测，但没有返回匹配的边缘设备评测报告；当前不展示未经核验的数字。")
        else:
            st.info(
                f"评测报告已绑定当前语料与策略指纹：固定题集 {report.get('case_count', 0)} 题，"
                f"DEV/HOLDOUT 各 {report.get('case_split_counts', {}).get('dev', 0)} / "
                f"{report.get('case_split_counts', {}).get('holdout', 0)} 题。"
            )
            st.caption(str(report.get("selection_reason") or "当前策略按冻结评测结果选择。"))
            rows = []
            candidates = report.get("candidates") or {}
            for split in ("dev", "holdout"):
                for strategy, values in (candidates.get(split) or {}).items():
                    rows.append({
                        "数据切分": "开发集" if split == "dev" else "留出集",
                        "检索策略": strategy,
                        "必需来源召回": values.get("mean_required_source_recall"),
                        "完整来源集率": values.get("complete_required_source_set_rate"),
                        "范围错误命中": values.get("wrong_scope_result_count"),
                        "无答案题返回候选比例": values.get("unanswerable_candidate_rate"),
                        "检索 P95 (ms)": (values.get("latency_ms") or {}).get("p95"),
                    })
            if rows:
                st.dataframe(rows, width="stretch", hide_index=True)
                st.caption(
                    "无答案题返回检索候选不等同于最终回答错误；它提示候选里有噪声，"
                    "需结合生成拒答与人工核验评估。当前 DEV/HOLDOUT 指标未显示 RRF 优于 BM25。"
                )
            agent_report = workspace.get("change_review_evaluation")
            if isinstance(agent_report, dict):
                st.markdown("**变更审查流程评测**")
                st.caption(
                    f"固定场景 {agent_report.get('case_count', 0)} 个；仅评估规则分类、检索覆盖、"
                    "范围缺口和人工审核边界，不代表大模型影响建议准确率。"
                )
                agent_rows = []
                for split, values in (agent_report.get("splits") or {}).items():
                    agent_rows.append({
                        "数据切分": "开发集" if split == "dev" else "留出集",
                        "变更类型识别率": values.get("expected_change_type_accuracy"),
                        "必需来源召回": values.get("required_source_recall_across_planned_queries"),
                        "完整来源集": f"{values.get('complete_required_source_set_count', 0)} / {values.get('answerable_case_count', 0)}",
                        "范围缺口识别率": values.get("scope_gap_detection_accuracy"),
                        "人工审核边界": values.get("manual_review_boundary_accuracy"),
                    })
                if agent_rows:
                    st.dataframe(agent_rows, width="stretch", hide_index=True)
                st.warning(
                    "影响候选精确率、建议正确性和最终回答事实性尚未完成人工盲评，不能据此宣称 Agent 准确率。"
                )

    corpus = workspace.get("corpus_fingerprint") or {}
    st.markdown("**当前运行范围**")
    st.write(
        f"{workspace.get('source_count', 0)} 份中文来源 · "
        f"{workspace.get('chunk_count', 0)} 个检索片段 · "
        f"语料指纹 `{corpus.get('fingerprint_sha256', '未返回')}`"
    )
    if status != "edge_ai_retrieval_v2_validated":
        st.caption("完成与当前语料、配置和冻结题集指纹匹配的评测后，才会展示可复现的策略比较结果。")
    st.caption("当前新语料默认使用可解释的 BM25 基线；重排策略需在同一冻结题集上验证后再考虑启用。")


def _limits() -> None:
    _page_header("系统说明", "已知限制", page_key="limits")
    for index, (title, detail) in enumerate((
        ("资料范围", "仅覆盖已收录的公开资料。"),
        ("回答", "请对照引用原文核验；证据不足时系统会拒答。"),
        ("影响分析", "没有显式关联时，Agent 提供的是待核对候选。"),
        ("人工审核", "审核记录按匿名会话保存，公网实例重启后可能清空；不会写回源资料。"),
        ("检索策略", "重排尚未在当前中文语料上完成评测，暂未启用。"),
    )):
        with st.container(border=True, key=f"limit_row_{index}"):
            st.markdown(f"**{title}**")
            st.write(detail)


def _about(workspace: dict | None) -> None:
    _page_header("系统说明", "系统说明", page_key="about")
    st.write("RAG 按版本检索公开资料并保留来源；Agent 根据证据整理影响候选和修改建议，交由人工确认。")
    name = _workspace_name(workspace)
    st.caption(f"独立工程演示 · 非 {name} 官方产品 · 不会写回源资料。")
    repositories = (workspace or {}).get("repositories") or [(workspace or {}).get("repository")]
    repository_links = [
        f"[{repository}](https://github.com/{repository})"
        for repository in repositories
        if isinstance(repository, str) and re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repository)
    ]
    if repository_links:
        st.markdown("公开来源仓库：" + " · ".join(repository_links))
    with st.expander("运行版本与资料指纹"):
        st.write(f"前端构建：`{ui_build_revision()}`")
        st.write(f"RAG 后端构建：`{(workspace or {}).get('build_revision') or 'unknown'}`")
        corpus_fingerprint = (workspace or {}).get("corpus_fingerprint") or {}
        corpus_hash = corpus_fingerprint.get("fingerprint_sha256", "unknown")
        st.write(f"语料指纹：`{corpus_hash}`")
        st.write(f"检索配置指纹：`{(workspace or {}).get('retrieval_config_fingerprint') or 'unknown'}`")
        st.write(f"评测集指纹：`{(workspace or {}).get('evaluation_fingerprint') or 'unknown'}`")
        st.caption("SHA 仅在 Git 提交可验证且工作区干净时显示；公网 Streamlit 与 RAG 服务分别部署，需核对两端版本。")


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
    ready = bool(workspace) and workspace.get("rag_ready", True) is not False
    _sync_workspace_version(workspace)
    with st.sidebar:
        st.markdown('<div class="sidebar-mark">工作台导航</div>', unsafe_allow_html=True)
        for group, pages in NAV_GROUPS:
            st.markdown(f'<div class="nav-heading">{escape(NAV_GROUP_LABELS.get(group, group))}</div>', unsafe_allow_html=True)
            for page in pages:
                st.button(NAV_PAGE_LABELS.get(page, page), key="nav_" + page,
                          type="primary" if choice == page else "secondary",
                          on_click=_navigate, args=(page,), use_container_width=True)
    mismatch = public_workspace_mismatch(
        workspace, public_demo=_setting("APP_ENV", "local").strip().casefold() == "public_demo",
    )
    if mismatch:
        st.warning(mismatch)
        st.info("为避免误用不匹配的资料，知识检索和变更审查暂不可用。")
        return
    readiness_message = workspace_readiness_message(workspace)
    if readiness_message:
        st.warning(readiness_message)
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
