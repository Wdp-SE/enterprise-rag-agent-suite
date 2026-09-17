"""Build the one approved native-text historical retrieval asset.

The target is selected by document id from the frozen corpus manifest. The
script refuses to overwrite either prepared text artifacts or a FAISS index,
so a successful online embedding build cannot be repeated accidentally.
"""

from __future__ import annotations

import argparse
import copy
import json
import sys
from datetime import datetime
from io import BytesIO
from pathlib import Path
from zoneinfo import ZoneInfo

import faiss
import pypdfium2 as pdfium
from docling.datamodel.base_models import ConversionStatus, DocumentStream

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.evaluation.corpus import load_corpus_manifest
from src.ingestion import VectorDBIngestor
from src.ocr_processing import sha256_file, write_json_atomic
from src.pdf_parsing import JsonReportProcessor, PDFParser
from src.parsed_reports_merging import PageTextPreparation
from src.text_splitter import TextSplitter
from src.vector_utils import faiss_index_has_unit_norm_vectors


EMBEDDING_PROVIDER = "dashscope"
EMBEDDING_MODEL = "text-embedding-v1"
CHUNK_SIZE = 300
CHUNK_OVERLAP = 50
METADATA_SCHEMA_VERSION = "generic-document-v1-compatible"


def _target_metainfo(document) -> dict:
    return {
        "sha1_name": document.document_id,
        "document_id": document.document_id,
        "title": document.title,
        "document_type": document.document_type,
        "source": document.source_filename,
        "source_url": document.source_url,
        "category": "special_equipment_use_management",
        "tags": ["safety_technical_specification", "use_management"],
        "organization": document.organization,
        "document_number": document.document_number,
        "publish_date": document.publish_date,
        "effective_date": document.effective_date,
        "version_family": document.version_family,
        "version": document.version,
        "status": document.status,
        "source_level": document.source_level,
        "ocr_status": "NOT_REQUIRED",
        "pages_amount": document.pages_total,
    }


def _verify_native_text(source: Path, expected_pages: int) -> dict:
    pdf = pdfium.PdfDocument(str(source))
    lengths = []
    for page_number in range(len(pdf)):
        page = pdf[page_number]
        text_page = page.get_textpage()
        lengths.append(len((text_page.get_text_bounded() or "").strip()))
        text_page.close()
        page.close()
    result = {
        "pages": len(pdf),
        "pages_with_native_text": sum(length > 0 for length in lengths),
        "native_text_characters": sum(lengths),
        "minimum_nonempty_page_characters": min(
            (length for length in lengths if length > 0), default=0
        ),
    }
    pdf.close()
    if result["pages"] != expected_pages:
        raise RuntimeError("PDF page count does not match the frozen manifest")
    if result["pages_with_native_text"] != expected_pages:
        raise RuntimeError("Historical source is not fully native-text parseable; OCR is forbidden")
    return result


def _paths(root: Path, document_id: str) -> dict[str, Path]:
    return {
        "parsed": root / "debug_data" / "01_parsed_reports" / f"{document_id}.json",
        "merged": root / "debug_data" / "02_merged_reports" / f"{document_id}.json",
        "markdown": root / "debug_data" / "03_reports_markdown" / f"{document_id}.md",
        "chunked": root / "databases" / "chunked_reports" / f"{document_id}.json",
        "embedding_batch": root / "embedding_batches" / "new" / f"{document_id}.json",
        "index": root / "databases" / "vector_dbs" / f"{document_id}.faiss",
        "manifest": root / "historical_asset_manifest.json",
    }


def prepare(args: argparse.Namespace) -> None:
    manifest = load_corpus_manifest(args.manifest, verify_source_files=True)
    document = next(
        item for item in manifest.documents if item.document_id == args.document_id
    )
    if document.status != "SUPERSEDED":
        raise RuntimeError("Historical asset target must remain SUPERSEDED")
    if document.ocr_status != "NOT_REQUIRED" or document.parse_status != "READY":
        raise RuntimeError("Historical asset is not approved for native-text parsing")
    if (
        document.document_id not in manifest.version_test_document_ids
        or document.document_id in manifest.default_index_document_ids
    ):
        raise RuntimeError("Target must be a non-default manifest version-test document")

    paths = _paths(args.output_root, args.document_id)
    prepared_outputs = [
        paths["parsed"],
        paths["merged"],
        paths["markdown"],
        paths["chunked"],
        paths["embedding_batch"],
    ]
    existing = [str(path) for path in prepared_outputs if path.exists()]
    if existing:
        raise RuntimeError(f"Refusing to repeat historical parse/chunk: {existing}")

    source = (args.manifest.parent / document.source_path).resolve()
    if sha256_file(source) != document.sha256:
        raise RuntimeError("Historical source hash does not match the frozen manifest")
    native_text = _verify_native_text(source, document.pages_total)

    raw_debug_dir = args.output_root / "debug_data" / "01_parsed_reports_debug"
    raw_debug_files = list(raw_debug_dir.glob("*.json"))
    recovered_from_completed_parse = False
    if raw_debug_files:
        if len(raw_debug_files) != 1:
            raise RuntimeError("Expected exactly one recoverable raw Docling export")
        # A prior invocation completed Docling conversion but failed during
        # local report-shape handling. Reuse that export; never parse twice.
        normalized_data = json.loads(raw_debug_files[0].read_text(encoding="utf-8"))
        recovered_from_completed_parse = True
    else:
        parser = PDFParser(output_dir=None, do_ocr=False)
        # BytesIO avoids passing the non-ASCII workspace path through the native
        # docling-parse library while preserving the exact PDF bytes and filename.
        document_stream = DocumentStream(
            name=source.name, stream=BytesIO(source.read_bytes())
        )
        results = list(parser.convert_documents([document_stream]))
        if len(results) != 1 or results[0].status != ConversionStatus.SUCCESS:
            raise RuntimeError("Native-text Docling parse failed")
        normalized_data = parser._normalize_page_sequence(
            results[0].document.export_to_dict()
        )
    if normalized_data.get("tables"):
        raise RuntimeError("Recovery path cannot silently discard parsed tables")
    processor = JsonReportProcessor(
        metadata_lookup={source.stem: _target_metainfo(document)},
    )
    parsed = {
        "metainfo": processor.assemble_metainfo(normalized_data),
        "content": processor.assemble_content(normalized_data),
        "tables": [],
        "pictures": processor.assemble_pictures(normalized_data),
    }
    merged = {
        "metainfo": parsed["metainfo"],
        "content": PageTextPreparation().process_report(parsed),
    }
    pages = merged["content"].get("pages", [])
    if len(pages) != document.pages_total or any(not page["text"].strip() for page in pages):
        raise RuntimeError("Parsed page output is incomplete; OCR fallback is forbidden")

    chunked = TextSplitter()._split_report(copy.deepcopy(merged))
    chunks = chunked["content"].get("chunks", [])
    if not chunks:
        raise RuntimeError("Historical document produced no chunks")
    if any(chunk.get("document_id") != args.document_id for chunk in chunks):
        raise RuntimeError("Historical chunk document_id propagation failed")

    write_json_atomic(paths["parsed"], parsed)
    write_json_atomic(paths["merged"], merged)
    for key in ("chunked", "embedding_batch"):
        write_json_atomic(paths[key], chunked)
    paths["markdown"].parent.mkdir(parents=True, exist_ok=True)
    paths["markdown"].write_text(
        "\n\n".join(
            f"<!-- physical_page:{page['page']} -->\n\n{page['text']}" for page in pages
        ),
        encoding="utf-8",
    )
    write_json_atomic(
        paths["manifest"],
        {
            "schema_version": "1.0",
            "document_id": args.document_id,
            "source_sha256": document.sha256,
            "status": document.status,
            "version_family": document.version_family,
            "version": document.version,
            "ocr_performed": False,
            "native_text_verification": native_text,
            "recovered_from_completed_parse": recovered_from_completed_parse,
            "parser": "PDFParser/DoclingParseV2DocumentBackend",
            "chunk_size": CHUNK_SIZE,
            "chunk_overlap": CHUNK_OVERLAP,
            "metadata_schema_version": METADATA_SCHEMA_VERSION,
            "pages": len(pages),
            "chunks": len(chunks),
            "vectors": 0,
            "embedding_provider": EMBEDDING_PROVIDER,
            "embedding_model": EMBEDDING_MODEL,
            "embedding_normalized": True,
            "state": "PREPARED_NOT_EMBEDDED",
        },
    )
    print(json.dumps({"pages": len(pages), "chunks": len(chunks)}, indent=2))


def embed(args: argparse.Namespace) -> None:
    paths = _paths(args.output_root, args.document_id)
    if paths["index"].exists():
        raise RuntimeError("Refusing to repeat historical embedding: index already exists")
    if not paths["embedding_batch"].is_file() or not paths["manifest"].is_file():
        raise RuntimeError("Prepared historical chunk asset is missing")
    batch_files = list(paths["embedding_batch"].parent.glob("*.json"))
    if [path.name for path in batch_files] != [paths["embedding_batch"].name]:
        raise RuntimeError("Embedding staging directory must contain only the approved document")

    VectorDBIngestor(
        embedding_provider=EMBEDDING_PROVIDER,
        embedding_model=EMBEDDING_MODEL,
    ).process_reports(paths["embedding_batch"].parent, paths["index"].parent)

    document = json.loads(paths["chunked"].read_text(encoding="utf-8"))
    index = faiss.read_index(str(paths["index"]))
    chunks = len(document["content"].get("chunks", []))
    if index.ntotal != chunks:
        raise RuntimeError("Historical FAISS vector count does not match chunks")
    if not faiss_index_has_unit_norm_vectors(index):
        raise RuntimeError("Historical FAISS vectors are not unit normalized")

    artifact = json.loads(paths["manifest"].read_text(encoding="utf-8"))
    artifact.update(
        {
            "vectors": index.ntotal,
            "vector_dimension": index.d,
            "faiss_type": type(index).__name__,
            "index_sha256": sha256_file(paths["index"]),
            "state": "READY",
            "completed_at": datetime.now(ZoneInfo("Asia/Shanghai")).isoformat(
                timespec="seconds"
            ),
        }
    )
    write_json_atomic(paths["manifest"], artifact)
    print(
        json.dumps(
            {
                "document_id": args.document_id,
                "chunks": chunks,
                "vectors": index.ntotal,
                "dimension": index.d,
                "unit_norm": True,
            },
            indent=2,
        )
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=("prepare", "embed"))
    parser.add_argument("--document-id", required=True)
    parser.add_argument(
        "--manifest",
        type=Path,
        default=Path("data/domain_corpus_v0_2/domain_corpus_manifest.json"),
    )
    parser.add_argument(
        "--output-root",
        type=Path,
        default=Path("data/domain_corpus_v0_2/historical_retrieval_assets"),
    )
    return parser


if __name__ == "__main__":
    parsed_args = build_parser().parse_args()
    if parsed_args.action == "prepare":
        prepare(parsed_args)
    else:
        embed(parsed_args)
