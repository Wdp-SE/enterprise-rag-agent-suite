"""Integrity checks for the versioned, Chinese PP-Human documentation corpus."""

from __future__ import annotations

import hashlib
import re
from pathlib import Path, PurePosixPath
from urllib.parse import quote


PPHUMAN_WORKSPACE_ID = "pphuman"
PPHUMAN_REPOSITORY = "PaddlePaddle/PaddleDetection"
PPHUMAN_PUBLISHER = "PaddlePaddle"
PPHUMAN_LICENSE = "Apache-2.0"
PPHUMAN_SOURCE_PATHS = frozenset({
    "configs/pphuman/pedestrian_yolov3/README_cn.md",
    "configs/pphuman/ppyoloe_crn_l_36e_pphuman.yml",
    "configs/pphuman/ppyoloe_crn_s_36e_pphuman.yml",
    "configs/pphuman/ppyoloe_plus_crn_t_auxhead_320_60e_pphuman.yml",
    "deploy/pipeline/config/infer_cfg_pphuman.yml",
    "deploy/pipeline/config/tracker_config.yml",
    "deploy/pipeline/docs/tutorials/PPHuman_QUICK_STARTED.md",
    "deploy/pipeline/docs/tutorials/pphuman_action.md",
    "deploy/pipeline/docs/tutorials/pphuman_attribute.md",
    "deploy/pipeline/docs/tutorials/pphuman_mot.md",
    "deploy/pipeline/docs/tutorials/pphuman_mtmct.md",
    "docs/advanced_tutorials/customization/pphuman_attribute.md",
    "docs/advanced_tutorials/customization/pphuman_mot.md",
    "docs/advanced_tutorials/customization/pphuman_mtmct.md",
})

_SHA40 = re.compile(r"^[0-9a-f]{40}$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_VERSION = re.compile(r"^v\d+\.\d+\.\d+$")
_SOURCE_ID = re.compile(r"^[a-z0-9][a-z0-9-]{2,100}$")


def _safe_relative_path(value: object) -> bool:
    if not isinstance(value, str) or not value or "\\" in value or "\x00" in value:
        return False
    path = PurePosixPath(value)
    return not path.is_absolute() and ".." not in path.parts and "." not in path.parts


def validate_pphuman_manifest(
    root: Path, manifest: dict, chunks: list[dict] | None = None,
) -> dict:
    """Validate exact release, publisher, Chinese-language and file provenance."""
    if not isinstance(manifest, dict) or manifest.get("schema_version") != 1:
        raise ValueError("unsupported PP-Human corpus manifest schema")
    if (
        manifest.get("workspace_id") != PPHUMAN_WORKSPACE_ID
        or manifest.get("repository") != PPHUMAN_REPOSITORY
        or manifest.get("publisher") != PPHUMAN_PUBLISHER
        or manifest.get("license") != PPHUMAN_LICENSE
        or manifest.get("languages") != ["zh"]
    ):
        raise ValueError("PP-Human corpus identity, publisher, license or Chinese-only scope mismatch")

    versions = manifest.get("versions")
    available_versions = manifest.get("available_versions")
    current_version = manifest.get("current_version")
    if (
        not isinstance(versions, dict) or not versions
        or not isinstance(available_versions, list)
        or available_versions != list(versions)
        or current_version != available_versions[-1]
        or not isinstance(current_version, str)
    ):
        raise ValueError("PP-Human release registry or latest version is invalid")
    for version, snapshot in versions.items():
        if (
            not isinstance(version, str) or not _VERSION.fullmatch(version)
            or not isinstance(snapshot, dict) or snapshot.get("tag") != version
            or not isinstance(snapshot.get("commit"), str)
            or not _SHA40.fullmatch(snapshot["commit"])
        ):
            raise ValueError("PP-Human release registry contains an invalid tag or commit")
    latest_scope = (manifest.get("version_scopes") or {}).get("latest")
    if not isinstance(latest_scope, dict) or latest_scope.get("versions") != [current_version]:
        raise ValueError("PP-Human latest scope must resolve to the newest pinned release")

    sources = manifest.get("sources")
    if not isinstance(sources, list) or not sources:
        raise ValueError("PP-Human source list is empty")
    root_resolved = Path(root).resolve()
    source_ids: set[str] = set()
    version_paths: set[tuple[str, str]] = set()
    sources_by_id: dict[str, dict] = {}
    for source in sources:
        if not isinstance(source, dict):
            raise ValueError("PP-Human source record is invalid")
        source_id = source.get("source_id")
        version = source.get("version")
        path = source.get("path")
        snapshot = versions.get(version) if isinstance(version, str) else None
        if (
            not isinstance(source_id, str) or not _SOURCE_ID.fullmatch(source_id)
            or source_id in source_ids
            or not isinstance(path, str) or path not in PPHUMAN_SOURCE_PATHS
            or (version, path) in version_paths
        ):
            raise ValueError("PP-Human source is outside the PP-Human allowlist or duplicated")
        if not isinstance(snapshot, dict):
            raise ValueError("PP-Human source does not reference a registered release")
        commit = snapshot["commit"]
        if (
            source.get("repository") != PPHUMAN_REPOSITORY
            or source.get("publisher") != PPHUMAN_PUBLISHER
            or source.get("version") not in available_versions
            or source.get("source_snapshot") != version
            or source.get("commit") != commit
        ):
            raise ValueError("PP-Human source repository or version commit mismatch")
        if (
            source.get("language") != "zh" or source.get("locale") != "zh-CN"
            or source.get("license") != PPHUMAN_LICENSE
            or source.get("license_status") != "redistributable"
            or not isinstance(source.get("attribution"), str)
            or "PaddleDetection" not in source["attribution"]
        ):
            raise ValueError("PP-Human source is not approved Chinese-language material")
        expected_url = (
            f"https://github.com/{PPHUMAN_REPOSITORY}/blob/{commit}/{quote(path, safe='/')}"
        )
        if source.get("source_url") != expected_url:
            raise ValueError("PP-Human source URL is not pinned to its release commit")

        local_path = source.get("local_path")
        if not _safe_relative_path(local_path) or not local_path.startswith("sources/"):
            raise ValueError("PP-Human local source path is invalid")
        candidate = root_resolved.joinpath(*PurePosixPath(local_path).parts)
        resolved = candidate.resolve()
        if candidate.is_symlink() or not resolved.is_relative_to(root_resolved) or not resolved.is_file():
            raise ValueError("PP-Human source body is missing or outside the corpus")
        digest = source.get("sha256")
        if not isinstance(digest, str) or not _SHA256.fullmatch(digest):
            raise ValueError("PP-Human source hash is invalid")
        if hashlib.sha256(resolved.read_bytes()).hexdigest() != digest:
            raise ValueError(f"PP-Human source hash mismatch: {local_path}")

        source_ids.add(source_id)
        version_paths.add((version, path))
        sources_by_id[source_id] = source

    if chunks is not None:
        for chunk in chunks:
            if not isinstance(chunk, dict):
                raise ValueError("PP-Human chunk record is invalid")
            source = sources_by_id.get(chunk.get("source_id"))
            if source is None or any(
                chunk.get(field) != source.get(source_field)
                for field, source_field in (
                    ("version", "version"), ("language", "language"),
                    ("repository", "repository"), ("commit", "commit"),
                    ("document_path", "path"), ("source_sha256", "sha256"),
                    ("license_status", "license_status"),
                )
            ) or not isinstance(chunk.get("content"), str) or not chunk["content"].strip():
                raise ValueError("PP-Human chunk has unregistered source provenance")
        if manifest.get("chunk_count") != len(chunks):
            raise ValueError("PP-Human chunk count does not match the manifest")

    if manifest.get("source_count") != len(sources):
        raise ValueError("PP-Human source count does not match the manifest")
    return {
        "workspace_id": PPHUMAN_WORKSPACE_ID,
        "repository": PPHUMAN_REPOSITORY,
        "current_version": current_version,
        "available_versions": list(available_versions),
        "source_count": len(sources),
    }
