from __future__ import annotations

import re

import streamlit as st


def _path(value) -> str:
    return " / ".join(value) if isinstance(value, list) else str(value or "—")


def _document_name(document_id: object, names: dict[str, str]) -> str:
    key = str(document_id or "unknown")
    return names.get(key, key)


def _source_lines(*, document_name: str, version: object, section: object, page: object) -> None:
    st.markdown(f"**《{document_name}》**")
    st.markdown(f"版本：{version or '版本信息不可用'}  ")
    st.markdown(f"章节：{_path(section)}  ")
    st.markdown(f"页码：第 {page or '—'} 页")


def _engineering_identifier(section_id: object, section_path: object, content: str) -> str | None:
    path = section_path if isinstance(section_path, list) else [section_path]
    searchable = " ".join([str(section_id or ""), *(str(part) for part in path), content[:160]])
    match = re.search(r"\b[A-Z]{2,5}-\d{3}\b", searchable)
    return match.group(0) if match else None


def _matching_trace(source: dict, trace: list[dict] | None) -> dict:
    document_id = source.get("document_id") or source.get("document_number")
    page = source.get("page_number") or source.get("page")
    return next(
        (
            item for item in (trace or [])
            if item.get("document_id") == document_id
            and (item.get("page_number") or item.get("page")) == page
        ),
        {},
    )


def render_retrieval_results(results: list[dict], document_names: dict[str, str]) -> None:
    if not results:
        st.info("当前范围内未找到足够相关的资料，可以尝试调整问题或扩大检索范围。")
        return

    def render_hit(item: dict) -> None:
        document_id = str(item.get("document_id") or "unknown")
        document_name = str(document_names.get(document_id) or item.get("document_title") or document_id)
        version = item.get("version_label") or "版本信息不可用"
        status = {"ACTIVE": "当前版本", "SUPERSEDED": "历史版本"}.get(
            item.get("version_status"), "版本状态未知"
        )
        content = str(item.get("content") or item.get("text") or "")
        identifier = _engineering_identifier(item.get("section_id"), item.get("section_path"), content)
        st.markdown(f"##### 第 {item.get('rank')} 条来源 · {status}")
        _source_lines(
            document_name=document_name,
            version=version,
            section=item.get("section_path"),
            page=item.get("page_number"),
        )
        if identifier:
            st.markdown(f"工程编号：{identifier}")
        st.write(content[:220] + ("…" if len(content) > 220 else ""))
        with st.expander("查看完整片段与技术详情"):
            st.write(content)
            st.caption("检索得分仅用于结果排序，不代表内容真实性。")
            st.json({
                "retrieval_score": item.get("similarity"),
                "document_id": document_id,
                "version_id": item.get("version_id"),
                "section_id": item.get("section_id"),
                "chunk_id": item.get("chunk_id"),
                "version_status": item.get("version_status"),
            })
        st.divider()

    for item in results[:3]:
        render_hit(item)
    if len(results) > 3:
        with st.expander(f"查看更多结果（{len(results) - 3}）", expanded=False):
            for item in results[3:]:
                render_hit(item)


def render_query_sources(
    sources: list[dict], document_names: dict[str, str], *, trace: list[dict] | None = None
) -> None:
    if not sources:
        st.info("本次回答没有可展示的引用依据。")
        return
    for index, source in enumerate(sources, start=1):
        trace_item = _matching_trace(source, trace)
        document_id = source.get("document_id") or source.get("document_number") or source.get("title")
        document_name = str(document_names.get(str(document_id)) or source.get("document_title") or document_id)
        page = source.get("page_number") or source.get("page") or "—"
        version = source.get("version_label") or trace_item.get("version_label") or "版本信息不可用"
        section = (
            source.get("section_path")
            or trace_item.get("section_path")
            or source.get("section")
            or trace_item.get("section_id")
        )
        st.markdown(f"##### 引用依据 {index}")
        _source_lines(document_name=document_name, version=version, section=section, page=page)
        status = source.get("version_status") or trace_item.get("version_status")
        if status == "ACTIVE":
            st.caption("当前版本 · 仍然有效")
        elif status == "SUPERSEDED":
            st.caption("历史版本")
        content = str(source.get("content") or source.get("text") or "").strip()
        identifier = _engineering_identifier(
            source.get("section_id") or trace_item.get("section_id"), section, content
        )
        if identifier:
            st.markdown(f"工程编号：{identifier}")
        if content:
            st.write(content)
        with st.expander("技术详情", expanded=False):
            st.json({
                "document_id": document_id,
                "version_id": source.get("version_id") or trace_item.get("version_id"),
                "section_id": source.get("section_id") or trace_item.get("section_id"),
                "chunk_id": source.get("chunk_id") or trace_item.get("chunk_id"),
                "validated_source": source,
            })


def render_agent_evidence(evidence: list[dict], document_names: dict[str, str]) -> None:
    if not evidence:
        st.caption("本章节没有引用证据。")
        return
    for item in evidence:
        evidence_id = item.get("evidence_id", "unknown")
        document = item.get("document_id") or item.get("document_number") or item.get("title") or "unknown"
        document_name = _document_name(document, document_names)
        page = item.get("page_number") or "—"
        section_path = item.get("section_path") or [item.get("section") or "—"]
        content = str(item.get("content", ""))
        version = item.get("version_label") or "版本信息不可用"
        freshness = "有效" if item.get("freshness") == "FRESH" else "需刷新"
        st.markdown(f"##### 来源 · {freshness}")
        _source_lines(document_name=document_name, version=version, section=section_path, page=page)
        st.write(content[:160] + ("…" if len(content) > 160 else ""))
        with st.expander("展开证据内容与技术详情"):
            st.write(content)
            st.markdown("**技术详情**")
            st.json({
                "document_id": document,
                "version_id": item.get("version_id"),
                "chunk_id": item.get("chunk_id"),
                "evidence_id": evidence_id,
                "freshness": item.get("freshness"),
            })
