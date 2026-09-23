"""Prototype Final UI for version-trusted knowledge and change review."""

from __future__ import annotations

import hashlib
import uuid
from pathlib import Path

import streamlit as st

from components.business_messages import business_failure_message
from components.change_impact_view import render_workbench_summary
from components.evidence_view import render_query_sources, render_retrieval_results
from components.prototype_final_view import (
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


st.set_page_config(page_title="版本可信研发知识与变更审查系统", page_icon="📄", layout="wide")
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
    background:
      radial-gradient(circle at 94% 3%, rgba(74, 144, 226, 0.13), transparent 26rem),
      linear-gradient(180deg, #f9fbfe 0%, var(--canvas) 38%, #f7f9fc 100%);
  }

  [data-testid="stHeader"] {background: rgba(249, 251, 254, 0.82); backdrop-filter: blur(12px);}
  [data-testid="stToolbar"], #MainMenu, footer {visibility: hidden;}

  .block-container {max-width: 1260px; padding: 2.35rem 2.4rem 4.5rem;}

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
    background: linear-gradient(90deg, var(--brand-600), #48a9e6);
  }

  h2, h3, h4 {color: var(--brand-950); letter-spacing: -0.018em;}
  h3 {margin-top: 1.5rem !important; padding-bottom: 0.55rem; border-bottom: 1px solid var(--line);}
  [data-testid="stCaptionContainer"], .stCaption {color: var(--ink-600);}

  [data-testid="stSidebar"] {
    background: linear-gradient(180deg, #f8fbff 0%, #edf4fb 100%);
    border-right: 1px solid var(--line);
  }
  [data-testid="stSidebar"] > div:first-child {padding-top: 1.2rem;}
  [data-testid="stSidebar"] h3 {border-bottom: 0; color: var(--brand-950);}

  [data-testid="stTabs"] [data-baseweb="tab-list"] {
    gap: 0.35rem;
    padding: 0.38rem;
    margin: 1.3rem 0 1rem;
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
    box-shadow: 0 5px 16px rgba(34, 72, 110, 0.10);
  }
  [data-testid="stTabs"] [data-baseweb="tab-highlight"],
  [data-testid="stTabs"] [data-baseweb="tab-border"] {display: none;}

  .boundary {
    margin: 0.35rem 0 1.15rem;
    padding: 1rem 1.15rem;
    color: #24415f;
    background: linear-gradient(135deg, #eef6ff 0%, #f8fbff 100%);
    border: 1px solid #cfe3f7;
    border-left: 0.32rem solid var(--brand-600);
    border-radius: 0.85rem;
    box-shadow: 0 7px 20px rgba(36, 117, 199, 0.07);
  }

  [data-testid="stMetric"] {
    min-height: 6.2rem;
    padding: 0.85rem 1rem;
    background: var(--surface);
    border: 1px solid var(--line);
    border-radius: 0.9rem;
    box-shadow: 0 6px 20px rgba(31, 63, 96, 0.06);
  }
  [data-testid="stMetricLabel"] {color: #607086;}
  [data-testid="stMetricValue"] {color: var(--brand-950); font-size: 1.55rem; font-weight: 750;}

  [data-testid="stExpander"] {
    overflow: hidden;
    margin: 0.55rem 0;
    background: var(--surface);
    border: 1px solid var(--line);
    border-radius: 0.85rem;
    box-shadow: 0 5px 18px rgba(31, 63, 96, 0.045);
  }
  [data-testid="stExpander"] summary {min-height: 3rem; color: #2a415a; font-weight: 640;}
  [data-testid="stAlert"] {border-radius: 0.8rem; border-width: 1px; box-shadow: 0 5px 16px rgba(31, 63, 96, 0.045);}

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
    box-shadow: 0 4px 12px rgba(31, 63, 96, 0.06);
    transition: transform 120ms ease, box-shadow 120ms ease, border-color 120ms ease;
  }
  .stButton > button:hover, .stDownloadButton > button:hover {
    border-color: var(--brand-600);
    transform: translateY(-1px);
    box-shadow: 0 7px 16px rgba(31, 92, 150, 0.12);
  }
  .stButton > button[kind="primary"] {
    color: #ffffff;
    border: 0;
    background: linear-gradient(135deg, #1f67ad 0%, #2f86d7 100%);
    box-shadow: 0 7px 18px rgba(36, 117, 199, 0.22);
  }

  [data-testid="stMarkdownContainer"] p,
  [data-testid="stMarkdownContainer"] li {line-height: 1.72;}
  hr {margin: 1.45rem 0 !important; border-color: #e1e8f0 !important;}
  code {color: #275a8d; background: #edf4fb; border-radius: 0.35rem;}

  .product-flow {
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    gap: 0.35rem;
    margin: 0.55rem 0 1.5rem;
    padding: 1rem 1.1rem;
    color: #173b50;
    background: #edf5f6;
    border-left: 0.35rem solid #167d8d;
  }
  .product-flow span::before, .product-flow b + span::before {
    content: "›";
    margin-right: 0.35rem;
    color: #6c8790;
  }

  @media (max-width: 760px) {
    .block-container {padding: 1.35rem 1rem 3rem;}
    [data-testid="stTabs"] button[data-baseweb="tab"] {padding: 0 0.7rem;}
    h1 {font-size: 1.85rem !important;}
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
selected_case_id = st.selectbox(
    "演示案例",
    list(demo_cases),
    format_func=lambda value: demo_cases[value].title,
    key="demo_case_selector",
)
if st.session_state.get("_active_demo_case") != selected_case_id:
    for state_key in (
        "v4_change_result", "rag_result", "version_diff", "workflow_result",
        "template_record", "uploaded_digest",
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

st.title("版本可信研发知识与变更审查系统")
st.caption("面向软件研发变更：只使用允许版本的资料，追溯引用依据，审查局部修改，并安全发布新的文档版本。")
st.caption(selected_case.description)
if config.is_public_demo:
    st.info(
        "**Public Demo** · 所有研发资料均为合成数据；Session 操作是临时的，"
        "免费服务可能存在首次访问冷启动。本原型不代表生产部署。"
    )

overview_tab, versions_tab, rag_tab, change_tab, trace_tab, evaluation_tab, agent_tab = st.tabs([
    "项目概览",
    "文档与版本",
    "可信检索与版本差异",
    "变更影响与修改审核",
    "执行轨迹",
    "评测结果",
    "扩展：文档起草",
])

with overview_tab:
    render_overview(catalog_documents, st.session_state.get("v4_change_result"))

with versions_tab:
    render_versions(catalog_documents)

with rag_tab:
    st.markdown('<div class="boundary"><b>可信问答</b>只使用允许的文档版本；<b>引用检索</b>保留文档、章节、页码和版本来源。</div>', unsafe_allow_html=True)
    if catalog_documents:
        with st.expander(f"当前文档目录（{len(catalog_documents)} 份）"):
            for item in catalog_documents:
                active = item.get("active_version") or {}
                status = (
                    version_status_label(active.get("status"))
                    if active else "无有效版本"
                )
                version = active.get("version_label") or "—"
                st.markdown(f"- **{item.get('title') or item['document_id']}** · {version} · {status}")
                st.caption(
                    f"项目：{item.get('project_name') or item.get('project_id', '—')}"
                    f"　|　类型：{item.get('document_type', '—')}"
                )
    else:
        active_prefix = "safe-" if config.online_generation_allowed else "rdv2-"
        active_documents = [
            (document_id, name)
            for document_id, name in document_names.items()
            if document_id.startswith(active_prefix)
        ]
        if active_documents:
            with st.expander(f"当前知识库文档（{len(active_documents)} 份）"):
                for _, name in active_documents:
                    st.markdown(f"- **{name}**")

    scope_mode = st.radio(
        "检索范围",
        ["全部当前有效文档", "指定项目", "指定文档类型", "指定文档", "指定版本 / 历史版本"],
        horizontal=True,
        key="scope_mode",
    )
    scope: dict = {"active_only": True}
    scope_valid = True
    if scope_mode == "指定项目":
        projects = sorted({str(item.get("project_id")) for item in catalog_documents if item.get("project_id")})
        selected_projects = st.multiselect("选择项目", projects, default=projects[:1], key="scope_projects")
        scope["project_ids"] = selected_projects
        scope_valid = bool(selected_projects)
    elif scope_mode == "指定文档类型":
        document_types = sorted({str(item.get("document_type")) for item in catalog_documents if item.get("document_type")})
        selected_types = st.multiselect("选择文档类型", document_types, default=document_types[:1], key="scope_types")
        scope["document_types"] = selected_types
        scope_valid = bool(selected_types)
    elif scope_mode == "指定文档":
        labels = {str(item["document_id"]): str(item.get("title") or item["document_id"]) for item in catalog_documents}
        selected_documents = st.multiselect(
            "选择一个或多个文档", list(labels), default=list(labels)[:1],
            format_func=lambda value: labels[value], key="scope_documents",
        )
        scope["document_ids"] = selected_documents
        scope_valid = bool(selected_documents)
    elif scope_mode == "指定版本 / 历史版本":
        labels = {str(item["document_id"]): str(item.get("title") or item["document_id"]) for item in catalog_documents}
        historical_document = st.selectbox(
            "选择文档", list(labels), format_func=lambda value: labels[value], key="historical_document"
        ) if labels else None
        selected_versions: list[str] = []
        if historical_document:
            document = next(item for item in catalog_documents if item["document_id"] == historical_document)
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
    render_scope(scope, catalog_documents)

    mode = st.radio("功能", ["RAG 问答", "证据检索"], horizontal=True, key="rag_mode")
    selected = st.selectbox("示例问题", example_questions(), key="rag_example")
    question = st.text_area("问题", value=selected, key="rag_question")
    if mode == "证据检索":
        top_k = st.slider("返回证据数量", 3, 10, 5, key="rag_top_k")
        if st.button("检索证据", type="primary", disabled=not bool(rag_health) or not scope_valid, key="retrieve_button"):
            try:
                with st.spinner("正在检索证据……"):
                    st.session_state.rag_result = {
                        "mode": mode, "scope": dict(scope),
                        "payload": rag.retrieve(question, top_k, scope),
                    }
            except Exception as exc:
                technical_error(exc)
        current = st.session_state.get("rag_result")
        if current and current.get("mode") == mode:
            render_scope(
                current.get("scope", scope), catalog_documents,
                title="本次检索实际使用的资料范围",
            )
            render_retrieval_results(current["payload"]["results"], document_names)
    else:
        if not config.online_generation_allowed:
            if config.is_public_demo:
                st.info("当前公共演示只开放证据检索；在线回答尚未启用。")
            else:
                st.warning("当前 Data 未标记为安全数据，已禁用可能调用在线模型的 RAG 问答。")
        budget_exhausted = config.is_public_demo and config.online_generation_allowed and budget.remaining == 0
        if config.is_public_demo and config.online_generation_allowed:
            st.caption(f"本 Session 剩余在线模型调用额度：{budget.remaining}")
            if budget_exhausted:
                st.warning("公共 Demo 调用额度已用完，本次请求已停止，不会返回假结果。")
        if st.button(
            "生成回答", type="primary",
            disabled=(
                not bool(rag_health)
                or not config.online_generation_allowed
                or not scope_valid
                or budget_exhausted
            ),
            key="query_button",
        ):
            try:
                if config.is_public_demo and not budget.reserve():
                    raise ServiceError(
                        "公共 Demo 调用额度已用完，本次请求已停止。",
                        "MAX_LLM_CALLS_PER_SESSION",
                        "LLM_BUDGET_EXHAUSTED",
                    )
                with st.spinner("正在生成 RAG 回答……"):
                    st.session_state.rag_result = {
                        "mode": mode, "scope": dict(scope),
                        "payload": rag.query(question, scope),
                    }
            except Exception as exc:
                technical_error(exc)
        current = st.session_state.get("rag_result")
        if current and current.get("mode") == mode:
            payload = current["payload"]
            render_scope(
                current.get("scope", scope), catalog_documents,
                title="本次问答实际使用的资料范围",
            )
            st.markdown("### RAG 回答")
            failure = business_failure_message(
                (payload.get("trusted_qa") or {}).get("post_validation_status")
            )
            if failure:
                st.warning(failure)
            elif payload.get("status") in {"ABSTAINED", "FAIL_CLOSED"}:
                st.warning("当前回答未通过资料与引用校验，本次结果已停止进入正式流程。")
            if payload.get("answer") == "N/A":
                st.caption("未生成回答")
            else:
                st.write(payload["answer"])
            st.markdown("### 引用来源")
            render_query_sources(
                payload["sources"], document_names, trace=payload.get("trace")
            )

    with st.expander("版本对比"):
        versioned_documents = [item for item in catalog_documents if len(item.get("versions") or []) >= 2]
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
                for column, change in zip(metrics, ("ADDED", "REMOVED", "MODIFIED", "UNCHANGED")):
                    column.metric(change, version_diff["summary"].get(change, 0))
                for row in version_diff["sections"]:
                    with st.expander(f"{row['change_type']} · {' / '.join(row['section_path'])}"):
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
    st.caption("原文档工作流 Agent 作为稳定的扩展能力保留；Prototype Final 的主流程是版本变化、影响分析、修改审核与安全发布。")
    st.markdown("#### Step 1–2：选择项目与文档版本范围")
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

    st.markdown("### Step 3–4：选择并解析 Word 模板")
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
            "Step 5：运行工作流", type="primary",
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
            st.info("RAG 服务或 Artifact 尚未就绪，工作流执行已禁用。")

    result = st.session_state.get("workflow_result")
    if result:
        st.markdown("### Step 6：Evidence 与字段草稿")
        render_scope(
            result["scope"], catalog_documents,
            title="本次工作流实际使用的资料范围",
        )
        render_workflow_result(result, document_names)
        st.markdown("### Step 7：人工逐章节审核")
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
        st.markdown("### Step 8–9：生成正式文档")
        pending_review_count = sum(
            bool(section["fields"]) and section.get("review", {}).get("status") != "APPROVED"
            for section in result["sections"]
        )
        if st.button(
            "生成 Approved DOCX", type="primary", disabled=not result["all_sections_approved"],
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

with change_tab:
    st.markdown("### 研发文档变更影响分析与人工审核")
    st.markdown(
        f"**当前组织：** {selected_case.organization_id}　　"
        f"**当前项目：** {selected_case.project_id}　　"
        "**数据：** 完全合成"
    )
    st.caption(f"{selected_case.title} · {selected_case.description}")
    st.markdown(
        '<div class="boundary">需求版本变化 → 影响分析 → 引用依据 → 修改建议 → '
        '人工审核 → 候选版本 → 安全发布</div>',
        unsafe_allow_html=True,
    )
    change_status = change_impact.status()
    if not rag_health:
        st.info("RAG 版本服务暂不可用；页面说明与案例信息仍可查看。")
    if st.button(
        "准备合成变更任务",
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

    v4_result = st.session_state.get("v4_change_result")
    render_workbench_summary(v4_result)
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
