"""Public-demo corpus identity checks and human-readable corpus counts."""

from __future__ import annotations


AUTOWARE_CHINESE_REPOSITORY = "tomato-ros/autoware-documentation-cn"


def public_workspace_mismatch(workspace: dict | None, *, public_demo: bool) -> str | None:
    """Flag an API configured for a different corpus instead of presenting it as Autoware."""
    if not public_demo or not workspace:
        return None
    repository = str(workspace.get("repository") or "未声明").strip()
    repositories = sorted(str(value).strip() for value in workspace.get("repositories") or [repository])
    name = str(workspace.get("workspace") or "未声明").strip()
    languages = sorted(str(value) for value in workspace.get("languages") or [])
    if (
        repository != AUTOWARE_CHINESE_REPOSITORY
        or repositories != [AUTOWARE_CHINESE_REPOSITORY]
        or name.casefold() != "autoware"
        or languages != ["zh-CN"]
    ):
        return (
            "当前知识库与 Autoware 工作台不匹配，检索暂不可用。请联系维护者。"
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
