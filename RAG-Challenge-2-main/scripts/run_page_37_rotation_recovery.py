"""Run bounded 90/270-degree OCR recovery for physical page 37 only."""

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
from src.ocr_processing import OcrConfig, PageOcrResult, _filesystem_path, sha256_file, write_json_atomic
from src.ocr_retention import HybridRetentionConfig, build_repeat_stats, reassemble_page
from src.ocr_rotation import OrientationStatus, RotationOcrProcessor


TARGET_DOCUMENT_ID = "tsg-08-2026"
TARGET_PAGE_NUMBER = 37


def _compact(text: str) -> str:
    return re.sub(r"\s+", "", text or "").casefold()


def _load_normal_pages(args: argparse.Namespace) -> list[PageOcrResult]:
    smoke = json.loads(
        (args.report_root / "ocr_smoke_validation.json").read_text(encoding="utf-8")
    )
    cache_root = _filesystem_path(
        args.cache_root
        / args.document_id
        / smoke["file_sha256"]
        / smoke["ocr_config_sha256"]
        / "pages"
    )
    pages = [
        PageOcrResult.model_validate_json(path.read_text(encoding="utf-8"))
        for path in sorted(cache_root.glob("page_*.json"))
    ]
    if [page.page_number for page in pages] != list(range(1, 55)):
        raise RuntimeError("Rotation recovery requires the complete 54-page normal OCR cache")
    if sum(page.ocr_used and bool(page.raw_blocks) for page in pages) != 53:
        raise RuntimeError("Rotation recovery requires raw blocks for all 53 OCR pages")
    return pages


def _source_pdf(args: argparse.Namespace) -> Path:
    manifest = load_corpus_manifest(
        args.corpus_root / "domain_corpus_manifest.json", verify_source_files=True
    )
    document = next(
        document
        for document in manifest.documents
        if document.document_id == args.document_id
    )
    return args.corpus_root / document.source_path


def _candidate_summary(
    candidate,
    selected_rotation,
    second_by_rotation,
    previous_by_rotation,
) -> dict:
    second = second_by_rotation[candidate.rotation_degrees]
    previous = previous_by_rotation.get(candidate.rotation_degrees, {})
    return {
        "rotation": candidate.rotation_degrees,
        "raw_block_count": len(candidate.raw_blocks),
        "retained_block_count": len(candidate.retained_blocks),
        "meaningful_char_count": candidate.meaningful_char_count,
        "chinese_character_ratio": candidate.chinese_character_ratio,
        "structured_text_count": candidate.structured_text_count,
        "garbled_ratio": candidate.garbled_ratio,
        "quality_score": candidate.quality_score,
        "rotation_recovered": candidate.rotation_recovered,
        "selected": candidate.rotation_degrees == selected_rotation,
        "cache_generation_run_cache_hit": previous.get(
            "cache_generation_run_cache_hit",
            previous.get("first_run_cache_hit", candidate.cache_hit),
        ),
        "validation_run_cache_hit": candidate.cache_hit,
        "second_run_cache_hit": second.cache_hit,
        "error": candidate.error,
    }


def run(args: argparse.Namespace) -> dict:
    report_path = args.report_root / "page_37_rotation_validation.json"
    previous_report = (
        json.loads(report_path.read_text(encoding="utf-8"))
        if report_path.is_file()
        else None
    )
    pages = _load_normal_pages(args)
    page_by_number = {page.page_number: page for page in pages}
    normal_page = page_by_number[args.page_number]
    retention_config = HybridRetentionConfig()
    repeats = build_repeat_stats(pages, retention_config)
    normal_assembled = reassemble_page(
        normal_page,
        total_pages=len(pages),
        repeat_stats=repeats,
        config=retention_config,
    )
    if normal_assembled.text.strip():
        raise RuntimeError("Refusing rotation: normal hybrid assembly is not empty")

    visual_review = json.loads(
        (args.report_root / "ocr_page_visual_review.json").read_text(encoding="utf-8")
    )
    page_review = next(
        row
        for row in visual_review["pages"]
        if row["page_number"] == args.page_number
    )
    if not page_review.get("source_has_meaningful_content"):
        raise RuntimeError("Page must have a confirmed non-empty source render")

    pdf_path = _source_pdf(args)
    normal_cache_path = _filesystem_path(
        args.cache_root
        / args.document_id
        / normal_page.file_sha256
        / normal_page.ocr_config_sha256
        / "pages"
        / f"page_{args.page_number:04d}.json"
    )
    normal_cache_hash_before = sha256_file(normal_cache_path)
    processor = RotationOcrProcessor(
        args.cache_root,
        ocr_config=OcrConfig(),
        retention_config=retention_config,
    )
    first = processor.recover_page(
        pdf_path,
        normal_page=normal_page,
        assembled_page=normal_assembled,
        orientation_status=OrientationStatus.OCR_ORIENTATION_SUSPECTED,
        context_pages=pages,
    )
    # A new processor proves that the second run is served by persisted cache,
    # not by an in-memory candidate or backend instance.
    second = RotationOcrProcessor(
        args.cache_root,
        ocr_config=OcrConfig(),
        retention_config=retention_config,
    ).recover_page(
        pdf_path,
        normal_page=normal_page,
        assembled_page=normal_assembled,
        orientation_status=OrientationStatus.OCR_ORIENTATION_SUSPECTED,
        context_pages=pages,
    )
    normal_cache_hash_after = sha256_file(normal_cache_path)
    second_by_rotation = {
        candidate.rotation_degrees: candidate for candidate in second.candidates
    }
    selected = first.selected_candidate
    selected_text = selected.assembled_text if selected else ""
    title = "压力管道基本信息汇总表"
    field_signals = {
        "使用单位": ["使用单位"],
        "管道名称": ["管道名称"],
        "使用登记编号": ["登记", "编号"],
        "途经区域": ["途经", "区域"],
        "设计压力": ["设计", "压力"],
        "工作压力": ["工作", "压力"],
        "公称直径": ["公称", "直径"],
        "公称厚度": ["公称", "厚度"],
        "管道材质": ["管道", "材质"],
        "管道级别": ["管道", "级别"],
        "介质": ["介质"],
    }
    compact_text = _compact(selected_text)
    found_fields = [
        field
        for field, signals in field_signals.items()
        if all(_compact(signal) in compact_text for signal in signals)
    ]
    previous_by_rotation = {
        row["rotation"]: row
        for row in (previous_report or {}).get("candidates", [])
    }
    cache_generation_invocations = (
        previous_report.get(
            "cache_generation_rotation_ocr_invocation_count",
            previous_report.get("first_run_rotation_ocr_invocation_count", 0),
        )
        if previous_report
        else first.ocr_invocation_count
    )
    selected_cache_path = (
        first.cache_paths[str(first.selected_rotation_degrees)]
        if first.selected_rotation_degrees is not None
        else None
    )
    checks = {
        "normal_hybrid_text_empty": not normal_assembled.text.strip(),
        "rendered_page_has_content": bool(first.rendered_page and first.rendered_page.has_content),
        "page_37_not_empty_after_recovery": bool(selected_text.strip()),
        "table_title_recovered": _compact(title) in compact_text,
        "multiple_table_fields_recovered": len(found_fields) >= 5,
        "chinese_text_quality_passed": bool(
            selected
            and selected.chinese_character_ratio
            >= processor.rotation_config.minimum_chinese_ratio
        ),
        "garbled_ratio_passed": bool(
            selected
            and selected.garbled_ratio
            <= processor.rotation_config.maximum_garbled_ratio
        ),
        "physical_page_number_preserved": bool(
            selected and selected.page_number == args.page_number
        ),
        "rotation_metadata_correct": bool(
            first.orientation_status == OrientationStatus.OCR_ROTATION_RECOVERED
            and first.selected_rotation_degrees in {90, 270}
        ),
        "second_run_all_candidates_cache_hit": bool(
            second.candidates and all(candidate.cache_hit for candidate in second.candidates)
        ),
        "second_run_easyocr_invocations_zero": second.ocr_invocation_count == 0,
        "other_53_pages_easyocr_invocations_zero": (
            first.other_page_ocr_invocation_count == 0
            and second.other_page_ocr_invocation_count == 0
        ),
        "normal_ocr_cache_unchanged": normal_cache_hash_before == normal_cache_hash_after,
    }
    passed = all(checks.values())
    report = {
        "schema_version": "1.0",
        "document_id": args.document_id,
        "page_number": args.page_number,
        "rotation_trigger": {
            "native_text_insufficient": normal_page.source_type == "OCR",
            "normal_ocr_executed": normal_page.ocr_status.value == "OCR_SUCCEEDED",
            "normal_raw_block_count": len(normal_page.raw_blocks),
            "normal_retained_block_count": len(normal_assembled.retained_block_indices),
            "normal_meaningful_char_count": 0,
            "normal_hybrid_text_empty": not normal_assembled.text.strip(),
            "orientation_status": "OCR_ORIENTATION_SUSPECTED",
            "source_render_manually_confirmed_nonempty": True,
        },
        "rotation_attempted": first.rotation_attempted,
        "rotation_degrees": first.rotation_degrees,
        "rotation_recovered": first.rotation_recovered,
        "orientation_status": first.orientation_status.value,
        "selected_rotation": first.selected_rotation_degrees,
        "rendered_page": first.rendered_page.model_dump() if first.rendered_page else None,
        "candidates": [
            _candidate_summary(
                candidate,
                first.selected_rotation_degrees,
                second_by_rotation,
                previous_by_rotation,
            )
            for candidate in first.candidates
        ],
        "validation_terms": {
            "required_title": title,
            "title_recovered": checks["table_title_recovered"],
            "candidate_field_signals": field_signals,
            "fields_recovered": found_fields,
            "field_matching_method": "all generic OCR tokens for a validation-only field must be present",
        },
        "selected_assembled_text": selected_text,
        "selected_candidate_cache_path": selected_cache_path,
        "normal_cache_preserved": checks["normal_ocr_cache_unchanged"],
        "cache_generation_rotation_ocr_invocation_count": cache_generation_invocations,
        "first_run_rotation_ocr_invocation_count": cache_generation_invocations,
        "current_validation_run_rotation_ocr_invocation_count": first.ocr_invocation_count,
        "second_run_rotation_ocr_invocation_count": second.ocr_invocation_count,
        "other_page_ocr_invocation_count": 0,
        "checks": checks,
        "passed": passed,
        "downstream_allowed": passed,
    }
    write_json_atomic(report_path, report)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    if not passed:
        raise SystemExit("Page 37 rotation recovery failed; downstream work remains blocked")
    return report


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    parser.add_argument("--corpus-root", type=Path, default=Path("data/domain_corpus"))
    parser.add_argument(
        "--cache-root", type=Path, default=Path("data/domain_corpus_v0_2/ocr_cache")
    )
    parser.add_argument(
        "--report-root", type=Path, default=Path("reports/domain_evaluation_v0_2")
    )
    parser.add_argument("--document-id", default=TARGET_DOCUMENT_ID)
    parser.add_argument("--page-number", type=int, default=TARGET_PAGE_NUMBER)
    return parser


if __name__ == "__main__":
    run(build_parser().parse_args())
