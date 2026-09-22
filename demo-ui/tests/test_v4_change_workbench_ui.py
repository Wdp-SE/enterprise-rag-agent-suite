from pathlib import Path

from streamlit.testing.v1 import AppTest


UI_ROOT = Path(__file__).parents[1]


def test_v4_workbench_is_a_third_isolated_tab_and_loads_without_rag(monkeypatch) -> None:
    monkeypatch.setenv("DEMO_RAG_BASE_URL", "http://127.0.0.1:1")
    app = AppTest.from_file(UI_ROOT / "app.py", default_timeout=60).run()

    assert not app.exception
    assert [tab.label for tab in app.tabs] == [
        "研发文档 RAG",
        "文档工作流 Agent",
        "工程变更审核工作台",
    ]
    page = "\n".join(item.value for item in app.markdown)
    assert "当前组织" in page
    assert "demo_company_a" in page
    assert "Requirement Diff" in page
    assert "已确认关系" in page
    assert "疑似影响" in page
    assert "Evidence" in page
    assert "Patch Before / After" in page
    assert "Conflict / Validation" in page
    assert "Candidate Version" in page
    assert "Workflow Progress" in page
    assert any(button.label == "准备合成变更任务" for button in app.button)
