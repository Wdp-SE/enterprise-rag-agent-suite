"""Public-demo domain identity checks and human-readable corpus counts."""

from __future__ import annotations


EDGE_AI_REPOSITORY = "Seeed-Studio/wiki-documents"


def public_workspace_mismatch(workspace: dict | None, *, public_demo: bool) -> str | None:
    """Refuse to label an unrelated workspace as the public edge-AI demo."""
    if not public_demo or not workspace:
        return None
    repository = str(workspace.get("repository") or "未声明").strip()
    repositories = sorted(str(value).strip() for value in workspace.get("repositories") or [repository])
    profile = workspace.get("domain_profile") or {}
    languages = sorted(str(value) for value in workspace.get("languages") or [])
    if (
        workspace.get("workspace_id") != "edge_ai_device"
        or profile.get("id") != "edge_ai_device"
        or repository != EDGE_AI_REPOSITORY
        or repositories != [EDGE_AI_REPOSITORY]
        or languages != ["zh"]
    ):
        return (
            "当前知识空间不匹配边缘 AI 设备演示配置，检索暂不可用。请联系维护者。"
        )
    return None


def workspace_snapshot(workspace: dict) -> str:
    unique_documents = workspace.get("unique_document_count")
    sources = workspace.get("source_count")
    chunks = workspace.get("chunk_count", 0)
    if unique_documents is not None and sources is not None:
        return (
            f"资料规模：{unique_documents} 个主题 · {sources} 条版本/语言来源 · "
            f"{chunks} 个检索片段"
        )
    return f"资料规模：{sources or 0} 条来源 · {chunks} 个检索片段"
