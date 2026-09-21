from __future__ import annotations

from pathlib import Path

import streamlit as st

from components.business_messages import business_failure_message
from components.evidence_view import render_agent_evidence
from components.status_view import badge


def render_template_summary(record: dict) -> None:
    summary = record["summary"]
    st.markdown("#### 模板解析结果")
    cols = st.columns(4)
    cols[0].metric("章节", summary["section_count"])
    cols[1].metric("表格", summary["table_count"])
    cols[2].metric("字段", summary["field_count"])
    cols[3].metric("大小", f"{record['size'] / 1024:.1f} KB")
    st.caption(f"模板：{record['filename']}")
    for section in summary["sections"]:
        st.write(f"{'　' * max(0, section['level'] - 1)}{section['order']}. {section['title']}")
    with st.expander("执行前任务计划"):
        for task in summary["tasks"]:
            names = [field["field_name"] for field in task["required_fields"]]
            st.markdown(f"- **{task['section_title']}** · {badge(task['status'])} · 字段：{', '.join(names)}", unsafe_allow_html=True)


def render_refresh_summary(result: dict) -> None:
    summary = result.get("refresh_summary")
    if not summary:
        return
    section_titles = {
        item["section_id"]: item["title"] for item in result["template"].get("sections", [])
    }
    st.markdown("#### 版本更新处理结果")
    metrics = st.columns(5)
    metrics[0].metric("总章节", summary["total_sections"])
    metrics[1].metric("受影响章节", len(summary["affected_section_ids"]))
    metrics[2].metric("复用章节", len(summary["reused_section_ids"]))
    metrics[3].metric("重新检索章节", len(summary["re_retrieved_section_ids"]))
    metrics[4].metric("重新生成章节", len(summary["regenerated_section_ids"]))
    st.markdown("**需要重新处理**")
    for section_id in summary["affected_section_ids"]:
        st.write(f"- {section_titles.get(section_id, section_id)}")
    unchanged = summary["unchanged_section_ids"]
    st.markdown(f"**保持不变：其余 {len(unchanged)} 个章节**")
    with st.expander("查看保持不变的章节", expanded=False):
        for section_id in unchanged:
            st.write(f"- {section_titles.get(section_id, section_id)}")


def render_workflow_result(result: dict, document_names: dict[str, str]) -> None:
    st.markdown("### 工作流结果")
    cols = st.columns(6)
    cols[0].markdown(f"**状态**<br>{badge(result['workflow_status'])}", unsafe_allow_html=True)
    cols[1].metric("章节", result["template"]["section_count"])
    cols[2].metric("RAG 调用", result["total_rag_calls"])
    cols[3].metric("Evidence", result["unique_evidence_count"])
    cols[4].metric("待补字段", result["missing_field_count"])
    cols[5].markdown(f"**全部通过**<br>{badge('YES' if result['all_sections_approved'] else 'NO')}", unsafe_allow_html=True)
    render_refresh_summary(result)
    workflow_reason = business_failure_message(result.get("last_stop_reason"))
    if workflow_reason:
        st.warning(workflow_reason)
    for section in result["sections"]:
        if not section["fields"]:
            continue
        review_status = section.get("review", {}).get("status", "PENDING")
        label = f"{section['section_title']} · {section['status']} · 审核 {review_status}"
        with st.expander(label):
            st.markdown("**检索 Query**")
            for query in section.get("queries", []):
                st.write(f"- {query}")
            st.markdown("**字段草稿**")
            for field in section["fields"]:
                st.markdown(f"- **{field['field_name']}** · {field['status']} · {field['drafting_mode']}")
                st.write(field["content"])
                if field.get("missing_reason"):
                    message = business_failure_message(field["missing_reason"]) or "该字段暂不能进入正式流程，技术原因可在执行 Trace 中查看。"
                    st.warning(message)
            st.markdown("**Evidence**")
            render_agent_evidence(section.get("evidence", []), document_names)
            review = section.get("review") or {}
            if review.get("reviewer"):
                st.caption(f"审核人：{review['reviewer']} · 意见：{review.get('comment') or '—'}")


def render_downloads(result: dict, artifact_reader) -> None:
    st.markdown("### 下载输出")
    labels = {
        "draft": ("下载草稿 DOCX", "application/vnd.openxmlformats-officedocument.wordprocessingml.document"),
        "approved": ("下载正式 DOCX", "application/vnd.openxmlformats-officedocument.wordprocessingml.document"),
        "evidence": ("下载 Evidence JSON", "application/json"),
        "trace": ("下载执行 Trace", "application/json"),
    }
    available = [(key, value) for key, value in result["artifacts"].items() if value]
    columns = st.columns(max(1, len(available)))
    for column, (key, path_value) in zip(columns, available):
        label, mime = labels[key]
        path = Path(path_value)
        column.download_button(
            label, data=artifact_reader(path), file_name=path.name, mime=mime,
            key=f"download_{result['workflow_id']}_{key}",
        )
