from __future__ import annotations

from pathlib import Path

from streamlit.testing.v1 import AppTest


def test_streamlit_module_imports_and_handles_unavailable_rag(monkeypatch):
    monkeypatch.setenv("DEMO_RAG_BASE_URL", "http://127.0.0.1:1")
    monkeypatch.setenv("DEMO_REQUEST_TIMEOUT_SECONDS", "0.2")
    app = AppTest.from_file(Path(__file__).parents[1] / "app.py", default_timeout=60).run()
    assert not app.exception
    assert [item.value for item in app.title] == ["研发文档 RAG + 文档工作流 Agent"]
    assert len(app.tabs) == 3
    assert app.tabs[2].label == "工程变更审核工作台"
    assert app.button(key="query_button").disabled is True
    assert any("Unavailable" in item.value for item in app.markdown)
