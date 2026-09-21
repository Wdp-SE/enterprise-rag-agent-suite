"""Streamlit interview demo for the frozen RAG and Document Workflow projects."""

from __future__ import annotations

import hashlib

import streamlit as st

from components.business_messages import business_failure_message
from components.evidence_view import render_query_sources, render_retrieval_results
from components.scope_view import render_scope, version_status_label
from components.status_view import render_about, render_sidebar_status
from components.workflow_view import render_downloads, render_template_summary, render_workflow_result
from config import DemoConfig, document_display_names, example_questions
from services.agent_client import AgentClient
from services.rag_client import RAGClient, ServiceError


st.set_page_config(page_title="研发文档 RAG + 文档工作流 Agent", page_icon="📄", layout="wide")
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

  @media (max-width: 760px) {
    .block-container {padding: 1.35rem 1rem 3rem;}
    [data-testid="stTabs"] button[data-baseweb="tab"] {padding: 0 0.7rem;}
    h1 {font-size: 1.85rem !important;}
  }
</style>
""", unsafe_allow_html=True)


@st.cache_resource
def clients(config: DemoConfig):
    return RAGClient(config.rag_base_url, config.request_timeout_seconds), AgentClient(config)


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
    with st.expander("技术详情"):
        if isinstance(exc, ServiceError):
            st.code(f"code={exc.code}\ndetail={exc.detail}")
        else:
            st.code(f"type={type(exc).__name__}\ndetail={exc}")


config = DemoConfig.from_env()
document_names = document_display_names()
rag, agent = clients(config)
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

st.title("研发文档 RAG + 文档工作流 Agent")
st.caption("RAG 负责可靠检索研发资料，Agent 负责按 Word 模板拆解任务并组织 Evidence，生成待人工审核的文档草稿。")

rag_tab, agent_tab = st.tabs(["研发文档 RAG", "文档工作流 Agent"])

with rag_tab:
    st.markdown('<div class="boundary"><b>RAG 问答</b>生成最终答案；<b>证据检索</b>返回供 Agent 使用的原始证据。</div>', unsafe_allow_html=True)
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
            st.warning("当前 Data 未标记为安全数据，已禁用可能调用在线模型的 RAG 问答。")
        if st.button(
            "生成回答", type="primary",
            disabled=not bool(rag_health) or not config.online_generation_allowed or not scope_valid,
            key="query_button",
        ):
            try:
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
        st.info("启动提示：请先启动本地 RAG 服务，再刷新页面。")

with agent_tab:
    st.markdown("### Step 1–2：选择项目与文档版本范围")
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

st.divider()
st.caption("Word Template → Document Workflow Agent → RAG /retrieve → Evidence → Draft → Human Review")
