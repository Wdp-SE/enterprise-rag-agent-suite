"""Business-facing presentation for the engineering change review workbench."""

from __future__ import annotations

import streamlit as st

from components.prototype_final_view import (
    GATE_REASON_MESSAGES,
    REVIEW_STATUS_LABELS,
    TASK_STATUS_LABELS,
)


APPLY_STATUS_LABELS = {
    "PENDING": "待应用",
    "APPLIED": "已应用",
    "SKIPPED_ALREADY_APPLIED": "已应用，本次未重复写入",
    "BLOCKED_REVIEW": "待人工审核",
    "BLOCKED_STALE_EVIDENCE": "引用资料已更新",
    "BLOCKED_SCOPE": "超出当前范围",
    "CONFLICT": "目标已变化",
}


def render_workbench_summary(result: dict | None) -> None:
    st.markdown("### 需求变化")
    if not result:
        st.caption("准备任务后展示所选案例的需求版本变化。")
    else:
        changes = result.get("changes", [])
        modified = [item for item in changes if item.get("change_type") != "UNCHANGED"]
        for item in modified:
            with st.expander(
                f"已识别变化 · {item['external_identifier']}", expanded=True
            ):
                left, right = st.columns(2)
                left.markdown("**变更前**")
                left.write(item.get("old_content") or "—")
                right.markdown("**变更后**")
                right.write(item.get("new_content") or "—")
                with st.expander("技术详情"):
                    st.json(item)

    st.markdown("### 变更影响")
    confirmed, suggested = st.columns(2)
    confirmed.markdown("#### 已确认关系")
    suggested.markdown("#### 疑似影响")
    if not result:
        confirmed.caption("来自研发资料中已经登记的关系。")
        suggested.caption("来自语义检索，只作为人工审核建议。")
    else:
        state = result["state"]
        items = result.get("items", {})
        for impact in state.get("impacts", []):
            item = items.get(impact["impacted_item_id"], {})
            label = item.get("external_identifier") or "相关研发资产"
            target = (
                confirmed
                if impact["discovery_source"] == "EXPLICIT_TRACE"
                else suggested
            )
            target.write(f"- {label}")
            with target.expander(f"{label} · 技术详情"):
                target.json(impact)

    st.markdown("### 引用依据")
    if not result:
        st.caption("每条修改建议必须引用可追溯且仍然有效的资料。")
    else:
        selected = set(
            (result.get("evidence_selection") or {}).get("selected_evidence_ids") or []
        )
        for evidence in result.get("evidence", {}).values():
            if selected and evidence.get("evidence_id") not in selected:
                continue
            title = evidence.get("title") or evidence.get("document_id") or "研发文档"
            version = evidence.get("version_label") or "当前有效版本"
            with st.expander(f"《{title}》 · {version}"):
                st.write(evidence["content"])
                section = " / ".join(evidence.get("section_path") or [])
                page = evidence.get("page_number")
                st.caption(
                    f"章节：{section or '—'}"
                    + (f"　|　第 {page} 页" if page else "")
                )
                with st.expander("技术详情"):
                    st.json(
                        {
                            "evidence_id": evidence.get("evidence_id"),
                            "document_id": evidence.get("document_id"),
                            "version_id": evidence.get("version_id"),
                            "chunk_id": evidence.get("chunk_id"),
                        }
                    )

    st.markdown("### 修改前与修改建议")
    if not result:
        st.caption("当前只修改指定段落，不进行整篇文档重写。")
    else:
        for patch in result["state"].get("patches", []):
            before, after = st.columns(2)
            before.markdown("**修改前**")
            before.write(patch["original_content"])
            after.markdown("**修改建议**")
            after.write(patch["proposed_content"])
            st.caption(
                f"审核：{REVIEW_STATUS_LABELS.get(patch['review_status'], patch['review_status'])}"
                f"　|　应用：{APPLY_STATUS_LABELS.get(patch['apply_status'], patch['apply_status'])}"
                f"　|　基础版本：{patch['base_version_id']}"
            )
            st.write(f"修改原因：{patch['reason']}")
            with st.expander("技术详情"):
                st.json(
                    {
                        "patch_id": patch["patch_id"],
                        "target_anchor": patch["target_anchor"],
                        "operation": patch["operation"],
                        "review_status": patch["review_status"],
                        "apply_status": patch["apply_status"],
                    }
                )

    st.markdown("### 安全校验")
    if result:
        state = result["state"]
        gate = state.get("quality_gate") or {}
        reasons = gate.get("reasons") or []
        if gate.get("status") == "BLOCKED":
            for reason in reasons:
                st.error(GATE_REASON_MESSAGES.get(reason, "本次修改未通过安全校验。"))
        elif gate.get("status") == "PASS":
            st.success("确定性校验通过：引用、版本、目标段落、人工审核和重复写入检查均满足要求。")
        elif state.get("failure_reason"):
            st.error("本次操作已阻断，当前有效版本保持不变。")
        else:
            st.info("应用前会重新检查版本、目标段落、原文哈希、引用时效和重复写入。")
    else:
        st.caption("应用前执行版本、目标段落、原文哈希、引用时效和重复写入校验。")

    st.markdown("### 候选版本")
    if result:
        state = result["state"]
        record = state.get("candidate_version_record") or {}
        st.write(
            f"任务状态：**{TASK_STATUS_LABELS.get(state.get('status'), state.get('status'))}**"
        )
        if record:
            if record.get("status") == "ACTIVE":
                st.success("候选版本校验成功并已发布。")
            elif record.get("status") == "FAILED":
                st.error("候选版本校验失败，当前有效版本保持不变。")
            else:
                st.write(f"候选版本状态：**{record.get('status')}**")
            validations = record.get("validations") or {}
            for name, passed in validations.items():
                st.write(f"- {'✅' if passed else '⛔'} {name}")
            with st.expander("技术详情"):
                st.json(record)
    else:
        st.caption("批准的修改先生成候选版本；全部校验通过后才会安全发布。")
