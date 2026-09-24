"""Local Chromium smoke of the official-source workbench.

Start the public FastAPI service and Streamlit UI first, then run this script.
No real secret is read or written by this script.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from playwright.sync_api import sync_playwright


REPO = Path(__file__).resolve().parents[2]
ASSETS = REPO / "RAG-Challenge-2-main" / "public_corpus"
OUT = REPO / "project_delivery" / "real_public_release"
URL = "http://127.0.0.1:8505/"


def baseline_hash() -> str:
    digest = hashlib.sha256()
    for name in ("corpus_manifest.json", "chunks.json", "dense_vectors.npy", "retrieval_policy.json"):
        digest.update((ASSETS / name).read_bytes())
    return digest.hexdigest()


def wait_for_sources(page) -> list[str]:
    page.get_by_role("link", name="查看官方原文").first.wait_for(timeout=90000)
    links = page.get_by_role("link", name="查看官方原文")
    return [links.nth(i).get_attribute("href") for i in range(min(3, links.count()))]


def set_question(page, question: str) -> None:
    field = page.locator("textarea")
    field.fill(question)
    field.press("Tab")


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    before = baseline_hash()
    checks: dict[str, object] = {}
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        context = browser.new_context(viewport={"width": 1440, "height": 900})
        page = context.new_page()
        page.goto(URL, wait_until="domcontentloaded", timeout=30000)
        page.get_by_role("button", name="进入可信检索问答").wait_for(timeout=30000)
        home = page.locator("body").inner_text()
        assert "Apache DolphinScheduler" in home
        assert "可信检索问答" in home and "假设变更审查" in home
        assert "Case A" not in home and "Case B" not in home
        assert "演示案例 A" not in home and "演示案例 B" not in home
        page.screenshot(path=str(OUT / "home.png"), full_page=True)
        checks["home"] = "PASS"

        page.get_by_role("button", name="进入可信检索问答").click()
        page.get_by_role("heading", name="可信检索问答").wait_for()
        set_question(page, "DolphinScheduler 参数优先级从高到低是什么？")
        page.get_by_role("button", name="带引用回答").click()
        page.locator('a[href*="/docs/docs/zh/guide/parameter/priority.md"]').first.wait_for(timeout=90000)
        source_urls = wait_for_sources(page)
        assert any("/docs/docs/zh/guide/parameter/priority.md" in url for url in source_urls)
        assert "上游任务传递的参数" in page.locator("body").inner_text()
        checks["chinese_rag_answer"] = {"status": "PASS", "sources": source_urls}

        set_question(page, "3.4.3 的 missed_fire_policy 对旧 schedule 默认什么？")
        page.get_by_role("button", name="仅检索官方资料").click()
        page.locator('a[href*="/pull/18464"]').first.wait_for(timeout=90000)
        mixed_urls = wait_for_sources(page)
        assert any("dolphinscheduler" in url for url in mixed_urls)
        checks["mixed_search"] = {"status": "PASS", "sources": mixed_urls}

        page.get_by_role("combobox").nth(1).click()
        page.get_by_role("option", name="English").click()
        set_question(page, "What is the default dependency check interval?")
        page.get_by_role("button", name="仅检索官方资料").click()
        page.locator('a[href*="/docs/docs/en/guide/task/dependent.md"]').first.wait_for(timeout=90000)
        english_urls = wait_for_sources(page)
        assert any("/docs/docs/en/guide/task/dependent.md" in url for url in english_urls)
        checks["english_search"] = {"status": "PASS", "sources": english_urls}

        page.get_by_role("combobox").nth(0).click()
        page.get_by_role("option", name="3.4.2 · 历史版本").click()
        set_question(page, "DSIP-95 API complement data dependencies")
        page.get_by_role("button", name="仅检索官方资料").click()
        page.locator('a[href*="/releases/tag/3.4.2"]').first.wait_for(timeout=90000)
        version_urls = wait_for_sources(page)
        assert any("/releases/tag/3.4.2" in url for url in version_urls), version_urls
        checks["historical_version"] = {"status": "PASS", "sources": version_urls}

        # The pinned official Parameter Priority text genuinely differs between
        # 3.4.2 and 3.4.3. Search both versions so the warning is evidence-based.
        page.get_by_role("combobox").nth(0).click()
        page.get_by_role("option", name="全部固定版本").click()
        set_question(page, "Parameter Priority")
        page.get_by_role("button", name="仅检索官方资料").click()
        page.get_by_text("版本与资料一致性提醒", exact=False).first.wait_for(timeout=30000)
        old_priority = (
            "https://github.com/apache/dolphinscheduler/blob/"
            "71eb6412f940afa1f171f1097dc0e99ed61d16e2/"
            "docs/docs/en/guide/parameter/priority.md"
        )
        current_priority = (
            "https://github.com/apache/dolphinscheduler/blob/"
            "a190201acffa03d199d4ca216288734a6513de3d/"
            "docs/docs/en/guide/parameter/priority.md"
        )
        assert page.locator(f'a[href="{old_priority}"]').count() >= 1
        assert page.locator(f'a[href="{current_priority}"]').count() >= 1
        checks["consistency_warning"] = {
            "status": "PASS", "sources": [old_priority, current_priority],
        }
        page.screenshot(path=str(OUT / "rag.png"), full_page=True)
        page.get_by_text("版本与资料一致性提醒", exact=False).first.scroll_into_view_if_needed()
        page.mouse.move(900, 650)
        page.mouse.wheel(0, 480)
        page.screenshot(path=str(OUT / "rag_consistency.png"), full_page=True)

        page.locator('[data-testid="stSidebar"]').get_by_role("button", name="新建变更审查").click()
        page.get_by_role("heading", name="假设变更审查").wait_for()
        document = page.get_by_role("combobox").nth(0)
        document.click()
        document.fill("DSIP-107")
        page.get_by_role("option").filter(has_text="官方 Issue").click()
        textarea = page.locator("textarea")
        page.wait_for_function("() => document.querySelector('textarea')?.value.includes('I had searched the existing DSIP issues')", timeout=30000)
        page.screenshot(path=str(OUT / "agent_start.png"), full_page=True)
        current = textarea.input_value()
        textarea.fill(current + "\nHypothetical review change: require an additional schedule approval.")
        textarea.press("Tab")
        assert "Hypothetical review change" in textarea.input_value()
        checks["hypothetical_change_input"] = "PASS"
        page.get_by_role("button", name="开始变更审查").click()
        page.get_by_role("button", name="确认已审阅会话草案").wait_for(timeout=30000)
        review_text = page.locator("body").inner_text()
        assert "已确认关系" in review_text
        assert "建议核对" in review_text
        checks["impact_candidates"] = "PASS"
        assert "当前官方原文" in review_text
        assert "会话内假设草案" in review_text
        checks["patch_suggestions"] = "PASS"
        page.get_by_role("button", name="确认已审阅会话草案").click()
        page.get_by_text("公共基线未修改", exact=False).wait_for(timeout=10000)
        checks["human_review"] = "PASS"
        page.screenshot(path=str(OUT / "agent.png"), full_page=True)

        isolated = browser.new_context(viewport={"width": 1440, "height": 900}).new_page()
        isolated.goto(URL, wait_until="domcontentloaded", timeout=30000)
        isolated.locator('[data-testid="stSidebar"]').get_by_role("button", name="新建变更审查").click()
        assert "已记录本次会话的人工审核结果" not in isolated.locator("body").inner_text()
        checks["session_isolation"] = "PASS"
        browser.close()
    assert baseline_hash() == before
    checks["public_baseline_unchanged"] = "PASS"
    (OUT / "browser_smoke.json").write_text(
        json.dumps(checks, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps({key: value if isinstance(value, str) else value["status"] for key, value in checks.items()}))


if __name__ == "__main__":
    main()
