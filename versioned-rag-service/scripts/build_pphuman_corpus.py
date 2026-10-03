"""Import an allowlisted, release-pinned Chinese PP-Human corpus."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
from pathlib import Path, PurePosixPath
from urllib.parse import quote, urlparse

from src.document_relations import document_id
from src.pphuman_corpus import (
    PPHUMAN_LICENSE,
    PPHUMAN_PUBLISHER,
    PPHUMAN_REPOSITORY,
    PPHUMAN_SOURCE_PATHS,
    PPHUMAN_WORKSPACE_ID,
)
from src.public_knowledge import build_index


SERVICE_ROOT = Path(__file__).resolve().parents[1]
PROJECT_CONFIG = SERVICE_ROOT / "config" / "pphuman_project.json"
SOURCE_SELECTION = SERVICE_ROOT / "config" / "pphuman_source_selection.json"
DEFAULT_OUTPUT = SERVICE_ROOT / "public_corpus_pphuman"
_HAN = re.compile(r"[\u3400-\u9fff]")


def _run_git(repository_root: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess:
    try:
        result = subprocess.run(
            ["git", "-C", str(Path(repository_root).resolve()), *args],
            check=False,
            capture_output=True,
            timeout=30,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise ValueError("could not read the pinned PaddleDetection repository") from exc
    if check and result.returncode != 0:
        raise ValueError("could not resolve a pinned PaddleDetection tag or source file")
    return result


def _resolve_remote_repository(remote: str) -> str:
    candidate = remote.strip()
    if candidate.startswith("git@github.com:"):
        path = candidate.removeprefix("git@github.com:")
    else:
        parsed = urlparse(candidate)
        if parsed.scheme != "https" or parsed.hostname != "github.com" or parsed.username or parsed.password:
            raise ValueError("upstream origin must be the official PaddleDetection GitHub repository")
        path = parsed.path.strip("/")
    return path.removesuffix(".git").casefold()


def _json_bytes(payload: dict) -> bytes:
    return (json.dumps(payload, ensure_ascii=False, indent=2) + "\n").encode("utf-8")


def write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(_json_bytes(payload))


def _read_blob(repository_root: Path, commit: str, path: str) -> bytes:
    result = _run_git(repository_root, "show", f"{commit}:{path}", check=False)
    if result.returncode != 0:
        return b""
    return result.stdout


def _tree_mode(repository_root: Path, commit: str, path: str) -> str | None:
    result = _run_git(repository_root, "ls-tree", commit, "--", path, check=False)
    if result.returncode != 0 or not result.stdout.strip():
        return None
    metadata = result.stdout.decode("utf-8", errors="replace").split("\t", 1)[0].split()
    return metadata[0] if len(metadata) >= 3 else None


def _validate_inputs(repository_root: Path, project: dict, selection: dict) -> list[str]:
    if project.get("schema_version") != 1 or project.get("workspace_id") != PPHUMAN_WORKSPACE_ID:
        raise ValueError("project config does not belong to PP-Human")
    if project.get("repository") != PPHUMAN_REPOSITORY or project.get("publisher") != PPHUMAN_PUBLISHER:
        raise ValueError("project config must use the official PaddleDetection repository and publisher")
    if project.get("license") != PPHUMAN_LICENSE:
        raise ValueError("project config has an unapproved source license")
    origin = _run_git(repository_root, "remote", "get-url", "origin").stdout.decode().strip()
    if _resolve_remote_repository(origin) != PPHUMAN_REPOSITORY.casefold():
        raise ValueError("repository origin is not the official PaddleDetection repository")
    versions = project.get("versions")
    if not isinstance(versions, dict) or not versions or list(versions)[-1] != project.get("current_version"):
        raise ValueError("project config must list releases in order with the latest release last")
    if selection.get("schema_version") != 1 or selection.get("workspace_id") != PPHUMAN_WORKSPACE_ID:
        raise ValueError("source selection does not belong to PP-Human")
    sources = selection.get("sources")
    if not isinstance(sources, list) or not sources:
        raise ValueError("PP-Human source selection is empty")
    paths = []
    for row in sources:
        if not isinstance(row, dict):
            raise ValueError("PP-Human selected source metadata is invalid")
        path = row.get("path")
        if not isinstance(path, str) or path not in PPHUMAN_SOURCE_PATHS or path in paths:
            raise ValueError("PP-Human source selection contains an unapproved or duplicate path")
        if not isinstance(row.get("title"), str) or not row["title"].strip():
            raise ValueError("PP-Human source selection is missing a Chinese title")
        if not isinstance(row.get("document_family"), str) or not row["document_family"].strip():
            raise ValueError("PP-Human source selection is missing its document family")
        paths.append(path)
    return paths


def _license_text(repository_root: Path, commit: str) -> None:
    body = _read_blob(repository_root, commit, "LICENSE").decode("utf-8", errors="replace")
    if "Apache License" not in body or "Version 2.0" not in body:
        raise ValueError("the pinned PaddleDetection release does not declare Apache License 2.0")


def _source_id(version: str, path: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", path.casefold()).strip("-")
    suffix = hashlib.sha1(path.encode("utf-8")).hexdigest()[:7]
    return f"{version.replace('.', '-')}-{slug[:65]}-{suffix}"


def _source_title(row: dict, path: str) -> str:
    return str(row.get("title") or PurePosixPath(path).stem)


def _build_relation_registry(manifest: dict) -> dict:
    groups: dict[str, list[dict]] = {}
    for source in manifest["sources"]:
        groups.setdefault(source["document_key"], []).append(source)
    relations = []
    for path, rows in sorted(groups.items()):
        ordered = sorted(rows, key=lambda row: manifest["available_versions"].index(row["version"]))
        for older, newer in zip(ordered, ordered[1:]):
            relation_id = f"version-path-{hashlib.sha1((path + older['version'] + newer['version']).encode()).hexdigest()[:16]}"
            relations.append({
                "relation_id": relation_id,
                "relation_type": "supersedes",
                "verification_status": "candidate",
                "source_document_id": document_id(newer),
                "target_document_id": document_id(older),
                "verification_evidence": (
                    f"同一 PaddleDetection 路径 {path} 出现在正式 release {older['version']} 与 {newer['version']}；"
                    "这里只标记版本沿革候选，未据此断言实现行为变化，影响范围仍需工程师复核。"
                ),
            })
    manifest_hash = hashlib.sha256(_json_bytes(manifest)).hexdigest()
    return {"schema_version": 1, "corpus_manifest_sha256": manifest_hash, "relations": relations}


def _audit_markdown(import_manifest: dict, project: dict) -> str:
    lines = [
        "# PP-Human 语料来源、版本与许可审计",
        "",
        "## 语料范围",
        "",
        f"活动来源限定为 `{PPHUMAN_REPOSITORY}` 的 PP-Human 中文教程与相关工程配置，发布方为 PaddlePaddle。正式 release 范围：",
        "",
    ]
    for version, row in project["versions"].items():
        lines.append(f"- `{version}`：提交 `{row['commit']}`")
    lines.extend([
        "",
        f"默认版本为 `{project['current_version']}`。v2.4.0 不含所选 PP-Human 文档目录，因此不作为空的历史版本展示。",
        "",
        "## 许可与边界",
        "",
        "纳入文件来自 PaddleDetection 仓库根目录声明的 Apache-2.0 许可，并逐条保留仓库、正式 tag、原始路径、提交 SHA 和文件 SHA-256。不同发布方的资料不混入本语料。",
        "",
        "本次只复制白名单中的 Markdown 中文教程和 YAML 工程配置，不复制模型权重、示例图片/视频或数据集文件。页面引用的第三方媒体只保留在官方页面链接中；文档内标注的学术使用限制仍按原文显示。",
        "",
        "该工作台用于公开研发资料查询与变更影响候选整理，不处理真人图像、视频、身份或员工行为数据，也不代表真实企业内部评审、模型效果或量产验证。",
        "",
        "## 纳入文件",
        "",
        "| 版本 | 页面/配置 | 原始路径 | SHA-256 |",
        "| --- | --- | --- | --- |",
    ])
    for source in import_manifest["sources"]:
        lines.append(
            f"| `{source['version']}` | [{source['title']}]({source['source_url']}) | `.{source['path']}` | `{source['sha256']}` |"
        )
    lines.extend(["", "## 未纳入项", ""])
    if import_manifest["excluded"]:
        for row in import_manifest["excluded"]:
            lines.append(f"- `{row['version']}` `{row['path']}`：{row['reason']}")
    else:
        lines.append("- 本次白名单中各 release 均找到对应文件。")
    lines.append("")
    return "\n".join(lines)


def build_corpus(
    repository_root: Path,
    project_config: dict,
    source_selection: dict,
    output_root: Path,
) -> dict:
    """Copy approved Git blobs per release, build versioned index and locks."""
    repository_root = Path(repository_root).resolve()
    output_root = Path(output_root).resolve()
    paths = _validate_inputs(repository_root, project_config, source_selection)
    if output_root.exists() and any(output_root.iterdir()):
        raise ValueError("PP-Human build requires a new, empty output directory")

    versions = project_config["versions"]
    for version, snapshot in versions.items():
        result = _run_git(repository_root, "rev-parse", "--verify", f"{snapshot['tag']}^{{commit}}", check=False)
        actual = result.stdout.decode("ascii", errors="ignore").strip().casefold()
        if result.returncode != 0 or actual != snapshot.get("commit"):
            raise ValueError(f"official release tag does not match its pinned commit: {version}")
    _license_text(repository_root, project_config["versions"][project_config["current_version"]]["commit"])

    output_root.mkdir(parents=True, exist_ok=True)
    selected_by_path = {row["path"]: row for row in source_selection["sources"]}
    imported = []
    excluded = []
    available_versions = list(versions)
    for version, snapshot in versions.items():
        commit = snapshot["commit"]
        for path in paths:
            mode = _tree_mode(repository_root, commit, path)
            if mode is None:
                excluded.append({"version": version, "path": path, "reason": "not_present_in_release_tag"})
                continue
            if mode not in {"100644", "100755"}:
                raise ValueError(f"PP-Human source must be a regular Git file: {version}:{path}")
            raw = _read_blob(repository_root, commit, path)
            if not raw:
                excluded.append({"version": version, "path": path, "reason": "empty_source"})
                continue
            try:
                content = raw.decode("utf-8-sig")
            except UnicodeDecodeError as exc:
                raise ValueError(f"selected PP-Human source is not UTF-8 text: {version}:{path}") from exc
            suffix = PurePosixPath(path).suffix.casefold()
            source_format = {".md": "markdown", ".yml": "yaml"}.get(suffix)
            if source_format is None:
                raise ValueError(f"unsupported PP-Human source format: {path}")
            if source_format == "markdown" and not _HAN.search(content):
                raise ValueError(f"English-only or non-Chinese documentation is not allowed: {path}")

            selection = selected_by_path[path]
            source_id = _source_id(version, path)
            local_path = f"sources/{version}/{path}"
            destination = output_root.joinpath(*PurePosixPath(local_path).parts)
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes(raw)
            digest = hashlib.sha256(raw).hexdigest()
            source_url = (
                f"https://github.com/{PPHUMAN_REPOSITORY}/blob/{commit}/{quote(path, safe='/')}"
            )
            imported.append({
                "source_id": source_id,
                "version": version,
                "source_snapshot": version,
                "document_key": str(PurePosixPath(path).with_suffix("")),
                "document_title": _source_title(selection, path),
                "document_path": path,
                "path": path,
                "local_path": local_path,
                "source_type": "official_documentation" if source_format == "markdown" else "official_project_config",
                "source_format": source_format,
                "source_url": source_url,
                "repository": PPHUMAN_REPOSITORY,
                "publisher": PPHUMAN_PUBLISHER,
                "commit": commit,
                "sha256": digest,
                "language": "zh",
                "locale": "zh-CN",
                "license": PPHUMAN_LICENSE,
                "license_status": "redistributable",
                "license_url": project_config["license_url"],
                "attribution": (
                    f"PaddleDetection · {version} · {path} · Apache-2.0 · commit {commit}"
                ),
                "document_family": selection["document_family"],
                "title": _source_title(selection, path),
                "size_bytes": len(raw),
            })

    if not imported:
        raise ValueError("none of the selected PP-Human sources exist in the pinned releases")
    import_manifest = {
        "schema_version": 1,
        "workspace_id": PPHUMAN_WORKSPACE_ID,
        "publisher": PPHUMAN_PUBLISHER,
        "repository": PPHUMAN_REPOSITORY,
        "license": PPHUMAN_LICENSE,
        "latest_version": project_config["current_version"],
        "version_count": len(available_versions),
        "selected_path_count": len(paths),
        "included_count": len(imported),
        "sources": imported,
        "excluded": excluded,
    }
    write_json(output_root / "source_import_manifest.json", import_manifest)

    manifest = {
        "schema_version": 1,
        "workspace_id": PPHUMAN_WORKSPACE_ID,
        "workspace": project_config["workspace"],
        "domain_profile": project_config["domain_profile"],
        "repository": PPHUMAN_REPOSITORY,
        "publisher": PPHUMAN_PUBLISHER,
        "license": PPHUMAN_LICENSE,
        "license_url": project_config["license_url"],
        "baseline_version": available_versions[0],
        "current_version": project_config["current_version"],
        "available_versions": available_versions,
        "version_scopes": {"latest": {"versions": [project_config["current_version"]]}},
        "versions": {version: dict(snapshot) for version, snapshot in versions.items()},
        "languages": ["zh"],
        "source_count": len(imported),
        "unique_document_count": len({row["document_key"] for row in imported}),
        "chunk_count": 0,
        "active": True,
        "source_status": "ready",
        "public_body_indexing_enabled": True,
        "retrieval_evaluation_status": "new_corpus_pending_rebenchmark",
        "data_origin": project_config["data_origin"],
        "upstream_writes_enabled": False,
        "sources": imported,
    }
    write_json(output_root / "corpus_manifest.json", manifest)
    write_json(output_root / "retrieval_policy.json", {
        "schema_version": 1,
        "default_policy": "bm25",
        "selection_status": "new_corpus_pending_rebenchmark",
        "benchmark_query_count": 0,
        "reranker_enabled": False,
        "benchmark_corpus_sha256": "",
    })
    write_json(output_root / "public_retrieval_runtime.json", {
        "schema_version": 1,
        "default_policy": "bm25",
        "allowed_policies": ["bm25", "bm25_faceted_rrf"],
        "max_facets": 4,
        "rrf_k": 60,
        "image_top_k": 5,
    })
    result = build_index(output_root)
    final_manifest = json.loads((output_root / "corpus_manifest.json").read_text(encoding="utf-8"))
    write_json(output_root / "document_relations.json", _build_relation_registry(final_manifest))
    manifest_hash = hashlib.sha256((output_root / "corpus_manifest.json").read_bytes()).hexdigest()
    inventory = {"schema_version": 1, "corpus_manifest_sha256": manifest_hash, "figures": []}
    reviewed = {"schema_version": 1, "corpus_manifest_sha256": manifest_hash, "chunks": []}
    inventory_bytes = _json_bytes(inventory)
    reviewed_bytes = _json_bytes(reviewed)
    (output_root / "figure_evidence.json").write_bytes(inventory_bytes)
    (output_root / "figure_evidence_reviewed.json").write_bytes(reviewed_bytes)
    write_json(output_root / "figure_evidence_reviewed.lock.json", {
        "schema_version": 1,
        "sidecar_sha256": hashlib.sha256(reviewed_bytes).hexdigest(),
        "corpus_manifest_sha256": manifest_hash,
    })
    (output_root / "SOURCE_AUDIT.md").write_text(
        _audit_markdown(import_manifest, project_config), encoding="utf-8", newline="\n",
    )
    return {
        **result,
        "workspace_id": PPHUMAN_WORKSPACE_ID,
        "source_count": len(imported),
        "excluded_count": len(excluded),
        "versions": available_versions,
        "current_version": project_config["current_version"],
        "manifest_sha256": manifest_hash,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repository-root", type=Path, required=True)
    parser.add_argument("--project-config", type=Path, default=PROJECT_CONFIG)
    parser.add_argument("--source-selection", type=Path, default=SOURCE_SELECTION)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    project = json.loads(args.project_config.read_text(encoding="utf-8"))
    selection = json.loads(args.source_selection.read_text(encoding="utf-8"))
    result = build_corpus(args.repository_root, project, selection, args.output)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
