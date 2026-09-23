from pathlib import Path

from streamlit.testing.v1 import AppTest


UI_ROOT = Path(__file__).parents[1]


def test_v4_workbench_is_the_primary_change_review_flow_and_loads_without_rag(monkeypatch) -> None:
    monkeypatch.setenv("DEMO_RAG_BASE_URL", "http://127.0.0.1:1")
    app = AppTest.from_file(UI_ROOT / "app.py", default_timeout=60).run()

    assert not app.exception
    assert [tab.label for tab in app.tabs] == [
        "工作台",
        "变更分析",
        "修改审核",
        "版本发布",
        "知识检索",
        "执行轨迹",
        "评测结果",
        "扩展工具",
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
    assert any(button.label == "运行变更分析" for button in app.button)

def test_change_analysis_explains_added_and_removed_without_blank_placeholders() -> None:
    result = {
        "changes": [
            {"change_type": "ADDED", "external_identifier": "REQ-025", "old_content": None, "new_content": "新增状态要求"},
            {"change_type": "MODIFIED", "external_identifier": "REQ-023", "old_content": "最大并发 500", "new_content": "最大并发 1000"},
            {"change_type": "REMOVED", "external_identifier": "REQ-099", "old_content": "旧要求", "new_content": None},
        ],
        "state": {"impacts": []},
        "evidence": {},
    }

    def render_changes(value):
        from components.change_impact_view import render_workbench_analysis
        render_workbench_analysis(value)

    app = AppTest.from_function(render_changes, args=(result,)).run()

    assert not app.exception
    assert [item.label for item in app.expander if item.label.startswith("已识别变化")] == [
        "已识别变化 · REQ-023 · 已修改",
        "已识别变化 · REQ-025 · 新增需求",
        "已识别变化 · REQ-099 · 已移除",
    ]
    rendered = "\n".join(item.value for item in app.markdown)
    assert "最大并发 500" in rendered
    assert "最大并发 1000" in rendered
    assert "新增需求，无历史版本内容" in rendered
    assert "需求已移除，无当前版本内容" in rendered
    assert "—" not in rendered
