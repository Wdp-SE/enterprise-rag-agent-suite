from __future__ import annotations

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
        st.warning("当前选择的资料范围内未找到足够依据，暂不生成该内容。")
        return
    for item in results:
        document_id = str(item.get("document_id") or "unknown")
        document_name = _document_name(document_id, document_names)
        version = item.get("version_label") or "版本信息不可用"
        status = {"ACTIVE": "当前版本", "SUPERSEDED": "历史版本"}.get(item.get("version_status"), "版本状态未知")
        content = str(item.get("content", ""))
        st.markdown(f"##### 第 {item.get('rank')} 条来源 · {status}")
        _source_lines(
            document_name=document_name,
            version=version,
            section=item.get("section_path"),
            page=item.get("page_number"),
        )
        st.caption(f"检索相似度：{float(item.get('similarity', 0)):.4f}")
        st.write(content[:180] + ("…" if len(content) > 180 else ""))
        with st.expander(f"展开第 {item.get('rank')} 条证据内容"):
            st.write(content)
            st.markdown("**技术详情**")
            st.json({
                "document_id": document_id,
                "version_id": item.get("version_id"),
                "section_id": item.get("section_id"),
                "chunk_id": item.get("chunk_id"),
                "version_status": item.get("version_status"),
            })
        st.divider()


def render_query_sources(
    sources: list[dict], document_names: dict[str, str], *, trace: list[dict] | None = None
) -> None:
    if not sources:
        st.warning("回答没有返回引用来源。")
        return
    for index, source in enumerate(sources, start=1):
        trace_item = _matching_trace(source, trace)
        document_id = source.get("document_id") or source.get("document_number") or source.get("title")
        document_name = _document_name(document_id, document_names)
        page = source.get("page_number") or source.get("page") or "—"
        version = source.get("version_label") or trace_item.get("version_label") or "版本信息不可用"
        section = (
            source.get("section_path")
            or trace_item.get("section_path")
            or source.get("section")
            or trace_item.get("section_id")
        )
        st.markdown(f"##### 引用来源 {index}")
        _source_lines(document_name=document_name, version=version, section=section, page=page)
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
