from __future__ import annotations

import streamlit as st


STATUS_COLOR = {
    "COMPLETE": "#15803d", "APPROVED": "#15803d", "DRAFTED": "#15803d", "READY": "#15803d", "HEALTHY": "#15803d",
    "PARTIAL": "#b45309", "MISSING": "#b45309", "INSUFFICIENT_EVIDENCE": "#b45309", "REVIEW_REQUIRED": "#b45309",
    "FAILED": "#b91c1c", "REJECTED": "#b91c1c", "INVALID": "#b91c1c", "UNAVAILABLE": "#b91c1c",
    "RUNNING": "#1d4ed8", "PENDING": "#64748b",
}


def badge(label: str) -> str:
    normalized = str(label).upper().replace(" ", "_")
    color = STATUS_COLOR.get(normalized, "#475569")
    return (f'<span style="display:inline-block;padding:0.18rem 0.55rem;border-radius:999px;'
            f'background:{color}18;color:{color};border:1px solid {color}55;'
            f'font-weight:700;font-size:0.82rem">{label}</span>')


def render_sidebar_status(rag_health: dict | None, artifact: dict | None,
                          agent_status: dict, demo_data: str) -> None:
    st.sidebar.subheader("系统状态")
    st.sidebar.markdown(
        f"**RAG Service**  {badge('Healthy' if rag_health else 'Unavailable')}",
        unsafe_allow_html=True,
    )
    artifact_ready = bool(artifact and artifact.get("artifact_status") == "COMPLETE")
    st.sidebar.markdown(
        f"**RAG Artifact**  {badge('Ready' if artifact_ready else 'Not Ready')}",
        unsafe_allow_html=True,
    )
    st.sidebar.markdown(
        f"**Agent**  {badge('Ready' if agent_status.get('ready') else 'Unavailable')}",
        unsafe_allow_html=True,
    )
    st.sidebar.markdown(f"**Data**  `{demo_data}`")


def render_about(artifact: dict | None) -> None:
    with st.sidebar.expander("About / Technical Details"):
        st.markdown("**RAG**")
        st.write(f"Policy: {(artifact or {}).get('retrieval_policy', 'DENSE_ONLY')}")
        st.write(f"Dense representation: {(artifact or {}).get('dense_representation', 'SECTION_PATH')}")
        st.markdown("**Agent**")
        st.write("Evidence-driven Document Workflow Agent")
        st.write("Scope · Evidence Sufficiency · Drafting · Review · Checkpoint/Resume")
        st.caption("测试结果以当前 README 与最终工程报告为准。")
