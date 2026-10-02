from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from scripts.build_edge_ai_corpus import build_manifest
from src.public_knowledge import PublicKnowledgeIndex, build_index


def _write_corpus(root: Path, *, invalid_source: dict | None = None) -> Path:
    docs = [
        {
            "document_key": "guide/common-setup",
            "title": "通用安装指南",
            "content": "# 通用安装指南\n\n所有设备均需先确认 JetPack 软件基线。",
            "device_model": ["*"],
            "module_sku": ["*"],
            "carrier_board": ["*"],
            "software_baselines": ["*"],
            "document_family": "setup",
        },
        {
            "document_key": "guide/j4012-jp62",
            "title": "J4012 JetPack 6.2 配置",
            "content": "# J4012 JetPack 6.2 配置\n\n仅此示例配置支持 JP62。",
            "device_model": ["reComputer Industrial J4012"],
            "module_sku": ["P3767-0000"],
            "carrier_board": ["J401 carrier"],
            "software_baselines": ["JetPack 6.2"],
            "document_family": "configuration",
        },
        {
            "document_key": "guide/j4012-jp72",
            "title": "J4012 JetPack 7.2 配置",
            "content": "# J4012 JetPack 7.2 配置\n\n仅此示例配置支持 JP72。",
            "device_model": ["reComputer Industrial J4012"],
            "module_sku": ["P3767-0000"],
            "carrier_board": ["J401 carrier"],
            "software_baselines": ["JetPack 7.2"],
            "document_family": "configuration",
        },
        {
            "document_key": "guide/j3011-jp62",
            "title": "J3011 JetPack 6.2 配置",
            "content": "# J3011 JetPack 6.2 配置\n\nJ3011 JP62 示例配置。",
            "device_model": ["reComputer Industrial J3011"],
            "module_sku": ["P3767-0003"],
            "carrier_board": ["J301 carrier"],
            "software_baselines": ["JetPack 6.2"],
            "document_family": "configuration",
        },
    ]
    sources = []
    for doc in docs:
        local_path = f"sources/{doc['document_key'].split('/')[-1]}.md"
        path = root / local_path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(doc["content"], encoding="utf-8")
        sources.append({
            "version": "wiki-1eadc6584f96",
            "language": "zh",
            "locale": "zh-CN",
            "document_key": doc["document_key"],
            "document_title": doc["title"],
            "document_path": f"docs/{doc['document_key']}.md",
            "local_path": local_path,
            "source_type": "official_documentation",
            "source_url": f"https://wiki.seeedstudio.com/cn/{doc['document_key'].split('/')[-1]}/",
            "repository": "Seeed-Studio/wiki-documents",
            "commit": "1eadc6584f962b6efdbdb3e49b2b4ce30c85be08",
            "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            "license": "CC BY-SA 4.0",
            "license_status": "redistributable",
            "attribution": "Seeed Studio Wiki; CC BY-SA 4.0",
            "source_snapshot": "wiki-1eadc6584f96",
            "device_model": doc["device_model"],
            "module_sku": doc["module_sku"],
            "carrier_board": doc["carrier_board"],
            "software_baselines": doc["software_baselines"],
            "document_family": doc["document_family"],
            "source_format": "markdown",
        })
    if invalid_source:
        sources[0].update(invalid_source)
    manifest = {
        "schema_version": 1,
        "workspace_id": "edge_ai_device",
        "workspace": "reComputer Industrial / Jetson 边缘 AI 工程知识",
        "domain_profile": "edge_ai_device",
        "repository": "Seeed-Studio/wiki-documents",
        "current_version": "wiki-1eadc6584f96",
        "available_versions": ["wiki-1eadc6584f96"],
        "source_snapshot": {
            "version": "wiki-1eadc6584f96",
            "repository": "Seeed-Studio/wiki-documents",
            "commit": "1eadc6584f962b6efdbdb3e49b2b4ce30c85be08",
        },
        "software_baselines": ["JetPack 6.2", "JetPack 7.2"],
        "hardware_models": ["reComputer Industrial J4012", "reComputer Industrial J3011"],
        "module_skus": ["P3767-0000", "P3767-0003"],
        "carrier_boards": ["J401 carrier", "J301 carrier"],
        "sources": sources,
    }
    manifest_path = root / "corpus_manifest.json"
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False), encoding="utf-8")
    (root / "retrieval_policy.json").write_text(json.dumps({"default_policy": "bm25"}), encoding="utf-8")
    return manifest_path


def test_edge_ai_index_carries_scope_metadata_and_separates_snapshot_from_software(tmp_path):
    _write_corpus(tmp_path)

    build_index(tmp_path)
    index = PublicKnowledgeIndex(tmp_path)
    hits = index.search("JetPack 配置", version="current", language="zh")

    assert index.manifest["current_version"] == "wiki-1eadc6584f96"
    assert hits
    assert {row["version"] for row in hits} == {"wiki-1eadc6584f96"}
    hit = next(row for row in hits if row["document_key"] == "guide/j4012-jp62")
    assert hit["source_snapshot"] == "wiki-1eadc6584f96"
    assert hit["software_baselines"] == ["JetPack 6.2"]
    assert hit["device_model"] == ["reComputer Industrial J4012"]
    assert hit["module_sku"] == ["P3767-0000"]
    assert hit["carrier_board"] == ["J401 carrier"]
    assert hit["license_status"] == "redistributable"


def test_real_source_manifest_builds_a_chinese_workspace_with_snapshot_scopes():
    source_root = Path(__file__).resolve().parents[1] / "public_corpus_edge_ai"
    service_root = Path(__file__).resolve().parents[1]
    imported = json.loads((source_root / "source_import_manifest.json").read_text(encoding="utf-8"))
    selection = json.loads((service_root / "config" / "edge_ai_source_selection.json").read_text(encoding="utf-8"))

    manifest = build_manifest(imported, selection)

    assert manifest["workspace_id"] == "edge_ai_device"
    assert manifest["current_version"].startswith("wiki-")
    assert manifest["available_versions"] == [manifest["current_version"]]
    assert manifest["languages"] == ["zh"]
    assert len(manifest["sources"]) == 18
    assert all(row["source_snapshot"] == row["version"] == manifest["current_version"] for row in manifest["sources"])
    assert all(row["software_baselines"] for row in manifest["sources"])
    assert all(row["license_status"] == "redistributable" for row in manifest["sources"])


def test_manifest_builder_rejects_import_metadata_not_in_audited_selection():
    source_root = Path(__file__).resolve().parents[1] / "public_corpus_edge_ai"
    service_root = Path(__file__).resolve().parents[1]
    imported = json.loads((source_root / "source_import_manifest.json").read_text(encoding="utf-8"))
    selection = json.loads((service_root / "config" / "edge_ai_source_selection.json").read_text(encoding="utf-8"))
    imported["sources"][0]["license"] = "CC0"

    with pytest.raises(ValueError, match="differs from the audited selection"):
        build_manifest(imported, selection)


def test_device_and_software_facets_intersect_while_general_sources_remain_eligible(tmp_path):
    _write_corpus(tmp_path)
    build_index(tmp_path)
    index = PublicKnowledgeIndex(tmp_path)

    hits = index.search(
        "JetPack 配置", language="zh",
        device_model="reComputer Industrial J4012",
        module_sku="P3767-0000", carrier_board="J401 carrier",
        software_baseline="JetPack 6.2",
    )

    keys = {row["document_key"] for row in hits}
    assert "guide/j4012-jp62" in keys
    assert "guide/common-setup" in keys
    assert "guide/j4012-jp72" not in keys
    assert "guide/j3011-jp62" not in keys


@pytest.mark.parametrize("facet,value", [
    ("device_model", "reComputer Industrial J3011"),
    ("module_sku", "P3767-0003"),
    ("carrier_board", "J301 carrier"),
    ("software_baseline", "JetPack 7.2"),
])
def test_each_facet_is_applied_as_a_hard_filter(tmp_path, facet, value):
    _write_corpus(tmp_path)
    build_index(tmp_path)
    hits = PublicKnowledgeIndex(tmp_path).search("JetPack 配置", language="zh", **{facet: value})

    assert hits
    if facet == "device_model":
        assert all(value in row[facet] or row[facet] == ["*"] for row in hits)
    elif facet in {"module_sku", "carrier_board"}:
        assert all(value in row[facet] or row[facet] == ["*"] for row in hits)
    else:
        assert all(value in row["software_baselines"] or row["software_baselines"] == ["*"] for row in hits)


def test_undeclared_facet_values_are_rejected_instead_of_expanding_scope(tmp_path):
    _write_corpus(tmp_path)
    build_index(tmp_path)

    with pytest.raises(ValueError, match="unsupported public device or software scope"):
        PublicKnowledgeIndex(tmp_path).search("JetPack", device_model="unlisted device")


@pytest.mark.parametrize("invalid_source", [
    {"license_status": "review_required"},
    {"language": "en"},
    {"source_url": "https://example.com/copied-page"},
])
def test_edge_ai_manifest_rejects_unapproved_or_non_chinese_source(tmp_path, invalid_source):
    _write_corpus(tmp_path, invalid_source=invalid_source)

    with pytest.raises(ValueError):
        build_index(tmp_path)
