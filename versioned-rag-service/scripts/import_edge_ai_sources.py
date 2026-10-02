"""Validate and normalize a license-audited snapshot of Seeed Jetson docs."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path, PurePosixPath
from urllib.parse import urlparse

from bs4 import BeautifulSoup, NavigableString, Tag


SERVICE_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SELECTION = SERVICE_ROOT / "config" / "edge_ai_source_selection.json"
DEFAULT_SOURCE_ROOT = SERVICE_ROOT / "public_corpus_edge_ai"
DEFAULT_OUTPUT_ROOT = SERVICE_ROOT / "public_corpus_edge_ai"
MAX_SOURCE_BYTES = 20_000_000
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
COMMIT_RE = re.compile(r"^[0-9a-f]{40}$")
SOURCE_ID_RE = re.compile(r"^[a-z0-9][a-z0-9-]{2,79}$")
ALLOWED_SOURCE_HOSTS = frozenset({"wiki.seeedstudio.com", "github.com", "files.seeedstudio.com"})
ALLOWED_FORMATS = frozenset({"markdown", "html", "pdf"})


def _safe_relative_path(value: str, *, label: str) -> str:
    if not isinstance(value, str) or not value or "\\" in value or "\x00" in value:
        raise ValueError(f"invalid {label}")
    path = PurePosixPath(value)
    if path.is_absolute() or any(part in {"", ".", ".."} for part in path.parts):
        raise ValueError(f"{label} escapes its pinned snapshot")
    return path.as_posix()


def load_source_selection(path: Path) -> dict:
    try:
        selection = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError("source selection is unreadable JSON") from exc
    if not isinstance(selection, dict) or selection.get("schema_version") != 1:
        raise ValueError("unsupported source selection schema")
    rows = selection.get("sources")
    if not isinstance(rows, list):
        raise ValueError("source selection must contain a sources list")
    ids = [row.get("source_id") for row in rows if isinstance(row, dict)]
    if len(ids) != len(rows) or len(ids) != len(set(ids)):
        raise ValueError("source selection contains invalid or duplicate source ids")
    return selection


def validate_source_record(row: dict, *, source_root: Path) -> None:
    """Validate provenance, individual license, safe path, and snapshot bytes."""
    required = (
        "source_id", "source_url", "repository", "document_path", "language", "license",
        "license_status", "attribution", "source_format", "device_model", "module_sku",
        "carrier_board", "software_baselines",
    )
    if not isinstance(row, dict) or any(
        not isinstance(row.get(key), str) or not row[key].strip()
        for key in required if key not in {"device_model", "module_sku", "carrier_board", "software_baselines"}
    ):
        raise ValueError("source record is incomplete")
    if not SOURCE_ID_RE.fullmatch(row["source_id"]):
        raise ValueError("source_id is invalid")
    for key in ("device_model", "module_sku", "carrier_board", "software_baselines"):
        if not isinstance(row.get(key), list) or any(not isinstance(value, str) or not value for value in row[key]):
            raise ValueError(f"source field {key} must be a list of nonempty strings")
    if row["language"] != "zh-CN":
        raise ValueError("only zh-CN source documents are accepted in the active corpus")
    if row["source_format"] not in ALLOWED_FORMATS:
        raise ValueError("unsupported source format")
    parsed = urlparse(row["source_url"])
    if parsed.scheme != "https" or parsed.hostname not in ALLOWED_SOURCE_HOSTS or parsed.username or parsed.password:
        raise ValueError("source URL host is not in the reviewed allowlist")
    if parsed.query or parsed.fragment:
        raise ValueError("source URL must be a stable canonical URL")
    if row.get("repository") == "Seeed-Studio/wiki-documents":
        if not isinstance(row.get("commit"), str) or not COMMIT_RE.fullmatch(row["commit"]):
            raise ValueError("a full pinned commit is required for repository sources")
    elif not row.get("commit") and not row.get("retrieved_at_utc"):
        raise ValueError("a fixed commit or retrieval timestamp is required")
    if row.get("commit") is not None and not COMMIT_RE.fullmatch(str(row["commit"])):
        raise ValueError("commit must be a full 40-character SHA")
    _safe_relative_path(row["document_path"], label="document path")

    status = row["license_status"]
    if status not in {"redistributable", "link_only"}:
        raise ValueError("license_status must be redistributable or link_only")
    if status != "redistributable":
        if row.get("local_path") is not None or row.get("sha256") is not None:
            raise ValueError("link_only source cannot include local content")
        return
    if not row["license"].strip() or not row["attribution"].strip():
        raise ValueError("redistributable source needs an explicit license and attribution")
    if not isinstance(row.get("local_path"), str) or not SHA256_RE.fullmatch(str(row.get("sha256", ""))):
        raise ValueError("redistributable source requires a local path and SHA-256")
    relative = _safe_relative_path(row["local_path"], label="source path")
    root = Path(source_root).resolve()
    candidate = root / Path(*PurePosixPath(relative).parts)
    if candidate.is_symlink():
        raise ValueError("source path is outside the pinned snapshot or is not a regular file")
    source_path = candidate.resolve()
    if not source_path.is_relative_to(root) or not source_path.is_file():
        raise ValueError("source path is outside the pinned snapshot or is not a regular file")
    if source_path.stat().st_size <= 0 or source_path.stat().st_size > MAX_SOURCE_BYTES:
        raise ValueError("source file is empty or exceeds the import size limit")
    digest = hashlib.sha256(source_path.read_bytes()).hexdigest()
    if digest != row["sha256"]:
        raise ValueError("source content hash mismatch")


def _render_inline(node) -> str:
    if isinstance(node, NavigableString):
        return re.sub(r"\s+", " ", str(node))
    if not isinstance(node, Tag):
        return ""
    name = node.name.casefold()
    if name in {"script", "style", "nav", "footer", "button", "svg"}:
        return ""
    if name == "img":
        return ""
    value = "".join(_render_inline(child) for child in node.children).strip()
    if name == "code" and value:
        return f"`{value}`"
    if name in {"strong", "b"} and value:
        return f"**{value}**"
    if name == "a":
        href = node.get("href", "")
        if href.startswith("https://") and value:
            return f"[{value}]({href})"
    return value


def _render_html_block(node) -> str:
    if not isinstance(node, Tag):
        return ""
    name = node.name.casefold()
    if name in {"script", "style", "nav", "footer", "button", "svg"}:
        return ""
    if name in {"h1", "h2", "h3", "h4", "h5", "h6"}:
        text = _render_inline(node).strip()
        return f"{'#' * int(name[1])} {text}\n\n" if text else ""
    if name == "table":
        rows = []
        pending: dict[int, int] = {}
        for tr in node.find_all("tr"):
            values = {column: "" for column in pending}
            pending = {column: remaining - 1 for column, remaining in pending.items() if remaining > 1}
            for cell in tr.find_all(["th", "td"], recursive=False):
                column = 0
                while column in values:
                    column += 1
                span_match = re.search(r"\d+", str(cell.get("colspan", "1")))
                colspan = max(int(span_match.group()) if span_match else 1, 1)
                rowspan_match = re.search(r"\d+", str(cell.get("rowspan", "1")))
                rowspan = max(int(rowspan_match.group()) if rowspan_match else 1, 1)
                value = re.sub(r"\s+", " ", cell.get_text(" ", strip=True)).replace("|", "\\|")
                for offset in range(colspan):
                    values[column + offset] = value if offset == 0 else ""
                    if rowspan > 1:
                        pending[column + offset] = rowspan - 1
            if values:
                rows.append([values[index] for index in range(max(values) + 1)])
        if not rows:
            return ""
        width = max(map(len, rows))
        rows = [row + [""] * (width - len(row)) for row in rows]
        lines = ["| " + " | ".join(rows[0]) + " |", "| " + " | ".join(["---"] * width) + " |"]
        lines.extend("| " + " | ".join(row) + " |" for row in rows[1:])
        return "\n".join(lines) + "\n\n"
    if name in {"pre", "code"}:
        text = node.get_text("", strip=False).strip()
        return f"```\n{text}\n```\n\n" if text else ""
    if name in {"ul", "ol"}:
        rows = []
        for index, item in enumerate(node.find_all("li", recursive=False), start=1):
            text = _render_inline(item).strip()
            if text:
                rows.append(f"{index}. {text}" if name == "ol" else f"- {text}")
        return "\n".join(rows) + "\n\n" if rows else ""
    if name == "p":
        text = _render_inline(node).strip()
        return f"{text}\n\n" if text else ""
    if node.find(["p", "h1", "h2", "h3", "h4", "h5", "h6", "table", "pre", "ul", "ol"]):
        return "".join(_render_html_block(child) for child in node.children)
    text = _render_inline(node).strip()
    return f"{text}\n\n" if text else ""


def _normalize_markdown(raw: bytes) -> tuple[str, str | None, int]:
    text = raw.decode("utf-8-sig")
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    title = None
    if text.startswith("---\n"):
        end = text.find("\n---", 4)
        if end >= 0:
            frontmatter = text[4:end]
            match = re.search(r"^title:\s*(.*)$", frontmatter, re.M)
            title = match.group(1).strip().strip("\"'") if match else None
            text = text[end + 4:].lstrip("\r\n")
    image_count = len(re.findall(r"!\[[^\]]*\]\([^)]*\)", text)) + len(re.findall(r"(?i)<img\b", text))
    code_blocks: list[str] = []

    def stash_code(match: re.Match[str]) -> str:
        code_blocks.append(match.group(0))
        return f"\x00EDGEAI_CODE_{len(code_blocks) - 1}\x00"

    text = re.sub(r"(?ms)^(`{3,}|~{3,})[^\n]*\n.*?^\1[ \t]*$", stash_code, text)
    text = re.sub(r"(?m)^\s*import\s+[^;\n]+;?\s*$", "", text)
    text = re.sub(r"(?is)<video\b[^>]*>.*?</video>", "", text)
    text = re.sub(
        r"(?is)<a\b(?=[^>]*\bclass\s*=\s*['\"][^'\"]*get_one_now_item)[^>]*>.*?</a>",
        "",
        text,
    )

    def render_tab_item(match: re.Match[str]) -> str:
        attrs = match.group(1)
        label_match = re.search(r"\blabel\s*=\s*(['\"])(.*?)\1", attrs, re.S)
        value_match = re.search(r"\bvalue\s*=\s*(['\"])(.*?)\1", attrs, re.S)
        label = label_match.group(2).strip() if label_match else value_match.group(2).strip() if value_match else ""
        label = re.sub(r"(?i)\bjetpack\s*(?=\d)", "JetPack ", label)
        return f"\n## {label}\n" if label else "\n"

    text = re.sub(r"(?i)<TabItem\b([^>]*)>", render_tab_item, text)
    text = re.sub(r"(?i)</TabItem\s*>|</?Tabs\b[^>]*>", "\n", text)

    def render_markdown_table(match: re.Match[str]) -> str:
        soup = BeautifulSoup(match.group(0), "html.parser")
        table = soup.find("table")
        return _render_html_block(table) if table else ""

    text = re.sub(r"(?is)<table\b[^>]*>.*?</table>", render_markdown_table, text)
    text = re.sub(r"!\[[^\]]*\]\([^)]*\)", "", text)
    text = re.sub(r"(?is)<img\b[^>]*>", "", text)
    text = re.sub(r"(?is)<video\b[^>]*>|</video>|<source\b[^>]*>", "", text)
    text = re.sub(r"(?i)</?[a-z][a-z0-9:-]*\b[^>]*>", "", text)
    text = re.sub(
        r"(?m)^:::(?:note|tip|warning|danger|info)(?:\s+(.+))?\s*$",
        lambda match: f"> 说明：{match.group(1).strip()}" if match.group(1) else "> 说明",
        text,
    )
    text = re.sub(r"(?m)^:::\s*$", "", text)
    text = re.sub(r"\n{3,}", "\n\n", text).strip() + "\n"
    for index, block in enumerate(code_blocks):
        text = text.replace(f"\x00EDGEAI_CODE_{index}\x00", block)
    if not text.strip():
        raise ValueError("Markdown source has no indexable text")
    return text, title, image_count


def _pdf_pages(raw: bytes) -> tuple[str, int, int]:
    try:
        from pypdf import PdfReader
    except ImportError:
        try:
            from PyPDF2 import PdfReader
        except ImportError as exc:
            raise ValueError("PDF import requires the optional source-import requirements") from exc
    from io import BytesIO

    reader = PdfReader(BytesIO(raw), strict=True)
    pages = []
    image_count = 0
    for number, page in enumerate(reader.pages, start=1):
        try:
            image_count += len(page.images)
        except (AttributeError, NotImplementedError, KeyError):
            pass
        value = (page.extract_text() or "").strip()
        if value:
            pages.append(f"## 第 {number} 页\n\n{value}")
    if not pages:
        raise ValueError("PDF contains no extractable text; OCR is not enabled")
    return "\n\n".join(pages) + "\n", len(reader.pages), image_count


def normalize_source_file(source: dict, input_path: Path) -> tuple[str, dict]:
    """Normalize an audited Markdown, HTML, or text PDF source to Markdown."""
    input_path = Path(input_path)
    if not input_path.is_file() or input_path.is_symlink():
        raise ValueError("source input must be a regular file")
    raw = input_path.read_bytes()
    if not raw or len(raw) > MAX_SOURCE_BYTES:
        raise ValueError("source file is empty or exceeds the import size limit")
    source_format = source.get("source_format")
    if source_format == "markdown":
        markdown, title, image_count = _normalize_markdown(raw)
        metadata = {
            "source_format": source_format,
            "title": title or source["source_id"],
            "image_references_omitted": image_count,
        }
    elif source_format == "html":
        soup = BeautifulSoup(raw.decode("utf-8"), "html.parser")
        article = soup.select_one("article") or soup.select_one("main")
        if article is None:
            raise ValueError("HTML source has no article or main element")
        image_count = len(article.select("img"))
        for element in article.select("script, style, nav, footer, button, svg"):
            element.decompose()
        markdown = "".join(_render_html_block(child) for child in article.children)
        markdown = re.sub(r"\n{3,}", "\n\n", markdown).strip() + "\n"
        heading = article.find("h1")
        title = re.sub(r"\s+", " ", heading.get_text(" ", strip=True)).strip() if heading else None
        metadata = {
            "source_format": source_format,
            "title": title or source["source_id"],
            "image_references_omitted": image_count,
        }
    elif source_format == "pdf":
        markdown, page_count, image_count = _pdf_pages(raw)
        metadata = {
            "source_format": source_format,
            "title": source["source_id"],
            "page_count": page_count,
            "image_references_omitted": image_count,
        }
    else:
        raise ValueError("unsupported source format")
    if not markdown.strip():
        raise ValueError("source has no indexable text")
    return markdown, metadata


def import_sources(*, selection_path: Path, source_root: Path, output_root: Path) -> dict:
    selection = load_source_selection(selection_path)
    root = Path(source_root).resolve()
    output = Path(output_root).resolve()
    output.mkdir(parents=True, exist_ok=True)
    sources_dir = output / "sources"
    if sources_dir.is_symlink():
        raise ValueError("generated source directory cannot be a symlink")
    previous_manifest_path = output / "source_import_manifest.json"
    try:
        previous_manifest = json.loads(previous_manifest_path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        previous_manifest = {"sources": []}
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError("existing import manifest is unreadable; refusing to overwrite generated content") from exc
    previous_rows = previous_manifest.get("sources")
    if not isinstance(previous_rows, list):
        raise ValueError("existing import manifest has an invalid source list")
    imported = []
    for row in selection["sources"]:
        validate_source_record(row, source_root=root)
        if row["license_status"] == "link_only":
            imported.append({key: value for key, value in row.items() if key not in {"local_path", "sha256"}})
            continue
        local = root.joinpath(*PurePosixPath(row["local_path"]).parts)
        markdown, parse_metadata = normalize_source_file(row, local)
        destination_rel = f"sources/{row['source_id']}.md"
        destination_candidate = output / destination_rel
        if destination_candidate.is_symlink():
            raise ValueError("generated source destination cannot be a symlink")
        destination = destination_candidate.resolve()
        if not destination.is_relative_to(output):
            raise ValueError("generated source output path escapes the corpus root")
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(markdown, encoding="utf-8", newline="\n")
        normalized = {
            **row,
            "local_path": destination_rel,
            "sha256": hashlib.sha256(destination.read_bytes()).hexdigest(),
            "raw_local_path": row["local_path"],
            "raw_sha256": row["sha256"],
            **parse_metadata,
        }
        imported.append(normalized)
    if not any(row.get("license_status") == "redistributable" for row in imported):
        raise ValueError("source selection contains no redistributable documents for the active index")
    current_paths = {row.get("local_path") for row in imported if row.get("license_status") == "redistributable"}
    for previous in previous_rows:
        if not isinstance(previous, dict) or not isinstance(previous.get("local_path"), str):
            continue
        stale_rel = _safe_relative_path(previous["local_path"], label="previous generated source path")
        if not stale_rel.startswith("sources/") or stale_rel in current_paths:
            continue
        stale_candidate = output.joinpath(*PurePosixPath(stale_rel).parts)
        if stale_candidate.is_symlink():
            raise ValueError("stale generated source is a symlink; refusing to remove it")
        stale_path = stale_candidate.resolve()
        if not stale_path.is_relative_to(output):
            raise ValueError("stale generated source escapes the corpus root")
        if stale_path.is_file():
            stale_path.unlink()
    result = {
        "schema_version": 1,
        "workspace_id": selection.get("workspace_id", "edge_ai_device"),
        "source_snapshot": selection.get("source_snapshot"),
        "source_count": len(imported),
        "indexable_source_count": sum(row.get("license_status") == "redistributable" for row in imported),
        "sources": imported,
    }
    (output / "source_import_manifest.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n",
    )
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--selection", type=Path, default=DEFAULT_SELECTION)
    parser.add_argument("--source-root", type=Path, default=DEFAULT_SOURCE_ROOT)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT_ROOT)
    args = parser.parse_args(argv)
    result = import_sources(selection_path=args.selection, source_root=args.source_root, output_root=args.output)
    print(json.dumps({key: result[key] for key in ("workspace_id", "source_count", "indexable_source_count")}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
