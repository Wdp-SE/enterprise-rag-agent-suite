from __future__ import annotations

from pathlib import Path

import streamlit as st

from components.evidence_view import render_agent_evidence
from components.status_view import badge


def render_template_summary(record: dict) -> None:
    summary = record["summary"]
    st.markdown("#### Template Parse")
    cols = st.columns(4)
    cols[0].metric("Sections", summary["section_count"])
    cols[1].metric("Tables", summary["table_count"])
    cols[2].metric("Fields", summary["field_count"])
    cols[3].metric("Size", f"{record['size'] / 1024:.1f} KB")
    st.caption(f"Template: {record['filename']} · 支持结构化 Word (.docx) 模板")
    for section in summary["sections"]:
        indent = "　" * max(0, section["level"] - 1)
        st.write(f"{indent}{section['order']}. {section['title']}")
    with st.expander("执行前 SectionTask 计划"):
        for task in summary["tasks"]:
            st.markdown(
                f"- **{task['section_title']}** · {badge(task['status'])} · "
                f"Fields: {', '.join(task['required_fields'])}", unsafe_allow_html=True
            )


def render_workflow_result(result: dict, document_names: dict[str, str]) -> None:
    st.markdown("### Workflow Summary")
    cols = st.columns(6)
    cols[0].markdown(f"**Status**<br>{badge(result['workflow_status'])}", unsafe_allow_html=True)
    cols[1].metric("Sections", result["template"]["section_count"])
    cols[2].metric("RAG Calls", result["total_rag_calls"])
    cols[3].metric("Unique Evidence", result["unique_evidence_count"])
    cols[4].metric("Missing", result["missing_field_count"])
    cols[5].markdown(
        f"**Human Review**<br>{badge('YES' if result['requires_human_review'] else 'NO')}",
        unsafe_allow_html=True,
    )
    if result["workflow_status"] == "PARTIAL":
        st.warning("Workflow 为 PARTIAL：存在 Evidence 不足的字段。系统保留 MISSING，并要求人工审核。")
    elif result["workflow_status"] == "FAILED":
        st.error("Workflow FAILED：没有形成可交付草稿。")

    st.markdown("### SectionTask")
    for section in result["sections"]:
        label = f"{section['section_title']} · {section['status']} · Evidence {len(section['evidence_ids'])}"
        with st.expander(label):
            metrics = st.columns(5)
            metrics[0].metric("Status", section["status"])
            metrics[1].metric("Queries", section["query_count"])
            metrics[2].metric("RAG Calls", section["rag_calls"])
            metrics[3].metric("Evidence", len(section["evidence_ids"]))
            metrics[4].metric("Missing", len(section["missing_fields"]))
            st.markdown("**Queries**")
            if section["queries"]:
                for query in section["queries"]:
                    st.write(f"- {query}")
            else:
                st.caption("无新查询（可能从 checkpoint 恢复）。")
            st.markdown("**Evidence**")
            render_agent_evidence(section["evidence"], document_names)
            if section["missing_fields"]:
                st.markdown("**Missing Fields**")
                for field in section["missing_fields"]:
                    st.warning(f"{field} · INSUFFICIENT_EVIDENCE")
            if section["stop_reason"]:
                st.caption(f"Stop reason: {section['stop_reason']}")
            st.markdown("**Draft Preview**")
            st.write(section["draft_preview"])

    if result["timeline"]:
        with st.expander("Execution Timeline（仅展示真实 Trace Event）"):
            for event in result["timeline"]:
                st.write(
                    f"{event.get('timestamp')} · {event.get('event_type')} · "
                    f"{event.get('step_id') or '—'} · {event.get('operation') or '—'}"
                )


def render_downloads(result: dict, artifact_reader) -> None:
    st.markdown("### 下载输出")
    artifacts = result["artifacts"]
    columns = st.columns(3)
    downloads = [
        ("Download Draft DOCX", "draft", "application/vnd.openxmlformats-officedocument.wordprocessingml.document"),
        ("Download Evidence JSON", "evidence", "application/json"),
        ("Download Execution Trace", "trace", "application/json"),
    ]
    for column, (label, key, mime) in zip(columns, downloads):
        path = Path(artifacts[key])
        column.download_button(label, data=artifact_reader(path), file_name=path.name,
                               mime=mime, key=f"download_{result['workflow_id']}_{key}")
