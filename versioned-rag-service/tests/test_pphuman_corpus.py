from __future__ import annotations

import hashlib
import subprocess
import json
from pathlib import Path

import pytest

from src.public_knowledge import PublicKnowledgeIndex, build_index
from src.pphuman_corpus import validate_pphuman_manifest
from scripts.build_pphuman_corpus import build_corpus


REPOSITORY = "PaddlePaddle/PaddleDetection"


def _manifest(root, *, language="zh", repository=REPOSITORY):
    snapshots = {
        "v2.8.1": {"tag": "v2.8.1", "commit": "a" * 40},
        "v2.9.0": {"tag": "v2.9.0", "commit": "b" * 40},
    }
    sources = []
    for version, snapshot in snapshots.items():
        path = "deploy/pipeline/docs/tutorials/PPHuman_QUICK_STARTED.md"
        local_path = f"sources/{version}/PPHuman_QUICK_STARTED.md"
        body = f"# {version} 快速开始\n\nPP-Human 配置与部署说明。\n".encode()
        local_file = root / local_path
        local_file.parent.mkdir(parents=True, exist_ok=True)
        local_file.write_bytes(body)
        sources.append({
            "source_id": f"{version.replace('.', '-')}-quick-start",
            "version": version,
            "source_snapshot": version,
            "document_key": "deploy/pipeline/docs/tutorials/PPHuman_QUICK_STARTED",
            "document_title": "PP-Human快速开始",
            "source_type": "official_documentation",
            "source_format": "markdown",
            "repository": repository,
            "commit": snapshot["commit"],
            "path": path,
            "document_path": path,
            "local_path": local_path,
            "language": language,
            "locale": "zh-CN" if language == "zh" else "en-US",
            "publisher": "PaddlePaddle",
            "license": "Apache-2.0",
            "license_status": "redistributable",
            "attribution": "PaddleDetection, Apache-2.0",
            "source_url": f"https://github.com/{repository}/blob/{snapshot['commit']}/{path}",
            "sha256": hashlib.sha256(body).hexdigest(),
        })
    return {
        "schema_version": 1,
        "workspace_id": "pphuman",
        "workspace": "PP-Human 行人分析工程资料",
        "publisher": "PaddlePaddle",
        "repository": REPOSITORY,
        "license": "Apache-2.0",
        "current_version": "v2.9.0",
        "available_versions": ["v2.8.1", "v2.9.0"],
        "version_scopes": {"latest": {"versions": ["v2.9.0"]}},
        "versions": snapshots,
        "source_count": len(sources),
        "languages": ["zh"],
        "sources": sources,
    }


def test_manifest_accepts_version_pinned_chinese_sources_from_one_official_repo(tmp_path):
    status = validate_pphuman_manifest(tmp_path, _manifest(tmp_path))

    assert status == {
        "workspace_id": "pphuman",
        "repository": REPOSITORY,
        "current_version": "v2.9.0",
        "available_versions": ["v2.8.1", "v2.9.0"],
        "source_count": 2,
    }


@pytest.mark.parametrize(
    "patch, message",
    [
        ({"repository": "PaddlePaddle/PaddleDetection"}, "repository or version commit"),
        ({"language": "en"}, "Chinese-language material"),
    ],
)
def test_manifest_rejects_unapproved_repository_or_non_chinese_source(tmp_path, patch, message):
    manifest = _manifest(tmp_path, **patch)
    if patch.get("repository"):
        manifest["sources"][0]["repository"] = "someone/other-project"
    with pytest.raises(ValueError, match=message):
        validate_pphuman_manifest(tmp_path, manifest)


def test_manifest_rejects_source_commit_drift_and_hash_mismatch(tmp_path):
    manifest = _manifest(tmp_path)
    manifest["sources"][0]["commit"] = "c" * 40

    with pytest.raises(ValueError, match="version commit"):
        validate_pphuman_manifest(tmp_path, manifest)

    manifest = _manifest(tmp_path)
    manifest["sources"][0]["sha256"] = "0" * 64
    with pytest.raises(ValueError, match="hash mismatch"):
        validate_pphuman_manifest(tmp_path, manifest)


def test_manifest_rejects_foreign_path_and_release_not_registered(tmp_path):
    manifest = _manifest(tmp_path)
    manifest["sources"][0]["path"] = "docs/unrelated.md"
    with pytest.raises(ValueError, match="outside the PP-Human allowlist"):
        validate_pphuman_manifest(tmp_path, manifest)

    manifest = _manifest(tmp_path)
    manifest["sources"][0]["version"] = "v9.9.9"
    with pytest.raises(ValueError, match="registered release"):
        validate_pphuman_manifest(tmp_path, manifest)


def test_index_builds_release_scoped_chinese_chunks_and_defaults_to_latest(tmp_path):
    manifest = _manifest(tmp_path)
    manifest_path = tmp_path / "corpus_manifest.json"
    manifest_path.write_text(__import__("json").dumps(manifest, ensure_ascii=False), encoding="utf-8")
    (tmp_path / "retrieval_policy.json").write_text(
        '{"default_policy":"bm25","benchmark_corpus_sha256":"","index_artifacts_sha256":{}}',
        encoding="utf-8",
    )

    result = build_index(tmp_path)
    index = PublicKnowledgeIndex(tmp_path)
    latest = index.search("PP-Human 配置 部署", version="latest", language="zh")
    historical = index.search("PP-Human 配置 部署", version="v2.8.1", language="zh")

    assert result["files"] == 2
    assert index.manifest["current_version"] == "v2.9.0"
    assert {hit["version"] for hit in latest} == {"v2.9.0"}
    assert {hit["version"] for hit in historical} == {"v2.8.1"}
    assert all(hit["repository"] == REPOSITORY for hit in latest + historical)
    assert all(hit["commit"] in {"a" * 40, "b" * 40} for hit in latest + historical)


def _git(root: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(root), *args], check=True,
        capture_output=True, text=True,
    )
    return result.stdout.strip()


def test_builder_imports_only_licensed_chinese_docs_from_exact_release_tags(tmp_path):
    repository_root = tmp_path / "upstream"
    repository_root.mkdir()
    _git(repository_root, "init", "--quiet")
    _git(repository_root, "config", "user.email", "builder@example.invalid")
    _git(repository_root, "config", "user.name", "Corpus Fixture")
    _git(repository_root, "remote", "add", "origin", f"https://github.com/{REPOSITORY}.git")
    (repository_root / "LICENSE").write_text(
        "Apache License\nVersion 2.0, January 2004\n", encoding="utf-8",
    )
    source_path = repository_root / "deploy" / "pipeline" / "docs" / "tutorials" / "PPHuman_QUICK_STARTED.md"
    source_path.parent.mkdir(parents=True)
    source_path.write_text("# v2.8.1 快速开始\n\n推理配置说明。\n", encoding="utf-8")
    _git(repository_root, "add", ".")
    _git(repository_root, "commit", "--quiet", "-m", "release 2.8.1 docs")
    old_commit = _git(repository_root, "rev-parse", "HEAD")
    _git(repository_root, "tag", "v2.8.1")
    source_path.write_text("# v2.9.0 快速开始\n\n新版本推理配置说明。\n", encoding="utf-8")
    _git(repository_root, "add", ".")
    _git(repository_root, "commit", "--quiet", "-m", "release 2.9.0 docs")
    latest_commit = _git(repository_root, "rev-parse", "HEAD")
    _git(repository_root, "tag", "v2.9.0")

    project_config = {
        "schema_version": 1,
        "workspace_id": "pphuman",
        "workspace": "PP-Human 行人分析工程知识",
        "publisher": "PaddlePaddle",
        "repository": REPOSITORY,
        "repository_url": f"https://github.com/{REPOSITORY}",
        "license": "Apache-2.0",
        "license_url": f"https://github.com/{REPOSITORY}/blob/v2.9.0/LICENSE",
        "license_review_reference": "PaddleDetection root LICENSE",
        "current_version": "v2.9.0",
        "versions": {
            "v2.8.1": {"tag": "v2.8.1", "commit": old_commit},
            "v2.9.0": {"tag": "v2.9.0", "commit": latest_commit},
        },
        "domain_profile": {"id": "pphuman", "example_queries": ["PP-Human 如何配置？"]},
        "data_origin": "PaddleDetection 官方中文 PP-Human 资料。",
    }
    selection = {
        "schema_version": 1,
        "workspace_id": "pphuman",
        "sources": [{
            "path": "deploy/pipeline/docs/tutorials/PPHuman_QUICK_STARTED.md",
            "title": "PP-Human 快速开始",
            "document_family": "quick_start",
        }],
    }

    result = build_corpus(repository_root, project_config, selection, tmp_path / "corpus")
    index = PublicKnowledgeIndex(tmp_path / "corpus")
    latest = index.search("推理配置", version="latest", language="zh")
    history = index.search("推理配置", version="v2.8.1", language="zh")
    imported = json.loads((tmp_path / "corpus" / "source_import_manifest.json").read_text(encoding="utf-8"))

    assert result["source_count"] == 2
    assert imported["excluded"] == []
    assert {hit["version"] for hit in latest} == {"v2.9.0"}
    assert {hit["version"] for hit in history} == {"v2.8.1"}
    assert {hit["commit"] for hit in latest + history} == {old_commit, latest_commit}
