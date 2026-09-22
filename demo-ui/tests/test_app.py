from __future__ import annotations

from pathlib import Path

from streamlit.testing.v1 import AppTest


def test_streamlit_module_imports_and_handles_unavailable_rag(monkeypatch):
    monkeypatch.setenv("DEMO_RAG_BASE_URL", "http://127.0.0.1:1")
    monkeypatch.setenv("DEMO_REQUEST_TIMEOUT_SECONDS", "0.2")
    app = AppTest.from_file(Path(__file__).parents[1] / "app.py", default_timeout=60).run()
    assert not app.exception
    assert [item.value for item in app.title] == ["版本可信研发知识与变更审查系统"]
    assert [item.label for item in app.tabs] == [
        "项目概览",
        "文档与版本",
        "可信检索与版本差异",
        "变更影响与修改审核",
        "执行轨迹",
        "评测结果",
        "扩展：文档起草",
    ]
    assert app.button(key="query_button").disabled is True
    assert any("Unavailable" in item.value for item in app.markdown)
