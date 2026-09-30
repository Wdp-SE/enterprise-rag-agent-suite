from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path

import pytest

from scripts.fetch_autoware_sources import fetch_pinned_sources
from scripts.figure_evidence import preserve_verified_figure_evidence
from scripts.sync_autoware_sources import (
    _checkout_info, _copy_retrieval_policies, build_pinned_sources, load_source_selection,
)


REPOSITORY = "autowarefoundation/autoware_universe"


def test_default_allowlist_covers_freespace_and_intersection_velocity_planning():
    selection = load_source_selection()
    by_key = {row["document_key"]: row["document_path"] for row in selection}

    assert by_key["planning/freespace_planner/design"] == (
        "planning/autoware_freespace_planner/README.md"
    )
    assert by_key["planning/intersection_velocity/design"] == (
        "planning/behavior_velocity_planner/autoware_behavior_velocity_intersection_module/README.md"
    )


def test_sync_keeps_base_index_policy_separate_from_selected_runtime_policy(tmp_path):
    _copy_retrieval_policies(tmp_path)

    base_policy = json.loads((tmp_path / "retrieval_policy.json").read_text(encoding="utf-8"))
    runtime_policy = json.loads((tmp_path / "public_retrieval_runtime.json").read_text(encoding="utf-8"))

    assert base_policy["default_policy"] == "bm25"
    assert runtime_policy["default_policy"] == "bm25_figure_ocr"


def _checkout(tmp_path: Path, version: str, commit: str) -> dict:
    root = tmp_path / "checkouts" / version
    (root / "planning" / "validator").mkdir(parents=True)
    (root / "LICENSE").write_text(
        "Apache License\nVersion 2.0, January 2004\n",
        encoding="utf-8",
    )
    (root / "planning" / "validator" / "README.md").write_text(
        f"# Planning Validator {version}\n\nPinned behavior for {version}.\n",
        encoding="utf-8",
    )
    return {"root": root, "commit": commit}


def test_build_pinned_sources_copies_allowlist_and_emits_commit_bound_manifest(tmp_path):
    selection_path = tmp_path / "selection.json"
    selection_path.write_text(json.dumps([{
        "document_path": "planning/validator/README.md",
        "document_key": "planning/validator",
        "source_type": "official_documentation",
        "language": "en",
        "locale": "en-US",
    }]), encoding="utf-8")
    selection = load_source_selection(selection_path)
    commits = {"0.51.0": "a" * 40, "0.52.0": "b" * 40}
    checkouts = {
        version: _checkout(tmp_path, version, commit)
        for version, commit in commits.items()
    }

    manifest = build_pinned_sources(checkouts, selection, tmp_path / "corpus")

    assert manifest["workspace"] == "Autoware"
    assert manifest["repository"] == REPOSITORY
    assert manifest["baseline_version"] == "0.51.0"
    assert manifest["current_version"] == "0.52.0"
    assert manifest["available_versions"] == ["0.51.0", "0.52.0"]
    assert manifest["commits"] == commits
    for source in manifest["sources"]:
        raw = (tmp_path / "corpus" / source["local_path"]).read_bytes()
        assert hashlib.sha256(raw).hexdigest() == source["sha256"]
        assert source["repository"] == REPOSITORY
        assert source["source_url"].startswith(
            f"https://github.com/{REPOSITORY}/blob/{source['commit']}/"
        )
        assert source["commit"] == commits[source["version"]]


@pytest.mark.parametrize("bad_path", ["../secret.md", "/etc/passwd", "planning/../LICENSE"])
def test_source_selection_rejects_paths_outside_allowlisted_checkout(tmp_path, bad_path):
    selection_path = tmp_path / "selection.json"
    selection_path.write_text(json.dumps([{
        "document_path": bad_path,
        "document_key": "planning/validator",
        "source_type": "official_documentation",
        "language": "en",
        "locale": "en-US",
    }]), encoding="utf-8")

    with pytest.raises(ValueError, match="path|source|allowlist"):
        load_source_selection(selection_path)


def test_builder_rejects_unpinned_commits_and_missing_release(tmp_path):
    selection = [{
        "document_path": "planning/validator/README.md",
        "document_key": "planning/validator",
        "source_type": "official_documentation",
        "language": "en",
        "locale": "en-US",
    }]
    checkouts = {"0.51.0": _checkout(tmp_path, "0.51.0", "a" * 40)}

    with pytest.raises(ValueError, match="release|checkout|commit"):
        build_pinned_sources(checkouts, selection, tmp_path / "corpus")

    checkouts["0.52.0"] = _checkout(tmp_path, "0.52.0", "main")
    with pytest.raises(ValueError, match="commit"):
        build_pinned_sources(checkouts, selection, tmp_path / "corpus")


def test_fetcher_downloads_only_commit_pinned_allowlisted_sources(tmp_path):
    selection = {
        "repository": REPOSITORY,
        "releases": {
            "0.51.0": {"commit": "a" * 40},
            "0.52.0": {"commit": "b" * 40},
        },
        "sources": [{
            "document_path": "planning/validator/README.md",
            "document_key": "planning/validator",
            "source_type": "official_documentation",
            "language": "en",
            "locale": "en-US",
        }],
    }
    selection_path = tmp_path / "selection.json"
    selection_path.write_text(json.dumps(selection), encoding="utf-8")
    seen = []

    def fetcher(url):
        seen.append(url)
        if url.endswith("/LICENSE"):
            return b"Apache License\nVersion 2.0, January 2004\n"
        return f"# Source from {url}\n".encode()

    snapshots = fetch_pinned_sources(selection_path, tmp_path / "snapshots", fetcher=fetcher)

    assert set(snapshots) == {"0.51.0", "0.52.0"}
    assert len(seen) == 4
    assert all("/blob/" not in url for url in seen)
    for version, snapshot in snapshots.items():
        metadata = json.loads((snapshot["root"] / ".autoware_source_ref.json").read_text(encoding="utf-8"))
        assert metadata["version"] == version
        assert metadata["commit"] == selection["releases"][version]["commit"]
        assert (snapshot["root"] / "planning/validator/README.md").is_file()
        assert (snapshot["root"] / "LICENSE").is_file()
        assert _checkout_info(snapshot["root"], version)["commit"] == metadata["commit"]


def test_checkout_info_rejects_tampered_source_snapshot(tmp_path):
    selection = {
        "repository": REPOSITORY,
        "releases": {"0.51.0": {"commit": "a" * 40}, "0.52.0": {"commit": "b" * 40}},
        "sources": [{
            "document_path": "planning/validator/README.md", "document_key": "planning/validator",
            "source_type": "official_documentation", "language": "en", "locale": "en-US",
        }],
    }
    selection_path = tmp_path / "selection.json"
    selection_path.write_text(json.dumps(selection), encoding="utf-8")
    snapshots = fetch_pinned_sources(
        selection_path, tmp_path / "snapshots",
        fetcher=lambda url: b"Apache License Version 2.0" if url.endswith("/LICENSE") else b"# original\n",
    )
    source = snapshots["0.51.0"]["root"] / "planning/validator/README.md"
    source.write_bytes(b"# original\r\n")
    assert _checkout_info(snapshots["0.51.0"]["root"], "0.51.0")["commit"] == "a" * 40
    source.write_text("# tampered\n", encoding="utf-8")

    with pytest.raises(ValueError, match="hash mismatch"):
        _checkout_info(snapshots["0.51.0"]["root"], "0.51.0")


def test_checkout_info_rejects_missing_hash_for_allowlisted_source(tmp_path):
    selection = {
        "repository": REPOSITORY,
        "releases": {"0.51.0": {"commit": "a" * 40}, "0.52.0": {"commit": "b" * 40}},
        "sources": [{
            "document_path": "planning/validator/README.md", "document_key": "planning/validator",
            "source_type": "official_documentation", "language": "en", "locale": "en-US",
        }],
    }
    selection_path = tmp_path / "selection.json"
    selection_path.write_text(json.dumps(selection), encoding="utf-8")
    snapshots = fetch_pinned_sources(
        selection_path, tmp_path / "snapshots",
        fetcher=lambda url: b"Apache License Version 2.0" if url.endswith("/LICENSE") else b"# source\n",
    )
    root = snapshots["0.51.0"]["root"]
    metadata_path = root / ".autoware_source_ref.json"
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    del metadata["files_sha256"]["planning/validator/README.md"]
    metadata_path.write_text(json.dumps(metadata), encoding="utf-8")

    with pytest.raises(ValueError, match="missing.*hash|incomplete"):
        _checkout_info(
            root,
            "0.51.0",
            required_files={"LICENSE", "planning/validator/README.md"},
        )


def test_checkout_info_hash_verifies_allowlisted_files_in_exact_tag_worktree(tmp_path):
    root = tmp_path / "tag-checkout"
    (root / "planning" / "validator").mkdir(parents=True)
    (root / "LICENSE").write_text("Apache License\nVersion 2.0\n", encoding="utf-8")
    source_path = root / "planning" / "validator" / "README.md"
    source_path.write_text("# pinned content\n", encoding="utf-8")
    subprocess.run(["git", "-C", str(root), "init", "-q"], check=True)
    subprocess.run(["git", "-C", str(root), "add", "LICENSE", "planning/validator/README.md"], check=True)
    subprocess.run([
        "git", "-C", str(root), "-c", "user.name=Test", "-c", "user.email=test@example.invalid",
        "commit", "-qm", "pinned",
    ], check=True)
    subprocess.run(["git", "-C", str(root), "tag", "0.51.0"], check=True)
    expected_sha256 = hashlib.sha256(b"# pinned content\n").hexdigest()
    source_path.write_bytes(b"# pinned content\r\n")
    pinned = _checkout_info(
        root,
        "0.51.0",
        required_files={"planning/validator/README.md"},
    )
    assert pinned["files_sha256"]["planning/validator/README.md"] == expected_sha256
    assert "LICENSE" in pinned["files_sha256"]
    source_path.write_text("# modified after tag\n", encoding="utf-8")

    with pytest.raises(ValueError, match="sha256 mismatch"):
        _checkout_info(
            root,
            "0.51.0",
            required_files={"planning/validator/README.md"},
        )


def test_inventory_rebuild_preserves_verified_review_only_for_identical_manifest_and_reference():
    manifest_sha = "a" * 64
    figure = {
        "figure_id": "figure-1", "repository": REPOSITORY, "version": "0.52.0",
        "commit": "b" * 40, "asset_path": "planning/flow.svg",
        "raw_url": f"https://raw.githubusercontent.com/{REPOSITORY}/{'b' * 40}/planning/flow.svg",
        "references": [{"document_key": "planning/overview", "heading": "Flow", "language": "en"}],
        "validation": {"status": "unverified"}, "ocr": {"status": "not_run"},
    }
    previous_figure = {
        **figure,
        "validation": {"status": "verified", "sha256": "c" * 64},
        "ocr": {"status": "text_extracted", "index_review_status": "approved"},
        "review": {"status": "approved"},
    }
    current = {
        "schema_version": 1, "corpus_manifest_sha256": manifest_sha,
        "figures": [figure],
    }
    previous = {
        "schema_version": 1, "corpus_manifest_sha256": manifest_sha,
        "figures": [previous_figure],
    }

    preserved = preserve_verified_figure_evidence(current, previous)

    assert preserved["figures"][0]["validation"]["sha256"] == "c" * 64
    assert preserved["figures"][0]["review"]["status"] == "approved"
    assert preserved["verified_count"] == 1

    changed = {
        **figure,
        "references": [{"document_key": "other", "heading": "Flow", "language": "en"}],
        # The previous preservation call mutates its current inventory in place.
        # Model the fresh inventory produced by a rebuild explicitly.
        "validation": {"status": "unverified"},
        "ocr": {"status": "not_run"},
    }
    fresh = preserve_verified_figure_evidence(
        {"schema_version": 1, "corpus_manifest_sha256": manifest_sha, "figures": [changed]},
        previous,
    )
    assert fresh["figures"][0]["validation"]["status"] == "unverified"


def test_inventory_rebuild_preserves_reviews_for_append_only_corpus_extension():
    source = {
        "repository": REPOSITORY, "version": "0.52.0", "commit": "b" * 40,
        "document_key": "planning/validator", "language": "en", "document_path": "planning/validator/README.md",
        "source_url": f"https://github.com/{REPOSITORY}/blob/{'b' * 40}/planning/validator/README.md",
        "sha256": "c" * 64,
    }
    previous_manifest = {
        "repository": REPOSITORY, "workspace": "Autoware", "baseline_version": "0.51.0",
        "current_version": "0.52.0", "available_versions": ["0.51.0", "0.52.0"],
        "languages": ["en-US"], "commits": {"0.51.0": "a" * 40, "0.52.0": "b" * 40},
        "sources": [source],
    }
    added_source = {**source, "document_key": "planning/freespace", "document_path": "planning/freespace/README.md"}
    current_manifest = {
        **previous_manifest,
        "scope": "expanded planning and documentation scope",
        "baseline_version": "0.51.0",
        "current_version": "latest",
        "available_versions": ["latest", "docs-main", "0.52.0", "0.51.0"],
        "languages": ["en-US", "zh-CN"],
        "commits": {"docs-main": "e" * 40, "0.51.0": "a" * 40, "0.52.0": "b" * 40},
        "version_scopes": {"latest": {"versions": ["docs-main", "0.52.0"]}},
        "sources": [source, added_source],
    }
    previous_bytes = (json.dumps(previous_manifest, ensure_ascii=False, indent=2) + "\n").encode()
    current_bytes = (json.dumps(current_manifest, ensure_ascii=False, indent=2) + "\n").encode()
    figure = {
        "figure_id": "figure-1", "repository": REPOSITORY, "version": "0.52.0", "commit": "b" * 40,
        "asset_path": "planning/validator/figure.svg",
        "raw_url": f"https://raw.githubusercontent.com/{REPOSITORY}/{'b' * 40}/planning/validator/figure.svg",
        "references": [{"document_key": "planning/validator", "heading": "Validation", "language": "en"}],
        "validation": {"status": "verified", "sha256": "d" * 64},
        "ocr": {"status": "text_extracted", "index_review_status": "approved"},
        "review": {"status": "approved", "reviewed_text": "verified label"},
    }
    previous = {
        "schema_version": 1, "corpus_manifest_sha256": hashlib.sha256(previous_bytes).hexdigest(),
        "figures": [figure],
    }
    current = {
        "schema_version": 1, "corpus_manifest_sha256": hashlib.sha256(current_bytes).hexdigest(),
        "figures": [{**figure, "validation": {"status": "unverified"}, "ocr": {"status": "not_run"}}],
    }

    preserved = preserve_verified_figure_evidence(
        current, previous,
        previous_manifest_bytes=previous_bytes,
        current_manifest_bytes=current_bytes,
    )

    assert preserved["figures"][0]["validation"]["sha256"] == "d" * 64
    assert preserved["figures"][0]["review"]["reviewed_text"] == "verified label"
