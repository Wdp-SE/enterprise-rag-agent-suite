"""Build Domain Corpus v0.2 after the recorded OCR quality gate passes."""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import shutil
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import faiss

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.artifact_reuse import ArtifactBuildConfig, evaluate_artifact_reuse
from src.evaluation.corpus import CorpusManifest, load_corpus_manifest
from src.ocr_processing import PageOcrResult, sha256_file, write_json_atomic
from src.text_splitter import TextSplitter
from src.vector_utils import faiss_index_has_unit_norm_vectors


REUSED_DOCUMENT_IDS = (
    "cn-law-special-equipment-safety-2013",
    "samr-order-50-2022",
    "samr-order-57-2022",
    "samr-order-74-2023",
)
TARGET_DOCUMENT_ID = "tsg-08-2026"
EMBEDDING_PROVIDER = "dashscope"
EMBEDDING_MODEL = "text-embedding-v1"
CHUNK_SIZE = 300
CHUNK_OVERLAP = 50
METADATA_SCHEMA_VERSION = "generic-document-v1-compatible"


def _json_load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _json_write(path: Path, payload: object) -> None:
    write_json_atomic(path, payload)


def _copy_verified(source: Path, destination: Path) -> str:
    if not source.is_file():
        raise FileNotFoundError(source)
    destination.parent.mkdir(parents=True, exist_ok=True)
    source_hash = sha256_file(source)
    if destination.exists():
        if not destination.is_file() or sha256_file(destination) != source_hash:
            raise RuntimeError(f"Refusing to overwrite mismatched artifact: {destination}")
        return "ALREADY_PRESENT_HASH_VERIFIED"
    shutil.copy2(source, destination)
    if sha256_file(destination) != source_hash:
        raise RuntimeError(f"Copied artifact failed hash verification: {destination}")
    return "COPIED_AND_HASH_VERIFIED"


def _semantic_chunk_projection(chunks: list[dict]) -> list[dict]:
    fields = ("page", "text", "length_tokens", "id", "chunk_id", "document_id", "type")
    return [{field: chunk.get(field) for field in fields} for chunk in chunks]


def _chunks_match_current_splitter(document: dict) -> bool:
    expected = _semantic_chunk_projection(document["content"].get("chunks", []))
    input_document = copy.deepcopy(document)
    input_document["content"]["chunks"] = None
    rebuilt = TextSplitter()._split_report(input_document)
    actual = _semantic_chunk_projection(rebuilt["content"].get("chunks", []))
    return actual == expected


def _baseline_embedding_provenance(report_root: Path) -> dict:
    result = _json_load(report_root / "retrieval_results.json")
    return {
        "provider": result.get("embedding_provider"),
        "model": result.get("embedding_model"),
        "source": str(report_root / "retrieval_results.json"),
    }


def _reuse_document(
    document_id: str,
    *,
    manifest_document,
    corpus_v01: Path,
    corpus_v02: Path,
    baseline_embedding: dict,
) -> dict:
    chunk_source = corpus_v01 / "databases" / "chunked_reports" / f"{document_id}.json"
    index_source = corpus_v01 / "databases" / "vector_dbs" / f"{document_id}.faiss"
    document = _json_load(chunk_source)
    actual_source_hash = sha256_file(corpus_v01 / manifest_document.source_path)
    index = faiss.read_index(str(index_source))
    unit_norm = faiss_index_has_unit_norm_vectors(index)
    chunk_config_match = _chunks_match_current_splitter(document)
    metadata_compatible = all(
        document.get("metainfo", {}).get(field)
        for field in ("document_id", "title", "source")
    ) and all(
        chunk.get("document_id") == document_id
        and chunk.get("page") is not None
        and chunk.get("chunk_id")
        for chunk in document["content"].get("chunks", [])
    )
    index_count_match = index.ntotal == len(document["content"].get("chunks", []))
    existing = ArtifactBuildConfig(
        source_sha256=actual_source_hash,
        embedding_provider=str(baseline_embedding["provider"]),
        embedding_model=str(baseline_embedding["model"]),
        embedding_normalized=unit_norm,
        chunk_size=CHUNK_SIZE if chunk_config_match else -1,
        chunk_overlap=CHUNK_OVERLAP if chunk_config_match else -1,
        metadata_schema_version=(
            METADATA_SCHEMA_VERSION if metadata_compatible else "INCOMPATIBLE"
        ),
    )
    target = ArtifactBuildConfig(
        source_sha256=manifest_document.sha256,
        embedding_provider=EMBEDDING_PROVIDER,
        embedding_model=EMBEDDING_MODEL,
        embedding_normalized=True,
        chunk_size=CHUNK_SIZE,
        chunk_overlap=CHUNK_OVERLAP,
        metadata_schema_version=METADATA_SCHEMA_VERSION,
    )
    decision = evaluate_artifact_reuse(existing, target)
    if not index_count_match:
        decision = decision.model_copy(
            update={
                "reusable": False,
                "reason": "CONFIG_MISMATCH",
                "mismatches": [*decision.mismatches, "index_vector_count"],
            }
        )
    if not decision.reusable:
        raise RuntimeError(
            f"Artifact reuse conditions failed for {document_id}: {decision.mismatches}"
        )

    copied = {}
    artifact_pairs = [
        (
            chunk_source,
            corpus_v02 / "databases" / "chunked_reports" / chunk_source.name,
        ),
        (
            index_source,
            corpus_v02 / "databases" / "vector_dbs" / index_source.name,
        ),
    ]
    for directory in (
        "01_parsed_reports_debug",
        "01_parsed_reports",
        "02_merged_reports",
        "03_reports_markdown",
    ):
        candidates = list((corpus_v01 / "debug_data" / directory).glob(f"{document_id}.*"))
        for source in candidates:
            artifact_pairs.append((source, corpus_v02 / "debug_data" / directory / source.name))
    for source, destination in artifact_pairs:
        copied[str(destination)] = _copy_verified(source, destination)

    return {
        "document_id": document_id,
        "decision": decision.model_dump(mode="json"),
        "verification": {
            "source_sha256_matches_manifest": actual_source_hash
            == manifest_document.sha256,
            "embedding_provenance": baseline_embedding,
            "faiss_vectors_are_unit_norm": unit_norm,
            "faiss_vector_count_matches_chunks": index_count_match,
            "current_300_50_split_reproduces_existing_semantic_chunks": chunk_config_match,
            "metadata_schema_compatible": bool(metadata_compatible),
        },
        "artifacts": copied,
    }


def _target_metainfo(manifest_document) -> dict:
    return {
        "sha1_name": manifest_document.document_id,
        "document_id": manifest_document.document_id,
        "title": manifest_document.title,
        "document_type": manifest_document.document_type,
        "source": manifest_document.source_filename,
        "source_url": manifest_document.source_url,
        "category": "special_equipment_use_management",
        "tags": ["safety_technical_specification", "use_management"],
        "organization": manifest_document.organization,
        "document_number": manifest_document.document_number,
        "publish_date": manifest_document.publish_date,
        "effective_date": manifest_document.effective_date,
        "version": manifest_document.version,
        "status": manifest_document.status,
        "source_level": manifest_document.source_level,
        "ocr_status": "OCR_SUCCEEDED",
        "pages_amount": manifest_document.pages_total,
    }


def _build_target_document(validation: dict, manifest_document, corpus_v02: Path) -> dict:
    pages = []
    for payload in validation["pages"]:
        page = PageOcrResult.model_validate(payload)
        pages.append(
            {
                "page": page.page_number,
                "page_number": page.page_number,
                "document_id": page.document_id,
                "text": page.text,
                "source_type": page.source_type,
                "ocr_used": page.ocr_used,
                "ocr_engine": page.ocr_engine,
                "ocr_status": page.ocr_status.value,
                "file_sha256": page.file_sha256,
                "ocr_config_sha256": page.ocr_config_sha256,
            }
        )
    parsed = {"metainfo": _target_metainfo(manifest_document), "content": {"pages": pages, "chunks": None}}
    chunked = TextSplitter()._split_report(copy.deepcopy(parsed))
    document_id = manifest_document.document_id
    _json_write(corpus_v02 / "debug_data" / "01_parsed_reports" / f"{document_id}.json", parsed)
    _json_write(corpus_v02 / "debug_data" / "02_merged_reports" / f"{document_id}.json", parsed)
    _json_write(corpus_v02 / "databases" / "chunked_reports" / f"{document_id}.json", chunked)
    # This staging directory contains only the new/changed document, making it
    # impossible for the approved incremental command to re-embed reused docs.
    _json_write(corpus_v02 / "embedding_batches" / "new" / f"{document_id}.json", chunked)
    markdown = "\n\n".join(
        f"<!-- physical_page:{page['page']} -->\n\n{page['text']}" for page in pages
    )
    markdown_path = corpus_v02 / "debug_data" / "03_reports_markdown" / f"{document_id}.md"
    markdown_path.parent.mkdir(parents=True, exist_ok=True)
    markdown_path.write_text(markdown, encoding="utf-8")
    return {
        "document_id": document_id,
        "pages": len(pages),
        "chunks": len(chunked["content"]["chunks"]),
        "embedding_action": "REBUILD_NEW_DOCUMENT_ONLY",
        "index_created": False,
    }


def _build_v02_manifest(v01: CorpusManifest) -> CorpusManifest:
    payload = v01.model_dump(mode="json", exclude_none=True)
    payload["corpus_version"] = "0.2"
    payload["frozen_at"] = datetime.now(ZoneInfo("Asia/Shanghai")).isoformat(timespec="seconds")
    payload["default_index_document_ids"] = [
        *v01.default_index_document_ids,
        TARGET_DOCUMENT_ID,
    ]
    payload["target_current_document_ids_blocked_by_ocr"] = [
        document_id
        for document_id in v01.target_current_document_ids_blocked_by_ocr
        if document_id != TARGET_DOCUMENT_ID
    ]
    for document in payload["documents"]:
        if document["document_id"] == TARGET_DOCUMENT_ID:
            document.update(
                {
                    "parse_status": "READY",
                    "ocr_status": "OCR_SUCCEEDED",
                    "pages_with_text": document["pages_total"],
                    "empty_pages": 0,
                    "included_in_default_index": True,
                }
            )
        elif document["parse_status"] == "OCR_REQUIRED":
            document["ocr_status"] = "OCR_REQUIRED"
        else:
            document["ocr_status"] = "NOT_REQUIRED"
    return CorpusManifest.model_validate(payload)


def build(args: argparse.Namespace) -> None:
    validation_path = args.report_v02 / "ocr_validation.json"
    if not validation_path.is_file():
        raise RuntimeError("Full OCR validation is missing")
    validation = _json_load(validation_path)
    if not validation.get("passed"):
        raise RuntimeError("Full OCR validation did not pass; v0.2 build is blocked")

    manifest_v01 = load_corpus_manifest(
        args.corpus_v01 / "domain_corpus_manifest.json", verify_source_files=True
    )
    manifest_by_id = {document.document_id: document for document in manifest_v01.documents}
    target_document = manifest_by_id[TARGET_DOCUMENT_ID]
    if validation["file_sha256"] != target_document.sha256:
        raise RuntimeError("OCR validation source hash does not match the frozen manifest")

    source_copy_results = {}
    for document in manifest_v01.documents:
        source = args.corpus_v01 / document.source_path
        destination = args.corpus_v02 / document.source_path
        source_copy_results[document.document_id] = _copy_verified(source, destination)

    baseline_embedding = _baseline_embedding_provenance(args.report_v01)
    reused = [
        _reuse_document(
            document_id,
            manifest_document=manifest_by_id[document_id],
            corpus_v01=args.corpus_v01,
            corpus_v02=args.corpus_v02,
            baseline_embedding=baseline_embedding,
        )
        for document_id in REUSED_DOCUMENT_IDS
    ]
    target_build = _build_target_document(validation, target_document, args.corpus_v02)
    manifest_v02 = _build_v02_manifest(manifest_v01)
    _json_write(
        args.corpus_v02 / "domain_corpus_manifest.json",
        manifest_v02.model_dump(mode="json", exclude_none=True),
    )
    _json_write(
        args.corpus_v02 / "artifact_build_config.json",
        {
            "embedding_provider": EMBEDDING_PROVIDER,
            "embedding_model": EMBEDDING_MODEL,
            "embedding_normalized": True,
            "chunk_size": CHUNK_SIZE,
            "chunk_overlap": CHUNK_OVERLAP,
            "metadata_schema_version": METADATA_SCHEMA_VERSION,
        },
    )
    report = {
        "schema_version": "1.0",
        "source_corpus_version": "0.1",
        "target_corpus_version": "0.2",
        "source_pdf_copy_results": source_copy_results,
        "reused_documents": reused,
        "rebuilt_documents": [target_build],
        "summary": {
            "reused_document_count": len(reused),
            "rebuilt_document_count": 1,
            "reused_embedding_count": sum(
                _json_load(
                    args.corpus_v02 / "databases" / "chunked_reports" / f"{document_id}.json"
                )["content"]["chunks"].__len__()
                for document_id in REUSED_DOCUMENT_IDS
            ),
            "new_embedding_required_count": target_build["chunks"],
        },
    }
    _json_write(args.report_v02 / "artifact_reuse_report.json", report)
    print(json.dumps(report["summary"], ensure_ascii=False, indent=2))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    parser.add_argument("--corpus-v01", type=Path, default=Path("data/domain_corpus"))
    parser.add_argument("--corpus-v02", type=Path, default=Path("data/domain_corpus_v0_2"))
    parser.add_argument("--report-v01", type=Path, default=Path("reports/domain_evaluation_v0_1"))
    parser.add_argument("--report-v02", type=Path, default=Path("reports/domain_evaluation_v0_2"))
    return parser


if __name__ == "__main__":
    build(build_parser().parse_args())
