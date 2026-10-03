from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from scripts.audit_project_source import (
    assert_indexable,
    audit_repository,
    validate_project_manifest,
)


REPOSITORY = "xbs0325/industrial-inspection"


def _git(root: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(root), *args],
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


def _repository(root: Path, *, remote: str | None = None) -> str:
    root.mkdir(parents=True, exist_ok=True)
    _git(root, "init", "--quiet")
    _git(root, "config", "user.email", "audit@example.invalid")
    _git(root, "config", "user.name", "Audit Fixture")
    (root / "README.md").write_text("fixture\n", encoding="utf-8")
    (root / "app").mkdir()
    (root / "app" / "main.py").write_text("print('fixture')\n", encoding="utf-8")
    (root / "app" / "third_party").mkdir()
    (root / "app" / "third_party" / "data.json").write_text("{}\n", encoding="utf-8")
    (root / "LICENSE").write_text("A root-level license notice.\n", encoding="utf-8")
    _git(root, "add", ".")
    _git(root, "commit", "--quiet", "-m", "fixture")
    _git(root, "remote", "add", "origin", remote or f"https://github.com/{REPOSITORY}.git")
    return _git(root, "rev-parse", "HEAD")


def _manifest(commit: str, **overrides) -> dict:
    payload = {
        "schema_version": 1,
        "project_id": "industrial-inspection",
        "primary_repository": REPOSITORY,
        "pinned_commit": commit,
        "allowed_path_prefixes": ["README.md", "app/"],
        "dependency_reference_allowlist": [],
        "source_license_reviews": {},
    }
    payload.update(overrides)
    return payload


def test_audit_rejects_a_different_remote_repository(tmp_path: Path):
    root = tmp_path / "repo"
    _repository(root, remote="https://github.com/other/project.git")

    with pytest.raises(ValueError, match="repository"):
        audit_repository(root, expected_repository=REPOSITORY)


@pytest.mark.parametrize("commit", ["6d0df95", "not-a-commit", "0" * 40])
def test_manifest_requires_a_resolvable_full_pinned_commit(tmp_path: Path, commit: str):
    root = tmp_path / "repo"
    actual_commit = _repository(root)

    with pytest.raises(ValueError, match="commit"):
        validate_project_manifest(_manifest(commit), repository_root=root)

    assert actual_commit != commit or commit == "0" * 40


def test_manifest_rejects_two_primary_repositories(tmp_path: Path):
    root = tmp_path / "repo"
    commit = _repository(root)
    manifest = _manifest(
        commit,
        primary_repositories=[REPOSITORY, "another/app"],
    )

    with pytest.raises(ValueError, match="one primary repository"):
        validate_project_manifest(manifest, repository_root=root)


def test_audit_keeps_unreviewed_files_unknown_and_blocks_their_bodies(tmp_path: Path):
    root = tmp_path / "repo"
    commit = _repository(root)
    report = audit_repository(root, expected_repository=REPOSITORY, pinned_commit=commit)

    dispositions = {row["path"]: row["license_status"] for row in report["paths"]}
    assert dispositions["README.md"] == "unknown"
    assert dispositions["app/third_party/data.json"] == "unknown"
    with pytest.raises(ValueError, match="not approved"):
        assert_indexable(report, ["README.md"])


def test_repository_license_does_not_approve_nested_third_party_files(tmp_path: Path):
    root = tmp_path / "repo"
    commit = _repository(root)
    report = audit_repository(
        root,
        expected_repository=REPOSITORY,
        pinned_commit=commit,
        reviewed_licenses={
            "README.md": {
                "license_status": "approved",
                "license_id": "CC-BY-4.0",
                "publisher": "xbs0325",
                "review_reference": "explicit-path-review-1",
            }
        },
    )

    dispositions = {row["path"]: row["license_status"] for row in report["paths"]}
    assert dispositions["README.md"] == "approved"
    assert dispositions["app/third_party/data.json"] == "unknown"
    with pytest.raises(ValueError, match="not approved"):
        assert_indexable(report, ["app/third_party/data.json"])
