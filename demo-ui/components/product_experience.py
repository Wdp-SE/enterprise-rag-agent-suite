"""Read-only UI projections for the public change-review workbench."""

from __future__ import annotations

from typing import Any


STEPS = (
    "检测需求变化",
    "分析影响文档",
    "查看引用依据",
    "生成修改建议",
    "人工审核",
    "生成候选版本",
    "安全发布新版本",
)


def case_knowledge_scope(mode: str, case: Any) -> dict:
    """The current case is the default; global search requires an explicit choice."""
    if mode == "当前案例":
        return {"project_ids": [case.project_id], "active_only": True}
    if mode == "全部资料":
        return {"active_only": True}
    raise ValueError("未知检索范围")


def build_status_cards(
    case: Any,
    catalog: list[dict],
    rag_health: dict | None,
    artifact_status: dict | None,
    agent_status: dict,
) -> dict[str, str | int]:
    project_catalog = [
        document for document in catalog
        if document.get("project_id") == case.project_id
    ]
    requirement = next(
        (
            document for document in project_catalog
            if document.get("document_type") in {"REQUIREMENT", "需求规格说明书"}
        ),
        None,
    )
    active_version = (requirement or {}).get("active_version") or {}
    current_version = str(active_version.get("version_label") or "待连接")
    current_version_id = str(active_version.get("version_id") or "—")
    ready = bool(
        rag_health
        and rag_health.get("service_status") == "READY"
        and artifact_status
        and artifact_status.get("artifact_status") == "COMPLETE"
        and agent_status.get("ready")
    )
    return {
        "project": case.project_id,
        "current_version": current_version,
        "current_version_id": current_version_id,
        "document_count": len(project_catalog),
        "version_count": sum(len(item.get("versions") or []) for item in project_catalog),
        "system_status": "就绪" if ready else "待连接",
    }


def build_workflow_progress(result: dict | None) -> list[tuple[str, str]]:
    result = result or {}
    state = result.get("state") or {}
    patches = state.get("patches") or []
    reviews = [patch.get("review_status") for patch in patches]
    selected_evidence = (
        (result.get("evidence_selection") or {}).get("selected_evidence_ids") or []
    )
    if patches and all(review == "APPROVED" for review in reviews):
        review_status = "已完成"
    elif "REJECTED" in reviews:
        review_status = "已阻断"
    elif patches:
        review_status = "待人工审核"
    else:
        review_status = "待执行"
    candidate = state.get("candidate_version_record") or {}
    if candidate.get("status") == "ACTIVE":
        candidate_status = "已完成"
    elif candidate.get("status") == "FAILED":
        candidate_status = "已阻断"
    elif state.get("status") == "CANDIDATE_READY":
        candidate_status = "待校验"
    else:
        candidate_status = "待执行"
    if state.get("status") == "COMPLETED":
        publication_status = "已完成"
    elif state.get("status") == "FAILED":
        publication_status = "已阻断"
    else:
        publication_status = "待执行"
    return list(zip(STEPS, (
        "已完成" if result.get("changes") else "待执行",
        "已完成" if state.get("impacts") else "待执行",
        "已完成" if selected_evidence else "待执行",
        "已完成" if patches else "待执行",
        review_status,
        candidate_status,
        publication_status,
    )))