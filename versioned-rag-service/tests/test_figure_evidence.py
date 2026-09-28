"""Contract tests for pinned figure provenance and OCR inventory."""

from __future__ import annotations

import hashlib
import importlib.util
import json
import struct
import zlib
from pathlib import Path


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "figure_evidence.py"
COMMIT = "a190201acffa03d199d4ca216288734a6513de3d"


def _png_chunk(kind: bytes, data: bytes) -> bytes:
    return (
        struct.pack(">I", len(data)) + kind + data
        + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF)
    )


PNG = (
    b"\x89PNG\r\n\x1a\n"
    + _png_chunk(b"IHDR", struct.pack(">IIBBBBB", 1, 1, 8, 2, 0, 0, 0))
    + _png_chunk(b"IDAT", zlib.compress(b"\x00\xff\x00\x00"))
    + _png_chunk(b"IEND", b"")
)


def _module():
    spec = importlib.util.spec_from_file_location("figure_evidence", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _corpus(tmp_path: Path) -> Path:
    root = tmp_path / "public_corpus"
    document_path = "docs/docs/zh/guide/parameter/priority.md"
    local_path = "sources/3.4.3/zh/guide/parameter/priority.md"
    source = root / local_path
    source.parent.mkdir(parents=True)
    source.write_text(
        "# 优先级\n\n"
        "![参数图](../../../../img/new_ui/dev/parameter/priority_parameter01.png)\n"
        "![同一张图](../../../../img/new_ui/dev/parameter/priority_parameter01.png)\n"
        "![站外图](https://other.example/figure.png)\n",
        encoding="utf-8",
    )
    manifest = {
        "source_count": 1,
        "current_version": "3.4.3",
        "sources": [{
            "document_key": "guide/parameter/priority",
            "version": "3.4.3",
            "commit": COMMIT,
            "language": "zh",
            "source_type": "official_documentation",
            "repository": "apache/dolphinscheduler",
            "document_path": document_path,
            "local_path": local_path,
            "sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
        }],
    }
    (root / "corpus_manifest.json").write_text(
        json.dumps(manifest), encoding="utf-8"
    )
    return root


def test_resolve_pinned_relative_image_without_accepting_external_or_escape():
    module = _module()
    source = "docs/docs/zh/guide/parameter/priority.md"
    assert module.resolve_asset_path(
        source, "../../../../img/new_ui/dev/parameter/priority_parameter01.png"
    ) == "docs/img/new_ui/dev/parameter/priority_parameter01.png"
    assert module.resolve_asset_path(source, "https://example.org/image.png") is None
    assert module.resolve_asset_path(source, "../../../../../../private.png") is None


def test_inventory_groups_same_asset_and_does_not_turn_alt_into_ocr(tmp_path):
    module = _module()
    inventory = module.scan_inventory(_corpus(tmp_path))
    assert inventory["source_count"] == 1
    assert inventory["relative_reference_count"] == 2
    assert inventory["external_reference_count"] == 1
    assert len(inventory["figures"]) == 1
    figure = inventory["figures"][0]
    assert figure["asset_path"] == (
        "docs/img/new_ui/dev/parameter/priority_parameter01.png"
    )
    assert figure["raw_url"] == (
        "https://raw.githubusercontent.com/apache/dolphinscheduler/"
        f"{COMMIT}/docs/img/new_ui/dev/parameter/priority_parameter01.png"
    )
    assert len(figure["references"]) == 2
    assert figure["ocr"]["status"] == "not_run"
    assert "text" not in figure["ocr"]


def test_fetch_records_sha_and_real_ocr_only_when_returned(tmp_path):
    module = _module()
    inventory = module.scan_inventory(_corpus(tmp_path))
    figure_path = inventory["figures"][0]["asset_path"]
    seen = []

    def fetcher(url, max_bytes):
        seen.append((url, max_bytes))
        return PNG, "image/png"

    result = module.verify_selected_images(
        inventory, selectors=(figure_path,), fetcher=fetcher,
        ocr_runner=lambda payload: ("识别出的图中文字", 83.5),
    )
    figure = result["figures"][0]
    assert len(seen) == 1
    assert figure["validation"]["status"] == "verified"
    assert figure["validation"]["sha256"] == hashlib.sha256(PNG).hexdigest()
    assert figure["validation"]["bytes"] == len(PNG)
    assert figure["validation"]["decode_status"] == "verified"
    assert figure["validation"]["width"] == 1
    assert figure["validation"]["height"] == 1
    assert figure["ocr"]["text"] == "识别出的图中文字"
    assert figure["ocr"]["status"] == "text_extracted"
    assert figure["ocr"]["quality"] == "unreviewed"
    assert figure["ocr"]["index_review_status"] == "pending"


def test_verified_image_without_ocr_engine_has_no_searchable_text(tmp_path):
    module = _module()
    inventory = module.scan_inventory(_corpus(tmp_path))
    figure_path = inventory["figures"][0]["asset_path"]
    result = module.verify_selected_images(
        inventory, selectors=(figure_path,),
        fetcher=lambda url, max_bytes: (PNG, "image/png"),
        ocr_runner=None,
    )
    figure = result["figures"][0]
    assert figure["ocr"]["status"] == "tool_unavailable"
    assert "text" not in figure["ocr"]
    assert "参数图" not in json.dumps(figure["ocr"], ensure_ascii=False)


def test_magic_bytes_without_decodable_image_are_not_counted_verified(tmp_path):
    module = _module()
    inventory = module.scan_inventory(_corpus(tmp_path))
    figure_path = inventory["figures"][0]["asset_path"]
    result = module.verify_selected_images(
        inventory, selectors=(figure_path,),
        fetcher=lambda url, max_bytes: (b"\x89PNG\r\n\x1a\nnot-a-png", "image/png"),
        ocr_runner=lambda payload: ("should not run", 100.0),
    )
    figure = result["figures"][0]
    assert figure["validation"]["status"] == "invalid_image_content"
    assert figure["ocr"]["status"] == "not_run"
