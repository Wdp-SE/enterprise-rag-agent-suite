"""Fetch only the allowlisted Autoware files from immutable release commits."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path, PurePosixPath
from urllib.parse import quote
from urllib.request import Request, urlopen

from scripts.sync_autoware_sources import DEFAULT_SELECTION, REPOSITORY, _normalized_repo_path, load_source_selection


VERSIONS = ("0.51.0", "0.52.0")
MAX_SOURCE_BYTES = 5_000_000
SHA_RE = re.compile(r"^[0-9a-f]{40}$")


def _fetch(url: str) -> bytes:
    request = Request(url, headers={"User-Agent": "versioned-rag-autoware-corpus/1.0"})
    with urlopen(request, timeout=30) as response:
        payload = response.read(MAX_SOURCE_BYTES + 1)
    if len(payload) > MAX_SOURCE_BYTES:
        raise ValueError("pinned source exceeded the 5 MB import limit")
    return payload


def fetch_pinned_sources(selection_path: Path, destination: Path, *, fetcher=_fetch) -> dict[str, dict]:
    payload = json.loads(Path(selection_path).read_text(encoding="utf-8"))
    if not isinstance(payload, dict) or payload.get("repository") != REPOSITORY:
        raise ValueError("source selection must identify the approved Autoware repository")
    releases = payload.get("releases")
    if not isinstance(releases, dict) or set(releases) != set(VERSIONS):
        raise ValueError("source selection must pin exactly the supported release tags")
    sources = load_source_selection(selection_path)
    result = {}
    for version in VERSIONS:
        commit = releases[version].get("commit") if isinstance(releases[version], dict) else None
        if not isinstance(commit, str) or not SHA_RE.fullmatch(commit):
            raise ValueError(f"release {version} must pin a full immutable commit SHA")
        root = Path(destination) / version
        root.mkdir(parents=True, exist_ok=True)
        file_hashes = {}
        paths = [_normalized_repo_path(row["document_path"]) for row in sources]
        paths.append("LICENSE")
        for relative in paths:
            url = f"https://raw.githubusercontent.com/{REPOSITORY}/{commit}/{quote(relative, safe='/-._')}"
            content = fetcher(url)
            if not isinstance(content, bytes) or len(content) > MAX_SOURCE_BYTES:
                raise ValueError(f"invalid pinned source response: {relative}")
            content = content.replace(b"\r\n", b"\n")
            if relative != "LICENSE":
                content.decode("utf-8")
            target = root.joinpath(*PurePosixPath(relative).parts)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(content)
            file_hashes[relative] = hashlib.sha256(content).hexdigest()
        license_text = (root / "LICENSE").read_text(encoding="utf-8", errors="replace")
        if "Apache License" not in license_text or "Version 2.0" not in license_text:
            raise ValueError("downloaded repository license is not Apache-2.0")
        metadata = {
            "schema_version": 1,
            "repository": REPOSITORY,
            "tag": version,
            "version": version,
            "commit": commit,
            "files_sha256": file_hashes,
        }
        (root / ".autoware_source_ref.json").write_text(
            json.dumps(metadata, indent=2) + "\n", encoding="utf-8", newline="\n",
        )
        result[version] = {"root": root, "commit": commit}
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--selection", type=Path, default=DEFAULT_SELECTION)
    parser.add_argument("--destination", type=Path, required=True)
    args = parser.parse_args(argv)
    rows = fetch_pinned_sources(args.selection, args.destination)
    print(json.dumps({version: str(row["root"]) for version, row in rows.items()}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
