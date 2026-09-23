from __future__ import annotations

from pathlib import Path

from streamlit.testing.v1 import AppTest


UI_ROOT = Path(__file__).parents[1]


def test_public_ui_shows_case_selector_and_cold_start_reconnect(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("APP_ENV", "public_demo")
    monkeypatch.setenv("RAG_API_BASE_URL", "http://127.0.0.1:1")
    monkeypatch.setenv("DEMO_REQUEST_TIMEOUT_SECONDS", "0.05")
    monkeypatch.setenv("DEMO_RUNTIME_ROOT", str(tmp_path))
    app = AppTest.from_file(UI_ROOT / "app.py", default_timeout=60).run()

    assert not app.exception
    selector = app.selectbox(key="demo_case_selector")
    assert len(selector.options) == 2
    assert selector.value == "case-a"
    page = "\n".join(
        [item.value for item in app.markdown]
        + [item.value for item in app.info]
        + [item.value for item in app.caption]
    )
    assert "Public Demo" in page
    assert "公共免费演示后端可能正在启动，请稍后重试" in page
    assert app.button(key="reconnect_backend").label == "重新连接"
    assert "当前公共演示只开放证据检索" in page
    assert "剩余在线模型调用额度" not in page
    assert app.button(key="query_button").disabled is True
