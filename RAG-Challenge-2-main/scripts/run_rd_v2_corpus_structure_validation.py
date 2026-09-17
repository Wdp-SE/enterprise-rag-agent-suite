"""Run one canonical PDF through the local pre-embedding V2 structure path.

The command intentionally accepts exactly one document. All parser stdout and
stderr are discarded so source text or cleaning substitutions cannot leak to
terminal logs. No embedding, retrieval, reranking, generation, or online model
is invoked.
"""

from __future__ import annotations

import argparse
import contextlib
import io
import json
import logging
import os
import sys
from collections import Counter
from pathlib import Path


os.environ.setdefault("HF_HUB_OFFLINE", "1")
os.environ.setdefault("TRANSFORMERS_OFFLINE", "1")
os.environ.setdefault("DO_NOT_TRACK", "1")

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from docling.backend.pypdfium2_backend import PyPdfiumDocumentBackend
try:
    from pypdf import PdfReader
except ImportError:  # The project environment currently carries the legacy package name.
    from PyPDF2 import PdfReader

from src.parsed_reports_merging import PageTextPreparation
from src.pdf_parsing import PDFParser
from src.sectioning import SectionAwareTextSplitter


def write_json_atomic(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".partial")
    if temporary.exists():
        raise RuntimeError("Refusing to overwrite an existing partial JSON artifact")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    temporary.replace(path)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--corpus-root", type=Path, required=True)
    parser.add_argument("--document-id", required=True)
    parser.add_argument("--normalization-manifest", type=Path, required=True)
    args = parser.parse_args()

    if not args.document_id.startswith("rdv2-"):
        raise SystemExit("Invalid deterministic document ID")
    corpus_root = args.corpus_root.resolve()
    manifest = json.loads(args.normalization_manifest.read_text(encoding="utf-8"))
    matches = [
        item for item in manifest["documents"] if item["document_id"] == args.document_id
    ]
    if len(matches) != 1 or matches[0].get("status") != "success":
        raise SystemExit("Document is not a successful normalization manifest entry")
    metadata = matches[0]
    pdf_path = (corpus_root / metadata["normalized_relative_path"]).resolve()
    normalized_root = (corpus_root / "normalized").resolve()
    if normalized_root not in pdf_path.parents or not pdf_path.is_file():
        raise SystemExit("Canonical PDF is missing or outside normalized root")

    parsed_dir = normalized_root / "parsed" / args.document_id
    merged_dir = normalized_root / "merged" / args.document_id
    chunked_dir = normalized_root / "chunked" / args.document_id
    stats_path = corpus_root / "manifest" / f"{args.document_id}.structure_stats.json"
    if stats_path.exists():
        raise SystemExit("Refusing to overwrite existing structure validation stats")

    stage = "pdf_page_count"
    try:
        capture = io.StringIO()
        logging.disable(logging.CRITICAL)
        with contextlib.redirect_stdout(capture), contextlib.redirect_stderr(capture):
            canonical_pages = len(PdfReader(str(pdf_path)).pages)

            stage = "pdf_parser"
            pdf_parser = PDFParser(
                pdf_backend=PyPdfiumDocumentBackend,
                output_dir=parsed_dir,
                do_ocr=False,
            )
            pdf_parser.metadata_lookup = {
                args.document_id: {
                    "sha1_name": args.document_id,
                    "document_id": args.document_id,
                    "filename": metadata["source_file_name"],
                    "source": metadata["source_relative_path"],
                    "document_type": metadata["document_type"],
                }
            }
            pdf_parser.debug_data_path = None
            pdf_parser.parse_and_export(input_doc_paths=[pdf_path])

            parsed_path = parsed_dir / f"{args.document_id}.json"
            stage = "page_text_preparation"
            preparer = PageTextPreparation(use_serialized_tables=False)
            preparer.process_reports(
                reports_paths=[parsed_path], output_dir=merged_dir
            )

            merged_path = merged_dir / f"{args.document_id}.json"
            stage = "section_and_child_chunking"
            merged = json.loads(merged_path.read_text(encoding="utf-8"))
            splitter = SectionAwareTextSplitter(
                child_chunk_size=180, child_chunk_overlap=30
            )
            chunked = splitter._split_report(merged)
            chunked_dir.mkdir(parents=True, exist_ok=True)
            chunked_path = chunked_dir / f"{args.document_id}.json"
            write_json_atomic(chunked_path, chunked)

        # Do not retain captured output: PageTextPreparation may include snippets.
        capture.close()

        parsed = json.loads(
            (parsed_dir / f"{args.document_id}.json").read_text(encoding="utf-8")
        )
        pages = chunked["content"].get("pages", [])
        sections = chunked["content"].get("sections", [])
        chunks = chunked["content"].get("chunks", [])
        section_detection = chunked["content"].get("section_detection", {})

        parsed_page_numbers = [int(item["page"]) for item in parsed.get("content", [])]
        merged_page_numbers = [int(item["page"]) for item in pages]
        canonical_page_numbers = list(range(1, canonical_pages + 1))
        section_ids = {item.get("section_id") for item in sections}
        mapped_chunks = sum(
            bool(item.get("parent_id"))
            and item.get("parent_id") == item.get("section_id")
            and item.get("parent_id") in section_ids
            for item in chunks
        )
        fallback_chunks = sum(not item.get("parent_id") for item in chunks)
        chunk_pages_valid = all(
            int(item.get("page_number", item.get("page", 0)))
            in canonical_page_numbers
            for item in chunks
        )
        page_sequence_valid = (
            parsed_page_numbers == canonical_page_numbers
            and merged_page_numbers == canonical_page_numbers
        )
        parent_child_success = bool(chunks) and mapped_chunks == len(chunks)
        section_parse_success = (
            section_detection.get("mode") == "section_aware" and bool(sections)
        )

        stats = {
            "schema_version": 1,
            "document_id": args.document_id,
            "document_type": metadata["document_type"],
            "normalization_status": "success",
            "canonical_pdf_pages": canonical_pages,
            "parsed_pages": len(parsed_page_numbers),
            "merged_pages": len(merged_page_numbers),
            "empty_pages": sum(not str(item.get("text", "")).strip() for item in pages),
            "sections": len(sections),
            "section_detection_mode": section_detection.get("mode"),
            "heading_count": int(section_detection.get("heading_count", 0)),
            "heading_sources": dict(
                sorted(Counter(item.get("heading_source", "unknown") for item in sections).items())
            ),
            "child_chunks": len(chunks),
            "parent_mapping_success_count": mapped_chunks,
            "parent_child_success": parent_child_success,
            "fallback_chunk_count": fallback_chunks,
            "ocr_requested": False,
            "ocr_usage": False,
            "parsing_failures": 0,
            "section_parse_success": section_parse_success,
            "physical_page_sequence_valid": page_sequence_valid,
            "chunk_page_numbers_valid": chunk_pages_valid,
            "citation_page_mapping_valid": page_sequence_valid and chunk_pages_valid,
            "online_models_called": False,
            "embedding_or_retrieval_run": False,
            "chunk_parameters": {"child_chunk_size": 180, "child_chunk_overlap": 30},
        }
        write_json_atomic(stats_path, stats)
        print(
            json.dumps(
                {
                    "document_id": args.document_id,
                    "pages": canonical_pages,
                    "sections": len(sections),
                    "child_chunks": len(chunks),
                    "fallback_chunks": fallback_chunks,
                    "citation_page_mapping_valid": stats["citation_page_mapping_valid"],
                },
                ensure_ascii=False,
            )
        )
    except Exception as exc:
        logging.disable(logging.NOTSET)
        failure = {
            "schema_version": 1,
            "document_id": args.document_id,
            "normalization_status": "success",
            "validation_status": "failed",
            "failure_stage": stage,
            "failure_type": type(exc).__name__,
            "failure_message_redacted": True,
            "online_models_called": False,
            "embedding_or_retrieval_run": False,
        }
        if not stats_path.exists():
            write_json_atomic(stats_path, failure)
        print(json.dumps(failure, ensure_ascii=False))
        raise SystemExit(2) from None
    finally:
        logging.disable(logging.NOTSET)


if __name__ == "__main__":
    main()
