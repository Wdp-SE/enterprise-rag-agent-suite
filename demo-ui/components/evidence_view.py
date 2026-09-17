from __future__ import annotations

import streamlit as st


def _path(value) -> str:
    return " / ".join(value) if isinstance(value, list) else str(value or "—")


def _document_name(document_id: object, names: dict[str, str]) -> str:
    key = str(document_id or "unknown")
    return names.get(key, key)


def render_retrieval_results(results: list[dict], document_names: dict[str, str]) -> None:
    if not results:
        st.warning("没有返回 Evidence。")
        return
    for item in results:
        document_id = str(item.get("document_id") or "unknown")
        document_name = _document_name(document_id, document_names)
        title = f"查看完整证据 #{item.get('rank')} · {document_name} · 第 {item.get('page_number')} 页"
        content = str(item.get("content", ""))
        st.markdown(
            f"**第 {item.get('rank')} 条** · **文档：{document_name}** · "
            f"第 `{item.get('page_number')}` 页 · 相似度 `{float(item.get('similarity', 0)):.4f}`"
        )
        st.caption(f"章节：{_path(item.get('section_path'))}　|　内部文档 ID：{document_id}")
        st.write(content[:180] + ("…" if len(content) > 180 else ""))
        with st.expander(title):
            st.write(content)
            st.caption(f"片段 ID：{item.get('chunk_id')}")
        st.divider()


def render_query_sources(sources: list[dict], document_names: dict[str, str]) -> None:
    if not sources:
        st.warning("回答没有返回引用来源。")
        return
    for index, source in enumerate(sources, start=1):
        document_id = source.get("document_id") or source.get("document_number") or source.get("title")
        document_name = _document_name(document_id, document_names)
        page = source.get("page_number") or source.get("page") or "—"
        with st.expander(f"引用 #{index} · {document_name} · 第 {page} 页"):
            st.caption(f"内部文档 ID：{document_id or 'unknown'}")
            st.json(source)


def render_agent_evidence(evidence: list[dict], document_names: dict[str, str]) -> None:
    if not evidence:
        st.caption("本章节没有引用 Evidence。")
        return
    for item in evidence:
        evidence_id = item.get("evidence_id", "unknown")
        document = item.get("document_number") or item.get("title") or "unknown"
        document_name = _document_name(document, document_names)
        page = item.get("page_number") or "—"
        section_path = item.get("section_path") or [item.get("section") or "—"]
        content = str(item.get("content", ""))
        st.markdown(f"**{evidence_id}** · **文档：{document_name}** · 第 `{page}` 页")
        st.caption(f"章节：{_path(section_path)}　|　内部文档 ID：{document}")
        st.write(content[:160] + ("…" if len(content) > 160 else ""))
        with st.expander(f"展开 {evidence_id} 完整内容"):
            st.write(content)
