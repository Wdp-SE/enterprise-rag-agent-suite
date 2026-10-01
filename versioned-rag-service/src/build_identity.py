"""Verified source and public-asset fingerprints for deployment diagnostics."""

from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
from pathlib import Path


_SHA40 = re.compile(r"^[0-9a-f]{40}$")


def git_revision(root: Path, *, timeout_seconds: float = 1.0) -> str | None:
    """Return the platform deploy commit or a clean Git HEAD; otherwise unknown."""
    if os.getenv("RENDER", "").casefold() == "true":
        render_revision = os.getenv("RENDER_GIT_COMMIT", "").strip().casefold()
        if _SHA40.fullmatch(render_revision):
            return render_revision
    try:
        revision = subprocess.run(
            ["git", "-C", str(root), "rev-parse", "--verify", "HEAD"],
            check=False, capture_output=True, text=True, timeout=timeout_seconds,
        )
        if revision.returncode != 0:
            return None
        value = revision.stdout.strip().casefold()
        if not _SHA40.fullmatch(value):
            return None
        status = subprocess.run(
            ["git", "-C", str(root), "status", "--porcelain", "--untracked-files=normal"],
            check=False, capture_output=True, text=True, timeout=timeout_seconds,
        )
        if status.returncode != 0 or status.stdout.strip():
            return None
        return value
    except (OSError, subprocess.SubprocessError):
        return None


def _sha256(path: Path) -> str | None:
    try:
        return hashlib.sha256(path.read_bytes().replace(b"\r\n", b"\n")).hexdigest()
    except OSError:
        return None


def content_fingerprint(paths: dict[str, Path]) -> dict[str, str | None]:
    """Hash named files without returning any file contents."""
    files = {name: _sha256(path) for name, path in sorted(paths.items())}
    if any(value is None for value in files.values()):
        aggregate = "unknown"
    else:
        serialized = json.dumps(files, sort_keys=True, separators=(",", ":")).encode("utf-8")
        aggregate = hashlib.sha256(serialized).hexdigest()
    return {**files, "fingerprint_sha256": aggregate}


def public_build_identity(
    *, repo_root: Path, corpus_root: Path, retrieval_config_path: Path,
) -> dict:
    evaluation_root = repo_root / "evaluation"
    corpus_fingerprint = content_fingerprint({
        "manifest_sha256": corpus_root / "corpus_manifest.json",
        "chunks_sha256": corpus_root / "chunks.json",
        "document_relationships_sha256": corpus_root / "document_relations.json",
        "reviewed_figure_sidecar_sha256": corpus_root / "figure_evidence_reviewed.json",
    })
    retrieval_fingerprint = content_fingerprint({
        "runtime_config_sha256": retrieval_config_path,
        "base_policy_sha256": corpus_root / "retrieval_policy.json",
        "figure_lock_sha256": corpus_root / "figure_evidence_reviewed.lock.json",
    })["fingerprint_sha256"]
    evaluation_fingerprint = content_fingerprint({
        "retrieval_cases_sha256": evaluation_root / "autoware_quality_v1" / "cases.jsonl",
        "retrieval_split_lock_sha256": evaluation_root / "autoware_quality_v1" / "split_lock.json",
        "agent_planning_cases_sha256": evaluation_root / "autoware_agent_query_planning_v1" / "cases.jsonl",
        "agent_planning_split_lock_sha256": evaluation_root / "autoware_agent_query_planning_v1" / "split_lock.json",
    })["fingerprint_sha256"]
    return {
        "build_revision": git_revision(repo_root) or "unknown",
        "corpus_fingerprint": corpus_fingerprint,
        "retrieval_config_fingerprint": retrieval_fingerprint,
        "evaluation_fingerprint": evaluation_fingerprint,
    }
