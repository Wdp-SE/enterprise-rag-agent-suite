"""Build isolated chunk candidates from the hash-pinned public source corpus.

This module only returns rows in memory. It never rewrites the official corpus,
its prebuilt index, or the deployed retrieval policy.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
from pathlib import Path


_HEADING_RE = re.compile(r"^(#{1,6})\s+(.+?)\s*$")
_VARIANTS = {
    "A": {"max_chars": 1250, "overlap_chars": 0, "title_context": False,
          "description": "exact prebuilt public chunks"},
    "B": {"max_chars": 650, "overlap_chars": 0, "title_context": False,
          "description": "finer heading and paragraph chunks"},
    "C": {"max_chars": 900, "overlap_chars": 100, "title_context": True,
          "description": "heading chunks with same-section overlap and title search context"},
}


def variant_metadata(variant: str) -> dict:
    """Return the parameters that identify one frozen candidate."""
    if variant not in _VARIANTS:
        raise ValueError(f"unknown chunk variant: {variant}")
    return {"variant": variant, **_VARIANTS[variant]}


def json_byte_size(chunks: list[dict]) -> int:
    """Size of the UTF-8 chunks.json representation used by the public index."""
    payload = json.dumps(chunks, ensure_ascii=False, separators=(",", ":")) + os.linesep
    return len(payload.encode("utf-8"))


def _sections(text: str) -> tuple[str, list[tuple[str, str]]]:
    """Keep content within its nearest Markdown heading, as baseline A does."""
    title = ""
    heading = ""
    body: list[str] = []
    sections: list[tuple[str, str]] = []

    def flush() -> None:
        raw = "\n".join(body).strip()
        if raw:
            sections.append((heading, raw))
        body.clear()

    for line in text.splitlines():
        found = _HEADING_RE.match(line)
        if found:
            flush()
            heading = found.group(2).strip()
            if found.group(1) == "#" and not title:
                title = heading
        else:
            body.append(line)
    flush()
    return title, sections


def _pack_paragraphs(raw: str, limit: int) -> list[str]:
    """Pack whole paragraphs where possible; split only paragraphs over limit."""
    pieces: list[str] = []
    current = ""
    for paragraph in re.split(r"\n\s*\n", raw):
        paragraph = paragraph.strip()
        if not paragraph:
            continue
        if current and len(current) + 2 + len(paragraph) > limit:
            pieces.append(current)
            current = ""
        if len(paragraph) > limit:
            for offset in range(0, len(paragraph), limit):
                segment = paragraph[offset:offset + limit].strip()
                if segment:
                    pieces.append(segment)
        else:
            current += ("\n\n" if current else "") + paragraph
    if current:
        pieces.append(current)
    return pieces


def _source_chunks(source: dict, text: str, variant: str) -> list[dict]:
    title, sections = _sections(text)
    chunks: list[dict] = []
    key = f"{source['version']}:{source['language']}:{source['document_key']}"
    for heading, raw in sections:
        if variant == "B":
            contents = _pack_paragraphs(raw, 650)
        else:
            base = _pack_paragraphs(raw, 800)
            contents = [part if index == 0 else base[index - 1][-100:] + part
                        for index, part in enumerate(base)]
        for content in contents:
            number = len(chunks) + 1
            row = {
                "chunk_id": f"{key}:{number}", "document_id": key,
                "document_key": source["document_key"], "version": source["version"],
                "locale": source["locale"], "language": source["language"],
                "source_type": source["source_type"], "source_url": source["source_url"],
                "heading": heading, "content": content,
                "repository": source["repository"], "document_path": source["document_path"],
            }
            if variant == "C":
                context = [title or source["document_key"]]
                if heading and heading != context[0]:
                    context.append(heading)
                context.append(content)
                row["search_text"] = "\n".join(context)
            chunks.append(row)
    return chunks


def build_chunks(corpus_root: Path, variant: str) -> list[dict]:
    """Return one candidate's chunks without writing any corpus or index files."""
    variant_metadata(variant)
    corpus_root = Path(corpus_root)
    if variant == "A":
        return json.loads((corpus_root / "chunks.json").read_text(encoding="utf-8"))

    manifest = json.loads((corpus_root / "corpus_manifest.json").read_text(encoding="utf-8"))
    chunks: list[dict] = []
    for source in manifest["sources"]:
        raw = (corpus_root / source["local_path"]).read_bytes()
        if hashlib.sha256(raw).hexdigest() != source["sha256"]:
            raise ValueError(f"source changed: {source['local_path']}")
        chunks.extend(_source_chunks(source, raw.decode("utf-8"), variant))
    return chunks
