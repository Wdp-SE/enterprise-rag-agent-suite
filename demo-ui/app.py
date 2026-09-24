"""Prototype Final UI for version-trusted knowledge and change review."""

from __future__ import annotations

import hashlib
import inspect
import os
from html import escape
import uuid
from pathlib import Path

import streamlit as st

from components.business_messages import business_failure_message
from components.change_impact_view import (
    render_workbench_analysis,
    render_workbench_review,
    render_workbench_publication,
)
from components.product_experience import build_status_cards, build_workflow_progress, case_knowledge_scope
from components.evidence_view import render_query_sources, render_retrieval_results
from components.prototype_final_view import (
    TASK_STATUS_LABELS,
    load_cross_case_report,
    load_evaluation_report,
    render_cross_case_evaluation,
    render_evaluation,
    render_overview,
    render_trace,
    render_versions,
)
from components.scope_view import render_scope, version_status_label
from components.status_view import render_about, render_sidebar_status
from components.workflow_view import render_downloads, render_template_summary, render_workflow_result
from config import DemoConfig, document_display_names, example_questions
from services.agent_client import AgentClient
from services.change_impact_client import ChangeImpactClient
from services.demo_cases import load_demo_cases
from services.rag_client import RAGClient, ServiceError
from services.session_guard import LLMSessionBudget


st.set_page_config(page_title="版本可信研发知识与变更审查系统", page_icon="📄", layout="wide", initial_sidebar_state="expanded")

if os.environ.get("DEMO_LEGACY_FIXTURES", "false").strip().casefold() not in {"1", "true", "yes"}:
    from public_workbench import render

    render()
    st.stop()

st.markdown("""
<style>
  :root {
    --brand-950: #102a43;
    --brand-800: #174a78;
    --brand-600: #2475c7;
    --ink-900: #172033;
    --ink-600: #5d6b7d;
    --line: #dbe5f0;
    --surface: rgba(255, 255, 255, 0.94);
    --canvas: #f4f7fb;
  }

  .stApp {
    color: var(--ink-900);
    background: var(--canvas);
  }

  [data-testid="stHeader"] {background: #ffffff;}
  [data-testid="stToolbar"], #MainMenu, footer {visibility: hidden;}

  .block-container {max-width: 1220px; padding: 1.65rem 2rem 3.5rem;}

  h1 {
    color: var(--brand-950);
    font-size: clamp(2rem, 3vw, 2.75rem) !important;
    line-height: 1.16 !important;
    letter-spacing: -0.035em !important;
    margin-bottom: 0.45rem !important;
  }

  h1::after {
    content: "";
    display: block;
    width: 3.7rem;
    height: 0.24rem;
    margin-top: 0.85rem;
    border-radius: 999px;
    background: var(--brand-600);
  }

  h2, h3, h4 {color: var(--brand-950); letter-spacing: -0.018em;}
  h3 {margin-top: 1rem !important; padding-bottom: 0.55rem; border-bottom: 1px solid var(--line);}
  [data-testid="stCaptionContainer"], .stCaption {color: var(--ink-600);}

  [data-testid="stSidebar"] {
    background: #f7f9fc;
    border-right: 1px solid var(--line);
  }
  [data-testid="stSidebar"] > div:first-child {padding-top: 1.2rem;}
  [data-testid="stSidebar"] h3 {border-bottom: 0; color: var(--brand-950);}

  [data-testid="stTabs"] [data-baseweb="tab-list"] {
    gap: 0.35rem;
    padding: 0.38rem;
    margin: 0.95rem 0 0.85rem;
    border-radius: 0.9rem;
    background: #eaf0f7;
    border: 1px solid #dce6f0;
  }
  [data-testid="stTabs"] button[data-baseweb="tab"] {
    height: 2.85rem;
    padding: 0 1.25rem;
    border-radius: 0.68rem;
    color: #53657a;
    font-weight: 650;
  }
  [data-testid="stTabs"] button[data-baseweb="tab"][aria-selected="true"] {
    color: var(--brand-800);
    background: #ffffff;
    box-shadow: none;
  }
  [data-testid="stTabs"] [data-baseweb="tab-highlight"],
  [data-testid="stTabs"] [data-baseweb="tab-border"] {display: none;}

  .boundary {
    margin: 0.35rem 0 1.15rem;
    padding: 1rem 1.15rem;
    color: #24415f;
    background: #f5f9ff;
    border: 1px solid #cfe3f7;
    border-left: 0.32rem solid var(--brand-600);
    border-radius: 0.85rem;
    box-shadow: none;
  }

  [data-testid="stMetric"] {
    min-height: 6.2rem;
    padding: 0.85rem 1rem;
    background: var(--surface);
    border: 1px solid var(--line);
    border-radius: 0.9rem;
    box-shadow: none;
  }
  [data-testid="stMetricLabel"] {color: #607086;}
  [data-testid="stMetricValue"] {color: var(--brand-950); font-size: 1.55rem; font-weight: 750;}

  [data-testid="stExpander"] {
    overflow: hidden;
    margin: 0.55rem 0;
    background: var(--surface);
    border: 1px solid var(--line);
    border-radius: 0.85rem;
    box-shadow: none;
  }
  [data-testid="stExpander"] summary {min-height: 3rem; color: #2a415a; font-weight: 640;}
  [data-testid="stAlert"] {border-radius: 0.6rem; border-width: 1px; box-shadow: none;}

  [data-testid="stTextArea"] textarea,
  [data-testid="stTextInput"] input,
  [data-baseweb="select"] > div,
  [data-testid="stFileUploader"] section {
    border-color: #cbd9e8 !important;
    border-radius: 0.72rem !important;
    background: rgba(255, 255, 255, 0.9) !important;
  }
  [data-testid="stTextArea"] textarea:focus,
  [data-testid="stTextInput"] input:focus,
  [data-baseweb="select"] > div:focus-within {
    border-color: var(--brand-600) !important;
    box-shadow: 0 0 0 0.18rem rgba(36, 117, 199, 0.12) !important;
  }

  [data-testid="stRadio"] > div {gap: 0.5rem;}
  [data-testid="stRadio"] label {padding: 0.3rem 0.55rem; border-radius: 0.55rem;}

  .stButton > button, .stDownloadButton > button {
    min-height: 2.65rem;
    border-radius: 0.7rem;
    border-color: #c7d6e6;
    font-weight: 680;
    box-shadow: none;
    transition: transform 120ms ease, box-shadow 120ms ease, border-color 120ms ease;
  }
  .stButton > button:hover, .stDownloadButton > button:hover {
    border-color: var(--brand-600);
    transform: none;
    box-shadow: none;
  }
  .stButton > button[kind="primary"] {
    color: #ffffff;
    border: 0;
    background: var(--brand-600);
    box-shadow: none;
  }

  [data-testid="stMarkdownContainer"] p,
  [data-testid="stMarkdownContainer"] li {line-height: 1.72;}
  hr {margin: 1.45rem 0 !important; border-color: #e1e8f0 !important;}
  code {color: #275a8d; background: #edf4fb; border-radius: 0.35rem;}

  .status-grid {
    display: grid;
    grid-template-columns: repeat(5, minmax(0, 1fr));
    gap: 0.75rem;
    margin: 0.65rem 0 0.35rem;
  }
  .status-item {
    padding: 0.85rem 0.9rem;
    background: #ffffff;
    border: 1px solid var(--line);
    border-radius: 0.65rem;
  }
  .status-item small {display: block; color: var(--ink-600);}
  .status-item strong {
    display: block;
    margin-top: 0.3rem;
    color: var(--brand-950);
    font-size: 1.22rem;
    line-height: 1.25;
    overflow-wrap: anywhere;
  }
  .st-key-mobile_quick_start {display: none;}
  .review-path {
    display: flex;
    flex-wrap: wrap;
    gap: 0.7rem;
    margin: 0.5rem 0 1.5rem;
    padding: 0.9rem 0;
    border-top: 1px solid var(--line);
    border-bottom: 1px solid var(--line);
  }
  .review-path span {
    flex: 1 1 9rem;
    padding: 0.45rem 0.6rem;
    border-left: 0.18rem solid var(--brand-600);
    color: var(--brand-950);
    font-weight: 620;
  }
  .st-key-rag_module [data-testid="stVerticalBlockBorderWrapper"],
  .st-key-agent_module [data-testid="stVerticalBlockBorderWrapper"] {
    min-height: 13.5rem;
    border-radius: 1rem;
    background: #ffffff;
    border-color: var(--line);
  }
  .st-key-rag_module [data-testid="stVerticalBlockBorderWrapper"] {border-top: 0.24rem solid #2475c7;}
  .st-key-agent_module [data-testid="stVerticalBlockBorderWrapper"] {border-top: 0.24rem solid #496d91;}
  .st-key-rag_module h4, .st-key-agent_module h4 {margin-top: 0.15rem !important;}
  .product-flow {
    display: grid;
    grid-template-columns: repeat(4, minmax(0, 1fr));
    gap: 0.5rem;
    padding: 0.8rem;
    margin: 0.45rem 0 1.2rem;
    border: 1px solid var(--line);
    border-radius: 0.85rem;
    background: #eef4fa;
  }
  .product-flow span {
    position: relative;
    padding: 0.45rem 1.2rem 0.45rem 0.55rem;
    color: #24415f;
    font-size: 0.91rem;
    font-weight: 600;
  }
  .product-flow span:not(:last-child)::after {
    content: "→";
    position: absolute;
    right: 0.05rem;
    color: #3c79b2;
  }
  .stButton > button:focus-visible,
  .stDownloadButton > button:focus-visible {
    outline: 2px solid var(--brand-600);
    outline-offset: 2px;
  }
  @media (prefers-reduced-motion: reduce) {
    .stButton > button, .stDownloadButton > button {transition: none;}
  }
  @media (max-width: 760px) {
    .block-container {padding: 1.35rem 1rem 3rem;}
    [data-testid="stTabs"] button[data-baseweb="tab"] {padding: 0 0.7rem;}
    h1 {font-size: 1.85rem !important;}
    .st-key-mobile_quick_start {display: block; margin: 0.6rem 0 1rem;}
    .product-flow {grid-template-columns: repeat(2, minmax(0, 1fr));}
    .product-flow span:nth-child(2)::after {display: none;}
    .status-grid {grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 0.5rem;}
    .status-item:last-child {grid-column: 1 / -1;}
  }
</style>
""", unsafe_allow_html=True)


def technical_error(exc: Exception, *, pending_review_count: int | None = None) -> None:
    public = exc.public_message if isinstance(exc, ServiceError) else str(exc)
    technical = (
        f"{exc.code} {exc.detail}" if isinstance(exc, ServiceError)
        else f"{type(exc).__name__} {exc}"
    )
    message = business_failure_message(
        technical, pending_review_count=pending_review_count
    )
    st.error(message or public or "操作失败。")
    if not st.session_state.get("_public_demo", False):
        with st.expander("技术详情"):
            if isinstance(exc, ServiceError):
                st.code(f"code={exc.code}\ndetail={exc.detail}")
            else:
                st.code(f"type={type(exc).__name__}\ndetail={exc}")


base_config = DemoConfig.from_env()
st.session_state["_public_demo"] = base_config.is_public_demo
session_id = st.session_state.setdefault("_demo_session_id", uuid.uuid4().hex)
demo_cases = load_demo_cases()
selected_case_id = st.session_state.get("demo_case_selector", "case-a")
if selected_case_id not in demo_cases:
    selected_case_id = "case-a"
    st.session_state["demo_case_selector"] = selected_case_id
if st.session_state.get("_active_demo_case") != selected_case_id:
    for state_key in (
        "v4_change_result", "rag_result", "version_diff", "workflow_result",
        "template_record", "uploaded_digest", "rag_question", "rag_example", "scope_mode",
        "custom_requirement_content", "custom_requirement_selector",
    ):
        st.session_state.pop(state_key, None)
    st.session_state["_active_demo_case"] = selected_case_id
config = base_config.for_session(session_id, selected_case_id)
selected_case = demo_cases[selected_case_id]
document_names = document_display_names()
rag = RAGClient(
    config.rag_base_url,
    config.request_timeout_seconds,
    session_id=session_id,
    retry_limit=config.rag_retry_limit,
)
agent = AgentClient(config)
change_impact = ChangeImpactClient(config, selected_case)
budget = st.session_state.get("_llm_budget")
if not isinstance(budget, LLMSessionBudget) or budget.limit != config.max_llm_calls_per_session:
    budget = LLMSessionBudget(config.max_llm_calls_per_session)
    st.session_state["_llm_budget"] = budget
try:
    rag_health = rag.health()
except Exception:
    rag_health = None
try:
    artifact_status = rag.artifact_status() if rag_health else None
except Exception:
    artifact_status = None
try:
    catalog_payload = rag.documents() if rag_health else {"documents": []}
except Exception:
    catalog_payload = {"documents": []}
catalog_documents = catalog_payload["documents"]
for item in catalog_documents:
    document_names[str(item["document_id"])] = str(item.get("title") or item["document_id"])
agent_status = agent.status()
render_sidebar_status(rag_health, artifact_status, agent_status, config.demo_data_classification)
render_about(artifact_status)

def open_change_analysis() -> None:
    if "on_change" in inspect.signature(st.tabs).parameters:
        st.session_state["product_nav"] = "变更分析"
    else:
        st.session_state["_analysis_navigation_hint"] = True
    st.session_state["_intro_dismissed"] = True


def open_knowledge_service() -> None:
    if "on_change" in inspect.signature(st.tabs).parameters:
        st.session_state["product_nav"] = "知识服务"
    else:
        st.session_state["_knowledge_navigation_hint"] = True


st.title("研发知识与变更审查工作台")
st.write(
    "在当前有效资料中查找有来源的答案，并把需求变化转化为可审核的局部修改。"
    "每一步都能查看对应资料和处理状态。"
)

nav_labels = [
    "工作台", "变更分析", "修改审核", "版本发布",
    "知识服务", "执行轨迹", "评测结果", "扩展工具",
]
pending_navigation = st.session_state.pop("_pending_navigation", None)
if pending_navigation in nav_labels and "on_change" in inspect.signature(st.tabs).parameters:
    st.session_state["product_nav"] = pending_navigation
if "on_change" in inspect.signature(st.tabs).parameters:
    nav_tabs = st.tabs(nav_labels, key="product_nav", on_change="rerun")
else:
    nav_tabs = st.tabs(nav_labels)
(
    overview_tab, analysis_tab, review_tab, publish_tab,
    rag_tab, trace_tab, evaluation_tab, agent_tab,
) = nav_tabs

with overview_tab:
    if st.session_state.get("_analysis_navigation_hint"):
        st.info("请点击上方的“变更分析”标签，继续当前案例。")
    if config.is_public_demo:
        st.info("公开演示：所有研发资料均为合成数据，用于展示版本可信检索与变更审查流程。")
    with st.container(key="mobile_quick_start"):
        st.button(
            "开始一次变更审查", type="primary",
            key="mobile_start_analysis", on_click=open_change_analysis,
        )
    st.markdown("### 两项核心能力")
    rag_column, agent_column = st.columns(2, gap="medium")
    with rag_column:
        with st.container(border=True, key="rag_module"):
            st.markdown("#### 版本可信 RAG")
            st.write("围绕当前项目与有效版本查找研发知识，查看回答所依据的原文。")
            st.caption("知识问答 · 证据检索 · 版本对比 · 引用溯源")
            st.button("进入知识服务", type="primary", key="open_knowledge", on_click=open_knowledge_service)
    with agent_column:
        with st.container(border=True, key="agent_module"):
            st.markdown("#### 变更审查 Agent")
            st.write("从需求变化出发，识别受影响资料，提出局部修改并交由人工审核。")
            st.caption("需求变更 · 影响识别 · 修改建议 · 人工审核 · 候选版本")
            st.button("开始变更审查", key="open_change", on_click=open_change_analysis)
    st.markdown(
        '<div class="product-flow"><span>研发资料</span><span>RAG 提供版本与引用依据</span>'
        '<span>Agent 分析变更影响</span><span>人工确认后形成候选版本</span></div>',
        unsafe_allow_html=True,
    )
    if st.session_state.get("_knowledge_navigation_hint"):
        st.info("请点击上方的“知识服务”标签继续。")

    cards = build_status_cards(
        selected_case, catalog_documents, rag_health, artifact_status, agent_status
    )
    st.markdown("### 当前项目状态")
    status_labels = (
        ("当前项目", "project"),
        ("当前需求版本", "current_version"),
        ("研发文档", "document_count"),
        ("文档版本", "version_count"),
        ("系统状态", "system_status"),
    )
    status_html = "".join(
        '<div class="status-item"><small>' + label + '</small><strong>'
        + escape(str(cards[key])) + '</strong></div>'
        for label, key in status_labels
    )
    st.markdown(f'<div class="status-grid">{status_html}</div>', unsafe_allow_html=True)
    if cards["current_version_id"] != "—":
        st.caption(f"当前需求文档版本标识：{cards['current_version_id']}")
    st.markdown("### 开始一次变更审查")
    with st.container(border=True):
        entry, quick_demo = st.columns([3, 2])
        with entry:
            st.markdown("**选择预置案例，或亲自修改一条当前需求。**")
            st.selectbox(
                "当前案例",
                list(demo_cases),
                format_func=lambda value: demo_cases[value].title,
                key="demo_case_selector",
            )
            change_mode = st.radio(
                "变更方式", ["预置演示案例", "自定义变更"],
                horizontal=True, key="change_mode",
            )
            if change_mode == "预置演示案例":
                st.caption(selected_case.description)
                st.button("开始分析", type="primary", key="start_analysis", on_click=open_change_analysis)
            else:
                inventory = change_impact._inventory()
                current_requirement = next(
                    item for item in inventory["items"]
                    if item["version_id"] == selected_case.requirement_new_version_id
                    and item["external_identifier"] == selected_case.changed_external_identifier
                )
                st.selectbox(
                    "选择当前需求", [selected_case.changed_external_identifier],
                    key="custom_requirement_selector",
                )
                with st.expander("查看当前需求内容", expanded=True):
                    st.write(current_requirement["content"])
                custom_content = st.text_area(
                    "修改后的需求内容",
                    value=current_requirement["content"],
                    key="custom_requirement_content",
                    height=180,
                )
                st.caption("本次输入只进入当前会话的影响分析与人工审核，不改变公共资料。")
                if st.button(
                    "开始变更审查", type="primary", key="custom_prepare",
                    disabled=not bool(rag_health) or custom_content.strip() == current_requirement["content"].strip(),
                ):
                    try:
                        with st.spinner("正在识别变更并准备引用依据与修改建议……"):
                            st.session_state.v4_change_result = change_impact.prepare_custom(
                                selected_case.changed_external_identifier, custom_content
                            )
                        st.session_state["_pending_navigation"] = "变更分析"
                        st.session_state["_intro_dismissed"] = True
                        st.rerun()
                    except Exception as exc:
                        technical_error(exc)
        with quick_demo:
            st.markdown("**快速体验预置案例**")
            st.caption("预计 3 分钟 · 版本变化、影响分析、引用依据、修改审核、安全发布。")
            st.button("开始预置案例", key="start_demo", on_click=open_change_analysis)

    st.markdown("### 审查流程")
    st.markdown(
        '<div class="review-path"><span>① 检测需求变化</span>'
        '<span>② 分析影响文档</span><span>③ 查看引用依据</span>'
        '<span>④ 审核修改建议</span><span>⑤ 发布新版本</span></div>',
        unsafe_allow_html=True,
    )
    if not st.session_state.get("_intro_dismissed", False):
        st.info(
            "建议体验流程：选择变更案例 → 查看影响分析 → 检查引用依据 → "
            "审核局部修改 → 发布候选版本。"
        )
        if st.button("隐藏引导", key="dismiss_intro"):
            st.session_state["_intro_dismissed"] = True
            st.rerun()
    st.divider()
    render_versions(catalog_documents)
with rag_tab:
    st.markdown('<div class="boundary"><b>可信问答</b>只使用允许的文档版本；<b>引用检索</b>保留文档、章节、页码和版本来源。</div>', unsafe_allow_html=True)
    scope_mode = st.radio(
        "检索范围",
        ["当前案例", "全部资料", "指定项目", "指定文档类型", "指定文档", "指定版本 / 历史版本"],
        horizontal=True,
        key="scope_mode",
    )

    def ensure_knowledge_documents() -> None:
        cases_to_seed = (
            list(demo_cases.values())
            if scope_mode != "当前案例"
            else [selected_case]
        )
        for case in cases_to_seed:
            client = (
                change_impact if case.case_id == selected_case.case_id
                else ChangeImpactClient(base_config.for_session(session_id, case.case_id), case)
            )
            client.ensure_documents()

    knowledge_documents: list[dict] = []
    if rag_health and st.session_state.get("product_nav") == "知识服务":
        try:
            with st.spinner("正在加载当前案例资料……"):
                ensure_knowledge_documents()
                knowledge_documents = change_impact._version_documents()
        except Exception as exc:
            st.warning("案例资料暂未加载成功，请检查知识服务连接后重试。")
            if not config.is_public_demo:
                st.caption(f"技术详情：{type(exc).__name__}")
    for item in knowledge_documents:
        active = item.get("active_version") or {}
        source_name = active.get("source_name")
        kind = item.get("document_type") or "研发文档"
        item["title"] = f"{kind}（{source_name}）" if source_name else str(item.get("title") or kind)
        document_names[str(item["document_id"])] = item["title"]
    if knowledge_documents:
        heading = "全部案例资料" if scope_mode == "全部资料" else "当前案例资料"
        with st.expander(f"{heading}（{len(knowledge_documents)} 份）"):
            visible = (
                knowledge_documents if scope_mode != "当前案例" else
                [item for item in knowledge_documents if item.get("project_id") == selected_case.project_id]
            )
            for item in visible:
                active = item.get("active_version") or {}
                st.markdown(
                    f"- **{item['title']}** · {active.get('version_label') or '—'}"
                    f" · {version_status_label(active.get('status')) if active else '无有效版本'}"
                )
    else:
        with st.expander("当前案例资料（待加载）"):
            for name in selected_case.baseline_documents:
                st.markdown(f"- {name}")

    scope: dict = case_knowledge_scope(scope_mode if scope_mode in {"当前案例", "全部资料"} else "当前案例", selected_case)
    scope_valid = True
    if scope_mode == "指定项目":
        projects = sorted({case.project_id for case in demo_cases.values()} | {str(item.get("project_id")) for item in knowledge_documents if item.get("project_id")})
        selected_projects = st.multiselect("选择项目", projects, default=[selected_case.project_id], key="scope_projects")
        scope["project_ids"] = selected_projects
        scope_valid = bool(selected_projects)
    elif scope_mode == "指定文档类型":
        document_types = sorted({str(item.get("document_type")) for item in knowledge_documents if item.get("document_type")})
        selected_types = st.multiselect("选择文档类型", document_types, default=document_types[:1], key="scope_types")
        scope["document_types"] = selected_types
        scope_valid = bool(selected_types)
    elif scope_mode == "指定文档":
        labels = {str(item["document_id"]): str(item.get("title") or item["document_id"]) for item in knowledge_documents}
        selected_documents = st.multiselect(
            "选择一个或多个文档", list(labels), default=list(labels)[:1],
            format_func=lambda value: labels[value], key="scope_documents",
        )
        scope["document_ids"] = selected_documents
        scope_valid = bool(selected_documents)
    elif scope_mode == "指定版本 / 历史版本":
        labels = {str(item["document_id"]): str(item.get("title") or item["document_id"]) for item in knowledge_documents}
        historical_document = st.selectbox(
            "选择文档", list(labels), format_func=lambda value: labels[value], key="historical_document"
        ) if labels else None
        selected_versions: list[str] = []
        if historical_document:
            document = next(item for item in knowledge_documents if item["document_id"] == historical_document)
            versions = list(document.get("versions") or [])
            version_labels = {
                str(item["version_id"]): f"{item['version_label']} · {version_status_label(item['status'])}"
                for item in versions
            }
            defaults = [
                str(item["version_id"]) for item in versions
                if item["status"] == "SUPERSEDED"
            ][:1]
            selected_versions = st.multiselect(
                "选择版本", list(version_labels), default=defaults or list(version_labels)[:1],
                format_func=lambda value: version_labels[value], key="scope_versions",
            )
        scope = {"version_ids": selected_versions, "active_only": False}
        scope_valid = bool(selected_versions)
    if not scope_valid:
        st.warning("请先完成检索范围选择。")
    render_scope(scope, knowledge_documents)

    mode = st.radio("知识服务功能", ["证据检索", "RAG 问答"], horizontal=True, key="rag_mode")
    suggested_questions = [f"{selected_case.changed_external_identifier} 的当前要求是什么？", *example_questions()]
    selected = st.selectbox("示例问题", suggested_questions, key="rag_example")
    question = st.text_area("问题", value=selected, key="rag_question")
    st.caption("默认只查当前案例的有效版本；选择“全部资料”才会跨案例检索。")

    if mode == "证据检索":
        top_k = st.slider("返回结果数量", 3, 10, 5, key="rag_top_k")
        if st.button("检索引用依据", type="primary", disabled=not bool(rag_health) or not scope_valid, key="retrieve_button"):
            try:
                with st.spinner("正在当前范围内检索资料……"):
                    ensure_knowledge_documents()
                    payload = rag.search_candidate_versions(question, top_k, scope)
                    st.session_state.rag_result = {
                        "mode": mode, "question": question, "scope": dict(scope), "payload": payload,
                    }
            except Exception as exc:
                technical_error(exc)
        current = st.session_state.get("rag_result")
        if current and current.get("mode") == mode and current.get("question") == question and current.get("scope") == scope:
            st.markdown("### 检索结果")
            render_retrieval_results(current["payload"]["results"], document_names)
            with st.expander("本次使用的资料范围"):
                render_scope(current["scope"], knowledge_documents)
    else:
        if not config.online_generation_allowed:
            st.info("当前环境暂未启用生成式回答，你仍可以使用证据检索查看引用依据。")
        budget_exhausted = config.is_public_demo and budget.remaining == 0
        if config.is_public_demo and config.online_generation_allowed:
            st.caption(f"本次会话剩余生成次数：{budget.remaining}")
            if budget_exhausted:
                st.warning("本次会话的生成次数已用完，仍可继续检索引用依据。")
        if st.button(
            "生成有引用的回答", type="primary",
            disabled=not bool(rag_health) or not config.online_generation_allowed or not scope_valid or budget_exhausted,
            key="query_button",
        ):
            try:
                ensure_knowledge_documents()
                if config.is_public_demo and not budget.reserve():
                    raise ServiceError("本次会话的生成次数已用完，仍可继续检索引用依据。", code="LLM_BUDGET_EXHAUSTED")
                with st.spinner("正在检索资料并生成有引用的回答……"):
                    payload = rag.query_candidate_versions(question, scope)
                    fallback = []
                    if payload.get("status") != "OK":
                        fallback = rag.search_candidate_versions(question, 5, scope)["results"]
                    st.session_state.rag_result = {
                        "mode": mode, "question": question, "scope": dict(scope),
                        "payload": payload, "fallback": fallback,
                    }
                    st.rerun()
            except Exception as exc:
                technical_error(exc)
        current = st.session_state.get("rag_result")
        if current and current.get("mode") == mode and current.get("question") == question and current.get("scope") == scope:
            payload = current["payload"]
            st.markdown(f"**问题：** {question}")
            st.markdown("### 回答")
            if payload.get("status") == "OK" and payload.get("answer") != "N/A" and payload.get("sources"):
                st.write(payload["answer"])
                st.markdown("### 引用依据")
                render_query_sources(payload["sources"], document_names, trace=payload.get("trace"))
            else:
                if payload.get("status") == "GENERATION_NOT_CONFIGURED":
                    st.info("当前服务未配置在线回答，仍可查看下方检索到的引用依据。")
                elif payload.get("status") == "NO_EVIDENCE":
                    st.info("当前范围内未找到足够相关的资料，可以调整问题或扩大检索范围。")
                else:
                    st.info("本次生成未通过引用校验，仍可查看下方检索到的资料。")
                if current.get("fallback"):
                    st.markdown("### 检索到的引用依据")
                    render_retrieval_results(current["fallback"], document_names)
            with st.expander("本次使用的资料范围"):
                render_scope(current["scope"], knowledge_documents)

    with st.expander("版本对比"):
        versioned_documents = [item for item in knowledge_documents if len(item.get("versions") or []) >= 2]
        if not versioned_documents:
            st.info("当前目录没有可对比的两个版本。导入新版本后可在此查看 Section 级差异。")
        else:
            diff_labels = {
                str(item["document_id"]): str(item.get("title") or item["document_id"])
                for item in versioned_documents
            }
            diff_document_id = st.selectbox(
                "对比文档", list(diff_labels), format_func=lambda value: diff_labels[value], key="diff_document"
            )
            diff_document = next(item for item in versioned_documents if item["document_id"] == diff_document_id)
            diff_versions = {
                str(item["version_id"]): f"{item['version_label']} · {version_status_label(item['status'])}"
                for item in diff_document["versions"]
            }
            version_ids = list(diff_versions)
            left, right = st.columns(2)
            from_version = left.selectbox(
                "原版本", version_ids, format_func=lambda value: diff_versions[value], key="diff_from"
            )
            to_version = right.selectbox(
                "新版本", version_ids, index=min(1, len(version_ids) - 1),
                format_func=lambda value: diff_versions[value], key="diff_to",
            )
            if st.button("比较版本", disabled=from_version == to_version, key="diff_button"):
                try:
                    st.session_state.version_diff = rag.diff(diff_document_id, from_version, to_version)
                except Exception as exc:
                    technical_error(exc)
            version_diff = st.session_state.get("version_diff")
            if version_diff and version_diff.get("document_id") == diff_document_id:
                metrics = st.columns(4)
                change_labels = {"ADDED": "新增", "REMOVED": "已移除", "MODIFIED": "已修改", "UNCHANGED": "未变化"}
                for column, change in zip(metrics, change_labels):
                    column.metric(change_labels[change], version_diff["summary"].get(change, 0))
                for row in version_diff["sections"]:
                    with st.expander(f"{change_labels.get(row['change_type'], '变化')} · {' / '.join(row['section_path'])}"):
                        with st.expander("技术详情"):
                            st.json(row)

    if not rag_health:
        if config.is_public_demo:
            st.info("公共免费演示后端可能正在启动，请稍后重试。")
            if st.button("重新连接", key="reconnect_backend"):
                st.rerun()
        else:
            st.info("启动提示：请先启动本地 RAG 服务，再刷新页面。")

with agent_tab:
    st.markdown("### 扩展能力：按模板起草文档")
    st.caption("模板文档起草作为扩展能力保留；核心流程是需求变更、影响分析、修改审核与安全发布。")
    st.markdown("#### 第一步：选择项目与文档版本范围")
    projects = sorted({str(item.get("project_id")) for item in catalog_documents if item.get("project_id")})
    if not projects:
        projects = ["DEMO-RD"]
    selected_project = st.selectbox("项目", projects, key="agent_project")
    project_documents = [item for item in catalog_documents if str(item.get("project_id")) == selected_project]
    scope_mode = st.radio(
        "文档范围", ["项目内全部当前版本", "指定文档", "指定版本 / 历史版本"],
        horizontal=True, key="agent_scope_mode",
    )
    agent_scope: dict = {"project_ids": [selected_project], "active_only": True}
    agent_scope_valid = True
    if scope_mode == "指定文档":
        labels = {str(item["document_id"]): str(item.get("title") or item["document_id"]) for item in project_documents}
        selected_documents = st.multiselect(
            "文档", list(labels), default=list(labels)[:1],
            format_func=lambda value: labels[value], key="agent_documents",
        )
        agent_scope["document_ids"] = selected_documents
        agent_scope_valid = bool(selected_documents)
    elif scope_mode == "指定版本 / 历史版本":
        versions = {
            str(version["version_id"]): f"{item.get('title') or item['document_id']} · {version['version_label']} · {version_status_label(version['status'])}"
            for item in project_documents for version in item.get("versions", [])
        }
        selected_versions = st.multiselect(
            "版本", list(versions), default=list(versions)[:1],
            format_func=lambda value: versions[value], key="agent_versions",
        )
        agent_scope = {"project_ids": [selected_project], "version_ids": selected_versions, "active_only": False}
        agent_scope_valid = bool(selected_versions)
    if not agent_scope_valid:
        st.warning("请先完成项目和文档范围选择。")
    render_scope(agent_scope, catalog_documents)

    with st.expander("历史任务", expanded=False):
        try:
            histories = agent.list_workflows()
            if not histories:
                st.caption("暂无历史任务。")
            for item in histories[:20]:
                cols = st.columns([4, 2, 2, 2])
                cols[0].write(f"{item['workflow_id']} · {item['template_name']}")
                cols[1].write(item["workflow_status"])
                cols[2].write(f"需刷新 {item['stale_evidence_count']}")
                if cols[3].button("查看", key=f"history_view_{item['workflow_id']}"):
                    st.session_state.workflow_result = agent.get_workflow(item["workflow_id"])
                if item["workflow_status"] != "APPROVED" and st.button("继续执行", key=f"history_resume_{item['workflow_id']}"):
                    st.session_state.workflow_result = agent.resume_workflow(item["workflow_id"])
                    st.rerun()
        except Exception as exc:
            technical_error(exc)

    st.markdown("### 第二步：选择并解析 Word 模板")
    st.caption("支持 Heading/标题 1–3、Outline Level、段落、表格和占位符，并尽量保持 Run 格式。")
    source_type = st.radio("模板来源", ["需求变更影响分析模板", "上传 .docx"], horizontal=True, key="template_source")
    if source_type == "需求变更影响分析模板":
        if st.button("加载旗舰模板", disabled=not agent_scope_valid, key="load_demo_template"):
            try:
                st.session_state.template_record = agent.load_demo_template(agent_scope)
                st.session_state.pop("workflow_result", None)
            except Exception as exc:
                technical_error(exc)
    else:
        upload = st.file_uploader("上传结构化 Word 模板", type=["docx"], key="docx_upload")
        if upload is not None and agent_scope_valid:
            digest = hashlib.sha256(upload.getvalue()).hexdigest()
            if st.session_state.get("uploaded_digest") != digest:
                try:
                    st.session_state.template_record = agent.save_upload(upload.name, upload.getvalue(), agent_scope)
                    st.session_state.uploaded_digest = digest
                    st.session_state.pop("workflow_result", None)
                except Exception as exc:
                    technical_error(exc)
    record = st.session_state.get("template_record")
    if record:
        if record.get("scope") != agent_scope:
            st.warning("检索范围已变化，请重新加载模板以创建新的不可变 Scope。")
        render_template_summary(record)
        rag_ready = bool(rag_health and artifact_status and artifact_status.get("artifact_status") == "COMPLETE")
        if st.button(
            "第三步：运行工作流", type="primary",
            disabled=not rag_ready or record.get("scope") != agent_scope,
            key="run_workflow",
        ):
            try:
                with st.spinner("正在执行范围受控检索和证据起草……"):
                    st.session_state.workflow_result = agent.run_workflow(record)
                st.rerun()
            except Exception as exc:
                technical_error(exc)
        if not rag_ready:
            st.info("RAG 服务或检索资料尚未就绪，请稍后重试。")

    result = st.session_state.get("workflow_result")
    if result:
        st.markdown("### 第六步：引用依据与字段草稿")
        render_scope(
            result["scope"], catalog_documents,
            title="本次工作流实际使用的资料范围",
        )
        render_workflow_result(result, document_names)
        st.markdown("### 第五步：人工逐章节审核")
        reviewer = st.text_input("审核人", key=f"reviewer_{result['workflow_id']}")
        for section in result["sections"]:
            if not section["fields"]:
                continue
            with st.expander(f"审核 · {section['section_title']} · {section['review'].get('status', 'PENDING')}"):
                edits = {}
                for field in section["fields"]:
                    value = st.text_area(
                        field["field_name"], value=field["content"],
                        key=f"review_field_{result['workflow_id']}_{field['field_id']}",
                    )
                    if value.strip() != field["content"].strip():
                        edits[field["field_id"]] = value
                comment = st.text_input("审核意见", key=f"review_comment_{result['workflow_id']}_{section['section_id']}")
                approve, reject = st.columns(2)
                if approve.button("通过章节", disabled=not reviewer.strip(), key=f"approve_{result['workflow_id']}_{section['section_id']}"):
                    try:
                        st.session_state.workflow_result = agent.review_section(
                            result["workflow_id"], section_id=section["section_id"], action="APPROVED",
                            reviewer=reviewer, comment=comment, edited_fields=edits,
                        )
                        st.rerun()
                    except Exception as exc:
                        technical_error(exc)
                if reject.button("驳回章节", disabled=not reviewer.strip(), key=f"reject_{result['workflow_id']}_{section['section_id']}"):
                    try:
                        st.session_state.workflow_result = agent.review_section(
                            result["workflow_id"], section_id=section["section_id"], action="REJECTED",
                            reviewer=reviewer, comment=comment, edited_fields=edits,
                        )
                        st.rerun()
                    except Exception as exc:
                        technical_error(exc)
        st.markdown("### 第六步：生成正式文档")
        pending_review_count = sum(
            bool(section["fields"]) and section.get("review", {}).get("status") != "APPROVED"
            for section in result["sections"]
        )
        if st.button(
            "生成已批准文档", type="primary", disabled=not result["all_sections_approved"],
            key=f"finalize_{result['workflow_id']}",
        ):
            try:
                st.session_state.workflow_result = agent.finalize_document(result["workflow_id"])
                st.rerun()
            except Exception as exc:
                technical_error(exc, pending_review_count=pending_review_count)
        if not result["all_sections_approved"]:
            st.info(
                business_failure_message(
                    "REVIEW_REQUIRED", pending_review_count=pending_review_count
                )
            )
        render_downloads(result, agent.artifact_bytes)

def render_review_progress(result: dict | None) -> None:
    state = (result or {}).get("state") or {}
    status = TASK_STATUS_LABELS.get(state.get("status"), "尚未开始")
    st.markdown("#### 任务进度")
    st.caption(f"任务：{state.get('task_id') or '尚未创建'}　|　状态：{status}")
    symbols = {"已完成": "✓", "待人工审核": "◉", "待校验": "◉", "已阻断": "⛔"}
    with st.container(border=True):
        for label, step_status in build_workflow_progress(result):
            st.write(f"{symbols.get(step_status, '○')} {label}：{step_status}")


v4_result = st.session_state.get("v4_change_result")
with analysis_tab:
    st.markdown("### 本次变更")
    st.write(
        f"**当前组织：** {selected_case.organization_id}　　"
        f"**当前项目：** {selected_case.project_id}　　"
        "**数据：** 完全合成"
    )
    st.markdown(f"**{selected_case.title}**")
    st.write(selected_case.description)
    if v4_result:
        affected = [
            (v4_result.get("items") or {}).get(row.get("impacted_item_id"), {}).get("external_identifier")
            for row in (v4_result.get("state") or {}).get("impacts") or []
        ]
        if affected:
            st.caption("已发现影响目标：" + "、".join(str(item) for item in affected if item))
    else:
        st.caption("运行分析后，将展示受影响文档和可追溯的引用依据。")
    render_review_progress(v4_result)
    change_status = change_impact.status()
    if not rag_health:
        st.info("RAG 版本服务暂不可用；页面说明与案例信息仍可查看。")
    if change_mode == "预置演示案例":
        if st.button(
            "运行变更分析",
            type="primary",
            disabled=not bool(rag_health) or not change_status["ready"],
            key="v4_prepare",
        ):
            try:
                with st.spinner("正在解析版本、识别变化并发现影响……"):
                    st.session_state.v4_change_result = change_impact.prepare_demo()
                st.rerun()
            except Exception as exc:
                technical_error(exc)
    elif not v4_result:
        st.info("请先在工作台填写修改后的需求内容，再开始变更审查。")
    render_workbench_analysis(v4_result)

with review_tab:
    st.markdown("### 修改审核")
    if v4_result and v4_result.get("custom_change"):
        st.info("本次修改建议来自你的需求输入；引用依据展示的是当前有效资料，批准前请核对两者差异。")
    render_review_progress(v4_result)
    render_workbench_review(v4_result)
    if not v4_result:
        st.info("请先到“变更分析”运行分析，再审核局部修改。")
    if v4_result:
        state = v4_result["state"]
        patches = state.get("patches", [])
        if patches:
            patch = patches[0]
            st.markdown("### 人工审核")
            reviewer = st.text_input("审核人", key=f"v4_reviewer_{state['task_id']}")
            edited = st.text_area(
                "审核后的建议内容",
                value=patch["proposed_content"],
                key=f"v4_patch_edit_{patch['patch_id']}",
            )
            comment = st.text_input("审核意见", key=f"v4_comment_{patch['patch_id']}")
            approve, save_edit, reject = st.columns(3)
            if approve.button(
                "批准修改",
                disabled=not reviewer.strip(),
                key=f"v4_approve_{patch['patch_id']}",
            ):
                try:
                    v4_result["state"] = change_impact.review_patch(
                        state["task_id"], patch["patch_id"],
                        action="APPROVE", reviewer=reviewer, comment=comment,
                    )
                    st.session_state.v4_change_result = v4_result
                    st.rerun()
                except Exception as exc:
                    technical_error(exc)
            if save_edit.button(
                "保存人工修改",
                disabled=not reviewer.strip() or edited.strip() == patch["proposed_content"].strip(),
                key=f"v4_edit_{patch['patch_id']}",
            ):
                try:
                    v4_result["state"] = change_impact.review_patch(
                        state["task_id"], patch["patch_id"],
                        action="EDIT", reviewer=reviewer, comment=comment,
                        edited_content=edited,
                    )
                    st.session_state.v4_change_result = v4_result
                    st.rerun()
                except Exception as exc:
                    technical_error(exc)
            if reject.button(
                "拒绝修改",
                disabled=not reviewer.strip(),
                key=f"v4_reject_{patch['patch_id']}",
            ):
                try:
                    v4_result["state"] = change_impact.review_patch(
                        state["task_id"], patch["patch_id"],
                        action="REJECT", reviewer=reviewer, comment=comment,
                    )
                    st.session_state.v4_change_result = v4_result
                    st.rerun()
                except Exception as exc:
                    technical_error(exc)

with publish_tab:
    st.markdown("### 版本发布")
    render_review_progress(v4_result)
    if v4_result and v4_result.get("custom_change"):
        st.info("自定义变更只到人工审核；当前不会生成或发布候选版本，也不会修改公共基线。")
    else:
        render_workbench_publication(v4_result)
        if not v4_result:
            st.info("请先完成变更分析和人工审核。")
        if v4_result:
            state = v4_result["state"]
            apply_col, publish_col = st.columns(2)
            if apply_col.button(
                "应用已批准修改",
                disabled=state["status"] != "APPLY_READY",
                key=f"v4_apply_{state['task_id']}",
            ):
                try:
                    applied = change_impact.apply(state["task_id"])
                    v4_result["state"] = applied["state"]
                    v4_result["apply_results"] = applied["apply_results"]
                    st.session_state.v4_change_result = v4_result
                    st.rerun()
                except Exception as exc:
                    technical_error(exc)
            if publish_col.button(
                "校验并安全发布新版本",
                disabled=state["status"] != "CANDIDATE_READY",
                key=f"v4_publish_{state['task_id']}",
            ):
                try:
                    v4_result["state"] = change_impact.publish(state["task_id"])
                    st.session_state.v4_change_result = v4_result
                    st.rerun()
                except Exception as exc:
                    technical_error(exc)
            candidate_path = state.get("candidate_path")
            if candidate_path and Path(candidate_path).is_file():
                st.download_button(
                    "下载候选版本文档",
                    data=Path(candidate_path).read_bytes(),
                    file_name=f"{selected_case.candidate_version_id}_candidate.docx",
                    mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                    key=f"v4_download_{state['task_id']}",
                )

with trace_tab:
    render_trace(st.session_state.get("v4_change_result"))

with evaluation_tab:
    render_evaluation(load_evaluation_report())
    render_cross_case_evaluation(load_cross_case_report())

st.divider()
st.caption("研发资料 → 版本治理 → 可信检索 → 变更影响 → 修改审核 → 候选版本 → 安全发布")
