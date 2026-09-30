"""Contract tests for pinned figure provenance and OCR inventory."""

from __future__ import annotations

import hashlib
import base64
import urllib.parse
import zlib
import xml.etree.ElementTree as ET
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


def test_autoware_markdown_inventory_uses_manifest_repository_and_commit(tmp_path):
    module = _module()
    root = tmp_path / "autoware"
    source_path = "planning/behavior_planner/README.md"
    local_path = "sources/0.52.0/en/planning/behavior_planner/README.md"
    source = root / local_path
    source.parent.mkdir(parents=True)
    source.write_text(
        "# Behavior Planner\n\n"
        "![Trajectory states](images/trajectory_states.png)\n",
        encoding="utf-8",
    )
    commit = "b" * 40
    manifest = {
        "source_count": 1,
        "workspace": "Autoware",
        "repository": "autowarefoundation/autoware_universe",
        "current_version": "0.52.0",
        "commits": {"0.52.0": commit},
        "sources": [{
            "document_key": "planning/behavior_planner",
            "version": "0.52.0",
            "commit": commit,
            "language": "en",
            "source_type": "official_documentation",
            "repository": "autowarefoundation/autoware_universe",
            "document_path": source_path,
            "local_path": local_path,
            "source_url": f"https://github.com/autowarefoundation/autoware_universe/blob/{commit}/{source_path}",
            "sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
        }],
    }
    (root / "corpus_manifest.json").write_text(json.dumps(manifest), encoding="utf-8")

    inventory = module.scan_inventory(root)

    assert inventory["unique_figure_count"] == 1
    figure = inventory["figures"][0]
    assert figure["repository"] == "autowarefoundation/autoware_universe"
    assert figure["asset_path"] == "planning/behavior_planner/images/trajectory_states.png"
    assert figure["raw_url"] == (
        f"https://raw.githubusercontent.com/autowarefoundation/autoware_universe/{commit}/"
        "planning/behavior_planner/images/trajectory_states.png"
    )


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


def test_svg_diagram_text_is_extracted_as_unreviewed_candidate():
    module = _module()
    inventory = {
        "current_version": "0.52.0",
        "figures": [{
            "version": "0.52.0", "asset_path": "planning/start_planner/flow.svg",
            "raw_url": "https://example.test/flow.svg",
            "references": [{"document_key": "planning/start_planner/design"}],
            "validation": {"status": "unverified"}, "ocr": {"status": "not_run"},
        }],
    }
    svg = b'<svg xmlns="http://www.w3.org/2000/svg"><text>Outside drivable area</text><text><tspan>Obstacle</tspan> stop</text></svg>'

    result = module.verify_selected_images(
        inventory, selectors=("planning/start_planner/flow.svg",),
        fetcher=lambda _url, _cap: (svg, "image/svg+xml"),
    )

    figure = result["figures"][0]
    assert figure["validation"]["status"] == "verified"
    assert figure["ocr"]["status"] == "text_extracted"
    assert figure["ocr"]["engine"] == "svg_text"
    assert figure["ocr"]["index_review_status"] == "pending"
    assert figure["ocr"]["text"] == "Outside drivable area Obstacle stop"


def test_drawio_svg_embedded_compressed_labels_are_extracted_locally():
    module = _module()
    graph = '<mxGraphModel><root><mxCell value="planner_priority"/><mxCell value="high priority"/><mxCell value="low priority"/></root></mxGraphModel>'
    packed = zlib.compress(urllib.parse.quote(graph, safe="").encode("utf-8"))[2:-4]
    diagram = base64.b64encode(packed).decode("ascii")
    nested = f'<mxfile><diagram>{diagram}</diagram></mxfile>'
    svg = ET.tostring(ET.Element("svg", {"content": nested}), encoding="utf-8")

    extracted = module._extract_svg_text(svg)

    assert "planner_priority" in extracted
    assert "high priority" in extracted
    assert "low priority" in extracted


def test_svg_text_extraction_rejects_dtd_and_entities():
    module = _module()
    payload = b'<!DOCTYPE svg [<!ENTITY x "expanded">]><svg><text>&x;</text></svg>'

    try:
        module._extract_svg_text(payload)
    except ValueError as exc:
        assert "DTD" in str(exc)
    else:
        raise AssertionError("SVG DTD must be rejected")


def test_auto_selection_prefers_relevant_raster_figures_and_is_bounded():
    module = _module()
    inventory = {
        "current_version": "0.52.0",
        "figures": [
            {"version": "0.52.0", "asset_path": "planning/start_planner/flow.drawio.svg",
             "raw_url": "https://example.test/flow.svg", "references": [{"document_key": "planning/start_planner/design"}],
             "validation": {"status": "unverified"}, "ocr": {"status": "not_run"}},
            {"version": "0.52.0", "asset_path": "planning/start_planner/trajectory.png",
             "raw_url": "https://example.test/trajectory.png", "references": [{"document_key": "planning/start_planner/design"}],
             "validation": {"status": "unverified"}, "ocr": {"status": "not_run"}},
            {"version": "0.51.0", "asset_path": "planning/start_planner/old.png",
             "raw_url": "https://example.test/old.png", "references": [{"document_key": "planning/start_planner/design"}],
             "validation": {"status": "unverified"}, "ocr": {"status": "not_run"}},
        ],
    }
    fetched = []

    result = module.verify_selected_images(
        inventory, selectors=None, max_images=1,
        fetcher=lambda url, _cap: (fetched.append(url) or (PNG, "image/png")),
        ocr_runner=lambda _payload: ("planner text", 95.0),
    )

    assert fetched == ["https://example.test/trajectory.png"]
    assert result["figures"][1]["ocr"]["status"] == "text_extracted"
    assert result["figures"][0]["ocr"]["status"] == "not_run"


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


def test_reviewed_builder_accepts_commit_bound_autoware_figure_evidence(tmp_path):
    module = _module()
    root = tmp_path / "autoware"
    repository = "autowarefoundation/autoware_universe"
    commit = "b" * 40
    source_path = "planning/behavior_planner/README.md"
    local_path = "sources/0.52.0/en/planning/behavior_planner/README.md"
    source = root / local_path
    source.parent.mkdir(parents=True)
    source.write_text("# Behavior Planner\n", encoding="utf-8")
    source_url = f"https://github.com/{repository}/blob/{commit}/{source_path}"
    manifest = {
        "commits": {"0.52.0": commit},
        "sources": [{
            "repository": repository, "version": "0.52.0", "commit": commit,
            "document_key": "planning/behavior_planner", "language": "en",
            "source_type": "official_documentation", "document_path": source_path,
            "local_path": local_path, "source_url": source_url,
        }],
    }
    row = {
        "schema_version": 1, "figure_id": "figure-autoware-1", "repository": repository,
        "version": "0.52.0", "commit": commit,
        "asset_path": "planning/behavior_planner/images/trajectory_states.png",
        "raw_url": f"https://raw.githubusercontent.com/{repository}/{commit}/planning/behavior_planner/images/trajectory_states.png",
        "references": [{
            "document_key": "planning/behavior_planner", "language": "en",
            "local_path": local_path, "line": 4, "heading": "Trajectory validation",
        }],
        "validation": {"status": "verified", "sha256": "c" * 64},
        "ocr": {"status": "text_extracted", "engine": "tesseract", "index_review_status": "approved"},
        "review": {"status": "approved", "sha256": "c" * 64,
                   "reviewed_text": "Trajectory status: validated", "reviewed_at": "2026-09-30T00:00:00Z"},
    }

    chunks = module.build_reviewed_figure_chunks([row], manifest)

    assert len(chunks) == 1
    assert chunks[0]["repository"] == repository
    assert chunks[0]["source_url"] == source_url
    assert chunks[0]["modality"] == "image_ocr"


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


def test_sidecar_builder_writes_valid_empty_index_without_inventing_figure_text(tmp_path):
    from scripts.build_reviewed_figure_sidecar import build_reviewed_figure_sidecar

    root = _corpus(tmp_path)
    inventory = _module().scan_inventory(root)
    (root / "figure_evidence.json").write_text(
        json.dumps(inventory, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )

    summary = build_reviewed_figure_sidecar(root)

    sidecar_path = root / "figure_evidence_reviewed.json"
    lock_path = root / "figure_evidence_reviewed.lock.json"
    sidecar = json.loads(sidecar_path.read_text(encoding="utf-8"))
    lock = json.loads(lock_path.read_text(encoding="utf-8"))
    assert summary["approved_figure_chunks"] == 0
    assert sidecar["chunks"] == []
    assert lock["sidecar_sha256"] == hashlib.sha256(sidecar_path.read_bytes()).hexdigest()
    assert lock["corpus_manifest_sha256"] == hashlib.sha256(
        (root / "corpus_manifest.json").read_bytes()
    ).hexdigest()


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
