"""Runtime validation for the single-project public corpus contract."""

from __future__ import annotations

import hashlib
import re
from pathlib import Path, PurePosixPath


_SHA40 = re.compile(r"^[0-9a-f]{40}$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_SOURCE_ID = re.compile(r"^[a-z0-9][a-z0-9-]{2,79}$")


def _is_allowed_path(path: str, prefixes: list[str]) -> bool:
    candidate = PurePosixPath(path)
    if candidate.is_absolute() or ".." in candidate.parts or "\\" in path or "\x00" in path:
        return False
    return any(
        path == prefix.rstrip("/") or path.startswith(prefix.rstrip("/") + "/")
        for prefix in prefixes
    )


def validate_project_corpus(root: Path, manifest: dict, chunks: list[dict] | None = None) -> dict:
    """Verify project identity, source approvals/hashes, namespace and chunk provenance."""
    project_id = manifest.get("project_id")
    repository = manifest.get("primary_repository")
    commit = manifest.get("pinned_commit")
    prefixes = manifest.get("allowed_path_prefixes")
    sources = manifest.get("sources")
    dependencies = manifest.get("dependency_reference_allowlist", [])
    if not isinstance(project_id, str) or not project_id.strip():
        raise ValueError("project corpus project_id is missing")
    if not isinstance(repository, str) or not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repository):
        raise ValueError("project corpus must have exactly one primary repository")
    if manifest.get("repository") != repository:
        raise ValueError("project corpus repository identity mismatch")
    if not isinstance(commit, str) or not _SHA40.fullmatch(commit):
        raise ValueError("project corpus must pin one full 40-character commit")
    if not isinstance(prefixes, list) or not prefixes:
        raise ValueError("project corpus path allowlist is missing")
    if not isinstance(sources, list):
        raise ValueError("project corpus sources must be a list")
    if not isinstance(dependencies, list):
        raise ValueError("dependency reference allowlist must be a list")
    if dependencies or int(manifest.get("dependency_reference_count", 0)) != 0:
        raise ValueError("dependency references must use a separate reviewed index")
    source_by_id = {}
    seen_paths = set()
    root_resolved = Path(root).resolve()
    for source in sources:
        if not isinstance(source, dict):
            raise ValueError("project corpus source record is invalid")
        source_id = source.get("source_id")
        path = source.get("path")
        if not isinstance(source_id, str) or not _SOURCE_ID.fullmatch(source_id) or source_id in source_by_id:
            raise ValueError("project corpus source_id is invalid or duplicated")
        if not isinstance(path, str) or not _is_allowed_path(path, prefixes) or path in seen_paths:
            raise ValueError("project corpus source path is outside the allowlist or duplicated")
        seen_paths.add(path)
        if (
            source.get("project_id") != project_id
            or source.get("namespace") != "project_primary"
            or source.get("repository") != repository
            or source.get("commit") != commit
        ):
            raise ValueError("project corpus source crosses project, repository, commit or namespace boundaries")
        if source.get("license_status") != "approved" or not all(
            isinstance(source.get(field), str) and source[field].strip()
            for field in ("license_id", "publisher", "review_reference")
        ):
            raise ValueError("project corpus contains a source without approved license provenance")
        digest = source.get("sha256")
        if not isinstance(digest, str) or not _SHA256.fullmatch(digest):
            raise ValueError("project corpus source hash is missing")
        local_path = source.get("local_path")
        if not isinstance(local_path, str) or not _is_allowed_path(local_path, ["sources/"]):
            raise ValueError("project corpus local source path is invalid")
        candidate = root_resolved / Path(*PurePosixPath(local_path).parts)
        resolved = candidate.resolve()
        if candidate.is_symlink() or not resolved.is_relative_to(root_resolved) or not resolved.is_file():
            raise ValueError("project corpus body path is missing or outside the corpus")
        if hashlib.sha256(resolved.read_bytes()).hexdigest() != digest:
            raise ValueError("project corpus source body hash mismatch")
        source_by_id[source_id] = source

    primary_count = manifest.get("project_primary_count")
    if primary_count != len(sources) or manifest.get("source_count", len(sources)) != len(sources):
        raise ValueError("project corpus source counts do not match its manifest")
    if chunks is not None:
        for chunk in chunks:
            if not isinstance(chunk, dict):
                raise ValueError("project corpus chunk record is invalid")
            source = source_by_id.get(chunk.get("source_id"))
            if source is None or (
                chunk.get("project_id") != project_id
                or chunk.get("namespace") != "project_primary"
                or chunk.get("repository") != repository
                or chunk.get("commit") != commit
                or chunk.get("document_path") != source.get("path")
                or chunk.get("source_sha256") != source.get("sha256")
                or chunk.get("license_status") != "approved"
                or not isinstance(chunk.get("content"), str)
                or not chunk["content"].strip()
            ):
                raise ValueError("project corpus chunk has unregistered provenance")
    declared_chunks = manifest.get("chunk_count")
    if chunks is not None and declared_chunks != len(chunks):
        raise ValueError("project corpus chunk count does not match its manifest")

    active = manifest.get("active") is True
    if active and manifest.get("public_body_indexing_enabled") is not True:
        raise ValueError("active project corpus requires explicit public body indexing approval")
    if active and (not sources or not chunks or manifest.get("activation_status") != "ready"):
        raise ValueError("active project corpus is empty or has an invalid activation status")
    reason = None if active else str(manifest.get("source_status") or "pending_project_corpus_activation")
    return {
        "project_id": project_id,
        "repository": repository,
        "commit": commit,
        "active": active,
        "reason": reason,
        "project_primary_count": len(sources),
        "dependency_reference_count": 0,
        "chunk_count": len(chunks) if chunks is not None else int(manifest.get("chunk_count", 0)),
    }
