"""Read-only, path-level license gate for the active public project corpus.

The audit records repository metadata and filenames only. It never copies
repository file contents into its report, and repository-level license files
do not implicitly approve nested third-party material.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
from pathlib import Path, PurePosixPath
from urllib.parse import urlparse


SERVICE_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_MANIFEST = SERVICE_ROOT / "config" / "industrial_inspection_project.json"
DEFAULT_REPORT = SERVICE_ROOT / "project_delivery" / "industrial_inspection_source_audit.json"
_SHA40 = re.compile(r"^[0-9a-f]{40}$")
_PROJECT_ID = re.compile(r"^[a-z0-9][a-z0-9_-]{2,63}$")
_REVIEW_STATUSES = {"approved", "link_only", "unknown"}


def _run_git(root: Path, *args: str) -> str:
    try:
        result = subprocess.run(
            ["git", "-C", str(Path(root).resolve()), *args],
            check=False,
            capture_output=True,
            text=True,
            timeout=10,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise ValueError("git source audit could not read the repository") from exc
    if result.returncode != 0:
        raise ValueError("git source audit could not resolve the repository or commit")
    return result.stdout.strip()


def normalize_repository(value: str) -> str:
    """Return a canonical GitHub owner/repository identity."""
    if not isinstance(value, str) or not value.strip():
        raise ValueError("repository identity is missing")
    candidate = value.strip()
    if candidate.startswith("git@github.com:"):
        candidate = candidate.removeprefix("git@github.com:")
    elif "://" in candidate:
        parsed = urlparse(candidate)
        if parsed.scheme != "https" or parsed.hostname != "github.com" or parsed.username or parsed.password:
            raise ValueError("repository must be a canonical GitHub repository")
        candidate = parsed.path.strip("/")
    candidate = candidate.removesuffix(".git").strip("/")
    parts = candidate.split("/")
    if len(parts) != 2 or any(not re.fullmatch(r"[A-Za-z0-9_.-]+", part) for part in parts):
        raise ValueError("repository must use owner/repository form")
    return "/".join(parts).casefold()


def _safe_repo_path(value: str, *, label: str) -> str:
    if not isinstance(value, str) or not value or "\\" in value or "\x00" in value:
        raise ValueError(f"invalid {label}")
    path = PurePosixPath(value)
    if path.is_absolute() or any(part in {"", ".", ".."} for part in path.parts):
        raise ValueError(f"{label} escapes the repository")
    return path.as_posix()


def validate_project_manifest(manifest: dict, *, repository_root: Path | None = None) -> dict:
    """Validate the one-project identity and, when available, resolve its SHA."""
    if not isinstance(manifest, dict) or manifest.get("schema_version") != 1:
        raise ValueError("unsupported project manifest schema")
    project_id = manifest.get("project_id")
    if not isinstance(project_id, str) or not _PROJECT_ID.fullmatch(project_id):
        raise ValueError("project_id is invalid")
    repository = normalize_repository(manifest.get("primary_repository"))
    declared_repositories = manifest.get("primary_repositories")
    if declared_repositories is not None:
        if (
            not isinstance(declared_repositories, list)
            or len(declared_repositories) != 1
            or normalize_repository(declared_repositories[0]) != repository
        ):
            raise ValueError("manifest must declare exactly one primary repository")
    commit = manifest.get("pinned_commit")
    if not isinstance(commit, str) or not _SHA40.fullmatch(commit):
        raise ValueError("pinned commit must be a full 40-character SHA")
    prefixes = manifest.get("allowed_path_prefixes")
    if not isinstance(prefixes, list) or not prefixes:
        raise ValueError("allowed_path_prefixes must be a non-empty list")
    safe_prefixes = [_safe_repo_path(value, label="allowed path prefix") for value in prefixes]
    if len(safe_prefixes) != len(set(safe_prefixes)):
        raise ValueError("allowed path prefixes must be unique")
    dependency_allowlist = manifest.get("dependency_reference_allowlist", [])
    if not isinstance(dependency_allowlist, list):
        raise ValueError("dependency reference allowlist must be a list")
    reviews = manifest.get("source_license_reviews", {})
    if not isinstance(reviews, dict):
        raise ValueError("source_license_reviews must be an explicit path map")
    for source_path, review in reviews.items():
        safe_source_path = _safe_repo_path(source_path, label="reviewed source path")
        if not any(
            safe_source_path == prefix or safe_source_path.startswith(prefix.rstrip("/") + "/")
            for prefix in safe_prefixes
        ):
            raise ValueError("reviewed source path is outside the allowed path prefixes")
        if not isinstance(review, dict) or review.get("license_status") not in _REVIEW_STATUSES:
            raise ValueError("source license review has an invalid status")
        if review["license_status"] == "approved" and any(
            not isinstance(review.get(field), str) or not review[field].strip()
            for field in ("license_id", "publisher", "review_reference")
        ):
            raise ValueError("approved source review requires license, publisher and review reference")
    if repository_root is not None:
        resolved = _run_git(Path(repository_root), "rev-parse", "--verify", f"{commit}^{{commit}}").casefold()
        if resolved != commit:
            raise ValueError("pinned commit is not a full resolvable commit in the repository")
    return {
        "project_id": project_id,
        "primary_repository": repository,
        "pinned_commit": commit,
        "allowed_path_prefixes": safe_prefixes,
        "dependency_reference_allowlist": dependency_allowlist,
    }


def _license_disposition(path: str, reviews: dict) -> dict:
    """Apply only explicit path-level review decisions; never inherit a root license."""
    review = reviews.get(path)
    if review is None:
        return {"license_status": "unknown", "license_id": None, "publisher": None, "review_reference": None}
    return {
        "license_status": review["license_status"],
        "license_id": review.get("license_id"),
        "publisher": review.get("publisher"),
        "review_reference": review.get("review_reference"),
    }


def audit_repository(
    root: Path,
    expected_repository: str,
    *,
    pinned_commit: str | None = None,
    reviewed_licenses: dict | None = None,
    allowed_path_prefixes: list[str] | None = None,
) -> dict:
    """Return identity, fixed commit, tracked paths and explicit license status."""
    expected = normalize_repository(expected_repository)
    remote = _run_git(Path(root), "remote", "get-url", "origin")
    actual = normalize_repository(remote)
    if actual != expected:
        raise ValueError("repository origin does not match the approved repository")
    commit = pinned_commit or _run_git(Path(root), "rev-parse", "--verify", "HEAD")
    if not isinstance(commit, str) or not _SHA40.fullmatch(commit):
        raise ValueError("audit commit must be a full 40-character SHA")
    resolved = _run_git(Path(root), "rev-parse", "--verify", f"{commit}^{{commit}}").casefold()
    if resolved != commit:
        raise ValueError("audit commit is not present in the repository")
    tree = _run_git(Path(root), "ls-tree", "-r", "--name-only", commit)
    paths = sorted(path for path in tree.splitlines() if path)
    reviews = reviewed_licenses or {}
    if not isinstance(reviews, dict):
        raise ValueError("reviewed licenses must be a path map")
    unknown_reviews = set(reviews) - set(paths)
    if unknown_reviews:
        raise ValueError("license review refers to a path absent from the pinned commit")
    safe_prefixes = [
        _safe_repo_path(prefix, label="allowed path prefix")
        for prefix in (allowed_path_prefixes or [])
    ]
    rows = []
    for path in paths:
        safe_path = _safe_repo_path(path, label="tracked path")
        disposition = _license_disposition(safe_path, reviews)
        path_allowed = not safe_prefixes or any(
            safe_path == prefix or safe_path.startswith(prefix.rstrip("/") + "/")
            for prefix in safe_prefixes
        )
        rows.append({"path": safe_path, "allowed_for_indexing": path_allowed, **disposition})
    return {
        "schema_version": 1,
        "repository": expected,
        "repository_url": f"https://github.com/{expected}",
        "commit": commit,
        "tracked_path_count": len(rows),
        "approved_body_path_count": sum(row["license_status"] == "approved" for row in rows),
        "link_only_path_count": sum(row["license_status"] == "link_only" for row in rows),
        "unknown_path_count": sum(row["license_status"] == "unknown" for row in rows),
        "excluded_by_path_policy_count": sum(not row["allowed_for_indexing"] for row in rows),
        "allowed_path_prefixes": safe_prefixes,
        "paths": rows,
    }


def assert_indexable(report: dict, selected_paths: list[str]) -> None:
    """Reject any body import not explicitly approved in the audit report."""
    rows = {row.get("path"): row for row in report.get("paths", []) if isinstance(row, dict)}
    for path in selected_paths:
        row = rows.get(path)
        if row is None or row.get("license_status") != "approved" or row.get("allowed_for_indexing") is False:
            raise ValueError(f"source body is not approved for indexing: {path}")
        if not all(isinstance(row.get(field), str) and row[field].strip() for field in ("license_id", "publisher", "review_reference")):
            raise ValueError(f"approved source is missing license provenance: {path}")


def run_source_audit(repository_root: Path, manifest_path: Path, output_path: Path) -> dict:
    manifest = json.loads(Path(manifest_path).read_text(encoding="utf-8"))
    identity = validate_project_manifest(manifest, repository_root=repository_root)
    report = audit_repository(
        repository_root,
        identity["primary_repository"],
        pinned_commit=identity["pinned_commit"],
        reviewed_licenses=manifest.get("source_license_reviews", {}),
        allowed_path_prefixes=identity["allowed_path_prefixes"],
    )
    report["project_id"] = identity["project_id"]
    report["audit_mode"] = "metadata_only"
    report["source_status"] = manifest.get("source_status", "pending_source_review")
    report["public_body_indexing_enabled"] = bool(manifest.get("public_body_indexing_enabled", False))
    report["license_discovery"] = manifest.get("license_discovery", {})
    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    Path(output_path).write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repository-root", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--output", type=Path, default=DEFAULT_REPORT)
    args = parser.parse_args()
    report = run_source_audit(args.repository_root, args.manifest, args.output)
    print(json.dumps({key: value for key, value in report.items() if key != "paths"}, ensure_ascii=False))


if __name__ == "__main__":
    main()
