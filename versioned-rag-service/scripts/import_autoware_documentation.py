"""Import pinned Autoware documentation and community Chinese HTML snapshots."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
import subprocess
import tarfile
from io import BytesIO
from pathlib import Path, PurePosixPath
from urllib.parse import unquote, urlparse

from bs4 import BeautifulSoup, NavigableString, Tag

from src.public_knowledge import build_index
from scripts.build_reviewed_figure_sidecar import build_reviewed_figure_sidecar
from scripts.figure_evidence import preserve_verified_figure_evidence, scan_inventory


SERVICE_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SELECTION = SERVICE_ROOT / "config" / "autoware_documentation_selection.json"
CORPUS_ROOT = SERVICE_ROOT / "public_corpus_autoware"
IMPORTER_ID = "autoware_documentation_import_v1"
MAX_SOURCE_BYTES = 5_000_000
SHA_RE = re.compile(r"^[0-9a-f]{40}$")
REPOSITORY_RE = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")


def _safe_repo_path(value: str) -> str:
    if not isinstance(value, str) or not value or "\\" in value or "\x00" in value:
        raise ValueError("invalid repository-relative document path")
    path = PurePosixPath(value)
    if path.is_absolute() or any(part in {"", ".", ".."} for part in path.parts):
        raise ValueError("document path escapes the pinned repository")
    return path.as_posix()


def canonical_source_path(canonical_url: str) -> str | None:
    """Map a canonical Autoware docs URL to a candidate Markdown source path."""
    if not isinstance(canonical_url, str):
        return None
    parsed = urlparse(canonical_url)
    if (
        parsed.scheme != "https"
        or parsed.netloc.casefold() != "autowarefoundation.github.io"
        or parsed.query or parsed.fragment
    ):
        return None
    parts = [unquote(part) for part in parsed.path.split("/") if part]
    if not parts or parts[0] != "autoware-documentation":
        return None
    relative = parts[1:]
    if any(part in {".", ".."} or "/" in part or "\\" in part for part in relative):
        return None
    if not relative:
        return "docs/index.md"
    if relative[-1].lower().endswith((".md", ".markdown")):
        candidate = PurePosixPath("docs", *relative).as_posix()
    else:
        candidate = PurePosixPath("docs", *relative, "index.md").as_posix()
    try:
        return _safe_repo_path(candidate)
    except ValueError:
        return None


def _inline(node) -> str:
    if isinstance(node, NavigableString):
        return re.sub(r"\s+", " ", str(node))
    if not isinstance(node, Tag):
        return ""
    name = node.name.casefold()
    if name in {"script", "style", "button", "svg"} or "md-clipboard" in node.get("class", []):
        return ""
    if name == "br":
        return "\n"
    if name == "img":
        alt = re.sub(r"\s+", " ", node.get("alt", "")).strip()
        return f"（图片说明：{alt}；未对图片像素执行 OCR）" if alt else "（原文含图片，未对图片像素执行 OCR）"
    content = "".join(_inline(child) for child in node.children).strip()
    if name == "a":
        href = node.get("href", "")
        if href and not href.startswith(("javascript:", "data:")):
            return f"[{content}]({href})" if content else ""
    if name == "code":
        return f"`{content}`" if content else ""
    if name in {"strong", "b"} and content:
        return f"**{content}**"
    if name in {"em", "i"} and content:
        return f"*{content}*"
    return content


def _render_block(node) -> str:
    if isinstance(node, NavigableString):
        return ""
    if not isinstance(node, Tag):
        return ""
    name = node.name.casefold()
    classes = set(node.get("class", []))
    if name in {"script", "style", "button", "svg", "nav", "footer"}:
        return ""
    if "headerlink" in classes or "md-clipboard" in classes:
        return ""
    if name in {"h1", "h2", "h3", "h4", "h5", "h6"}:
        level = int(name[1])
        text = _inline(node).strip()
        return f"{'#' * level} {text}\n\n" if text else ""
    if name == "p":
        text = _inline(node).strip()
        return f"{text}\n\n" if text else ""
    if name in {"ul", "ol"}:
        rows = []
        ordered = name == "ol"
        start = int(node.get("start", 1)) if ordered and str(node.get("start", "1")).isdigit() else 1
        for offset, item in enumerate(node.find_all("li", recursive=False)):
            pieces = []
            nested = []
            for child in item.children:
                if isinstance(child, Tag) and child.name.casefold() in {"ul", "ol"}:
                    nested.append(_render_block(child).strip())
                else:
                    value = _inline(child).strip()
                    if value:
                        pieces.append(value)
            text = " ".join(pieces).strip()
            if text:
                prefix = f"{start + offset}. " if ordered else "- "
                rows.append(prefix + text)
            rows.extend(nested)
        return "\n".join(rows) + "\n\n" if rows else ""
    if name == "pre":
        code = node.find("code")
        language = ""
        if code:
            for value in code.get("class", []):
                if value.startswith("language-"):
                    language = value.removeprefix("language-")
                    break
            text = code.get_text("", strip=False)
        else:
            text = node.get_text("", strip=False)
        return f"```{language}\n{text.strip()}\n```\n\n" if text.strip() else ""
    if name == "blockquote":
        text = "\n".join(
            line.strip() for line in "".join(_render_block(child) for child in node.children).splitlines()
            if line.strip()
        )
        return "\n".join(f"> {line}" for line in text.splitlines()) + "\n\n" if text else ""
    if name == "table":
        rows = []
        for tr in node.find_all("tr"):
            cells = [re.sub(r"\s+", " ", cell.get_text(" ", strip=True)).replace("|", "\\|")
                     for cell in tr.find_all(["th", "td"], recursive=False)]
            if cells:
                rows.append(cells)
        if not rows:
            return ""
        width = max(len(row) for row in rows)
        rows = [row + [""] * (width - len(row)) for row in rows]
        lines = ["| " + " | ".join(rows[0]) + " |", "| " + " | ".join(["---"] * width) + " |"]
        lines.extend("| " + " | ".join(row) + " |" for row in rows[1:])
        return "\n".join(lines) + "\n\n"
    if name == "hr":
        return "---\n\n"
    if name in {"figure", "figcaption"}:
        rendered = "".join(_render_block(child) for child in node.children)
        return rendered or (f"{_inline(node).strip()}\n\n" if _inline(node).strip() else "")
    if name in {"div", "section", "article", "main", "details", "summary", "dl", "dt", "dd"}:
        return "".join(_render_block(child) for child in node.children)
    # Inline container or an uncommon block tag: preserve its text without site chrome.
    if node.find(["p", "h1", "h2", "h3", "h4", "h5", "h6", "ul", "ol", "pre", "table"]):
        return "".join(_render_block(child) for child in node.children)
    text = _inline(node).strip()
    return f"{text}\n\n" if text else ""


def html_page_to_markdown(raw: bytes) -> dict:
    if not isinstance(raw, bytes) or not raw or len(raw) > MAX_SOURCE_BYTES:
        raise ValueError("community documentation page is empty or exceeds the import size limit")
    raw.decode("utf-8")
    soup = BeautifulSoup(raw, "html.parser")
    article = soup.select_one("article.md-content__inner") or soup.select_one("article")
    if article is None:
        raise ValueError("community documentation page has no article body")
    canonical = soup.find("link", rel="canonical")
    canonical_url = canonical.get("href") if canonical else None
    if not canonical_source_path(canonical_url):
        raise ValueError("community documentation page has no safe Autoware canonical URL")
    for node in article.select(".headerlink, .md-clipboard, script, style, button, svg"):
        node.decompose()
    markdown = "".join(_render_block(child) for child in article.children)
    markdown = re.sub(r"\n[ \t]+\n", "\n\n", markdown)
    markdown = re.sub(r"\n{3,}", "\n\n", markdown).strip() + "\n"
    if not markdown.strip():
        raise ValueError("community documentation article has no indexable text")
    title = ""
    heading = article.find("h1")
    if heading:
        title = re.sub(r"\s+", " ", heading.get_text(" ", strip=True)).strip()
    cjk_count = sum("\u3400" <= char <= "\u9fff" for char in markdown)
    return {
        "markdown": markdown,
        "canonical_url": canonical_url,
        "title": title or "Autoware community documentation",
        "cjk_count": cjk_count,
    }


def _git(root: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(root), *args], capture_output=True, check=True,
    )
    return result.stdout.decode("utf-8", errors="strict").strip()


def _archive_files(root: Path, commit: str, prefix: str, suffix: str) -> list[tuple[str, bytes]]:
    """Read pinned files from Git's tar stream without touching long Windows paths."""
    result = subprocess.run(
        ["git", "-C", str(root), "archive", "--format=tar", commit, prefix],
        capture_output=True,
        check=True,
    )
    return _archive_files_from_tar(result.stdout, prefix, suffix)


def _archive_files_from_tar(payload: bytes, prefix: str, suffix: str) -> list[tuple[str, bytes]]:
    """Select safe regular files from a Git archive without extracting its paths."""
    files: list[tuple[str, bytes]] = []
    with tarfile.open(fileobj=BytesIO(payload), mode="r:") as archive:
        for member in archive:
            if not member.isfile() or not member.name.startswith(prefix + "/"):
                continue
            if not member.name.casefold().endswith(suffix.casefold()):
                continue
            source = archive.extractfile(member)
            if source is None:
                raise ValueError(f"cannot read file from pinned source archive: {member.name}")
            files.append((_safe_repo_path(member.name), source.read()))
    files.sort(key=lambda item: item[0])
    return files


def verify_checkout(root: Path, *, repository: str, expected_commit: str) -> dict:
    root = Path(root).resolve()
    if not REPOSITORY_RE.fullmatch(repository) or not SHA_RE.fullmatch(expected_commit):
        raise ValueError("repository and full commit SHA are required")
    if not root.is_dir():
        raise ValueError(f"pinned documentation checkout is missing: {repository}")
    remote = _git(root, "remote", "get-url", "origin").strip()
    remote = re.sub(r"\.git$", "", remote, flags=re.I)
    expected_urls = {f"https://github.com/{repository}", f"git@github.com:{repository}"}
    if remote.casefold() not in {value.casefold() for value in expected_urls}:
        raise ValueError(f"checkout origin does not match approved repository: {repository}")
    actual_commit = _git(root, "rev-parse", "HEAD")
    if actual_commit != expected_commit:
        raise ValueError(f"checkout is not pinned to the selected commit: {repository}")
    if _git(root, "status", "--porcelain", "--untracked-files=no"):
        raise ValueError(f"pinned source checkout has modified tracked files: {repository}")
    license_path = root / "LICENSE"
    if not license_path.is_file():
        raise ValueError(f"license file is missing: {repository}")
    license_text = license_path.read_text(encoding="utf-8", errors="replace")
    if "Apache License" not in license_text or "Version 2.0" not in license_text:
        raise ValueError(f"repository license is not verified as Apache-2.0: {repository}")
    return {"root": root, "commit": actual_commit, "license": "Apache-2.0"}


def _source_url(repository: str, commit: str, document_path: str) -> str:
    from urllib.parse import quote

    return f"https://github.com/{repository}/blob/{commit}/{quote(document_path, safe='/-._')}"


def _document_key_from_repo_path(document_path: str) -> str:
    path = PurePosixPath(document_path)
    parts = list(path.parts)
    if parts and parts[0] == "docs":
        parts = parts[1:]
    if parts and parts[-1].casefold() in {"index.md", "index.markdown"}:
        parts = parts[:-1]
    elif parts:
        parts[-1] = PurePosixPath(parts[-1]).stem
    route = "/".join(parts) or "index"
    return f"autoware-documentation/{route}"


def _compact_local_path(version: str, language: str, repository_path: str) -> str:
    digest = hashlib.sha256(repository_path.encode("utf-8")).hexdigest()[:24]
    return f"sources/{version}/{language}/{digest}.md"


def _write_source(root: Path, item: dict, content: bytes, *, upstream_sha256: str | None = None) -> dict:
    local_path = _safe_repo_path(item["local_path"])
    destination = (root / local_path).resolve()
    if not destination.is_relative_to(root.resolve()):
        raise ValueError("output path escapes public corpus root")
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_bytes(content)
    return {
        **{key: value for key, value in item.items() if key != "local_path"},
        "local_path": local_path,
        "sha256": hashlib.sha256(content).hexdigest(),
        **({"upstream_sha256": upstream_sha256} if upstream_sha256 else {}),
        "license": "Apache-2.0",
        "importer": IMPORTER_ID,
    }


def collect_official_markdown(checkout: dict, *, version: str, output_root: Path) -> list[dict]:
    root = Path(checkout["root"])
    repository = checkout["repository"]
    commit = checkout["commit"]
    rows = []
    for relative, raw in _archive_files(root, commit, "docs", ".md"):
        relative = _safe_repo_path(relative)
        if not raw or len(raw) > MAX_SOURCE_BYTES:
            raise ValueError(f"official documentation file is empty or too large: {relative}")
        raw.decode("utf-8")
        document_key = _document_key_from_repo_path(relative)
        item = {
            "repository": repository, "version": version, "commit": commit,
            "document_key": document_key, "source_type": "official_documentation",
            "language": "en", "locale": "en-US", "document_path": relative,
            "source_url": _source_url(repository, commit, relative),
            "local_path": _compact_local_path(version, "en", relative),
            "release_alignment_status": "pinned_official_source",
        }
        rows.append(_write_source(Path(output_root), item, raw))
    if not rows:
        raise ValueError(f"official documentation snapshot contains no Markdown pages: {version}")
    return rows


def collect_community_html(
    checkout: dict, official_main: dict, *, version: str, output_root: Path,
) -> list[dict]:
    root = Path(checkout["root"])
    repository = checkout["repository"]
    commit = checkout["commit"]
    official_root = Path(official_main["root"])
    official_repo = official_main["repository"]
    official_commit = official_main["commit"]
    rows = []
    for relative, raw in _archive_files(root, commit, "docs", "index.html"):
        relative = _safe_repo_path(relative)
        page = html_page_to_markdown(raw)
        if page["cjk_count"] < 20:
            continue
        canonical_path = canonical_source_path(page["canonical_url"])
        if canonical_path is None:
            continue
        canonical_file = official_root.joinpath(*PurePosixPath(canonical_path).parts)
        official_match = None
        if canonical_file.is_file():
            official_match = canonical_path
        elif canonical_path.endswith("/index.md"):
            flattened = canonical_path.removesuffix("/index.md") + ".md"
            if official_root.joinpath(*PurePosixPath(flattened).parts).is_file():
                official_match = flattened
        document_key = _document_key_from_repo_path(canonical_path)
        route_parts = list(PurePosixPath(relative).parts[1:])
        if route_parts and route_parts[-1].casefold() == "index.html":
            route_parts.pop()
        rendered_route = "/".join(route_parts)
        rendered_url = "https://tomato-ros.github.io/autoware-documentation-cn/" + rendered_route
        if rendered_route:
            rendered_url += "/"
        alignment = "path_matched_to_official_main" if official_match else "source_path_not_found_in_official_main"
        item = {
            "repository": repository, "version": version, "commit": commit,
            "document_key": document_key, "source_type": "community_translation",
            "language": "zh", "locale": "zh-CN", "document_path": relative,
            "source_url": _source_url(repository, commit, relative),
            "rendered_url": rendered_url,
            "canonical_url": page["canonical_url"],
            "title": page["title"],
            "translation_alignment_status": alignment,
            "canonical_source_path": canonical_path,
            "english_source_url": (
                _source_url(official_repo, official_commit, official_match) if official_match else None
            ),
            "local_path": _compact_local_path(version, "zh", relative),
        }
        normalized = page["markdown"].encode("utf-8")
        rows.append(_write_source(Path(output_root), item, normalized, upstream_sha256=hashlib.sha256(raw).hexdigest()))
    if not rows:
        raise ValueError("community translation snapshot contains no Chinese article pages")
    return rows


def _repo_entries(selection: dict) -> tuple[dict, dict, dict]:
    docs_repository = selection.get("official_repository")
    community_repository = selection.get("community_repository")
    snapshots = selection.get("official_snapshots")
    community = selection.get("community_snapshot")
    if (
        selection.get("schema_version") != 1
        or not REPOSITORY_RE.fullmatch(str(docs_repository or ""))
        or not REPOSITORY_RE.fullmatch(str(community_repository or ""))
        or not isinstance(snapshots, dict)
        or not isinstance(snapshots.get("docs-main"), dict)
        or not isinstance(snapshots.get("docs-1.9.0"), dict)
        or not isinstance(community, dict)
    ):
        raise ValueError("invalid Autoware documentation snapshot selection")
    return snapshots["docs-main"], snapshots["docs-1.9.0"], community


def import_documentation(
    *, official_main_checkout: Path, official_release_checkout: Path,
    community_checkout: Path, output_root: Path = CORPUS_ROOT,
    selection_path: Path = DEFAULT_SELECTION,
) -> dict:
    selection = json.loads(Path(selection_path).read_text(encoding="utf-8"))
    main_spec, release_spec, community_spec = _repo_entries(selection)
    official_repository = selection["official_repository"]
    community_repository = selection["community_repository"]
    official_main = verify_checkout(
        official_main_checkout, repository=official_repository, expected_commit=main_spec["commit"],
    )
    official_release = verify_checkout(
        official_release_checkout, repository=official_repository, expected_commit=release_spec["commit"],
    )
    community = verify_checkout(
        community_checkout, repository=community_repository, expected_commit=community_spec["commit"],
    )
    official_main.update(repository=official_repository)
    official_release.update(repository=official_repository)
    community.update(repository=community_repository)

    output_root = Path(output_root).resolve()
    manifest_path = output_root / "corpus_manifest.json"
    previous_manifest_bytes = manifest_path.read_bytes()
    previous_manifest = json.loads(previous_manifest_bytes)
    previous_inventory_path = output_root / "figure_evidence.json"
    try:
        previous_inventory = json.loads(previous_inventory_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        previous_inventory = None

    managed = [row for row in previous_manifest.get("sources", []) if row.get("importer") == IMPORTER_ID]
    retained = [row for row in previous_manifest.get("sources", []) if row.get("importer") != IMPORTER_ID]
    imported = [
        *collect_official_markdown(official_main, version="docs-main", output_root=output_root),
        *collect_official_markdown(official_release, version="1.9.0", output_root=output_root),
        *collect_community_html(community, official_main, version="docs-main", output_root=output_root),
    ]
    sources = [*retained, *imported]
    identities = [(row["version"], row["language"], row["document_key"]) for row in sources]
    if len(identities) != len(set(identities)):
        raise ValueError("duplicate Autoware source identity across pinned snapshots")

    old_paths = {row.get("local_path") for row in managed if row.get("local_path")}
    new_paths = {row["local_path"] for row in imported}
    for stale in sorted(old_paths - new_paths):
        stale_path = (output_root / _safe_repo_path(stale)).resolve()
        if not stale_path.is_relative_to(output_root):
            raise ValueError("stale generated source path escapes public corpus root")
        if stale_path.is_file() and not stale_path.is_symlink():
            stale_path.unlink()

    # Keep the existing Universe planning line and make the latest scope an explicit union.
    versions = ["latest", "docs-main", "1.9.0", "0.52.0", "0.51.0"]
    repositories = sorted({row["repository"] for row in sources})
    commits_by_repository: dict[str, dict[str, str]] = {}
    for row in sources:
        commits_by_repository.setdefault(row["repository"], {})[row["version"]] = row["commit"]
    commits = dict(previous_manifest.get("commits", {}))
    commits["docs-main"] = official_main["commit"]
    commits["1.9.0"] = official_release["commit"]
    manifest = {
        **previous_manifest,
        "schema_version": 2,
        "workspace": "Autoware",
        "repository": "autowarefoundation/autoware_universe",
        "repositories": repositories,
        "data_origin": (
            "Autoware official documentation and Universe public sources, plus a pinned "
            "Tomato ROS community Chinese translation snapshot"
        ),
        "baseline_version": "0.51.0",
        "current_version": "latest",
        "available_versions": versions,
        "version_scopes": {
            "latest": {"versions": ["docs-main", "0.52.0"]},
        },
        "version_labels": {
            "latest": "最新资料范围 · 官方文档 main + Universe 0.52.0",
            "docs-main": "Autoware Documentation main · 固定当前快照",
            "1.9.0": "Autoware Documentation 1.9.0 · 官方稳定文档版",
            "0.52.0": "Autoware Universe 0.52.0 · Planning 最新已收录版",
            "0.51.0": "Autoware Universe 0.51.0 · Planning 历史基线",
        },
        "commits": commits,
        "commits_by_repository": commits_by_repository,
        "languages": sorted({row["locale"] for row in sources}),
        "corpus_is_complete": False,
        "corpus_scope": (
            "Autoware public documentation snapshots: official Documentation main and 1.9.0 release, "
            "a pinned Tomato ROS community Chinese translation snapshot with explicit path-alignment status, "
            "and the existing Autoware Universe Planning releases 0.51.0/0.52.0. "
            "The default latest scope combines Documentation main with Universe 0.52.0; this is not a single "
            "product release and the community translation is not an official Autoware translation."
        ),
        "sources": sources,
    }
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")
    shutil.copyfile(SERVICE_ROOT / "config" / "public_retrieval_runtime.json", output_root / "retrieval_policy.json")
    runtime_config = json.loads((SERVICE_ROOT / "config" / "autoware_retrieval_policy.json").read_text(encoding="utf-8"))
    runtime_config["default_policy"] = "bm25"
    runtime_config["selection_status"] = "pending_bilingual_rebenchmark"
    runtime_config["selection_evaluation"] = "evaluation/autoware_bilingual_v1/README.md"
    runtime_config["selection_note"] = (
        "The previous bm25_figure_ocr selection was validated only on the 26-source Autoware Universe "
        "Planning corpus. This expanded multilingual documentation corpus retains BM25 as a baseline; "
        "no candidate is presented as the best-performing policy until the bilingual benchmark is run."
    )
    (output_root / "public_retrieval_runtime.json").write_text(
        json.dumps(runtime_config, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n",
    )
    policy = json.loads((output_root / "retrieval_policy.json").read_text(encoding="utf-8"))
    policy["default_policy"] = "bm25"
    policy["selection_status"] = "pending_bilingual_rebenchmark"
    policy["benchmark_query_count"] = 0
    policy["selection_note"] = (
        "BM25 is retained as the transparent lexical baseline after corpus expansion. "
        "No retrieval strategy is claimed as optimal until the bilingual Autoware evaluation is run."
    )
    policy["benchmark_corpus_sha256"] = hashlib.sha256(manifest_path.read_bytes()).hexdigest()
    policy_path = output_root / "retrieval_policy.json"
    policy_path.write_text(json.dumps(policy, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")
    stats = build_index(output_root)

    current_manifest_bytes = manifest_path.read_bytes()
    inventory = preserve_verified_figure_evidence(
        scan_inventory(output_root), previous_inventory,
        previous_manifest_bytes=previous_manifest_bytes,
        current_manifest_bytes=current_manifest_bytes,
    )
    previous_inventory_path.write_text(
        json.dumps(inventory, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n",
    )
    sidecar = build_reviewed_figure_sidecar(output_root)
    return {
        "current_scope": manifest["current_version"], "versions": versions,
        "languages": manifest["languages"], "official_main_sources": sum(row["version"] == "docs-main" and row["language"] == "en" for row in imported),
        "official_release_sources": sum(row["version"] == "1.9.0" for row in imported),
        "community_chinese_sources": sum(row["source_type"] == "community_translation" for row in imported),
        "community_path_matched": sum(row.get("translation_alignment_status") == "path_matched_to_official_main" for row in imported),
        "community_alignment_unverified": sum(row.get("translation_alignment_status") != "path_matched_to_official_main" for row in imported if row["source_type"] == "community_translation"),
        **stats, **sidecar,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--official-main-checkout", type=Path, required=True)
    parser.add_argument("--official-release-checkout", type=Path, required=True)
    parser.add_argument("--community-checkout", type=Path, required=True)
    parser.add_argument("--root", type=Path, default=CORPUS_ROOT)
    parser.add_argument("--selection", type=Path, default=DEFAULT_SELECTION)
    parser.add_argument("--rebuild", action="store_true", required=True)
    args = parser.parse_args(argv)
    result = import_documentation(
        official_main_checkout=args.official_main_checkout,
        official_release_checkout=args.official_release_checkout,
        community_checkout=args.community_checkout,
        output_root=args.root,
        selection_path=args.selection,
    )
    print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
