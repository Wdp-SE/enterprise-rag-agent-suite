"""Public-demo corpus identity checks and human-readable corpus counts."""

from __future__ import annotations


AUTOWARE_REPOSITORY = "autowarefoundation/autoware_universe"


def public_workspace_mismatch(workspace: dict | None, *, public_demo: bool) -> str | None:
    """Flag an API configured for a different corpus instead of presenting it as Autoware."""
    if not public_demo or not workspace:
        return None
    repository = str(workspace.get("repository") or "未声明").strip()
    name = str(workspace.get("workspace") or "未声明").strip()
    languages = sorted(str(value) for value in workspace.get("languages") or [])
    if (
        repository.casefold() != AUTOWARE_REPOSITORY
        or name.casefold() != "autoware"
        or languages != ["en-US"]
    ):
        return (
            "当前知识服务与 Autoware 演示资料不匹配。"
            f"后端返回：知识空间 {name}；仓库 {repository}；语言 {', '.join(languages) or '未声明'}。"
            "请检查 Streamlit Secrets 的 RAG_API_BASE_URL 是否指向公开 Render RAG 服务，"
            "并确认 Render 的 RAG_PUBLIC_CORPUS_ROOT 与 RAG_PUBLIC_RETRIEVAL_CONFIG 使用 "
            "public_corpus_autoware 配置后重新部署。当前页面保留后端原始元数据，不会用静态标签掩盖错配。"
        )
    return None


def workspace_snapshot(workspace: dict) -> str:
    unique_documents = workspace.get("unique_document_count")
    sources = workspace.get("source_count")
    chunks = workspace.get("chunk_count", 0)
    if unique_documents is not None and sources is not None:
        return (
            f"当前快照：{unique_documents} 份不同资料、{sources} 条版本化来源、"
            f"{chunks} 个检索片段；检索策略以真实评测结果为准。"
        )
    return f"当前快照：{sources or 0} 条已登记来源、{chunks} 个检索片段；检索策略以真实评测结果为准。"
