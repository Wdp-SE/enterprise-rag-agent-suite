from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path

import pytest

from scripts.build_project_corpus import build_project_corpus


REPOSITORY = "xbs0325/industrial-inspection"


def _git(root: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(root), *args], check=True, capture_output=True, text=True,
    )
    return result.stdout.strip()


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
    output.extend(f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode("ascii"))
    return bytes(output)


def _repo_with_sources(root: Path, files: dict[str, bytes]) -> str:
    root.mkdir(parents=True, exist_ok=True)
    _git(root, "init", "--quiet")
    _git(root, "config", "user.email", "builder@example.invalid")
    _git(root, "config", "user.name", "Builder Fixture")
    for relative, content in files.items():
        target = root / Path(*relative.split("/"))
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(content)
    _git(root, "add", ".")
    _git(root, "commit", "--quiet", "-m", "fixture")
    _git(root, "remote", "add", "origin", f"https://github.com/{REPOSITORY}.git")
    return _git(root, "rev-parse", "HEAD")


def _documents() -> dict[str, bytes]:
    return {
        "README.md": b"# Camera Service\n\nThe camera service reads RTSP input.\n",
        "app/main.py": b"def start_camera():\n    return True\n",
        "config/runtime.yaml": b"camera:\n  source: rtsp\n",
        "config/events.json": b'{"event":"ppe_alert"}\n',
        "scripts/run.sh": b"#!/bin/sh\npython -m app.main\n",
        "docs/operations.txt": b"Restart the service after config changes.\n",
        "docs/guide.pdf": _minimal_text_pdf("Camera health check"),
        "app/private.bin": b"\x00\x01binary",
    }


def _project_manifest(root: Path, commit: str, files: dict[str, bytes], **overrides) -> dict:
    reviews = {
        path: {
            "license_status": "approved",
            "license_id": "CC-BY-4.0",
            "publisher": "xbs0325",
            "review_reference": f"file-review:{path}",
        }
        for path in files
    }
    payload = {
        "schema_version": 1,
        "project_id": "industrial-inspection",
        "primary_repository": REPOSITORY,
        "pinned_commit": commit,
        "allowed_path_prefixes": ["README.md", "app/", "config/", "scripts/", "docs/"],
        "dependency_reference_allowlist": [],
        "source_license_reviews": reviews,
        "public_body_indexing_enabled": True,
    }
    payload.update(overrides)
    return payload


def _selection(files: dict[str, bytes], **overrides) -> dict:
    rows = [
        {"source_id": f"source-{index}", "path": path, "sha256": hashlib.sha256(body).hexdigest()}
        for index, (path, body) in enumerate(files.items(), start=1)
        if path != "app/private.bin"
    ]
    payload = {"schema_version": 1, "sources": rows}
    payload.update(overrides)
    return payload


def test_builder_imports_approved_multiformat_project_sources_with_provenance(tmp_path: Path):
    files = _documents()
    repository_root = tmp_path / "repo"
    commit = _repo_with_sources(repository_root, files)
    output_root = tmp_path / "corpus"

    result = build_project_corpus(
        repository_root,
        _project_manifest(repository_root, commit, files),
        _selection(files),
        output_root,
    )

    assert result["source_count"] == 7
    assert result["namespace_counts"] == {"project_primary": 7, "dependency_reference": 0}
    corpus = json.loads((output_root / "corpus_manifest.json").read_text(encoding="utf-8"))
    assert corpus["active"] is True
    assert {row["source_format"] for row in corpus["sources"]} == {
        "markdown", "python", "yaml", "json", "shell", "text", "pdf"
    }
    assert all(row["namespace"] == "project_primary" for row in corpus["sources"])
    assert all(row["repository"] == REPOSITORY and row["commit"] == commit for row in corpus["sources"])
    assert all(row["publisher"] == "xbs0325" and row["license_status"] == "approved" for row in corpus["sources"])
    chunks = json.loads((output_root / "chunks.json").read_text(encoding="utf-8"))
    assert any("RTSP input" in row["content"] for row in chunks)
    assert any("Camera health check" in row["content"] and row["page_start"] == 1 for row in chunks)
    inventory = json.loads((output_root / "source_import_manifest.json").read_text(encoding="utf-8"))
    assert inventory["included_count"] == 7
    assert any(row["path"] == "app/private.bin" and row["reason"] == "unsupported_format" for row in inventory["excluded"])


def test_empty_approved_selection_builds_inactive_metadata_only_corpus(tmp_path: Path):
    files = {"README.md": b"# Private until license review\n"}
    repository_root = tmp_path / "repo"
    commit = _repo_with_sources(repository_root, files)
    manifest = _project_manifest(repository_root, commit, files)
    manifest["source_license_reviews"] = {}
    output_root = tmp_path / "corpus"

    result = build_project_corpus(
        repository_root,
        manifest,
        {"schema_version": 1, "sources": []},
        output_root,
    )

    assert result["source_count"] == 0
    assert result["active"] is False
    assert not list((output_root / "sources").glob("*"))
    chunks = json.loads((output_root / "chunks.json").read_text(encoding="utf-8"))
    assert chunks == []
    inventory = json.loads((output_root / "source_import_manifest.json").read_text(encoding="utf-8"))
    assert inventory["excluded"][0]["reason"] == "license_not_approved"


@pytest.mark.parametrize(
    "change, message",
    [
        (lambda selection: selection["sources"].append(dict(selection["sources"][0])), "duplicate source_id"),
        (lambda selection: selection["sources"][0].update(path="../outside.md"), "path"),
        (lambda selection: selection["sources"][0].update(sha256="0" * 64), "hash"),
        (lambda selection: selection["sources"][0].update(path="app/private.bin", source_id="binary-source", sha256=hashlib.sha256(b"\x00\x01binary").hexdigest()), "unsupported"),
    ],
)
def test_builder_rejects_duplicate_path_escape_hash_drift_and_unsupported_binary(
    tmp_path: Path, change, message: str,
):
    files = _documents()
    repository_root = tmp_path / "repo"
    commit = _repo_with_sources(repository_root, files)
    manifest = _project_manifest(repository_root, commit, files)
    selection = _selection(files)
    change(selection)

    with pytest.raises(ValueError, match=message):
        build_project_corpus(repository_root, manifest, selection, tmp_path / "corpus")


def test_builder_rejects_two_primary_repositories_and_path_symlink_escape(tmp_path: Path):
    files = {"README.md": b"# Approved\n"}
    repository_root = tmp_path / "repo"
    commit = _repo_with_sources(repository_root, files)
    manifest = _project_manifest(
        repository_root, commit, files,
        primary_repositories=[REPOSITORY, "other/app"],
    )
    with pytest.raises(ValueError, match="one primary repository"):
        build_project_corpus(
            repository_root, manifest, _selection(files), tmp_path / "corpus-a",
        )

    link_target = b"../external.md"
    blob = subprocess.run(
        ["git", "-C", str(repository_root), "hash-object", "-w", "--stdin"],
        input=link_target, capture_output=True, check=True,
    ).stdout.decode("ascii").strip()
    _git(repository_root, "update-index", "--add", "--cacheinfo", f"120000,{blob},escape.md")
    _git(repository_root, "commit", "--quiet", "-m", "add symlink fixture")
    commit = _git(repository_root, "rev-parse", "HEAD")
    manifest = _project_manifest(
        repository_root, commit, files,
        allowed_path_prefixes=["README.md", "escape.md"],
    )
    selection = _selection(files)
    selection["sources"].append({
        "source_id": "escaped-source", "path": "escape.md",
        "sha256": hashlib.sha256(link_target).hexdigest(),
    })
    manifest["source_license_reviews"]["escape.md"] = {
        "license_status": "approved", "license_id": "CC-BY-4.0",
        "publisher": "xbs0325", "review_reference": "explicit-review",
    }
    with pytest.raises(ValueError, match="symlink"):
        build_project_corpus(repository_root, manifest, selection, tmp_path / "corpus-b")


def test_builder_refuses_nonempty_output_directory_instead_of_overwriting_it(tmp_path: Path):
    files = {"README.md": b"# Approved\n"}
    repository_root = tmp_path / "repo"
    commit = _repo_with_sources(repository_root, files)
    output_root = tmp_path / "corpus"
    output_root.mkdir()
    sentinel = output_root / "user-file.txt"
    sentinel.write_text("keep", encoding="utf-8")

    with pytest.raises(ValueError, match="empty output directory"):
        build_project_corpus(
            repository_root,
            _project_manifest(repository_root, commit, files),
            _selection(files),
            output_root,
        )

    assert sentinel.read_text(encoding="utf-8") == "keep"
