"""Streamlit interview demo for the frozen RAG and Document Workflow projects."""

from __future__ import annotations

import hashlib

import streamlit as st

from components.evidence_view import render_query_sources, render_retrieval_results
from components.status_view import render_about, render_sidebar_status
from components.workflow_view import render_downloads, render_template_summary, render_workflow_result
from config import DemoConfig, document_display_names, example_questions
from services.agent_client import AgentClient
from services.rag_client import RAGClient, ServiceError


st.set_page_config(page_title="研发文档 RAG + 文档工作流 Agent", page_icon="📄", layout="wide")
st.markdown("""
<style>
  .block-container {padding-top: 2rem; max-width: 1280px;}
  h1, h2, h3 {color: #153a68;}
  [data-testid="stMetric"] {background:#f8fafc;border:1px solid #dbe4ee;padding:.65rem;border-radius:.5rem;}
  .boundary {background:#eff6ff;border-left:4px solid #2563eb;padding:.75rem 1rem;border-radius:.25rem;}
</style>
""", unsafe_allow_html=True)


@st.cache_resource
def clients(config: DemoConfig):
    return RAGClient(config.rag_base_url, config.request_timeout_seconds), AgentClient(config)


def technical_error(exc: Exception) -> None:
    public = exc.public_message if isinstance(exc, ServiceError) else str(exc)
    st.error(public or "操作失败。")
    with st.expander("Technical Details"):
        if isinstance(exc, ServiceError):
            st.code(f"code={exc.code}\ndetail={exc.detail}")
        else:
            st.code(type(exc).__name__)


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
agent_status = agent.status()
render_sidebar_status(rag_health, artifact_status, agent_status, config.demo_data_classification)
render_about(artifact_status)

st.title("研发文档 RAG + 文档工作流 Agent")
st.caption("RAG 负责可靠检索研发资料，Agent 负责按 Word 模板拆解任务并组织 Evidence，生成待人工审核的文档草稿。")

rag_tab, agent_tab = st.tabs(["研发文档 RAG", "文档工作流 Agent"])

with rag_tab:
    st.markdown('<div class="boundary"><b>/query</b> 面向最终问答；<b>/retrieve</b> 面向 Agent 的原始 Evidence Retrieval。</div>', unsafe_allow_html=True)
    active_prefix = "safe-" if config.online_generation_allowed else "rdv2-"
    active_documents = [
        (document_id, name)
        for document_id, name in document_names.items()
        if document_id.startswith(active_prefix)
    ]
    if active_documents:
        with st.expander(f"当前知识库文档（{len(active_documents)} 份）"):
            for document_id, name in active_documents:
                st.markdown(f"- **{name}**")
                st.caption(f"内部文档 ID：{document_id}")
    mode = st.radio("模式", ["RAG 问答", "证据检索"], horizontal=True, key="rag_mode")
    examples = example_questions()
    selected = st.selectbox("示例问题", examples, key="rag_example")
    question = st.text_area("Question", value=selected, key="rag_question")
    if mode == "证据检索":
        top_k = st.slider("Top K", 3, 10, 5, key="rag_top_k")
        if st.button("检索 Evidence", type="primary", disabled=not bool(rag_health), key="retrieve_button"):
            try:
                with st.spinner("正在调用 frozen RAG /retrieve …"):
                    st.session_state.rag_result = {"mode": mode, "payload": rag.retrieve(question, top_k)}
            except Exception as exc:
                technical_error(exc)
        current = st.session_state.get("rag_result")
        if current and current.get("mode") == mode:
            render_retrieval_results(current["payload"]["results"], document_names)
    else:
        if not config.online_generation_allowed:
            st.warning("当前 Data 未标记为安全数据，已禁用可能调用在线模型的 /query。")
        if st.button("生成回答", type="primary", disabled=not bool(rag_health) or not config.online_generation_allowed,
                     key="query_button"):
            try:
                with st.spinner("正在调用 frozen RAG /query …"):
                    st.session_state.rag_result = {"mode": mode, "payload": rag.query(question)}
            except Exception as exc:
                technical_error(exc)
        current = st.session_state.get("rag_result")
        if current and current.get("mode") == mode:
            payload = current["payload"]
            st.markdown("### Final Answer")
            st.write(payload["answer"])
            st.markdown("### Sources / Citations")
            render_query_sources(payload["sources"], document_names)
    if not rag_health:
        st.info("启动提示：先按 README 启动本地 frozen RAG 服务，再刷新页面。")

with agent_tab:
    st.markdown("### 结构化 Word Template")
    st.caption("支持 Heading 1–3、段落、简单表格字段和占位符；不宣称支持任意 Word 文档。")
    source_type = st.radio("Template 来源", ["Safe Demo Template", "上传 .docx"], horizontal=True,
                           key="template_source")
    if source_type == "Safe Demo Template":
        if st.button("加载 Demo Template", key="load_demo_template"):
            try:
                st.session_state.template_record = agent.load_demo_template()
                st.session_state.pop("workflow_result", None)
            except Exception as exc:
                technical_error(exc)
    else:
        upload = st.file_uploader("上传结构化 Word Template", type=["docx"], key="docx_upload")
        if upload is not None:
            digest = hashlib.sha256(upload.getvalue()).hexdigest()
            if st.session_state.get("uploaded_digest") != digest:
                try:
                    st.session_state.template_record = agent.save_upload(upload.name, upload.getvalue())
                    st.session_state.uploaded_digest = digest
                    st.session_state.pop("workflow_result", None)
                except Exception as exc:
                    technical_error(exc)
    record = st.session_state.get("template_record")
    if record:
        render_template_summary(record)
        rag_ready = bool(rag_health and artifact_status and artifact_status.get("artifact_status") == "COMPLETE")
        if st.button("开始生成草稿", type="primary", disabled=not rag_ready, key="run_workflow"):
            try:
                with st.status("执行 Document Workflow", expanded=True) as status:
                    st.write("使用现有 Workflow Runner；执行完成后读取真实 Trace。")
                    result = agent.run_workflow(record)
                    st.session_state.workflow_result = result
                    status.update(label="Workflow 执行完成", state="complete", expanded=False)
            except Exception as exc:
                technical_error(exc)
        if not rag_ready:
            st.info("RAG Service 或 Artifact 尚未 Ready，已禁用 Workflow 执行。")
    result = st.session_state.get("workflow_result")
    if result:
        render_workflow_result(result, document_names)
        render_downloads(result, agent.artifact_bytes)
        st.info("Requires Human Review = YES。该草稿未自动批准，也未发布。")

st.divider()
st.caption("Word Template → Document Workflow Agent → RAG /retrieve → Evidence → Draft → Human Review")
