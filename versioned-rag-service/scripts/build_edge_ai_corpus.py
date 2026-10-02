"""Build the pinned Chinese edge-AI workspace and integrity-bound index."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from src.public_knowledge import build_index


ROOT = Path(__file__).resolve().parents[1] / "public_corpus_edge_ai"
IMPORT_MANIFEST = ROOT / "source_import_manifest.json"
SOURCE_SELECTION = Path(__file__).resolve().parents[1] / "config" / "edge_ai_source_selection.json"


def _unique_values(rows: list[dict], field: str) -> list[str]:
    values = []
    for row in rows:
        for value in row.get(field, []):
            if value != "*" and value not in values:
                values.append(value)
    return values


def build_manifest(import_manifest: dict, selection: dict | None = None) -> dict:
    if import_manifest.get("workspace_id") != "edge_ai_device":
        raise ValueError("source import manifest does not belong to the edge-AI workspace")
    snapshot = import_manifest.get("source_snapshot")
    sources = import_manifest.get("sources")
    if not isinstance(snapshot, dict) or not isinstance(sources, list) or not sources:
        raise ValueError("source import manifest is incomplete")
    commit = snapshot.get("commit")
    if not isinstance(commit, str) or len(commit) != 40:
        raise ValueError("source import manifest has no pinned commit")
    version = f"wiki-{commit[:12]}"
    if selection is not None:
        if selection.get("workspace_id") != "edge_ai_device":
            raise ValueError("source selection belongs to another workspace")
        selected = {
            row.get("source_id"): row
            for row in selection.get("sources", [])
            if row.get("license_status") == "redistributable"
        }
        imported_ids = {row.get("source_id") for row in sources if isinstance(row, dict)}
        if not selected or imported_ids != set(selected):
            raise ValueError("imported sources do not match the audited active source selection")
        for imported in sources:
            expected = selected.get(imported.get("source_id"))
            if expected is None or any(
                imported.get(field) != expected.get(field)
                for field in (
                    "source_url", "repository", "commit", "document_path", "language",
                    "license", "license_status", "license_url", "attribution", "source_format",
                    "device_model", "module_sku", "carrier_board", "software_baselines", "document_family",
                )
            ):
                raise ValueError("imported source metadata differs from the audited selection")
    rows = []
    for imported in sources:
        if imported.get("license_status") != "redistributable" or imported.get("language") != "zh-CN":
            raise ValueError("only audited Chinese redistributable sources may enter the active corpus")
        if imported.get("commit") != commit:
            raise ValueError("source rows must share the pinned wiki snapshot")
        rows.append({
            "version": version,
            "source_snapshot": version,
            "language": "zh",
            "locale": "zh-CN",
            "document_key": imported["source_id"],
            "document_title": imported["title"],
            "document_path": imported["document_path"],
            "local_path": imported["local_path"],
            "source_type": "official_documentation",
            "source_url": imported["source_url"],
            "repository": imported["repository"],
            "commit": imported["commit"],
            "sha256": imported["sha256"],
            "license": imported["license"],
            "license_status": imported["license_status"],
            "license_url": imported["license_url"],
            "attribution": imported["attribution"],
            "source_id": imported["source_id"],
            "source_format": imported["source_format"],
            "source_updated_at": imported.get("source_updated_at"),
            "device_model": imported["device_model"],
            "module_sku": imported["module_sku"],
            "carrier_board": imported["carrier_board"],
            "software_baselines": imported["software_baselines"],
            "document_family": imported["document_family"],
            "scope_note": imported.get("scope_note", ""),
        })
    return {
        "schema_version": 1,
        "workspace_id": "edge_ai_device",
        "workspace": "reComputer Industrial / Jetson 边缘 AI 工程知识",
        "domain_profile": "edge_ai_device",
        "corpus_scope": "Seeed reComputer Industrial / Jetson 中文公开工程资料；覆盖设备、刷写、软件基线、部署、诊断与验证。",
        "repository": "Seeed-Studio/wiki-documents",
        "source_snapshot": {
            "version": version,
            "repository": snapshot["repository"],
            "branch": snapshot["branch"],
            "commit": commit,
            "captured_at_date": snapshot["captured_at_date"],
        },
        "current_version": version,
        "available_versions": [version],
        "version_scopes": {"latest": {"versions": [version]}},
        "hardware_models": _unique_values(rows, "device_model"),
        "module_skus": _unique_values(rows, "module_sku"),
        "carrier_boards": _unique_values(rows, "carrier_board"),
        "software_baselines": _unique_values(rows, "software_baselines"),
        "languages": ["zh"],
        "sources": rows,
    }


def write_json(path: Path, content: dict) -> None:
    path.write_text(json.dumps(content, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")


def build_corpus(root: Path = ROOT) -> dict:
    imported = json.loads((root / "source_import_manifest.json").read_text(encoding="utf-8"))
    selection = json.loads(SOURCE_SELECTION.read_text(encoding="utf-8"))
    manifest = build_manifest(imported, selection)
    write_json(root / "corpus_manifest.json", manifest)
    write_json(root / "retrieval_policy.json", {
        "schema_version": 1,
        "default_policy": "bm25",
        "selection_status": "new_corpus_pending_rebenchmark",
        "benchmark_query_count": 0,
        "reranker_enabled": False,
        "benchmark_corpus_sha256": "",
    })
    write_json(root / "public_retrieval_runtime.json", {
        "schema_version": 1,
        "default_policy": "bm25",
        "allowed_policies": ["bm25", "bm25_faceted_rrf"],
        "max_facets": 4,
        "rrf_k": 60,
        "image_top_k": 5,
    })
    result = build_index(root)
    return {
        **result,
        "workspace_id": manifest["workspace_id"],
        "snapshot": manifest["current_version"],
        "source_count": len(manifest["sources"]),
        "manifest_sha256": hashlib.sha256((root / "corpus_manifest.json").read_bytes()).hexdigest(),
    }


if __name__ == "__main__":
    print(json.dumps(build_corpus(), ensure_ascii=False, indent=2))
