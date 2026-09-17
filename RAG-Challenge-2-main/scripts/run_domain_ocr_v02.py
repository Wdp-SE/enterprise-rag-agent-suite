"""Run the bounded OCR stages for Domain Corpus v0.2.

The command is deliberately separate from the default PDF parser.  It only
targets the manifest document explicitly selected by ``--document-id`` and
never enables global Docling OCR.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.evaluation.corpus import load_corpus_manifest
from src.ocr_processing import (
    DocumentOcrResult,
    OcrConfig,
    OcrPageStatus,
    PageOcrProcessor,
    normalize_text_for_detection,
    repeated_text_candidates,
    write_json_atomic,
)


DEFAULT_CORPUS_V01 = Path("data/domain_corpus")
DEFAULT_CORPUS_V02 = Path("data/domain_corpus_v0_2")
DEFAULT_REPORT_V02 = Path("reports/domain_evaluation_v0_2")
TARGET_DOCUMENT_ID = "tsg-08-2026"
SMOKE_PAGES = [1, 4, 14]


def _compact(text: str) -> str:
    return re.sub(r"\s+", "", normalize_text_for_detection(text)).casefold()


def _contains_term(text: str, term: str) -> bool:
    return _compact(term) in _compact(text)


def _obvious_corruption(text: str) -> dict:
    suspicious_tokens = ["\ufffd", "锟斤拷", "烫烫烫"]
    found = [token for token in suspicious_tokens if token in text]
    meaningful = max(1, sum(character.isalnum() for character in text))
    return {
        "detected": bool(found),
        "tokens": found,
        "replacement_character_ratio": round(text.count("\ufffd") / meaningful, 8),
    }


def _load_target(corpus_root: Path, document_id: str) -> tuple[Path, object]:
    manifest = load_corpus_manifest(
        corpus_root / "domain_corpus_manifest.json", verify_source_files=True
    )
    document = next(
        (item for item in manifest.documents if item.document_id == document_id), None
    )
    if document is None:
        raise ValueError(f"document_id is not present in the manifest: {document_id}")
    if document.parse_status != "OCR_REQUIRED":
        raise ValueError(
            f"Refusing OCR for {document_id}: manifest parse_status is "
            f"{document.parse_status}, not OCR_REQUIRED"
        )
    return corpus_root / document.source_path, document


def _page_validation(page, required_terms: list[str]) -> dict:
    found = [term for term in required_terms if _contains_term(page.text, term)]
    return {
        "page_number": page.page_number,
        "source_type": page.source_type,
        "char_count": page.meaningful_char_count,
        "ocr_used": page.ocr_used,
        "ocr_engine": page.ocr_engine,
        "ocr_status": page.ocr_status.value,
        "cache_hit": page.cache_hit,
        "required_terms": required_terms,
        "required_terms_found": found,
        "required_terms_missing": [term for term in required_terms if term not in found],
        "obvious_corruption": _obvious_corruption(page.text),
        "text_preview": page.text[:500],
    }


def _classify_calibration_block(block, repeated_lines: set[str]) -> str:
    compact = _compact(block.text)
    if _obvious_corruption(block.text)["detected"]:
        return "GARBLED"
    if compact in repeated_lines:
        return "HEADER_FOOTER"
    # No geometric/visual watermark removal is attempted. A short standalone
    # low-confidence token is left uncertain instead of being overclaimed.
    if len(compact) < 3:
        return "UNCERTAIN"
    return "VALID_TEXT"


def run_smoke(args: argparse.Namespace) -> dict:
    pdf_path, _ = _load_target(args.corpus_v01, args.document_id)
    processor = PageOcrProcessor(args.corpus_v02 / "ocr_cache", config=OcrConfig())
    first = processor.process_document(
        pdf_path, document_id=args.document_id, page_numbers=SMOKE_PAGES
    )
    second = processor.process_document(
        pdf_path, document_id=args.document_id, page_numbers=SMOKE_PAGES
    )
    terms = {
        1: ["特种设备使用管理规则", "TSG 08—2026", "2026年2月2日"],
        4: ["1.1 目的", "1.2", "1.3", "1.4"],
        14: ["使用登记", "30日"],
    }
    pages = [_page_validation(page, terms[page.page_number]) for page in first.pages]
    page_map = {page.page_number: page for page in first.pages}
    pass_checks = {
        "all_required_terms_found": all(not page["required_terms_missing"] for page in pages),
        "page_1_native_bypass": (
            page_map[1].ocr_status == OcrPageStatus.TEXT_NATIVE
            and not page_map[1].ocr_used
        ),
        "pages_4_14_ocr_succeeded": all(
            page_map[number].ocr_status == OcrPageStatus.OCR_SUCCEEDED
            for number in (4, 14)
        ),
        "physical_page_numbers_preserved": [page.page_number for page in first.pages]
        == SMOKE_PAGES,
        "no_obvious_corruption": all(
            not page["obvious_corruption"]["detected"] for page in pages
        ),
        "second_read_all_cache_hits": second.cache_hits == len(SMOKE_PAGES),
        "second_read_text_identical": [page.text for page in first.pages]
        == [page.text for page in second.pages],
    }
    repeated_lines = {_compact(line) for line in repeated_text_candidates(first.pages)}
    calibration_blocks = []
    for page in first.pages:
        if page.page_number not in {4, 14}:
            continue
        for block in page.raw_blocks:
            if 0.60 <= block.confidence < 0.65:
                calibration_blocks.append(
                    {
                        "page_number": page.page_number,
                        "text": block.text,
                        "confidence": block.confidence,
                        "classification": _classify_calibration_block(
                            block, repeated_lines
                        ),
                    }
                )
    classification_counts = {
        category: sum(
            block["classification"] == category for block in calibration_blocks
        )
        for category in (
            "VALID_TEXT",
            "HEADER_FOOTER",
            "WATERMARK",
            "GARBLED",
            "UNCERTAIN",
        )
    }
    payload = {
        "schema_version": "1.0",
        "document_id": args.document_id,
        "pdf_path": str(pdf_path),
        "file_sha256": first.file_sha256,
        "ocr_config": processor.config.model_dump(mode="json"),
        "ocr_config_sha256": processor.config.config_sha256,
        "first_pass": {
            "cache_hits": first.cache_hits,
            "elapsed_ms": first.elapsed_ms,
            "pages": pages,
        },
        "second_pass": {
            "cache_hits": second.cache_hits,
            "elapsed_ms": second.elapsed_ms,
            "ocr_invocation_avoided_by_cache_contract": second.cache_hits
            == len(SMOKE_PAGES),
        },
        "repeated_text_candidates": repeated_text_candidates(first.pages),
        "threshold_calibration": {
            "threshold_semantics": "OCR block retention threshold; not RAG, answer, or knowledge confidence",
            "previous_threshold": 0.65,
            "current_threshold": processor.config.ocr_block_confidence_threshold,
            "reason": "A valid '1.1 目的' block with confidence 0.621376 was filtered at 0.65.",
            "newly_retained_blocks": calibration_blocks,
            "classification_counts": classification_counts,
            "recovered_valid_blocks": classification_counts["VALID_TEXT"],
            "introduced_noise_blocks": classification_counts["GARBLED"]
            + classification_counts["WATERMARK"],
            "scope_note": "0.60 is validated only for the current TSG 08—2026 smoke sample; it is not claimed as a globally optimal threshold.",
        },
        "pass_checks": pass_checks,
        "passed": all(pass_checks.values()),
    }
    payload["threshold_calibration"]["smoke_passed"] = payload["passed"]
    output = args.report_v02 / "ocr_smoke_validation.json"
    write_json_atomic(output, payload)
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    if not payload["passed"]:
        raise SystemExit("OCR smoke validation failed; full OCR is blocked")
    return payload


def _find_pages_with_terms(result: DocumentOcrResult, terms: list[str]) -> dict[str, list[int]]:
    return {
        term: [page.page_number for page in result.pages if _contains_term(page.text, term)]
        for term in terms
    }


def run_full(args: argparse.Namespace) -> dict:
    smoke_path = args.report_v02 / "ocr_smoke_validation.json"
    if not smoke_path.is_file():
        raise RuntimeError("Run and pass the 3-page smoke before full OCR")
    smoke = json.loads(smoke_path.read_text(encoding="utf-8"))
    if not smoke.get("passed"):
        raise RuntimeError("The recorded 3-page OCR smoke did not pass")

    pdf_path, document = _load_target(args.corpus_v01, args.document_id)
    processor = PageOcrProcessor(args.corpus_v02 / "ocr_cache", config=OcrConfig())
    result = processor.process_document(
        pdf_path, document_id=args.document_id, retry_failed=args.retry_failed
    )
    required_terms = [
        "特种设备使用管理规则",
        "TSG 08—2026",
        "2026年2月2日",
        "2026年5月1日",
        "使用单位",
        "主体责任",
        "使用登记",
    ]
    term_pages = _find_pages_with_terms(result, required_terms)
    clause_pages = {
        clause: [page.page_number for page in result.pages if _contains_term(page.text, clause)]
        for clause in ("1.1", "1.2", "1.3", "1.4", "2.1")
    }
    suspicious_pages = [
        page.page_number
        for page in result.pages
        if _obvious_corruption(page.text)["detected"]
    ]
    repeated = repeated_text_candidates(result.pages)
    quality_checks = {
        "all_physical_pages_present": result.processed_page_numbers
        == list(range(1, document.pages_total + 1)),
        "no_failed_pages": not result.ocr_failed_pages,
        "page_1_native": result.pages[0].ocr_status == OcrPageStatus.TEXT_NATIVE,
        "identity_terms_present": all(term_pages[term] for term in required_terms),
        "five_clause_numbers_present": all(clause_pages.values()),
        "no_obvious_garbled_pages": not suspicious_pages,
    }
    payload = {
        "schema_version": "1.0",
        "document_id": result.document_id,
        "file_sha256": result.file_sha256,
        "ocr_config_sha256": processor.config.config_sha256,
        "ocr_status": result.ocr_status.value,
        "pages_total": result.pages_total,
        "native_pages": result.native_pages,
        "ocr_required_pages": result.ocr_required_pages,
        "ocr_success_pages": result.ocr_success_pages,
        "ocr_failed_pages": result.ocr_failed_pages,
        "cache_hits": result.cache_hits,
        "elapsed_ms": result.elapsed_ms,
        "term_pages": term_pages,
        "clause_pages": clause_pages,
        "missing_clause_number": [clause for clause, pages in clause_pages.items() if not pages],
        "suspected_garbled_pages": suspicious_pages,
        "header_footer_pollution": {
            "automatic_removal_performed": False,
            "repeated_text_candidates": repeated,
        },
        "watermark_pollution": {
            "visual_removal_performed": False,
            "note": "No visual/LLM cleanup was performed; raw OCR blocks remain cached for audit.",
        },
        "quality_checks": quality_checks,
        "passed": all(quality_checks.values()),
        "pages": [page.model_dump(mode="json") for page in result.pages],
    }
    write_json_atomic(args.report_v02 / "ocr_validation.json", payload)
    print(
        json.dumps(
            {key: value for key, value in payload.items() if key != "pages"},
            ensure_ascii=False,
            indent=2,
        )
    )
    if not payload["passed"]:
        raise SystemExit("Full OCR quality validation failed; corpus v0.2 build is blocked")
    return payload


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    parser.add_argument("stage", choices=("smoke", "full"))
    parser.add_argument("--corpus-v01", type=Path, default=DEFAULT_CORPUS_V01)
    parser.add_argument("--corpus-v02", type=Path, default=DEFAULT_CORPUS_V02)
    parser.add_argument("--report-v02", type=Path, default=DEFAULT_REPORT_V02)
    parser.add_argument("--document-id", default=TARGET_DOCUMENT_ID)
    parser.add_argument("--retry-failed", action="store_true")
    return parser


if __name__ == "__main__":
    parsed = build_parser().parse_args()
    if parsed.stage == "smoke":
        run_smoke(parsed)
    else:
        run_full(parsed)
