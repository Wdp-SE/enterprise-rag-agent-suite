"""Inventory official Markdown figures at pinned commits and audit selected images.

This is an offline corpus audit. OCR text is an unreviewed candidate and is not
automatically added to the retrieval index. Markdown alt text is provenance,
never evidence that the words occur inside an image.
"""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import os
import posixpath
import re
import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable
from urllib.error import HTTPError
from urllib.parse import quote, unquote, urlsplit
from urllib.request import Request, urlopen


ROOT = Path(__file__).resolve().parents[1] / "public_corpus"
MAX_IMAGE_BYTES = 2_000_000
_COMMIT = re.compile(r"^[0-9a-f]{40}$")
_MARKDOWN_IMAGE = re.compile(
    r"!\[(?P<alt>[^\]]*)\]\(\s*(?:<(?P<angle>[^>]+)>|(?P<url>[^\s)]+))"
    r"(?:\s+[^)]*)?\)"
)
_HTML_IMAGE = re.compile(r"<img\b[^>]*\bsrc\s*=\s*['\"](?P<url>[^'\"]+)['\"][^>]*>", re.I)
_HTML_ALT = re.compile(r"\balt\s*=\s*['\"](?P<alt>[^'\"]*)['\"]", re.I)

# Deliberately small: sampling high-value business figures costs six GETs at most.
SELECTED_FIGURES = (
    "docs/img/new_ui/dev/parameter/priority_parameter01.png",
    "docs/img/new_ui/dev/parameter/context_parameter01.png",
    "docs/img/new_ui/dev/project/instance-parameter.png",
    "docs/img/tasks/demo/dependent_task01.png",
    "docs/img/new_ui/dev/monitor/failure-command-list.png",
    "docs/img/new_ui/dev/open-api/api_doc.png",
)


class ImageTooLarge(ValueError):
    """The remote file exceeded the fixed audit size cap."""


def resolve_asset_path(document_path: str, target: str) -> str | None:
    """Resolve a local Markdown target to a repository-relative asset path."""
    if not isinstance(target, str) or not target or "\\" in target:
        return None
    parts = urlsplit(target)
    if parts.scheme or parts.netloc or not parts.path or parts.path.startswith("/"):
        return None
    decoded = unquote(parts.path)
    if decoded.startswith("/") or "\\" in decoded or "\x00" in decoded:
        return None
    if not document_path.startswith("docs/docs/") or not document_path.endswith(".md"):
        return None
    result = posixpath.normpath(posixpath.join(posixpath.dirname(document_path), decoded))
    if result in {"", ".", ".."} or result.startswith("../"):
        return None
    if not result.startswith("docs/"):
        return None
    return result


def _references_in_markdown(text: str):
    for number, line in enumerate(text.splitlines(), 1):
        for match in _MARKDOWN_IMAGE.finditer(line):
            yield number, match.group("angle") or match.group("url"), match.group("alt")
        for match in _HTML_IMAGE.finditer(line):
            alt = _HTML_ALT.search(match.group(0))
            yield number, match.group("url"), alt.group("alt") if alt else ""


def scan_inventory(root: Path = ROOT) -> dict:
    manifest_bytes = (root / "corpus_manifest.json").read_bytes()
    manifest = json.loads(manifest_bytes)
    figures: dict[tuple[str, str], dict] = {}
    relative_count = external_count = unresolved_count = 0
    for source in manifest["sources"]:
        if source.get("source_type") != "official_documentation":
            continue
        if source.get("repository") != "apache/dolphinscheduler":
            continue
        commit = source.get("commit", "")
        if not _COMMIT.fullmatch(commit):
            raise ValueError("official source has no fixed commit")
        version = source["version"]
        if manifest.get("commits", {}).get(version, commit) != commit:
            raise ValueError("source commit differs from the pinned version")
        local_path = source["local_path"]
        source_file = (root / local_path).resolve()
        if not source_file.is_relative_to(root.resolve()):
            raise ValueError("source path leaves corpus root")
        content = source_file.read_bytes()
        if source.get("sha256") and hashlib.sha256(content).hexdigest() != source["sha256"]:
            raise ValueError(f"source hash differs from manifest: {local_path}")
        text = content.decode("utf-8")
        for line, target, alt in _references_in_markdown(text):
            asset_path = resolve_asset_path(source["document_path"], target)
            if asset_path is None:
                if urlsplit(target).scheme or urlsplit(target).netloc:
                    external_count += 1
                else:
                    unresolved_count += 1
                continue
            relative_count += 1
            key = (commit, asset_path)
            if key not in figures:
                figure_id = hashlib.sha256(f"{commit}:{asset_path}".encode()).hexdigest()[:16]
                figures[key] = {
                    "figure_id": figure_id,
                    "version": version,
                    "commit": commit,
                    "asset_path": asset_path,
                    "raw_url": (
                        f"https://raw.githubusercontent.com/apache/dolphinscheduler/"
                        f"{commit}/{quote(asset_path, safe='/-._')}"
                    ),
                    "references": [],
                    "validation": {"status": "unverified"},
                    "ocr": {"status": "not_run"},
                }
            figures[key]["references"].append({
                "document_key": source["document_key"],
                "language": source.get("language"),
                "local_path": local_path,
                "line": line,
                "alt_text": alt,
            })
    ordered = sorted(figures.values(), key=lambda row: (row["version"], row["asset_path"]))
    return {
        "schema_version": 1,
        "corpus_manifest_sha256": hashlib.sha256(manifest_bytes).hexdigest(),
        "source_count": manifest.get("source_count", len(manifest["sources"])),
        "current_version": manifest["current_version"],
        "relative_reference_count": relative_count,
        "external_reference_count": external_count,
        "unresolved_reference_count": unresolved_count,
        "unique_figure_count": len(ordered),
        "search_policy": "OCR text is an unreviewed candidate; alt text is not image content.",
        "figures": ordered,
    }


def _fetch_raw_image(url: str, max_bytes: int = MAX_IMAGE_BYTES) -> tuple[bytes, str] | None:
    request = Request(url, headers={"User-Agent": "enterprise-rag-figure-audit/1.0"})
    try:
        with urlopen(request, timeout=20) as response:
            length = response.headers.get("Content-Length")
            if length and int(length) > max_bytes:
                raise ImageTooLarge("declared image size exceeds audit cap")
            payload = response.read(max_bytes + 1)
            if len(payload) > max_bytes:
                raise ImageTooLarge("downloaded image exceeds audit cap")
            return payload, response.headers.get_content_type()
    except HTTPError as exc:
        if exc.code == 404:
            return None
        raise


def _image_type(payload: bytes) -> str | None:
    if payload.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if payload.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if payload.startswith((b"GIF87a", b"GIF89a")):
        return "image/gif"
    if payload.startswith(b"RIFF") and payload[8:12] == b"WEBP":
        return "image/webp"
    if payload.lstrip()[:100].startswith(b"<svg"):
        return "image/svg+xml"
    return None


def _decode_image(payload: bytes, media_type: str) -> tuple[str, int | None, int | None]:
    """Fully decode raster content when Pillow is installed locally."""
    if media_type == "image/svg+xml":
        return "not_checked", None, None
    try:
        from PIL import Image
    except ImportError:
        return "not_checked", None, None
    try:
        with Image.open(io.BytesIO(payload)) as image:
            width, height = image.size
            if width * height > 25_000_000:
                return "too_many_pixels", width, height
            image.load()
        return "verified", width, height
    except Exception:
        return "invalid", None, None


def _tesseract_path() -> str | None:
    path = shutil.which("tesseract")
    if path:
        return path
    if os.name == "nt":
        candidate = Path("C:/Program Files/Tesseract-OCR/tesseract.exe")
        if candidate.is_file():
            return str(candidate)
    return None


def run_tesseract_ocr(payload: bytes) -> tuple[str, float | None]:
    executable = _tesseract_path()
    if not executable:
        raise FileNotFoundError("tesseract is unavailable")
    result = subprocess.run(
        [executable, "stdin", "stdout", "-l", "chi_sim+eng", "tsv"],
        input=payload, capture_output=True, timeout=30, check=False,
    )
    if result.returncode:
        raise RuntimeError("tesseract returned a nonzero status")
    lines = result.stdout.decode("utf-8", errors="replace").splitlines()
    words, confidences = [], []
    for line in lines[1:]:
        cells = line.split("\t", 11)
        if len(cells) != 12 or not cells[11].strip():
            continue
        words.append(cells[11].strip())
        try:
            confidence = float(cells[10])
            if confidence >= 0:
                confidences.append(confidence)
        except ValueError:
            pass
    return " ".join(words), round(sum(confidences) / len(confidences), 2) if confidences else None


def verify_selected_images(
    inventory: dict,
    *,
    selectors: tuple[str, ...] = SELECTED_FIGURES,
    fetcher: Callable[[str, int], tuple[bytes, str] | None] = _fetch_raw_image,
    ocr_runner: Callable[[bytes], tuple[str, float | None]] | None = None,
    max_images: int = 8,
) -> dict:
    """Fetch a bounded sample; no image binaries or alt-derived OCR are retained."""
    count = 0
    for figure in inventory["figures"]:
        if figure["version"] != inventory["current_version"]:
            continue
        if not any(figure["asset_path"] == selector for selector in selectors):
            continue
        if count >= max_images:
            break
        count += 1
        try:
            fetched = fetcher(figure["raw_url"], MAX_IMAGE_BYTES)
            if fetched is None:
                figure["validation"] = {"status": "not_found"}
                continue
            payload, media_type = fetched
            sniffed = _image_type(payload)
            if not sniffed or sniffed != media_type:
                figure["validation"] = {"status": "invalid_image_content"}
                continue
            decode_status, width, height = _decode_image(payload, sniffed)
            if decode_status in {"invalid", "too_many_pixels"}:
                figure["validation"] = {
                    "status": "invalid_image_content", "decode_status": decode_status,
                }
                continue
            figure["validation"] = {
                "status": "verified" if decode_status == "verified" else "fetched_unchecked",
                "sha256": hashlib.sha256(payload).hexdigest(),
                "bytes": len(payload),
                "media_type": sniffed,
                "decode_status": decode_status,
                "width": width,
                "height": height,
                "checked_at": datetime.now(timezone.utc).isoformat(),
            }
            if decode_status != "verified":
                figure["ocr"] = {"status": "not_run"}
                continue
            if ocr_runner is None:
                figure["ocr"] = {"status": "tool_unavailable"}
                continue
            if sniffed == "image/svg+xml":
                figure["ocr"] = {"status": "unsupported_format", "engine": "tesseract"}
                continue
            try:
                text, confidence = ocr_runner(payload)
            except (OSError, RuntimeError, subprocess.TimeoutExpired):
                figure["ocr"] = {"status": "ocr_error", "engine": "tesseract"}
                continue
            text = text.strip()
            if text:
                figure["ocr"] = {
                    "status": "text_extracted",
                    "engine": "tesseract",
                    "quality": "unreviewed",
                    "index_review_status": "pending",
                    "mean_confidence": confidence,
                    "text": text,
                }
            else:
                figure["ocr"] = {"status": "no_text_detected", "engine": "tesseract"}
        except ImageTooLarge:
            figure["validation"] = {"status": "too_large"}
        except Exception as exc:  # Preserve partial audit results without leaking URLs/proxies.
            figure["validation"] = {"status": "fetch_error", "error_type": type(exc).__name__}
    inventory["verified_count"] = sum(
        row["validation"]["status"] == "verified" for row in inventory["figures"]
    )
    inventory["ocr_text_count"] = sum(
        row["ocr"]["status"] == "text_extracted" for row in inventory["figures"]
    )
    return inventory


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--fetch-selected", action="store_true")
    parser.add_argument("--max-images", type=int, default=6)
    args = parser.parse_args()
    if args.max_images < 0 or args.max_images > 20:
        parser.error("--max-images must be between 0 and 20")
    inventory = scan_inventory(args.root)
    if args.fetch_selected:
        runner = run_tesseract_ocr if _tesseract_path() else None
        verify_selected_images(inventory, ocr_runner=runner, max_images=args.max_images)
    output = args.output or args.root / "figure_evidence.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(inventory, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({
        "source_count": inventory["source_count"],
        "relative_references": inventory["relative_reference_count"],
        "unique_figures": inventory["unique_figure_count"],
        "verified": inventory.get("verified_count", 0),
        "ocr_text": inventory.get("ocr_text_count", 0),
        "output": str(output),
    }, ensure_ascii=False))


if __name__ == "__main__":
    main()
