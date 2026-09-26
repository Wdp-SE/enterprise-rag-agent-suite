from __future__ import annotations

import json

import streamlit as st


DOCUMENT_TYPE_LABELS = {
    "REQUIREMENT": "需求文档",
    "REQUIREMENTS": "需求文档",
    "DESIGN": "设计文档",
    "TEST": "测试文档",
    "DOCUMENT": "研发文档",
}

VERSION_STATUS_LABELS = {
    "ACTIVE": "当前版本",
    "SUPERSEDED": "历史版本",
}


def version_status_label(value: object) -> str:
    text = str(value or "").strip()
    return VERSION_STATUS_LABELS.get(text, "版本状态未知")


def _items(value: object) -> list[str]:
    if not isinstance(value, (list, tuple)):
        return []
    return [str(item) for item in value if str(item).strip()]


def _join(values: list[str], fallback: str) -> str:
    return "、".join(dict.fromkeys(values)) if values else fallback


def _document_type(value: object) -> str:
    text = str(value or "").strip()
    return DOCUMENT_TYPE_LABELS.get(text.upper(), text or "未标注文档类型")


def build_scope_view(scope: dict, catalog_documents: list[dict]) -> dict:
    """Resolve an existing scope to business labels without changing its meaning."""

    raw_scope = dict(scope or {})
    by_document = {str(item.get("document_id")): item for item in catalog_documents}
    by_version: dict[str, tuple[dict, dict]] = {}
    for document in catalog_documents:
        for version in document.get("versions") or []:
            by_version[str(version.get("version_id"))] = (document, version)

    document_ids = _items(raw_scope.get("document_ids"))
    version_ids = _items(raw_scope.get("version_ids"))
    project_ids = _items(raw_scope.get("project_ids"))
    document_types = _items(raw_scope.get("document_types"))

    selected_documents: list[dict] = [
        by_document[item] for item in document_ids if item in by_document
    ]
    for version_id in version_ids:
        match = by_version.get(version_id)
        if match and match[0] not in selected_documents:
            selected_documents.append(match[0])

    if project_ids:
        project_labels = []
        for project_id in project_ids:
            match = next(
                (item for item in catalog_documents if str(item.get("project_id")) == project_id),
                None,
            )
            project_labels.append(str((match or {}).get("project_name") or project_id))
        project_text = _join(project_labels, "全部项目")
    elif selected_documents:
        project_text = _join(
            [str(item.get("project_name") or item.get("project_id") or "未标注项目") for item in selected_documents],
            "未标注项目",
        )
    else:
        project_text = "全部项目"

    if document_types:
        type_text = _join([_document_type(item) for item in document_types], "全部文档类型")
    elif selected_documents:
        type_text = _join([_document_type(item.get("document_type")) for item in selected_documents], "未标注文档类型")
    else:
        type_text = "全部文档类型"

    if selected_documents:
        document_text = _join(
            [f"《{item.get('title') or item.get('document_id')}》" for item in selected_documents],
            "未找到对应文档名称",
        )
    elif project_ids or document_types:
        document_text = "所选范围内的全部文档"
    else:
        document_text = "全部当前有效文档" if raw_scope.get("active_only", True) else "全部版本文档"

    version_labels: list[str] = []
    historical = False
    for version_id in version_ids:
        match = by_version.get(version_id)
        if match:
            document, version = match
            status = str(version.get("status") or "")
            historical = historical or status == "SUPERSEDED"
            status_label = "历史版本" if status == "SUPERSEDED" else "当前版本"
            version_labels.append(
                f"《{document.get('title') or document.get('document_id')}》"
                f" {version.get('version_label') or '版本信息不可用'}（{status_label}）"
            )
        else:
            version_labels.append("已指定版本（目录中暂无展示信息）")
    if version_labels:
        version_text = _join(version_labels, "指定版本")
    elif raw_scope.get("active_only", True):
        version_text = "当前有效版本"
    else:
        version_text = "全部版本"

    return {
        "project": project_text,
        "document_type": type_text,
        "documents": document_text,
        "versions": version_text,
        "historical": historical,
        "technical_scope": raw_scope,
    }


def render_scope(scope: dict, catalog_documents: list[dict], *, title: str = "当前资料范围") -> dict:
    view = build_scope_view(scope, catalog_documents)
    st.markdown(f"#### {title}")
    left, right = st.columns(2)
    left.markdown(f"**项目**  \n{view['project']}")
    right.markdown(f"**文档类型**  \n{view['document_type']}")
    left.markdown(f"**选择文档**  \n{view['documents']}")
    right.markdown(f"**版本范围**  \n{view['versions']}")
    if view["historical"]:
        st.warning("当前正在查询历史版本资料")
    with st.expander("技术详情", expanded=False):
        st.code(json.dumps(view["technical_scope"], ensure_ascii=False, indent=2), language="json")
    return view
