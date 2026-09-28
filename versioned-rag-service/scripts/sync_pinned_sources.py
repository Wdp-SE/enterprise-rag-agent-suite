"""Fetch allowlisted Apache DolphinScheduler docs at pinned commits."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Callable
from urllib.error import HTTPError
from urllib.request import Request, urlopen
from urllib.parse import quote


SERVICE_ROOT = Path(__file__).resolve().parents[1]
ROOT = SERVICE_ROOT / "public_corpus"
_COMMIT_RE = re.compile(r"^[0-9a-f]{40}$")
_ALLOWED_LANGUAGES = {"en", "zh"}
_OFFICIAL_DOCS_PREFIX = "docs/docs/"
# These pages cover task execution, parameters, alerting, monitoring, and
# operational recovery in the public change-review scenario. Both locales and
# both pinned versions are fetched independently; a missing page stays missing.
ADDITIONAL_TOPICS = (
    "guide/project/task-instance",
    "guide/project/project-list",
    "guide/task/conditions",
    "guide/task/sub-workflow",
    "guide/resource/task-group",
    "guide/resource/file-manage",
    "guide/parameter/project-parameter",
    "guide/parameter/file-parameter",
    "guide/alert/alert_plugin_user_guide",
    "guide/monitor",
    "guide/installation/general-setting",
    "guide/remote-logging",
)


def _validate_relative_path(path: str) -> PurePosixPath:
    if not isinstance(path, str) or not path or "\\" in path:
        raise ValueError("path must be a repository-relative POSIX path")
    candidate = PurePosixPath(path)
    if candidate.is_absolute() or any(part in {"", ".", ".."} for part in candidate.parts):
        raise ValueError("path must stay inside the repository")
    return candidate


def raw_source_url(commit: str, path: str) -> str:
    if not isinstance(commit, str) or not _COMMIT_RE.fullmatch(commit):
        raise ValueError("commit must be a full 40-character SHA")
    relative = _validate_relative_path(path)
    encoded_path = quote(relative.as_posix(), safe="/-._")
    return f"https://raw.githubusercontent.com/apache/dolphinscheduler/{commit}/{encoded_path}"


def _fetch_raw_source(url: str, *, timeout: float = 25.0) -> bytes | None:
    request = Request(url, headers={"User-Agent": "enterprise-rag-source-sync/1.0"})
    try:
        with urlopen(request, timeout=timeout) as response:
            return response.read()
    except HTTPError as exc:
        if exc.code == 404:
            return None
        raise


def _official_docs(manifest: dict) -> list[dict]:
    current_version = manifest["current_version"]
    rows = []
    seen = set()
    for source in manifest["sources"]:
        path = source.get("document_path", "")
        language = source.get("language")
        if (
            source.get("version") != current_version
            or source.get("source_type") != "official_documentation"
            or language not in _ALLOWED_LANGUAGES
            or not path.startswith(_OFFICIAL_DOCS_PREFIX)
            or not path.endswith(".md")
        ):
            continue
        _validate_relative_path(path)
        key = (language, source.get("canonical_topic_id", source.get("document_key")))
        if key in seen:
            continue
        seen.add(key)
        rows.append(source)
    return sorted(rows, key=lambda row: (row["language"], row["document_key"]))


def _additional_docs(manifest: dict, topics: tuple[str, ...]) -> list[dict]:
    current_version = manifest["current_version"]
    current_commit = manifest["commits"][current_version]
    existing = {(row["language"], row.get("canonical_topic_id", row["document_key"]))
                for row in _official_docs(manifest)}
    rows = []
    for topic in topics:
        relative = _validate_relative_path(topic)
        if relative.suffix or relative.parts[0] != "guide":
            raise ValueError("additional topic must be a guide Markdown document key")
        for language in sorted(_ALLOWED_LANGUAGES):
            if (language, topic) in existing:
                continue
            path = f"docs/docs/{language}/{topic}.md"
            rows.append({
                "document_key": topic,
                "canonical_topic_id": topic,
                "version": current_version,
                "commit": current_commit,
                "locale": "zh-CN" if language == "zh" else "en-US",
                "language": language,
                "source_type": "official_documentation",
                "repository": "apache/dolphinscheduler",
                "document_path": path,
                "local_path": f"sources/{current_version}/{language}/{topic}.md",
                "source_url": f"https://github.com/apache/dolphinscheduler/blob/{current_commit}/{path}",
                "license": "Apache-2.0",
                "attribution": "Copyright The Apache Software Foundation and contributors",
            })
    return sorted(rows, key=lambda row: (row["language"], row["document_key"]))


def _safe_target(root: Path, relative_path: str) -> Path:
    relative = _validate_relative_path(relative_path)
    resolved_root = root.resolve()
    target = root.joinpath(*relative.parts).resolve()
    if not target.is_relative_to(resolved_root):
        raise ValueError("source destination escapes the corpus root")
    return target


def _atomic_write(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    try:
        temporary.write_bytes(data)
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


def sync_sources(
    root: Path = ROOT,
    fetcher: Callable[[str], bytes | None] = _fetch_raw_source,
    *,
    now: datetime | None = None,
    additional_topics: tuple[str, ...] = ADDITIONAL_TOPICS,
) -> dict[str, int]:
    """Add real pinned pages for the current and baseline versions.

    A fetcher returns raw source bytes, or ``None`` only for an upstream 404.
    All network reads complete before any source or manifest is published. A
    failed fetch writes a separate diagnostic report without changing the corpus.
    """
    root = Path(root)
    manifest_path = root / "corpus_manifest.json"
    manifest_bytes = manifest_path.read_bytes()
    manifest = json.loads(manifest_bytes)
    baseline = manifest["baseline_version"]
    current = manifest["current_version"]
    commits = manifest["commits"]
    baseline_commit = commits.get(baseline)
    current_commit = commits.get(current)
    if not _COMMIT_RE.fullmatch(str(baseline_commit)) or not _COMMIT_RE.fullmatch(str(current_commit)):
        raise ValueError("manifest must pin full commits for both versions")
    if now is None:
        now = datetime.now(timezone.utc)
    if now.tzinfo is None:
        raise ValueError("retrieval timestamp must include a timezone")
    retrieved_at = now.astimezone(timezone.utc).isoformat()

    existing = {
        (row["version"], row["language"], row.get("canonical_topic_id", row["document_key"])): row
        for row in manifest["sources"]
    }
    planned_files: list[tuple[Path, bytes]] = []
    planned_sources: list[dict] = []
    requested: list[dict] = []
    added = present = absent = 0

    def fetch(version: str, language: str, topic: str, path: str, url: str) -> bytes | None:
        try:
            return fetcher(url)
        except Exception as exc:
            requested.append({
                "version": version,
                "language": language,
                "canonical_topic_id": topic,
                "document_path": path,
                "fetch_url": url,
                "status": "failed",
                "error_type": type(exc).__name__,
            })
            _atomic_write(
                root / "source_sync_failure.json",
                (json.dumps({
                    "repository": manifest.get("repository", "apache/dolphinscheduler"),
                    "retrieval_timestamp": retrieved_at,
                    "commits": {baseline: baseline_commit, current: current_commit},
                    "requested_sources": requested,
                    "published_sources": 0,
                }, ensure_ascii=False, indent=2) + "\n").encode("utf-8"),
            )
            raise

    official_docs = _official_docs(manifest)
    for source in official_docs:
        expected_source_url = (
            f"https://github.com/apache/dolphinscheduler/blob/{current_commit}/"
            f"{source['document_path']}"
        )
        if (
            source.get("commit") != current_commit
            or source.get("repository") != "apache/dolphinscheduler"
            or source.get("source_url") != expected_source_url
        ):
            raise ValueError("allowlist source is not pinned current commit")

    candidates = [(source, True) for source in official_docs]
    candidates.extend((source, False) for source in _additional_docs(manifest, additional_topics))
    candidates.sort(key=lambda item: (item[0]["language"], item[0]["document_key"]))
    for source, already_indexed in candidates:
        language = source["language"]
        topic = source.get("canonical_topic_id", source["document_key"])
        path = source["document_path"]
        current_url = raw_source_url(current_commit, path)
        if already_indexed:
            present += 1
            requested.append({
                "version": current,
                "language": language,
                "canonical_topic_id": topic,
                "document_path": path,
                "fetch_url": current_url,
                "status": "present",
                "local_path": source["local_path"],
                "sha256": source["sha256"],
            })
        else:
            content = fetch(current, language, topic, path, current_url)
            if content is None:
                absent += 1
                requested.append({
                    "version": current,
                    "language": language,
                    "canonical_topic_id": topic,
                    "document_path": path,
                    "fetch_url": current_url,
                    "status": "absent",
                })
                requested.append({
                    "version": baseline,
                    "language": language,
                    "canonical_topic_id": topic,
                    "document_path": path,
                    "fetch_url": raw_source_url(baseline_commit, path),
                    "status": "skipped_current_absent",
                })
                continue
            if not isinstance(content, bytes) or not content:
                raise ValueError(f"invalid upstream bytes for {path}")
            content.decode("utf-8-sig")
            digest = hashlib.sha256(content).hexdigest()
            target = _safe_target(root, source["local_path"])
            if target.exists():
                raise FileExistsError(f"untracked source destination already exists: {source['local_path']}")
            source = {
                **source,
                "retrieval_timestamp": retrieved_at,
                "sha256": digest,
                "bytes": len(content),
            }
            planned_files.append((target, content))
            planned_sources.append(source)
            requested.append({
                "version": current,
                "language": language,
                "canonical_topic_id": topic,
                "document_path": path,
                "fetch_url": current_url,
                "status": "added",
                "local_path": source["local_path"],
                "sha256": digest,
            })
            added += 1

        url = raw_source_url(baseline_commit, path)
        existing_source = existing.get((baseline, language, topic))
        if existing_source is not None:
            present += 1
            requested.append({
                "version": baseline,
                "language": language,
                "canonical_topic_id": topic,
                "document_path": path,
                "fetch_url": url,
                "status": "present",
                "local_path": existing_source["local_path"],
                "sha256": existing_source["sha256"],
            })
            continue

        content = fetch(baseline, language, topic, path, url)
        if content is None:
            absent += 1
            requested.append({
                "version": baseline,
                "language": language,
                "canonical_topic_id": topic,
                "document_path": path,
                "fetch_url": url,
                "status": "absent",
            })
            continue
        if not isinstance(content, bytes) or not content:
            raise ValueError(f"invalid upstream bytes for {path}")
        content.decode("utf-8-sig")
        digest = hashlib.sha256(content).hexdigest()
        local_path = f"sources/{baseline}/{language}/{source['document_key']}.md"
        target = _safe_target(root, local_path)
        if target.exists():
            raise FileExistsError(f"untracked source destination already exists: {local_path}")

        new_source = {
            **source,
            "version": baseline,
            "commit": baseline_commit,
            "local_path": local_path,
            "source_url": f"https://github.com/apache/dolphinscheduler/blob/{baseline_commit}/{path}",
            "retrieval_timestamp": retrieved_at,
            "sha256": digest,
            "bytes": len(content),
        }
        planned_files.append((target, content))
        planned_sources.append(new_source)
        requested.append({
            "version": baseline,
            "language": language,
            "canonical_topic_id": topic,
            "document_path": path,
            "fetch_url": url,
            "status": "added",
            "local_path": local_path,
            "sha256": digest,
        })
        added += 1

    # No network or content validation errors occurred; now publish the prepared files.
    updated_manifest = dict(manifest)
    updated_manifest["sources"] = [*manifest["sources"], *planned_sources]
    updated_manifest["source_count"] = len(updated_manifest["sources"])
    coverage = {
        "repository": manifest.get("repository", "apache/dolphinscheduler"),
        "baseline_version": baseline,
        "current_version": current,
        "commits": {baseline: baseline_commit, current: current_commit},
        "retrieval_timestamp": retrieved_at,
        "allowlist_source_version": current,
        "additional_topics": list(additional_topics),
        "requested_sources": requested,
    }
    for path, content in planned_files:
        _atomic_write(path, content)
    _atomic_write(
        manifest_path,
        (json.dumps(updated_manifest, ensure_ascii=False, indent=2) + "\n").encode("utf-8"),
    )
    _atomic_write(
        root / "source_coverage.json",
        (json.dumps(coverage, ensure_ascii=False, indent=2) + "\n").encode("utf-8"),
    )
    (root / "source_sync_failure.json").unlink(missing_ok=True)
    return {"added": added, "present": present, "absent": absent}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=ROOT, help="public_corpus directory")
    parser.add_argument("--rebuild", action="store_true", help="rebuild chunks, vectors, and artifact hashes")
    args = parser.parse_args()
    if not args.rebuild:
        parser.error("--rebuild is required to keep the manifest and search index in sync")
    summary = sync_sources(args.root)
    sys.path.insert(0, str(SERVICE_ROOT))
    from src.public_knowledge import build_index

    summary.update(build_index(args.root))
    print(json.dumps(summary, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
