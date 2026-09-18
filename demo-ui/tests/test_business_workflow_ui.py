from __future__ import annotations

import ast
from pathlib import Path

from streamlit.testing.v1 import AppTest


UI_ROOT = Path(__file__).parents[1]


def test_agent_adapter_imports_only_facade_from_document_workflow():
    source = (UI_ROOT / "services" / "agent_client.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    imports = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module and node.module.startswith("app.document_workflow"):
            imports.append((node.module, tuple(alias.name for alias in node.names)))
    assert imports == [("app.document_workflow", ("DocumentWorkflowFacade",))]


def test_agent_page_exposes_scope_history_review_and_finalize(monkeypatch):
    monkeypatch.setenv("DEMO_RAG_BASE_URL", "http://127.0.0.1:1")
    monkeypatch.setenv("DEMO_REQUEST_TIMEOUT_SECONDS", "0.2")
    app = AppTest.from_file(UI_ROOT / "app.py", default_timeout=60).run()
    assert not app.exception
    assert any(item.label == "项目" for item in app.selectbox)
    assert any(item.label == "文档范围" for item in app.radio)
    assert any("历史任务" in item.label for item in app.expander)
    button_labels = {item.label for item in app.button}
    assert "加载旗舰模板" in button_labels


def test_ui_copy_uses_final_product_name_and_no_legacy_research_entry():
    source = (UI_ROOT / "app.py").read_text(encoding="utf-8")
    assert "文档工作流 Agent" in source
    for forbidden in ("Knowledge Research", "Candidate Knowledge", "Source Discovery", "网页研究"):
        assert forbidden not in source

