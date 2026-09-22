"""Presentation helpers for the V4 engineering change review workbench."""

from __future__ import annotations

import streamlit as st


def render_workbench_summary(result: dict | None) -> None:
    st.markdown("### Requirement Diff")
    if not result:
        st.caption("准备任务后展示 REQ-023 的新旧版本变化。")
    else:
        changes = result.get("changes", [])
        modified = [item for item in changes if item.get("change_type") != "UNCHANGED"]
        for item in modified:
            with st.expander(f"{item['change_type']} · {item['external_identifier']}", expanded=True):
                left, right = st.columns(2)
                left.markdown("**变更前**")
                left.write(item.get("old_content") or "—")
                right.markdown("**变更后**")
                right.write(item.get("new_content") or "—")

    st.markdown("### Impact Candidates")
    confirmed, suggested = st.columns(2)
    confirmed.markdown("#### 已确认关系")
    suggested.markdown("#### 疑似影响")
    if not result:
        confirmed.caption("来自 EXPLICIT + CONFIRMED TraceLink")
        suggested.caption("来自 Dense Retrieval，仅作为审核建议")
    else:
        state = result["state"]
        items = result.get("items", {})
        for impact in state.get("impacts", []):
            item = items.get(impact["impacted_item_id"], {})
            label = item.get("external_identifier") or impact["impacted_item_id"]
            target = confirmed if impact["discovery_source"] == "EXPLICIT_TRACE" else suggested
            target.write(f"- {label} · {impact['discovery_source']}")

    st.markdown("### Evidence")
    if not result:
        st.caption("每条 Patch 必须引用可追溯且仍然有效的 Evidence。")
    else:
        for evidence in result.get("evidence", {}).values():
            with st.expander(
                f"{evidence.get('document_id', '文档')} · {evidence.get('version_label') or evidence.get('version_id')}"
            ):
                st.write(evidence["content"])
                st.caption(
                    f"章节：{' / '.join(evidence.get('section_path') or [])}　|　"
                    f"Evidence ID：{evidence['evidence_id']}"
                )

    st.markdown("### Patch Before / After")
    if not result:
        st.caption("只支持指定段落的 REPLACE_PARAGRAPH，不进行全文重写。")
    else:
        for patch in result["state"].get("patches", []):
            before, after = st.columns(2)
            before.markdown("**修改前**")
            before.write(patch["original_content"])
            after.markdown("**修改建议**")
            after.write(patch["proposed_content"])
            st.caption(
                f"审核：{patch['review_status']}　|　应用：{patch['apply_status']}　|　"
                f"Anchor：{patch['target_anchor']}"
            )

    st.markdown("### Conflict / Validation")
    if result:
        failure = result["state"].get("failure_reason")
        if failure:
            st.error(f"已阻断：{failure}")
        else:
            st.success("当前未发现冲突；真正应用前仍会重新检查版本、Anchor、原文、哈希和 Evidence。")
    else:
        st.caption("应用前执行版本、Anchor、原文、内容哈希、Evidence Freshness 和幂等校验。")

    st.markdown("### Candidate Version")
    if result:
        record = result["state"].get("candidate_version_record") or {}
        st.write(f"任务状态：**{result['state']['status']}**")
        if record:
            st.write(f"版本状态：**{record.get('status')}**")
            validations = record.get("validations") or {}
            for name, passed in validations.items():
                st.write(f"- {'✅' if passed else '⛔'} {name}")
    else:
        st.caption("批准的 Patch 先生成候选版本；全部校验通过后才安全激活。")

    st.markdown("### Workflow Progress")
    if result:
        for row in result["state"].get("trace", []):
            st.write(
                f"- {row['step']} · {row['status']} · {float(row.get('latency', 0)):.3f}s"
            )
    else:
        st.caption("Change → Impact → Evidence → Review → Apply → Candidate → Activation")
