from pathlib import Path

from streamlit.testing.v1 import AppTest


UI_ROOT = Path(__file__).parents[1]


def test_v4_workbench_is_the_primary_change_review_flow_and_loads_without_rag(monkeypatch) -> None:
    monkeypatch.setenv("DEMO_RAG_BASE_URL", "http://127.0.0.1:1")
    app = AppTest.from_file(UI_ROOT / "app.py", default_timeout=60).run()

    assert not app.exception
    assert [tab.label for tab in app.tabs] == [
        "项目概览",
        "文档与版本",
        "可信检索与版本差异",
        "变更影响与修改审核",
        "执行轨迹",
        "评测结果",
        "扩展：文档起草",
    ]
    page = "\n".join(item.value for item in app.markdown)
    assert "当前组织" in page
    assert "demo_company_a" in page
    assert "需求变化" in page
    assert "已确认关系" in page
    assert "疑似影响" in page
    assert "引用依据" in page
    assert "修改前与修改建议" in page
    assert "安全校验" in page
    assert "候选版本" in page
    assert "执行轨迹" in page
    assert "固定评测" in page
    assert any(button.label == "准备合成变更任务" for button in app.button)
