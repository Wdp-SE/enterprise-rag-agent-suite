import hashlib
import importlib.util
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "sync_pinned_sources.py"
BASELINE_COMMIT = "71eb6412f940afa1f171f1097dc0e99ed61d16e2"
CURRENT_COMMIT = "a190201acffa03d199d4ca216288734a6513de3d"


def _load_sync_module():
    assert SCRIPT.is_file(), "pinned source synchronizer is missing"
    spec = importlib.util.spec_from_file_location("sync_pinned_sources", SCRIPT)
    assert spec and spec.loader, "pinned source synchronizer cannot be loaded"
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _source(version, language, topic, commit, path):
    locale = "zh-CN" if language == "zh" else "en-US"
    return {
        "document_key": topic,
        "canonical_topic_id": topic,
        "version": version,
        "commit": commit,
        "locale": locale,
        "language": language,
        "source_type": "official_documentation",
        "repository": "apache/dolphinscheduler",
        "document_path": path,
        "local_path": f"sources/{version}/{language}/{topic}.md",
        "source_url": f"https://github.com/apache/dolphinscheduler/blob/{commit}/{path}",
        "retrieval_timestamp": "2026-09-23T00:00:00+00:00",
        "license": "Apache-2.0",
        "attribution": "Copyright The Apache Software Foundation and contributors",
        "sha256": "0" * 64,
        "bytes": 1,
    }


def _write_manifest(root, sources):
    manifest = {
        "repository": "apache/dolphinscheduler",
        "commits": {"3.4.2": BASELINE_COMMIT, "3.4.3": CURRENT_COMMIT},
        "baseline_version": "3.4.2",
        "current_version": "3.4.3",
        "source_count": len(sources),
        "sources": sources,
    }
    path = root / "corpus_manifest.json"
    path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return path


def test_cli_refuses_to_touch_corpus_without_rebuild(tmp_path):
    corpus = tmp_path / "corpus"
    corpus.mkdir()
    sentinel = corpus / "unchanged.txt"
    sentinel.write_text("do not touch", encoding="utf-8")

    result = subprocess.run(
        [sys.executable, str(SCRIPT), "--root", str(corpus)],
        capture_output=True,
        text=True,
        timeout=10,
        check=False,
    )

    assert result.returncode == 2
    assert "--rebuild" in result.stderr
    assert sorted(path.name for path in corpus.iterdir()) == ["unchanged.txt"]
    assert sentinel.read_text(encoding="utf-8") == "do not touch"


def test_raw_source_url_uses_the_pinned_commit_and_rejects_traversal():
    module = _load_sync_module()

    assert module.raw_source_url(
        BASELINE_COMMIT, "docs/docs/zh/guide/parameter/priority.md"
    ) == (
        "https://raw.githubusercontent.com/apache/dolphinscheduler/"
        "71eb6412f940afa1f171f1097dc0e99ed61d16e2/"
        "docs/docs/zh/guide/parameter/priority.md"
    )
    with pytest.raises(ValueError, match="path"):
        module.raw_source_url(BASELINE_COMMIT, "../private.md")


def test_sync_adds_verified_sources_and_records_absent_pages(tmp_path):
    module = _load_sync_module()
    sources = [
        _source("3.4.3", "en", "guide/parameter/priority", CURRENT_COMMIT,
                "docs/docs/en/guide/parameter/priority.md"),
        _source("3.4.3", "zh", "guide/parameter/priority", CURRENT_COMMIT,
                "docs/docs/zh/guide/parameter/priority.md"),
        _source("3.4.3", "en", "release-notes", CURRENT_COMMIT,
                "releases/tag/3.4.3"),
    ]
    manifest_path = _write_manifest(tmp_path, sources)
    original_manifest = manifest_path.read_bytes()
    page = b"# Priority\n\nTask priority is configurable.\n"
    urls = []

    def fetcher(url):
        urls.append(url)
        if "/docs/docs/en/" in url:
            return page
        if "/docs/docs/zh/" in url:
            return None
        raise AssertionError("non-document source must not be fetched")

    result = module.sync_sources(
        tmp_path, fetcher, now=datetime(2026, 9, 27, tzinfo=timezone.utc),
        additional_topics=(),
    )

    expected_url = module.raw_source_url(
        BASELINE_COMMIT, "docs/docs/en/guide/parameter/priority.md"
    )
    assert urls == [
        expected_url,
        module.raw_source_url(BASELINE_COMMIT, "docs/docs/zh/guide/parameter/priority.md"),
    ]
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    added = [row for row in manifest["sources"] if row["version"] == "3.4.2"]
    assert len(added) == 1
    assert manifest["source_count"] == len(sources) + 1
    assert added[0]["document_key"] == "guide/parameter/priority"
    assert added[0]["commit"] == BASELINE_COMMIT
    assert added[0]["source_url"] == (
        "https://github.com/apache/dolphinscheduler/blob/"
        "71eb6412f940afa1f171f1097dc0e99ed61d16e2/"
        "docs/docs/en/guide/parameter/priority.md"
    )
    assert added[0]["sha256"] == hashlib.sha256(page).hexdigest()
    assert added[0]["bytes"] == len(page)
    assert added[0]["retrieval_timestamp"] == "2026-09-27T00:00:00+00:00"
    saved_page = tmp_path / "sources/3.4.2/en/guide/parameter/priority.md"
    assert saved_page.read_bytes() == page
    assert manifest_path.read_bytes() != original_manifest

    coverage = json.loads((tmp_path / "source_coverage.json").read_text(encoding="utf-8"))
    assert [row["status"] for row in coverage["requested_sources"]] == [
        "present", "added", "present", "absent"
    ]
    assert result == {"added": 1, "present": 2, "absent": 1}


def test_sync_does_not_write_partial_sources_when_fetch_fails(tmp_path):
    module = _load_sync_module()
    sources = [
        _source("3.4.3", "en", "guide/a", CURRENT_COMMIT, "docs/docs/en/guide/a.md"),
        _source("3.4.3", "zh", "guide/b", CURRENT_COMMIT, "docs/docs/zh/guide/b.md"),
    ]
    manifest_path = _write_manifest(tmp_path, sources)
    original_manifest = manifest_path.read_bytes()
    calls = 0

    def fetcher(_url):
        nonlocal calls
        calls += 1
        if calls == 1:
            return b"# A\n"
        raise TimeoutError("upstream unavailable")

    with pytest.raises(TimeoutError, match="upstream unavailable"):
        module.sync_sources(tmp_path, fetcher, additional_topics=())

    assert manifest_path.read_bytes() == original_manifest
    assert not (tmp_path / "source_coverage.json").exists()
    assert not (tmp_path / "sources/3.4.2").exists()
    failure = json.loads((tmp_path / "source_sync_failure.json").read_text(encoding="utf-8"))
    assert failure["published_sources"] == 0
    assert failure["requested_sources"][-1]["status"] == "failed"
    assert failure["requested_sources"][-1]["error_type"] == "TimeoutError"


def test_sync_rejects_an_allowlist_source_not_pinned_to_current_commit(tmp_path):
    module = _load_sync_module()
    source = _source(
        "3.4.3", "en", "guide/parameter/priority", "f" * 40,
        "docs/docs/en/guide/parameter/priority.md",
    )
    manifest_path = _write_manifest(tmp_path, [source])
    original_manifest = manifest_path.read_bytes()

    def unexpected_fetch(_url):
        raise AssertionError("must reject the mismatched source before fetching")

    with pytest.raises(ValueError, match="pinned current commit"):
        module.sync_sources(tmp_path, unexpected_fetch, additional_topics=())

    assert manifest_path.read_bytes() == original_manifest
    assert not (tmp_path / "source_coverage.json").exists()


def test_sync_adds_both_versions_of_a_new_topic_and_marks_current_404(tmp_path):
    module = _load_sync_module()
    source = _source(
        "3.4.3", "en", "guide/parameter/priority", CURRENT_COMMIT,
        "docs/docs/en/guide/parameter/priority.md",
    )
    _write_manifest(tmp_path, [source])
    page = b"# Task instances\n\nStatus and log links.\n"
    calls = []

    def fetcher(url):
        calls.append(url)
        if "task-instance.md" in url and "/en/" in url:
            return page
        if "task-instance.md" in url and "/zh/" in url:
            return None
        if "priority.md" in url:
            return None
        raise AssertionError(url)

    result = module.sync_sources(
        tmp_path, fetcher, now=datetime(2026, 9, 27, tzinfo=timezone.utc),
        additional_topics=("guide/project/task-instance",),
    )

    manifest = json.loads((tmp_path / "corpus_manifest.json").read_text(encoding="utf-8"))
    new_rows = [row for row in manifest["sources"] if row["document_key"] == "guide/project/task-instance"]
    assert len(new_rows) == 2
    assert {row["version"] for row in new_rows} == {"3.4.2", "3.4.3"}
    assert {row["sha256"] for row in new_rows} == {hashlib.sha256(page).hexdigest()}
    assert all(row["source_url"].endswith("/docs/docs/en/guide/project/task-instance.md") for row in new_rows)
    assert result == {"added": 2, "present": 1, "absent": 2}
    coverage = json.loads((tmp_path / "source_coverage.json").read_text(encoding="utf-8"))
    rows = coverage["requested_sources"]
    assert any(row["language"] == "zh" and row["version"] == "3.4.3"
               and row["status"] == "absent" for row in rows)
    assert any(row["language"] == "zh" and row["version"] == "3.4.2"
               and row["status"] == "skipped_current_absent" for row in rows)
    assert all("/zh/guide/project/task-instance.md" not in url
               or CURRENT_COMMIT in url for url in calls)
