"""Read-only Prototype Final projections and Streamlit presentation."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import streamlit as st


WORKSPACE_ROOT = Path(__file__).resolve().parents[2]
EVALUATION_RESULTS = (
    WORKSPACE_ROOT
    / "project_delivery"
    / "v4_change_impact_review"
    / "evaluation_results.json"
)

CROSS_CASE_RESULTS = (
    WORKSPACE_ROOT
    / "project_delivery"
    / "public_value_prototype"
    / "cross_case_results.json"
)

TASK_STATUS_LABELS = {
    "PENDING": "待开始",
    "IMPACT_READY": "影响已识别",
    "REVIEW_REQUIRED": "待审核",
    "APPLY_READY": "待应用",
    "CANDIDATE_READY": "候选版本待校验",
    "COMPLETED": "发布成功",
    "FAILED": "发布失败，原版本保持有效",
}
REVIEW_STATUS_LABELS = {
    "PENDING": "待审核",
    "EDITED_RECONFIRM_REQUIRED": "人工修改后待复核",
    "APPROVED": "已批准",
    "REJECTED": "已拒绝",
}
GATE_REASON_MESSAGES = {
    "NO_EVIDENCE": "缺少可追溯的引用依据，本次修改不会写入。",
    "OUT_OF_SCOPE_EVIDENCE": "引用资料不在当前检索范围内，本次修改不会写入。",
    "STALE_EVIDENCE": "当前引用资料已更新，需要重新确认。",
    "BASE_VERSION_MISMATCH": "基础版本已变化，需要基于最新版本重新生成修改建议。",
    "TARGET_CHANGED": "目标段落在审核期间发生变化，本次修改不会自动覆盖。",
    "ALREADY_APPLIED": "该修改已经应用，本次不会重复写入。",
    "REVIEW_REQUIRED": "该修改尚未通过人工审核，不能写入候选版本。",
    "CANDIDATE_VALIDATION_FAILED": "候选版本未通过校验，当前有效版本保持不变。",
}


def _patches(result: dict | None) -> list[dict]:
    return list(((result or {}).get("state") or {}).get("patches") or [])


def build_overview(catalog: list[dict], result: dict | None) -> dict[str, Any]:
    versions = [
        version
        for document in catalog
        for version in (document.get("versions") or [])
    ]
    patches = _patches(result)
    state = (result or {}).get("state") or {}
    quality_gate = state.get("quality_gate") or {}
    reasons = set(quality_gate.get("reasons") or [])
    conflicts = sum(
        patch.get("apply_status") == "CONFLICT" for patch in patches
    ) + int(bool(reasons & {"BASE_VERSION_MISMATCH", "TARGET_CHANGED"}))
    active_count = sum(bool(document.get("active_version")) for document in catalog)
    historical_count = sum(
        str(version.get("status")) == "SUPERSEDED" for version in versions
    )
    return {
        "project": state.get("project_id") or "PAYMENT",
        "document_count": len(catalog),
        "active_version_count": active_count,
        "historical_version_count": historical_count,
        "change_task": state.get("task_id") or "尚未准备",
        "task_status": TASK_STATUS_LABELS.get(
            str(state.get("status")), str(state.get("status") or "尚未开始")
        ),
        "pending_patch_count": sum(
            patch.get("review_status") in {"PENDING", "EDITED_RECONFIRM_REQUIRED"}
            for patch in patches
        ),
        "approved_patch_count": sum(
            patch.get("review_status") == "APPROVED" for patch in patches
        ),
        "rejected_patch_count": sum(
            patch.get("review_status") == "REJECTED" for patch in patches
        ),
        "conflict_count": conflicts,
        "candidate_status": (
            (state.get("candidate_version_record") or {}).get("status")
            or ("待校验" if state.get("status") == "CANDIDATE_READY" else "尚未生成")
        ),
    }


def _last_event(trace: list[dict], *steps: str) -> dict:
    matching = [row for row in trace if row.get("step") in steps]
    return matching[-1] if matching else {}


def build_trace_view(result: dict | None) -> dict[str, Any]:
    result = result or {}
    state = result.get("state") or {}
    trace = list(state.get("trace") or [])
    patches = list(state.get("patches") or [])
    impacts = list(state.get("impacts") or [])
    evidence = result.get("evidence") or state.get("evidence_snapshot") or {}
    gate = state.get("quality_gate") or {}
    gate_reasons = list(gate.get("reasons") or [])

    approved = sum(row.get("review_status") == "APPROVED" for row in patches)
    rejected = sum(row.get("review_status") == "REJECTED" for row in patches)
    pending = sum(
        row.get("review_status") in {"PENDING", "EDITED_RECONFIRM_REQUIRED"}
        for row in patches
    )
    conflict_count = sum(row.get("apply_status") == "CONFLICT" for row in patches)
    if set(gate_reasons) & {"BASE_VERSION_MISMATCH", "TARGET_CHANGED"}:
        conflict_count += 1

    if approved and not pending:
        review_status = "已批准"
    elif rejected and not approved and not pending:
        review_status = "已拒绝"
    else:
        review_status = "待审核"

    apply_statuses = {row.get("apply_status") for row in patches}
    if "CONFLICT" in apply_statuses:
        apply_status = "已阻断"
    elif "APPLIED" in apply_statuses or "SKIPPED_ALREADY_APPLIED" in apply_statuses:
        apply_status = "已应用"
    else:
        apply_status = "待执行"

    candidate = state.get("candidate_version_record") or {}
    validations = candidate.get("validations") or {}
    if candidate and candidate.get("status") in {"FAILED", "REJECTED"}:
        candidate_status = "校验失败"
    elif validations and all(bool(value) for value in validations.values()):
        candidate_status = "校验成功"
    else:
        candidate_status = "待执行"

    if state.get("status") == "COMPLETED":
        activation_status = "发布成功"
    elif state.get("status") == "FAILED":
        activation_status = "已阻断"
    else:
        activation_status = "待执行"

    create_event = _last_event(trace, "CREATE_TASK")
    review_event = _last_event(trace, "HUMAN_REVIEW")
    apply_event = _last_event(trace, "APPLY_PATCH")
    candidate_event = _last_event(trace, "CANDIDATE_BUILD")
    activation_event = _last_event(trace, "SAFE_ACTIVATION")

    def step(label: str, status: str, event: dict) -> dict:
        return {
            "label": label,
            "status": status,
            "latency": event.get("latency"),
            "rag_calls": event.get("rag_calls"),
            "llm_calls": event.get("llm_calls"),
            "evidence_count": event.get("evidence_count"),
            "failure_reason": event.get("failure_reason"),
        }

    gate_status = (
        "校验通过"
        if gate.get("status") == "PASS"
        else ("已阻断" if gate.get("status") == "BLOCKED" else "待执行")
    )
    steps = [
        step("需求变化识别", "已完成" if result.get("changes") else "待执行", create_event),
        step("影响分析", "已完成" if impacts else "待执行", create_event),
        step("引用依据检索", "已完成" if evidence else "待执行", create_event),
        step("修改建议生成", "已完成" if patches else "待执行", create_event),
        step("确定性校验", gate_status, apply_event or create_event),
        step("人工审核", review_status, review_event),
        step(
            "冲突检查",
            "已阻断" if conflict_count else ("校验通过" if gate.get("status") == "PASS" else "待执行"),
            apply_event,
        ),
        step("修改应用", apply_status, apply_event),
        step("候选版本校验", candidate_status, candidate_event or activation_event),
        step("安全发布", activation_status, activation_event),
    ]

    return {
        "workflow_id": state.get("task_id") or "尚未创建",
        "status": TASK_STATUS_LABELS.get(
            str(state.get("status")), str(state.get("status") or "尚未开始")
        ),
        "total_latency": round(
            sum(float(row.get("latency") or 0) for row in trace), 6
        ),
        "rag_calls": int(state.get("rag_calls") or 0),
        "llm_calls": max(
            [int(row.get("llm_calls") or 0) for row in trace] or [0]
        ),
        "evidence_count": len(evidence),
        "approved_patch_count": approved,
        "rejected_patch_count": rejected,
        "conflict_count": conflict_count,
        "resume_status": (
            "已恢复且未重复写入"
            if "SKIPPED_ALREADY_APPLIED" in apply_statuses
            else "未发生恢复"
        ),
        "quality_gate_reasons": gate_reasons,
        "evidence_selection": result.get("evidence_selection") or {},
        "steps": steps,
        "technical_trace": trace,
    }


def load_evaluation_report(path: str | Path = EVALUATION_RESULTS) -> dict[str, Any]:
    source = Path(path)
    if not source.is_file():
        return {}
    payload = json.loads(source.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("evaluation result must be a JSON object")
    return payload


def load_cross_case_report(path: str | Path = CROSS_CASE_RESULTS) -> dict[str, Any]:
    source = Path(path)
    if not source.is_file():
        return {}
    payload = json.loads(source.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("cross-case result must be a JSON object")
    return payload


def render_cross_case_evaluation(report: dict[str, Any]) -> None:
    st.markdown("#### 跨案例复用验证")
    if not report:
        st.caption("尚未找到跨案例评测结果。")
        return
    st.caption(report.get("claim_boundary") or "仅报告两套合成案例的可重复验证结果。")
    for case in report.get("cases") or []:
        with st.expander(
            f"{case.get('title') or case.get('case_id')} · "
            f"{'通过' if case.get('passed') else '未通过'}",
            expanded=True,
        ):
            checks = case.get("checks") or {}
            st.write(
                "　".join(
                    f"{'✅' if passed else '⛔'} {name}"
                    for name, passed in checks.items()
                )
            )
            metrics = case.get("metrics") or {}
            cols = st.columns(4)
            cols[0].metric("影响候选", metrics.get("impact_candidates_found", 0))
            cols[1].metric("已确认关系", metrics.get("confirmed_trace_count", 0))
            cols[2].metric("疑似影响", metrics.get("suggested_impact_count", 0))
            cols[3].metric("LLM 调用", metrics.get("llm_calls", 0))


def render_overview(catalog: list[dict], result: dict | None) -> None:
    summary = build_overview(catalog, result)
    st.markdown(
        '<div class="product-flow"><b>研发资料</b><span>版本治理</span>'
        '<span>可信检索</span><span>变化识别</span><span>影响分析</span>'
        '<span>修改审核</span><span>候选版本</span><b>安全发布</b></div>',
        unsafe_allow_html=True,
    )
    st.markdown("### 当前工作区")
    cols = st.columns(4)
    cols[0].metric("当前项目", summary["project"])
    cols[1].metric("研发文档", summary["document_count"])
    cols[2].metric("当前有效版本", summary["active_version_count"])
    cols[3].metric("历史版本", summary["historical_version_count"])
    cols = st.columns(4)
    cols[0].metric("变更任务", summary["task_status"])
    cols[1].metric("待审核修改", summary["pending_patch_count"])
    cols[2].metric("冲突", summary["conflict_count"])
    cols[3].metric("候选版本", summary["candidate_status"])
    st.info(
        "主演示从需求版本变化开始，经引用依据、影响分析和人工审核，"
        "通过确定性校验后生成并激活新的文档版本。"
    )


def render_versions(catalog: list[dict]) -> None:
    st.markdown("### 文档与版本")
    if not catalog:
        st.info("本地 RAG 服务启动后，这里会显示当前有效版本与历史版本。")
        return
    for document in catalog:
        active = document.get("active_version") or {}
        title = str(document.get("title") or document.get("document_id") or "研发文档")
        title = title.replace("Case A", "演示案例 A").replace("Case B", "演示案例 B")
        document_type = {
            "REQUIREMENT": "需求规格说明书", "DESIGN": "系统设计说明书",
            "API": "接口规范", "TEST": "测试用例", "RUNBOOK": "运维手册",
        }.get(str(document.get("document_type") or ""), document.get("document_type") or "—")
        with st.expander(
            f"《{title}》 · 当前有效版本 {active.get('version_label') or '—'}",
            expanded=False,
        ):
            st.write(
                f"文档类型：{document_type}　"
                f"项目：{document.get('project_name') or document.get('project_id') or '—'}"
            )
            for version in document.get("versions") or []:
                label = (
                    "当前有效版本"
                    if version.get("status") == "ACTIVE"
                    else "历史版本"
                )
                updated = version.get("created_at") or version.get("updated_at") or "—"
                st.markdown(
                    f"- **{version.get('version_label') or version.get('version_id')}**"
                    f" · {label} · 更新时间：{updated}"
                )
            with st.expander("技术详情"):
                st.json(document)


def render_trace(result: dict | None) -> None:
    st.markdown("### 执行轨迹")
    if not result:
        st.info("准备一条变更任务后，这里会读取真实工作流状态；展示本身不会再次检索或调用模型。")
        return
    view = build_trace_view(result)
    cols = st.columns(5)
    cols[0].metric("当前状态", view["status"])
    cols[1].metric("总耗时", f"{view['total_latency']:.3f}s")
    cols[2].metric("RAG 调用", view["rag_calls"])
    cols[3].metric("LLM 调用", view["llm_calls"])
    cols[4].metric("引用依据", view["evidence_count"])

    selection = view["evidence_selection"]
    if selection:
        st.markdown("#### 上下文预算")
        cols = st.columns(4)
        cols[0].metric("检索候选", selection.get("retrieved_evidence_count", 0))
        cols[1].metric("范围/版本校验后", selection.get("valid_evidence_count", 0))
        cols[2].metric("去重后", selection.get("deduplicated_evidence_count", 0))
        cols[3].metric("最终入选", selection.get("selected_evidence_count", 0))

    symbols = {
        "已完成": "●",
        "已批准": "●",
        "校验通过": "●",
        "已应用": "●",
        "发布成功": "●",
        "已阻断": "■",
        "校验失败": "■",
        "已拒绝": "■",
    }
    for row in view["steps"]:
        symbol = symbols.get(row["status"], "○")
        detail = []
        if row.get("latency") is not None:
            detail.append(f"{float(row['latency']):.3f}s")
        if row.get("failure_reason"):
            detail.append(str(row["failure_reason"]))
        suffix = f"　{' · '.join(detail)}" if detail else ""
        st.markdown(f"**{symbol} {row['label']}**　{row['status']}{suffix}")

    for reason in view["quality_gate_reasons"]:
        if reason in GATE_REASON_MESSAGES:
            st.warning(GATE_REASON_MESSAGES[reason])
    with st.expander("技术执行记录"):
        st.json(
            {
                "workflow_id": view["workflow_id"],
                "resume_status": view["resume_status"],
                "approved_patch_count": view["approved_patch_count"],
                "rejected_patch_count": view["rejected_patch_count"],
                "conflict_count": view["conflict_count"],
                "trace": view["technical_trace"],
            }
        )


def render_evaluation(report: dict[str, Any]) -> None:
    st.markdown("### 固定评测")
    if not report:
        st.info("尚未找到固定评测结果。运行评测脚本后会在这里展示真实结果。")
        return
    rag = report.get("rag") or {}
    agent = report.get("agent") or {}
    safety = report.get("safety") or {}
    st.markdown("#### 版本可信检索")
    cols = st.columns(5)
    cols[0].metric("评测用例", rag.get("case_count", "—"))
    cols[1].metric("Hit@5", rag.get("hit_at_5", "—"))
    cols[2].metric("Recall@5", rag.get("recall_at_5", "—"))
    cols[3].metric("P50", f"{rag.get('p50_latency_ms', 0):.3f} ms")
    cols[4].metric("P95", f"{rag.get('p95_latency_ms', 0):.3f} ms")
    checks = [
        ("当前版本正确", rag.get("current_version_correctness")),
        ("引用成员关系正确", rag.get("citation_membership_correctness")),
        ("无答案时拒答", rag.get("no_answer_rejection")),
        ("范围越界拦截", rag.get("scope_violation_count") == 0),
    ]
    st.write("　".join(f"{'✅' if passed else '⛔'} {label}" for label, passed in checks))

    st.markdown("#### 变更影响")
    cols = st.columns(4)
    cols[0].metric("影响召回率", agent.get("impact_recall", "—"))
    cols[1].metric("影响准确率", agent.get("impact_precision", "—"))
    cols[2].metric("修改目标正确", "是" if agent.get("patch_target_correctness") else "否")
    cols[3].metric("引用覆盖率", agent.get("evidence_coverage", "—"))

    st.markdown("#### 修改安全与恢复")
    cols = st.columns(4)
    cols[0].metric("未批准写入", safety.get("unapproved_writes", "—"))
    cols[1].metric("重复写入", safety.get("duplicate_patch_applications", "—"))
    cols[2].metric("未拦截过期引用", safety.get("unblocked_stale_evidence", "—"))
    cols[3].metric("发布失败丢失旧版本", safety.get("lost_active_version_on_publish_failure", "—"))
    st.write(
        f"Checkpoint 恢复：{'通过' if agent.get('resume_correctness') else '未通过'}　"
        f"候选版本：{agent.get('candidate_status') or '—'}"
    )

    baseline = report.get("baseline_comparison") or {}
    st.markdown("#### 版本治理离线对照")
    if not baseline:
        st.caption("当前结果没有可复现的离线版本冲突对照。")
    else:
        st.caption("仅用于 Evaluation，不进入正式 Runtime。")
        for comparison in baseline.get("cases") or [baseline]:
            question = comparison.get("question") or "版本冲突问题"
            st.markdown(f"**{question}**")
            st.write(
                f"无版本约束：{comparison.get('baseline_summary') or comparison.get('baseline_versions') or '—'}"
            )
            st.write(
                f"版本可信检索：{comparison.get('version_aware_summary') or comparison.get('version_aware_versions') or '—'}"
            )
