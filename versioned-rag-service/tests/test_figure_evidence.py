"""Contract tests for pinned figure provenance and OCR inventory."""

from __future__ import annotations

import hashlib
import importlib.util
import json
import struct
import zlib
from copy import deepcopy
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


def _manifest(root: Path) -> dict:
    manifest = json.loads((root / "corpus_manifest.json").read_text(encoding="utf-8"))
    manifest["commits"] = {"3.4.3": COMMIT}
    source = manifest["sources"][0]
    source["source_url"] = (
        f"https://github.com/apache/dolphinscheduler/blob/{COMMIT}/"
        f"{source['document_path']}"
    )
    return manifest


def _reviewed_figure(root: Path) -> dict:
    module = _module()
    row = deepcopy(module.scan_inventory(root)["figures"][0])
    row["validation"] = {"status": "verified", "sha256": "a" * 64}
    row["ocr"] = {
        "status": "text_extracted", "engine": "tesseract",
        "index_review_status": "approved", "mean_confidence": 98.0,
        "text": "MAX_RETRY=3",
    }
    row["review"] = {
        "status": "approved", "sha256": "a" * 64,
        "reviewed_text": "MAX_RETRY = 3", "reviewed_at": "2026-09-29T00:00:00Z",
        "note": "逐项对照原图核验",
    }
    return row


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
    assert figure["references"][0]["heading"] == "优先级"
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
        review_dir=tmp_path / "review-images",
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
    preview_name = figure["validation"]["review_preview"]
    assert preview_name.endswith(".png")
    assert (tmp_path / "review-images" / preview_name).read_bytes() == PNG


def test_selected_figure_sample_is_stratified_and_bounded():
    module = _module()
    paths = module.SELECTED_FIGURES
    assert len(paths) == 20
    assert len(set(paths)) == 20
    assert any("parameter" in path for path in paths)
    assert any("project" in path for path in paths)
    assert any("monitor" in path for path in paths)
    assert any("open-api" in path for path in paths)
    assert any("tasks" in path for path in paths)


def test_reviewed_builder_accepts_only_pinned_approved_ocr(tmp_path):
    module = _module()
    root = _corpus(tmp_path)
    row = _reviewed_figure(root)

    chunks = module.build_reviewed_figure_chunks([row], _manifest(root))

    assert len(chunks) == 1
    hit = chunks[0]
    assert hit["schema_version"] == 1
    assert hit["modality"] == "image_ocr"
    assert hit["review_status"] == "approved"
    assert hit["content"] == "MAX_RETRY = 3"
    assert hit["version"] == "3.4.3"
    assert hit["heading"] == "优先级"
    assert hit["sha256"] == "a" * 64
    assert hit["raw_url"].endswith(f"/{COMMIT}/docs/img/new_ui/dev/parameter/priority_parameter01.png")


def test_reviewed_builder_rejects_unreviewed_or_mismatched_image_rows(tmp_path):
    module = _module()
    root = _corpus(tmp_path)
    base = _reviewed_figure(root)
    pending = deepcopy(base)
    pending["review"]["status"] = "pending"
    wrong_hash = deepcopy(base)
    wrong_hash["review"]["sha256"] = "b" * 64
    invalid_image = deepcopy(base)
    invalid_image["validation"]["status"] = "unverified"
    empty_review = deepcopy(base)
    empty_review["review"]["reviewed_text"] = "  "
    wrong_url = deepcopy(base)
    wrong_url["raw_url"] = "https://example.com/other.png"
    wrong_commit = deepcopy(base)
    wrong_commit["commit"] = "b" * 40
    wrong_schema = deepcopy(base)
    wrong_schema["schema_version"] = 2

    chunks = module.build_reviewed_figure_chunks(
        [pending, wrong_hash, invalid_image, empty_review, wrong_url, wrong_commit, wrong_schema],
        _manifest(root),
    )

    assert chunks == []


def test_reviewed_builder_keeps_language_specific_transcriptions(tmp_path):
    module = _module()
    root = _corpus(tmp_path)
    row = _reviewed_figure(root)
    row["review"]["reviewed_text_by_language"] = {
        "zh": "参数输出为 MAX_RETRY = 3",
        "en": "The parameter output is MAX_RETRY = 3",
    }
    row["references"].append({
        "document_key": "guide/parameter/priority",
        "language": "en",
        "local_path": "sources/3.4.3/en/guide/parameter/priority.md",
        "line": 2,
        "heading": "Priority",
    })
    manifest = _manifest(root)
    en_source = deepcopy(manifest["sources"][0])
    en_source.update({
        "language": "en",
        "local_path": "sources/3.4.3/en/guide/parameter/priority.md",
        "document_path": "docs/docs/en/guide/parameter/priority.md",
        "source_url": f"https://github.com/apache/dolphinscheduler/blob/{COMMIT}/docs/docs/en/guide/parameter/priority.md",
    })
    manifest["sources"].append(en_source)

    chunks = module.build_reviewed_figure_chunks([row], manifest)

    assert {chunk["language"]: chunk["content"] for chunk in chunks} == {
        "zh": "参数输出为 MAX_RETRY = 3",
        "en": "The parameter output is MAX_RETRY = 3",
    }


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
