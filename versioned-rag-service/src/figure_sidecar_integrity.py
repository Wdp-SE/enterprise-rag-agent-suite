"""Integrity checks for the reviewed OCR sidecar used by the public service."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path


def validate_reviewed_sidecar(*, sidecar_path: Path, lock_path: Path, manifest_path: Path) -> None:
    """Fail closed unless both the OCR sidecar and its corpus manifest are pinned."""
    try:
        sidecar_bytes = Path(sidecar_path).read_bytes()
        manifest_bytes = Path(manifest_path).read_bytes()
        lock = json.loads(Path(lock_path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError("public figure evidence sidecar integrity lock is unavailable/invalid") from exc

    if not isinstance(lock, dict) or lock.get("schema_version") != 1:
        raise ValueError("public figure evidence sidecar integrity lock is invalid")

    sidecar_sha256 = hashlib.sha256(sidecar_bytes).hexdigest()
    manifest_sha256 = hashlib.sha256(manifest_bytes).hexdigest()
    if (
        lock.get("sidecar_sha256") != sidecar_sha256
        or lock.get("corpus_manifest_sha256") != manifest_sha256
    ):
        raise ValueError("public figure evidence sidecar integrity does not match pinned digests")
