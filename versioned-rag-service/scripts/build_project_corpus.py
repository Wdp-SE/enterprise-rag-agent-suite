"""Build an isolated project corpus from explicitly approved, pinned files."""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import re
import subprocess
import sys
from pathlib import Path, PurePosixPath
from urllib.parse import quote

import numpy as np

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.audit_project_source import (
    SERVICE_ROOT,
    _run_git,
    _safe_repo_path,
    assert_indexable,
    audit_repository,
    validate_project_manifest,
)
from src.public_knowledge import dense_vector


MAX_SOURCE_BYTES = 20_000_000
MAX_CHARS_PER_CHUNK = 1200
_SOURCE_ID = re.compile(r"^[a-z0-9][a-z0-9-]{2,79}$")
_FORMAT_BY_SUFFIX = {
    ".md": "markdown", ".markdown": "markdown", ".pdf": "pdf", ".py": "python",
    ".yaml": "yaml", ".yml": "yaml", ".json": "json", ".sh": "shell",
    ".bash": "shell", ".txt": "text", ".toml": "toml", ".ini": "text",
    ".cfg": "text", ".conf": "text", ".xml": "xml", ".html": "html",
    ".css": "css", ".js": "javascript", ".ts": "typescript",
}


def _read_json_file(path: Path, label: str) -> dict:
    try:
        value = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"{label} is not readable JSON") from exc
    if not isinstance(value, dict):
        raise ValueError(f"{label} must be a JSON object")
    return value


def _git_tree(root: Path, commit: str) -> dict[str, str]:
    result = subprocess.run(
        ["git", "-C", str(Path(root).resolve()), "ls-tree", "-r", "-z", commit],
        check=False, capture_output=True, timeout=10,
    )
    if result.returncode != 0:
        raise ValueError("could not read the pinned project tree")
    rows: dict[str, str] = {}
    for entry in result.stdout.split(b"\x00"):
        if not entry:
            continue
        header, raw_path = entry.split(b"\t", 1)
        mode = header.split(b" ", 1)[0].decode("ascii")
        path = raw_path.decode("utf-8", errors="strict")
        rows[path] = mode
    return rows


def _git_blob(root: Path, commit: str, path: str) -> bytes:
    result = subprocess.run(
        ["git", "-C", str(Path(root).resolve()), "show", f"{commit}:{path}"],
        check=False, capture_output=True, timeout=15,
    )
    if result.returncode != 0:
        raise ValueError(f"pinned source blob is unavailable: {path}")
    if len(result.stdout) == 0 or len(result.stdout) > MAX_SOURCE_BYTES:
        raise ValueError(f"source is empty or exceeds the size limit: {path}")
    return result.stdout


def _source_format(path: str) -> str | None:
    name = PurePosixPath(path).name.casefold()
    if name == "dockerfile":
        return "dockerfile"
    return _FORMAT_BY_SUFFIX.get(PurePosixPath(path).suffix.casefold())


def _pdf_pages(raw: bytes, path: str) -> list[dict]:
    try:
        from pypdf import PdfReader
    except ImportError:
        from PyPDF2 import PdfReader

    try:
        reader = PdfReader(io.BytesIO(raw), strict=True)
        if reader.is_encrypted and not reader.decrypt(""):
            raise ValueError("encrypted PDF is not supported")
        pages = []
        for number, page in enumerate(reader.pages, start=1):
            text = (page.extract_text() or "").strip()
            if text:
                pages.append({"text": text, "page_start": number, "page_end": number})
    except Exception as exc:
        if isinstance(exc, ValueError):
            raise
        raise ValueError(f"PDF text extraction failed: {path}") from exc
    if not pages:
        raise ValueError(f"PDF has no extractable text: {path}")
    return pages


def _text_blocks(raw: bytes, path: str, source_format: str) -> list[dict]:
    if b"\x00" in raw or raw.startswith(b"%PDF-"):
        raise ValueError(f"unsupported binary source format: {path}")
    try:
        text = raw.decode("utf-8-sig").strip()
    except UnicodeDecodeError as exc:
        raise ValueError(f"source is not UTF-8 text: {path}") from exc
    if not text:
        raise ValueError(f"source has no text: {path}")
    lines = text.splitlines()
    blocks: list[dict] = []
    current_lines: list[str] = []
    start = 1
    heading_path: list[str] = []

    def flush(end: int) -> None:
        nonlocal current_lines, start
        value = "\n".join(current_lines).strip()
        if value:
            blocks.append({
                "text": value,
                "heading": heading_path[-1] if heading_path else PurePosixPath(path).stem,
                "heading_path": list(heading_path),
                "line_start": start,
                "line_end": max(start, end),
            })
        current_lines = []

    for number, line in enumerate(lines, start=1):
        heading_match = re.match(r"^(#{1,6})\s+(.+?)\s*$", line) if source_format == "markdown" else None
        if heading_match:
            flush(number - 1)
            level = len(heading_match.group(1))
            heading_path = heading_path[:level - 1]
            heading_path.append(heading_match.group(2))
            start = number
            current_lines = [line]
            continue
        if current_lines and len("\n".join(current_lines)) + len(line) + 1 > MAX_CHARS_PER_CHUNK:
            flush(number - 1)
            start = number
        current_lines.append(line)
    flush(len(lines))
    return blocks


def _inside_prefix(path: str, prefix: str) -> bool:
    normalized = prefix.rstrip("/")
    return path == normalized or path.startswith(normalized + "/")


def _write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")


def build_project_corpus(
    repository_root: Path,
    project_manifest: dict,
    source_selection: dict,
    output_root: Path,
) -> dict:
    """Build only approved path bodies, preserving a complete exclusion inventory."""
    output_root = Path(output_root)
    if output_root.exists() and any(output_root.iterdir()):
        raise ValueError("corpus build requires an empty output directory")
    identity = validate_project_manifest(project_manifest, repository_root=repository_root)
    report = audit_repository(
        repository_root,
        identity["primary_repository"],
        pinned_commit=identity["pinned_commit"],
        reviewed_licenses=project_manifest.get("source_license_reviews", {}),
        allowed_path_prefixes=identity["allowed_path_prefixes"],
    )
    if not isinstance(source_selection, dict) or source_selection.get("schema_version") != 1:
        raise ValueError("unsupported source selection schema")
    selected = source_selection.get("sources")
    if not isinstance(selected, list):
        raise ValueError("source selection must contain a sources list")
    ids = [row.get("source_id") for row in selected if isinstance(row, dict)]
    paths = [row.get("path") for row in selected if isinstance(row, dict)]
    if len(ids) != len(selected) or len(ids) != len(set(ids)):
        raise ValueError("duplicate source_id in source selection")
    if len(paths) != len(selected) or len(paths) != len(set(paths)):
        raise ValueError("duplicate source path in source selection")
    tree = _git_tree(repository_root, identity["pinned_commit"])
    audit_rows = {row["path"]: row for row in report["paths"]}
    for row in selected:
        path = _safe_repo_path(row.get("path"), label="source path")
        if not _SOURCE_ID.fullmatch(str(row.get("source_id", ""))):
            raise ValueError("source_id is invalid")
        audit_row = audit_rows.get(path)
        if audit_row is None:
            raise ValueError(f"selected source is not tracked at the pinned commit: {path}")
        assert_indexable(report, [path])
        if tree.get(path) in {"120000", "160000"}:
            raise ValueError(f"symlink or submodule source is not indexable: {path}")
        if not any(_inside_prefix(path, prefix) for prefix in identity["allowed_path_prefixes"]):
            raise ValueError(f"source path is outside the allowed path prefixes: {path}")
        expected_sha = row.get("sha256")
        if not isinstance(expected_sha, str) or not re.fullmatch(r"[0-9a-f]{64}", expected_sha):
            raise ValueError(f"source SHA-256 is invalid: {path}")
        raw = _git_blob(repository_root, identity["pinned_commit"], path)
        if hashlib.sha256(raw).hexdigest() != expected_sha:
            raise ValueError(f"source hash mismatch at the pinned commit: {path}")
        local_path = (Path(repository_root).resolve() / Path(*PurePosixPath(path).parts))
        if local_path.is_symlink() or not local_path.exists() or not local_path.resolve().is_relative_to(Path(repository_root).resolve()):
            raise ValueError(f"source path is missing or escapes the checkout: {path}")

    output_root.mkdir(parents=True, exist_ok=True)
    sources = []
    chunks = []
    included_paths = set()
    for row in selected:
        path = _safe_repo_path(row["path"], label="source path")
        source_format = _source_format(path)
        if source_format is None:
            raise ValueError(f"unsupported source format: {path}")
        raw = _git_blob(repository_root, identity["pinned_commit"], path)
        review = project_manifest["source_license_reviews"][path]
        source_id = row["source_id"]
        stored_path = f"sources/{source_id}{PurePosixPath(path).suffix.casefold()}"
        language = row.get("language", "en")
        if language not in {"en", "zh"}:
            raise ValueError(f"source language must be en or zh: {path}")
        locale = "zh-CN" if language == "zh" else "en-US"
        source_url = (
            f"https://github.com/{identity['primary_repository']}/blob/"
            f"{identity['pinned_commit']}/{quote(path, safe='/') }"
        )
        (output_root / stored_path).parent.mkdir(parents=True, exist_ok=True)
        (output_root / stored_path).write_bytes(raw)
        source = {
            "source_id": source_id,
            "document_id": source_id,
            "document_key": source_id,
            "document_key": source_id,
            "title": row.get("title") or PurePosixPath(path).name,
            "repository": identity["primary_repository"],
            "repository_url": f"https://github.com/{identity['primary_repository']}",
            "commit": identity["pinned_commit"],
            "path": path,
            "document_path": path,
            "local_path": stored_path,
            "source_format": source_format,
            "source_url": source_url,
            "source_type": "project_file",
            "version": identity["pinned_commit"],
            "language": language,
            "locale": locale,
            "namespace": "project_primary",
            "project_id": identity["project_id"],
            "publisher": review["publisher"],
            "license_id": review["license_id"],
            "license_status": review["license_status"],
            "review_reference": review["review_reference"],
            "sha256": expected_sha,
        }
        sources.append(source)
        blocks = _pdf_pages(raw, path) if source_format == "pdf" else _text_blocks(raw, path, source_format)
        for number, block in enumerate(blocks, start=1):
            chunks.append({
                "chunk_id": f"{source_id}:{number}",
                "document_id": source_id,
                "document_key": source_id,
                "document_title": source["title"],
                "heading": block.get("heading", source["title"]),
                "heading_path": block.get("heading_path", []),
                "content": block["text"],
                "project_id": identity["project_id"],
                "namespace": "project_primary",
                "repository": identity["primary_repository"],
                "commit": identity["pinned_commit"],
                "document_path": path,
                "version": identity["pinned_commit"],
                "language": language,
                "locale": locale,
                "source_url": source_url,
                "source_type": "project_file",
                "source_id": source_id,
                "source_format": source_format,
                "publisher": source["publisher"],
                "license_id": source["license_id"],
                "license_status": "approved",
                "source_sha256": expected_sha,
                "line_start": block.get("line_start"),
                "line_end": block.get("line_end"),
                "page_start": block.get("page_start"),
                "page_end": block.get("page_end"),
            })
        included_paths.add(path)

    excluded = []
    for path, audit_row in sorted(audit_rows.items()):
        if path in included_paths:
            continue
        source_format = _source_format(path)
        if source_format is None:
            reason = "unsupported_format"
        elif not audit_row["allowed_for_indexing"]:
            reason = "outside_path_allowlist"
        elif audit_row["license_status"] == "link_only":
            reason = "link_only_no_body"
        elif audit_row["license_status"] != "approved":
            reason = "license_not_approved"
        else:
            reason = "not_selected"
        excluded.append({"path": path, "license_status": audit_row["license_status"], "reason": reason})

    dependency_rows = project_manifest.get("dependency_reference_allowlist", [])
    if dependency_rows:
        raise ValueError("dependency references require a separate reviewed corpus build")
    active = bool(sources) and bool(project_manifest.get("public_body_indexing_enabled", False))
    corpus_manifest = {
        "schema_version": 1,
        "active": active,
        "activation_status": "ready" if active else "blocked_pending_approved_source_bodies",
        "project_id": identity["project_id"],
        "workspace_id": identity["project_id"],
        "project_name": project_manifest.get("project_name", identity["project_id"]),
        "workspace": project_manifest.get("project_name", identity["project_id"]),
        "domain_profile": project_manifest.get("domain_profile", {"id": identity["project_id"]}),
        "primary_repository": identity["primary_repository"],
        "repository": identity["primary_repository"],
        "commit": identity["pinned_commit"],
        "pinned_commit": identity["pinned_commit"],
        "current_version": identity["pinned_commit"],
        "available_versions": [identity["pinned_commit"]],
        "version_scopes": {"current": {"versions": [identity["pinned_commit"]]}},
        "languages": sorted({row["language"] for row in sources}),
        "source_snapshot": {
            "repository": identity["primary_repository"],
            "commit": identity["pinned_commit"],
            "version": identity["pinned_commit"],
        },
        "allowed_path_prefixes": identity["allowed_path_prefixes"],
        "sources": sources,
        "source_status": project_manifest.get("source_status", "pending_project_source_review"),
        "public_body_indexing_enabled": bool(project_manifest.get("public_body_indexing_enabled", False)),
        "license_discovery": project_manifest.get("license_discovery", {}),
        "source_count": len(sources),
        "project_primary_count": len(sources),
        "dependency_reference_count": 0,
        "chunk_count": len(chunks),
        "namespaces": ["project_primary"] if sources else [],
        "dependency_reference_allowlist": [],
    }
    vector_matrix = (
        np.stack([dense_vector(f"{row['heading']} {' '.join(row['heading_path'])} {row['content']}") for row in chunks])
        if chunks else np.zeros((0, 512), dtype=np.float32)
    )
    manifest_path = output_root / "corpus_manifest.json"
    chunks_path = output_root / "chunks.json"
    vectors_path = output_root / "dense_vectors.npy"
    _write_json(manifest_path, corpus_manifest)
    _write_json(chunks_path, chunks)
    np.save(vectors_path, vector_matrix)
    manifest_hash = hashlib.sha256(manifest_path.read_bytes()).hexdigest()
    artifact_hashes = {
        path.name: hashlib.sha256(path.read_bytes()).hexdigest()
        for path in (chunks_path, vectors_path)
    }
    _write_json(output_root / "retrieval_policy.json", {
        "schema_version": 1,
        "default_policy": "bm25",
        "selection_status": "pending_project_rebenchmark",
        "benchmark_query_count": 0,
        "reranker_enabled": False,
        "benchmark_corpus_sha256": manifest_hash,
        "index_artifacts_sha256": artifact_hashes,
    })
    runtime_config = {
        "schema_version": 1, "allowed_policies": ["bm25"], "default_policy": "bm25",
        "max_facets": 4, "rrf_k": 60, "image_top_k": 5,
    }
    _write_json(output_root / "public_retrieval_runtime.json", runtime_config)
    inventory_bytes = (json.dumps({
        "schema_version": 1, "corpus_manifest_sha256": manifest_hash, "figures": [],
    }, separators=(",", ":")) + "\n").encode("utf-8")
    reviewed_bytes = (json.dumps({
        "schema_version": 1, "corpus_manifest_sha256": manifest_hash, "chunks": [],
    }, separators=(",", ":")) + "\n").encode("utf-8")
    (output_root / "figure_evidence.json").write_bytes(inventory_bytes)
    (output_root / "figure_evidence_reviewed.json").write_bytes(reviewed_bytes)
    _write_json(output_root / "figure_evidence_reviewed.lock.json", {
        "schema_version": 1,
        "sidecar_sha256": hashlib.sha256(reviewed_bytes).hexdigest(),
        "corpus_manifest_sha256": manifest_hash,
    })
    import_manifest = {
        "schema_version": 1,
        "project_id": identity["project_id"],
        "repository": identity["primary_repository"],
        "commit": identity["pinned_commit"],
        "audit_mode": "metadata_only" if not sources else "approved_source_bodies",
        "included_count": len(sources),
        "excluded_count": len(excluded),
        "included": [{"source_id": row["source_id"], "path": row["path"], "namespace": row["namespace"]} for row in sources],
        "excluded": excluded,
    }
    _write_json(output_root / "source_import_manifest.json", import_manifest)
    manifest_sha = hashlib.sha256((output_root / "corpus_manifest.json").read_bytes()).hexdigest()
    return {
        "source_count": len(sources),
        "chunk_count": len(chunks),
        "namespace_counts": {
            "project_primary": len(sources),
            "dependency_reference": 0,
        },
        "active": active,
        "manifest_sha256": manifest_sha,
        "output_root": str(output_root),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repository-root", type=Path, required=True)
    parser.add_argument("--project-manifest", type=Path, required=True)
    parser.add_argument("--source-selection", type=Path, required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    args = parser.parse_args()
    project = _read_json_file(args.project_manifest, "project manifest")
    selection = _read_json_file(args.source_selection, "source selection")
    print(json.dumps(build_project_corpus(args.repository_root, project, selection, args.output_root), ensure_ascii=False))


if __name__ == "__main__":
    main()
