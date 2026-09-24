"""Focused checks for the isolated retrieval chunk candidates."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from evaluation.real_world_retrieval.final_selection.chunks import (
    build_chunks,
    json_byte_size,
    variant_metadata,
)


PUBLIC_CORPUS = Path(__file__).resolve().parents[3] / "RAG-Challenge-2-main" / "public_corpus"


def _toy_corpus(root: Path, body: str) -> Path:
    path = root / "sources" / "example.md"
    path.parent.mkdir(parents=True)
    raw = body.encode("utf-8")
    path.write_bytes(raw)
    source = {
        "version": "3.4.3", "language": "en", "document_key": "guide/example",
        "locale": "en-US", "source_type": "official_documentation",
        "source_url": "https://example.invalid/guide/example",
        "repository": "apache/dolphinscheduler", "document_path": "docs/example.md",
        "local_path": "sources/example.md", "sha256": hashlib.sha256(raw).hexdigest(),
    }
    (root / "corpus_manifest.json").write_text(
        json.dumps({"sources": [source]}), encoding="utf-8"
    )
    return root


def test_a_loads_the_exact_prebuilt_chunks_and_byte_size():
    existing_path = PUBLIC_CORPUS / "chunks.json"
    existing = json.loads(existing_path.read_text(encoding="utf-8"))

    chunks = build_chunks(PUBLIC_CORPUS, "A")

    assert chunks == existing
    assert len(chunks) == 659
    assert json_byte_size(chunks) == existing_path.stat().st_size
    assert variant_metadata("A")["max_chars"] == 1250


def test_b_is_a_deterministic_unoverlapped_650_character_split(tmp_path):
    body = "# Example Title\n\n## Details\n" + "a" * 700 + "b" * 200
    root = _toy_corpus(tmp_path, body)

    chunks = build_chunks(root, "B")

    assert [chunk["chunk_id"] for chunk in chunks] == [
        "3.4.3:en:guide/example:1", "3.4.3:en:guide/example:2"
    ]
    assert "".join(chunk["content"] for chunk in chunks) == "a" * 700 + "b" * 200
    assert all(len(chunk["content"]) <= 650 for chunk in chunks)
    assert all(chunk["heading"] == "Details" for chunk in chunks)
    assert all(chunk["document_key"] == "guide/example" for chunk in chunks)
    assert all(chunk["source_url"] == "https://example.invalid/guide/example" for chunk in chunks)
    assert all("search_text" not in chunk for chunk in chunks)
    assert build_chunks(root, "B") == chunks
    assert variant_metadata("B")["overlap_chars"] == 0


def test_c_overlaps_only_within_a_heading_and_keeps_title_out_of_content(tmp_path):
    first = "a" * 800 + "b" * 800
    body = "# Example Title\n\n## Details\n" + first + "\n\n## Next\n" + "c" * 810
    root = _toy_corpus(tmp_path, body)

    chunks = build_chunks(root, "C")
    details = [chunk for chunk in chunks if chunk["heading"] == "Details"]
    next_section = [chunk for chunk in chunks if chunk["heading"] == "Next"]

    assert len(details) == 2
    assert details[1]["content"][:100] == details[0]["content"][-100:]
    assert all(len(chunk["content"]) <= 900 for chunk in chunks)
    assert next_section[0]["content"].startswith("c")
    assert "Example Title" not in "".join(chunk["content"] for chunk in chunks)
    assert all(chunk["search_text"].startswith("Example Title\n") for chunk in chunks)
    assert all(chunk["heading"] in chunk["search_text"] for chunk in chunks)
    assert variant_metadata("C")["overlap_chars"] == 100
