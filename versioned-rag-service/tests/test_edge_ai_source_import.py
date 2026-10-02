from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from scripts.import_edge_ai_sources import (
    import_sources,
    load_source_selection,
    normalize_source_file,
    validate_source_record,
)


def _source(tmp_path: Path, **overrides) -> dict:
    body = b"# J40 Setup\n\nInstall the image for JetPack 6.2.\n"
    source_file = tmp_path / "j40.md"
    source_file.write_bytes(body)
    row = {
        "source_id": "seeed-j40-setup",
        "source_url": "https://wiki.seeedstudio.com/cn/reComputer_Industrial_Getting_Started/",
        "repository": "Seeed-Studio/wiki-documents",
        "commit": "1eadc6584f962b6efdbdb3e49b2b4ce30c85be08",
        "document_path": "sites/zh-CN/docs/Edge/NVIDIA_Jetson/reComputer_Jetson_Series/reComputer_Industrial/cn_reComputer_Industrial_Getting_Started.md",
        "language": "zh-CN",
        "license": "CC-BY-SA-4.0",
        "license_status": "redistributable",
        "attribution": "Seeed Studio Wiki; CC BY-SA 4.0; source commit pinned",
        "source_format": "markdown",
        "device_model": ["reComputer Industrial J401"],
        "module_sku": ["P3767-0000"],
        "carrier_board": ["reComputer Industrial J401"],
        "software_baselines": ["JetPack 6.2"],
        "local_path": "sources/seeed-j40-setup.md",
        "sha256": hashlib.sha256(body).hexdigest(),
    }
    row.update(overrides)
    return row


def test_source_selection_requires_a_versioned_source_list(tmp_path: Path):
    selection = tmp_path / "selection.json"
    selection.write_text(json.dumps({"schema_version": 1, "sources": []}), encoding="utf-8")

    loaded = load_source_selection(selection)

    assert loaded["schema_version"] == 1
    assert loaded["sources"] == []


@pytest.mark.parametrize(
    "overrides",
    [
        {"license_status": None},
        {"license_status": "link_only"},
        {"commit": None, "retrieved_at_utc": None},
        {"language": "en-US"},
        {"local_path": "../outside.md"},
        {"document_path": "sites/../outside.md"},
        {"source_url": "https://attacker.example/doc"},
        {"sha256": "0" * 64},
    ],
)
def test_invalid_or_unlicensed_source_records_are_rejected(tmp_path: Path, overrides: dict):
    with pytest.raises(ValueError):
        validate_source_record(_source(tmp_path, **overrides), source_root=tmp_path)


def test_source_path_must_remain_inside_pinned_snapshot(tmp_path: Path):
    outside = tmp_path.parent / "outside.md"
    outside.write_text("outside", encoding="utf-8")
    row = _source(tmp_path, local_path="../outside.md", sha256=hashlib.sha256(b"outside").hexdigest())

    with pytest.raises(ValueError, match="path"):
        validate_source_record(row, source_root=tmp_path)


def test_link_only_records_do_not_enter_the_local_content_index(tmp_path: Path):
    row = _source(tmp_path, license_status="link_only", local_path=None, sha256=None)

    validate_source_record(row, source_root=tmp_path)
    assert row.get("local_path") is None


def test_markdown_normalization_preserves_source_text_and_provenance(tmp_path: Path):
    path = tmp_path / "guide.md"
    path.write_text("---\ntitle: Industrial setup\n---\n# Install\n\nUse JetPack 6.2.\n", encoding="utf-8")

    markdown, metadata = normalize_source_file(_source(tmp_path), path)

    assert "# Install" in markdown
    assert "JetPack 6.2" in markdown
    assert metadata["source_format"] == "markdown"
    assert metadata["title"] == "Industrial setup"


def test_html_normalization_preserves_tables_without_site_chrome(tmp_path: Path):
    path = tmp_path / "guide.html"
    path.write_text(
        "<html><nav>site navigation</nav><article><h1>J40</h1><table>"
        "<tr><th>基线</th><th>状态</th></tr><tr><td>JetPack 6.2</td><td>支持</td></tr>"
        "</table></article></html>",
        encoding="utf-8",
    )
    row = _source(tmp_path, source_format="html")

    markdown, metadata = normalize_source_file(row, path)

    assert "JetPack 6.2" in markdown and "支持" in markdown
    assert "site navigation" not in markdown
    assert metadata["source_format"] == "html"


def test_markdown_normalization_removes_mdx_chrome_and_does_not_claim_image_ocr(tmp_path: Path):
    path = tmp_path / "guide.md"
    path.write_text(
        "import Quote from '@site/components/Quote';\n\n"
        "# J40\n\n<div align=\"center\"><img src=\"diagram.png\" alt=\"J401 carrier layout\" /></div>\n\n"
        ":::note Scope\nBuild configuration only.\n:::\n",
        encoding="utf-8",
    )

    markdown, metadata = normalize_source_file(_source(tmp_path), path)

    assert "import Quote" not in markdown
    assert "<div" not in markdown and "<img" not in markdown
    assert "J401 carrier layout" not in markdown
    assert "Build configuration only." in markdown
    assert ":::note" not in markdown and ":::" not in markdown
    assert metadata["image_references_omitted"] == 1


def test_markdown_normalization_preserves_mdx_version_tabs_tables_and_code(tmp_path: Path):
    path = tmp_path / "guide.md"
    path.write_text(
        "<Tabs>\n<TabItem value='jp61' label='JetPack 6.1'>\n"
        "L4T 36.4.0\n<table><tr><th colSpan={2}>产品名称</th><th>J4012</th><th>J4011</th></tr>"
        "<tr><td colSpan={2}>模组</td><td>Orin NX 16GB</td><td>Orin NX 8GB</td></tr></table>\n"
        "```xml\n<device model=\"J4012\" />\n```\n</TabItem>\n"
        "<TabItem value=\"jp62\" label=\"JetPack 6.2\">L4T 36.4.3</TabItem>\n"
        "<TabItem value=\"jp72\" label=\"Jetpack7.2\">L4T 39.2.0</TabItem>\n</Tabs>\n",
        encoding="utf-8",
    )

    markdown, _ = normalize_source_file(_source(tmp_path), path)

    assert "## JetPack 6.1" in markdown
    assert "## JetPack 6.2" in markdown
    assert "## JetPack 7.2" in markdown
    assert "| 产品名称 |  | J4012 | J4011 |" in markdown
    assert "| 模组 |  | Orin NX 16GB | Orin NX 8GB |" in markdown
    assert "<device model=\"J4012\" />" in markdown
    assert markdown.index("JetPack 6.1") < markdown.index("L4T 36.4.0")
    assert markdown.index("JetPack 6.2") < markdown.index("L4T 36.4.3")


def _minimal_text_pdf(text: str) -> bytes:
    stream = f"BT /F1 12 Tf 72 720 Td ({text}) Tj ET".encode("ascii")
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >>",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
        b"<< /Length " + str(len(stream)).encode("ascii") + b" >>\nstream\n" + stream + b"\nendstream",
    ]
    output = bytearray(b"%PDF-1.4\n")
    offsets = [0]
    for number, body in enumerate(objects, start=1):
        offsets.append(len(output))
        output.extend(f"{number} 0 obj\n".encode("ascii") + body + b"\nendobj\n")
    xref = len(output)
    output.extend(f"xref\n0 {len(objects) + 1}\n".encode("ascii"))
    output.extend(b"0000000000 65535 f \n")
    for offset in offsets[1:]:
        output.extend(f"{offset:010d} 00000 n \n".encode("ascii"))
    output.extend(
        f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode("ascii")
    )
    return bytes(output)


def test_pdf_normalization_preserves_pages_and_rejects_image_only_pdf(tmp_path: Path):
    pytest.importorskip("PyPDF2")
    path = tmp_path / "datasheet.pdf"
    path.write_bytes(_minimal_text_pdf("JetPack 6.2 setup"))
    row = _source(tmp_path, source_format="pdf")

    markdown, metadata = normalize_source_file(row, path)

    assert "第 1 页" in markdown and "JetPack 6.2 setup" in markdown
    assert metadata["page_count"] == 1
    blank_path = tmp_path / "blank.pdf"
    blank_path.write_bytes(_minimal_text_pdf(""))
    with pytest.raises(ValueError, match="no extractable text"):
        normalize_source_file(row, blank_path)


def test_importer_records_licensed_documents_and_keeps_link_only_sources_out(tmp_path: Path):
    raw_path = tmp_path / "snapshot.md"
    raw_path.write_text("# Industrial\n\nJ401 uses JetPack 6.2.\n", encoding="utf-8")
    row = _source(tmp_path, local_path="snapshot.md", sha256=hashlib.sha256(raw_path.read_bytes()).hexdigest())
    link = _source(
        tmp_path,
        source_id="seeed-industrial-datasheet-link",
        license_status="link_only",
        local_path=None,
        sha256=None,
        source_url="https://files.seeedstudio.com/datasheets/example.pdf",
        source_format="pdf",
    )
    selection = tmp_path / "selection.json"
    selection.write_text(json.dumps({"schema_version": 1, "sources": [row, link]}), encoding="utf-8")
    output = tmp_path / "out"

    result = import_sources(selection_path=selection, source_root=tmp_path, output_root=output)

    assert result["source_count"] == 2
    assert result["indexable_source_count"] == 1
    assert (output / "sources/seeed-j40-setup.md").is_file()
    assert not (output / "sources/seeed-industrial-datasheet-link.md").exists()
    assert result["sources"][1]["license_status"] == "link_only"


def test_importer_removes_only_stale_paths_owned_by_its_previous_manifest(tmp_path: Path):
    raw_path = tmp_path / "snapshot.md"
    raw_path.write_text("# Industrial\n\nJ401 setup.\n", encoding="utf-8")
    row = _source(tmp_path, local_path="snapshot.md", sha256=hashlib.sha256(raw_path.read_bytes()).hexdigest())
    selection = tmp_path / "selection.json"
    selection.write_text(json.dumps({"schema_version": 1, "sources": [row]}), encoding="utf-8")
    output = tmp_path / "out"
    (output / "sources").mkdir(parents=True)
    stale = output / "sources/stale-owned.md"
    unmanaged = output / "sources/unmanaged.md"
    stale.write_text("old generated source", encoding="utf-8")
    unmanaged.write_text("keep this file", encoding="utf-8")
    (output / "source_import_manifest.json").write_text(
        json.dumps({"sources": [{"local_path": "sources/stale-owned.md"}]}), encoding="utf-8"
    )

    import_sources(selection_path=selection, source_root=tmp_path, output_root=output)

    assert not stale.exists()
    assert unmanaged.read_text(encoding="utf-8") == "keep this file"


def test_importer_rejects_existing_generated_destination_symlink(tmp_path: Path, monkeypatch):
    raw_path = tmp_path / "snapshot.md"
    raw_path.write_text("# Industrial\n\nJ401 setup.\n", encoding="utf-8")
    row = _source(tmp_path, local_path="snapshot.md", sha256=hashlib.sha256(raw_path.read_bytes()).hexdigest())
    selection = tmp_path / "selection.json"
    selection.write_text(json.dumps({"schema_version": 1, "sources": [row]}), encoding="utf-8")
    output = tmp_path / "out"
    sources = output / "sources"
    sources.mkdir(parents=True)
    destination = sources / f"{row['source_id']}.md"
    destination.write_text("placeholder", encoding="utf-8")
    target = output / "other-generated-artifact.md"
    target.write_text("must not be overwritten", encoding="utf-8")
    original_is_symlink = Path.is_symlink
    original_resolve = Path.resolve

    def report_symlink_for_destination(path: Path) -> bool:
        return path == destination or original_is_symlink(path)

    def resolve_destination_link(path: Path, strict: bool = False) -> Path:
        if path == destination:
            return target
        return original_resolve(path, strict=strict)

    monkeypatch.setattr(Path, "is_symlink", report_symlink_for_destination)
    monkeypatch.setattr(Path, "resolve", resolve_destination_link)

    with pytest.raises(ValueError, match="symlink"):
        import_sources(selection_path=selection, source_root=tmp_path, output_root=output)

    assert target.read_text(encoding="utf-8") == "must not be overwritten"
