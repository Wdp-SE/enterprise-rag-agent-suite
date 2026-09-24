"""Build a pinned, small corpus from Apache DolphinScheduler official sources.

The selected paths are reviewed, explicit inputs. No moving branch or third-party
mirror can silently change the public corpus.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

import requests


ROOT = Path(__file__).resolve().parents[2] / "RAG-Challenge-2-main" / "public_corpus"
REPOSITORY = "apache/dolphinscheduler"
COMMITS = {
    "3.4.2": "71eb6412f940afa1f171f1097dc0e99ed61d16e2",
    "3.4.3": "a190201acffa03d199d4ca216288734a6513de3d",
}
TOPICS = (
    "about/introduction.md",
    "architecture/design.md",
    "architecture/configuration.md",
    "architecture/task-structure.md",
    "guide/api/open-api.md",
    "guide/api/healthcheck.md",
    "guide/parameter/built-in.md",
    "guide/parameter/context.md",
    "guide/parameter/global.md",
    "guide/parameter/local.md",
    "guide/parameter/priority.md",
    "guide/parameter/startup-parameter.md",
    "guide/project/workflow-definition.md",
    "guide/project/workflow-instance.md",
    "guide/task/dependent.md",
    "guide/task/switch.md",
    "guide/upgrade/incompatible.md",
    "guide/upgrade/upgrade.md",
    "contribute/backend/mechanism/global-parameter.md",
    "contribute/api-test.md",
)
HISTORICAL_TOPICS = (
    "guide/parameter/priority.md",
    "guide/project/workflow-definition.md",
    "guide/upgrade/incompatible.md",
    "architecture/configuration.md",
)


def _get(session: requests.Session, url: str) -> bytes:
    response = session.get(url, timeout=45)
    response.raise_for_status()
    return response.content


def build(root: Path = ROOT) -> dict:
    now = datetime.now(timezone.utc).isoformat()
    session = requests.Session()
    session.headers.update({"User-Agent": "version-aware-rag-public-corpus/1.0"})
    records: list[dict] = []
    entries = [("3.4.3", locale, topic) for locale in ("en", "zh") for topic in TOPICS]
    entries += [("3.4.2", locale, topic) for locale in ("en", "zh") for topic in HISTORICAL_TOPICS]
    for version, locale, topic in entries:
        path = f"docs/docs/{locale}/{topic}"
        commit = COMMITS[version]
        source_url = f"https://github.com/{REPOSITORY}/blob/{commit}/{path}"
        raw_url = f"https://raw.githubusercontent.com/{REPOSITORY}/{commit}/{path}"
        content = _get(session, raw_url)
        content.decode("utf-8")
        target = root / "sources" / version / locale / topic
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(content)
        records.append({
            "document_key": topic.removesuffix(".md"),
            "canonical_topic_id": topic.removesuffix(".md"),
            "version": version,
            "commit": commit,
            "locale": "zh-CN" if locale == "zh" else "en-US",
            "language": locale,
            "source_type": "official_documentation",
            "repository": REPOSITORY,
            "document_path": path,
            "local_path": target.relative_to(root).as_posix(),
            "source_url": source_url,
            "retrieval_timestamp": now,
            "license": "Apache-2.0",
            "attribution": "Copyright The Apache Software Foundation and contributors",
            "sha256": hashlib.sha256(content).hexdigest(),
            "bytes": len(content),
        })
    for version in COMMITS:
        api_url = f"https://api.github.com/repos/{REPOSITORY}/releases/tags/{version}"
        release = json.loads(_get(session, api_url))
        content = release["body"].encode("utf-8")
        target = root / "sources" / version / "en" / "release-notes.md"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(content)
        records.append({
            "document_key": "release-notes", "canonical_topic_id": "release-notes",
            "version": version, "commit": COMMITS[version], "locale": "en-US",
            "language": "en", "source_type": "github_release",
            "repository": REPOSITORY, "document_path": f"releases/tag/{version}",
            "local_path": target.relative_to(root).as_posix(),
            "source_url": release["html_url"], "retrieval_timestamp": now,
            "license": "Apache-2.0", "attribution": "The Apache Software Foundation",
            "sha256": hashlib.sha256(content).hexdigest(), "bytes": len(content),
        })
    for number, kind, key in (
        (18454, "issues", "dsip-107-proposal"),
        (18464, "pulls", "dsip-107-implementation"),
    ):
        api_url = f"https://api.github.com/repos/{REPOSITORY}/{kind}/{number}"
        record = json.loads(_get(session, api_url))
        if "DSIP-107" not in record["title"]:
            raise ValueError("unexpected DSIP source")
        content = (f"# {record['title']}\n\n" + (record.get("body") or "")).encode("utf-8")
        target = root / "sources" / "3.4.3" / "en" / f"{key}.md"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(content)
        records.append({
            "document_key": f"proposals/{key}", "canonical_topic_id": "DSIP-107",
            "version": "3.4.3", "commit": COMMITS["3.4.3"], "locale": "en-US",
            "language": "en", "source_type": "github_issue" if kind == "issues" else "github_pull_request",
            "repository": REPOSITORY, "document_path": f"{kind}/{number}",
            "local_path": target.relative_to(root).as_posix(),
            "source_url": record["html_url"], "source_updated_at": record["updated_at"],
            "retrieval_timestamp": now, "license": "Apache-2.0",
            "attribution": "The Apache Software Foundation and original contributor",
            "sha256": hashlib.sha256(content).hexdigest(), "bytes": len(content),
        })
    for name in ("LICENSE", "NOTICE"):
        commit = COMMITS["3.4.3"]
        content = _get(session, f"https://raw.githubusercontent.com/{REPOSITORY}/{commit}/{name}")
        (root / name).write_bytes(content)
    manifest = {
        "workspace": "Apache DolphinScheduler", "repository": REPOSITORY,
        "baseline_version": "3.4.2", "current_version": "3.4.3",
        "commits": COMMITS, "retrieval_timestamp": now,
        "source_count": len(records), "sources": records,
        "license_file": "LICENSE", "notice_file": "NOTICE",
    }
    (root / "corpus_manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return manifest


if __name__ == "__main__":
    print(json.dumps({key: value for key, value in build().items() if key != "sources"}, indent=2))
