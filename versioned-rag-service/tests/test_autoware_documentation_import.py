from __future__ import annotations

from io import BytesIO
import tarfile

from scripts.import_autoware_documentation import (
    _archive_files_from_tar,
    canonical_source_path,
    html_page_to_markdown,
)


def test_community_html_import_keeps_article_structure_and_excludes_site_navigation():
    raw = """<!doctype html>
    <html><head><link rel="canonical" href="https://autowarefoundation.github.io/autoware-documentation/design/planning/" /></head>
    <body><nav>Autoware navigation must not enter the evidence.</nav>
      <article class="md-content__inner md-typeset">
        <h1>Planning</h1><p>规划模块会生成安全轨迹。</p>
        <h2>输入条件</h2><ul><li>定位状态有效</li><li>路径点完整</li></ul>
        <pre><code class="language-yaml">enabled: true</code></pre>
        <table><tr><th>字段</th><th>含义</th></tr><tr><td>velocity</td><td>目标速度</td></tr></table>
        <img src="diagram.png" alt="规划模块数据流图" />
      </article>
    </body></html>""".encode("utf-8")

    page = html_page_to_markdown(raw)

    assert page["canonical_url"].endswith("/design/planning/")
    assert "# Planning" in page["markdown"]
    assert "## 输入条件" in page["markdown"]
    assert "定位状态有效" in page["markdown"]
    assert "enabled: true" in page["markdown"]
    assert "velocity" in page["markdown"] and "目标速度" in page["markdown"]
    assert "规划模块数据流图" in page["markdown"]
    assert "Autoware navigation" not in page["markdown"]


def test_canonical_page_routes_resolve_only_to_safe_document_paths():
    assert canonical_source_path(
        "https://autowarefoundation.github.io/autoware-documentation/design/planning/"
    ) == "docs/design/planning/index.md"
    assert canonical_source_path(
        "https://autowarefoundation.github.io/autoware-documentation/installation/setup.md"
    ) == "docs/installation/setup.md"
    assert canonical_source_path("https://example.com/design/planning/") is None
    assert canonical_source_path(
        "https://autowarefoundation.github.io/autoware-documentation/../LICENSE"
    ) is None


def test_archive_reader_selects_pinned_files_without_extracting_paths():
    buffer = BytesIO()
    with tarfile.open(fileobj=buffer, mode="w:") as archive:
        guide = tarfile.TarInfo("docs/guide.md")
        guide_data = b"# Guide\n"
        guide.size = len(guide_data)
        archive.addfile(guide, BytesIO(guide_data))
        ignored = tarfile.TarInfo("docs/assets/image.png")
        ignored_data = b"image"
        ignored.size = len(ignored_data)
        archive.addfile(ignored, BytesIO(ignored_data))
        outside = tarfile.TarInfo("other/readme.md")
        outside_data = b"outside"
        outside.size = len(outside_data)
        archive.addfile(outside, BytesIO(outside_data))

    assert _archive_files_from_tar(buffer.getvalue(), "docs", ".md") == [("docs/guide.md", b"# Guide\n")]
