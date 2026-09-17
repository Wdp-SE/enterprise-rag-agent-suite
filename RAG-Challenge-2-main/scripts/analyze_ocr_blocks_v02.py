"""Offline confidence and geometry audit for cached OCR blocks.

This module never imports or constructs an OCR backend and never renders PDF
pages.  It reads only completed page JSON caches.
"""

from __future__ import annotations

import argparse
import json
import math
import re
import statistics
import sys
import unicodedata
from collections import Counter, defaultdict
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.ocr_processing import PageOcrResult, _filesystem_path, normalize_text_for_detection, write_json_atomic


CONFIDENCE_BINS = (
    (">=0.90", 0.90, math.inf),
    ("0.80-0.90", 0.80, 0.90),
    ("0.70-0.80", 0.70, 0.80),
    ("0.60-0.70", 0.60, 0.70),
    ("0.575-0.60", 0.575, 0.60),
    ("0.55-0.575", 0.55, 0.575),
    ("0.525-0.55", 0.525, 0.55),
    ("0.50-0.525", 0.50, 0.525),
    ("0.45-0.50", 0.45, 0.50),
    ("<0.45", -math.inf, 0.45),
)
CLAUSE_PATTERN = re.compile(r"^(?:\d+(?:\.\d+){1,3}|第[一二三四五六七八九十百零〇两\d]+条)$")
CHAPTER_PATTERN = re.compile(r"^第[一二三四五六七八九十百零〇两\d]+[章节]$")
DATE_PATTERN = re.compile(r"\d{4}年\d{1,2}月\d{1,2}日")


def _normalize_block_text(text: str) -> str:
    return re.sub(r"\s+", "", normalize_text_for_detection(text)).casefold()


def _character_stats(text: str) -> dict:
    normalized = normalize_text_for_detection(text)
    non_space = [character for character in normalized if not character.isspace()]
    chinese = [character for character in non_space if "\u4e00" <= character <= "\u9fff"]
    alnum = [character for character in non_space if character.isalnum()]
    unusual = [
        character
        for character in non_space
        if not character.isalnum()
        and not unicodedata.category(character).startswith("P")
        and character not in "()（）[]【】+-=.%‰/：:"
    ]
    denominator = max(1, len(non_space))
    return {
        "non_space_chars": len(non_space),
        "chinese_chars": len(chinese),
        "alnum_chars": len(alnum),
        "chinese_ratio": round(len(chinese) / denominator, 6),
        "unusual_ratio": round(len(unusual) / denominator, 6),
    }


def _relative_geometry(page: PageOcrResult, bbox: list[list[float]]) -> dict:
    scale = 3.0
    page_width = (page.page_width or 1.0) * scale
    page_height = (page.page_height or 1.0) * scale
    xs = [point[0] for point in bbox]
    ys = [point[1] for point in bbox]
    top_edge_angle = math.degrees(math.atan2(bbox[1][1] - bbox[0][1], bbox[1][0] - bbox[0][0]))
    return {
        "left": round(min(xs) / page_width, 6),
        "top": round(min(ys) / page_height, 6),
        "right": round(max(xs) / page_width, 6),
        "bottom": round(max(ys) / page_height, 6),
        "width": round((max(xs) - min(xs)) / page_width, 6),
        "height": round((max(ys) - min(ys)) / page_height, 6),
        "top_edge_angle_degrees": round(top_edge_angle, 3),
    }


def _stable_margin_repeat(record: dict, repetition: dict) -> bool:
    if repetition["page_count"] < 3 or not repetition["position_stable"]:
        return False
    top = record["relative_bbox"]["top"]
    bottom = record["relative_bbox"]["bottom"]
    return top <= 0.12 or bottom >= 0.88


def _calibration_class(record: dict, repetition: dict) -> str:
    text = record["normalized_text"]
    stats = record["character_stats"]
    angle = abs(record["relative_bbox"]["top_edge_angle_degrees"])
    if _stable_margin_repeat(record, repetition):
        return "HEADER_FOOTER"
    if repetition["page_count"] >= 3 and angle >= 15:
        return "WATERMARK"
    if DATE_PATTERN.search(text):
        return "DATE_OR_EFFECTIVE_TERM"
    if CLAUSE_PATTERN.fullmatch(text):
        return "CLAUSE_NUMBER"
    if CHAPTER_PATTERN.fullmatch(text):
        return "HEADING"
    if stats["unusual_ratio"] > 0.35 or (
        stats["chinese_chars"] == 0 and stats["alnum_chars"] < 3
    ):
        return "GARBLED"
    if stats["chinese_chars"] >= 4 and stats["chinese_ratio"] >= 0.45:
        return "BODY_TEXT"
    return "UNKNOWN"


def _load_pages(args: argparse.Namespace) -> list[PageOcrResult]:
    smoke = json.loads((args.report_root / "ocr_smoke_validation.json").read_text(encoding="utf-8"))
    cache_dir = _filesystem_path(
        args.cache_root
        / args.document_id
        / smoke["file_sha256"]
        / smoke["ocr_config_sha256"]
        / "pages"
    )
    paths = sorted(cache_dir.glob("page_*.json"))
    pages = [PageOcrResult.model_validate_json(path.read_text(encoding="utf-8")) for path in paths]
    actual_numbers = [page.page_number for page in pages]
    expected_numbers = list(range(1, args.expected_pages + 1))
    if actual_numbers != expected_numbers:
        raise RuntimeError(
            f"Raw OCR cache is incomplete: expected {expected_numbers}, got {actual_numbers}"
        )
    ocr_pages = [page for page in pages if page.ocr_used]
    if len(ocr_pages) != args.expected_ocr_pages or any(not page.raw_blocks for page in ocr_pages):
        raise RuntimeError("Not all expected OCR pages contain raw_blocks")
    return pages


def audit(args: argparse.Namespace) -> None:
    pages = _load_pages(args)
    records = []
    pages_by_text = defaultdict(set)
    positions_by_text = defaultdict(list)
    for page in pages:
        for block_index, block in enumerate(page.raw_blocks):
            normalized = _normalize_block_text(block.text)
            geometry = _relative_geometry(page, block.bbox)
            record = {
                "page_number": page.page_number,
                "block_index": block_index,
                "text": block.text,
                "confidence": block.confidence,
                "bbox": block.bbox,
                "relative_bbox": geometry,
                "current_retained": block.confidence >= 0.60,
                "normalized_text": normalized,
                "character_stats": _character_stats(block.text),
            }
            records.append(record)
            if normalized:
                pages_by_text[normalized].add(page.page_number)
                positions_by_text[normalized].append(geometry["top"])

    repetitions = {}
    for text, page_numbers in pages_by_text.items():
        positions = positions_by_text[text]
        repetitions[text] = {
            "page_count": len(page_numbers),
            "page_numbers": sorted(page_numbers),
            "mean_top": round(statistics.mean(positions), 6),
            "top_stddev": round(statistics.pstdev(positions), 6),
            "position_stable": len(positions) >= 3 and statistics.pstdev(positions) <= 0.03,
        }

    low_records = []
    for record in records:
        if not 0.50 <= record["confidence"] < 0.60:
            continue
        repetition = repetitions.get(
            record["normalized_text"],
            {"page_count": 0, "page_numbers": [], "mean_top": None, "top_stddev": None, "position_stable": False},
        )
        enriched = {
            **record,
            "repeat_page_count": repetition["page_count"],
            "repeat_page_numbers": repetition["page_numbers"],
            "repeat_position_stable": repetition["position_stable"],
        }
        enriched["calibration_class"] = _calibration_class(enriched, repetition)
        low_records.append(enriched)

    distribution = {}
    for label, lower, upper in CONFIDENCE_BINS:
        distribution[label] = sum(lower <= record["confidence"] < upper for record in records)
    observed_counts = Counter(record["calibration_class"] for record in low_records)
    class_counts = {
        category: observed_counts[category]
        for category in (
            "BODY_TEXT",
            "CLAUSE_NUMBER",
            "HEADING",
            "DATE_OR_EFFECTIVE_TERM",
            "HEADER_FOOTER",
            "WATERMARK",
            "GARBLED",
            "UNKNOWN",
        )
    }
    repeated_candidates = [
        {"normalized_text": text, **details}
        for text, details in repetitions.items()
        if details["page_count"] >= 3
    ]
    repeated_candidates.sort(key=lambda item: (-item["page_count"], item["normalized_text"]))
    required_examples = {}
    for label, expected_text in {
        "clause": "1.1目的",
        "effective_date": "本规则自2026年5月1日起施行,",
        "continuation": "以本规则为准。",
    }.items():
        matches = [record for record in records if record["normalized_text"] == _normalize_block_text(expected_text)]
        required_examples[label] = matches

    low_path = args.report_root / "ocr_low_confidence_blocks.json"
    write_json_atomic(
        low_path,
        {
            "schema_version": "1.0",
            "scope": "0.50 <= EasyOCR block confidence < 0.60",
            "classification_boundary": "Deterministic calibration labels only; not a general OCR semantic classifier.",
            "blocks": low_records,
        },
    )
    payload = {
        "schema_version": "1.0",
        "document_id": args.document_id,
        "cache_complete": True,
        "physical_pages": len(pages),
        "native_pages": sum(not page.ocr_used for page in pages),
        "ocr_pages_with_raw_blocks": sum(page.ocr_used and bool(page.raw_blocks) for page in pages),
        "total_blocks": len(records),
        "confidence_distribution": distribution,
        "low_confidence_0_50_0_60": {
            "total": len(low_records),
            "classification_counts": class_counts,
        },
        "required_false_negative_examples": required_examples,
        "bbox_observations": {
            "coordinate_normalization": "bbox image pixels divided by physical PDF page size times render_scale=3",
            "simple_margin_repeat_rule_available": any(
                record["calibration_class"] == "HEADER_FOOTER" for record in low_records
            ),
            "rotated_repeated_watermark_candidates": sum(
                record["calibration_class"] == "WATERMARK" for record in low_records
            ),
        },
        "repeated_text_candidates": repeated_candidates,
        "ocr_invocation_count": 0,
    }
    write_json_atomic(args.report_root / "ocr_block_confidence_audit.json", payload)
    print(json.dumps({key: value for key, value in payload.items() if key != "repeated_text_candidates"}, ensure_ascii=False, indent=2))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    parser.add_argument("--cache-root", type=Path, default=Path("data/domain_corpus_v0_2/ocr_cache"))
    parser.add_argument("--report-root", type=Path, default=Path("reports/domain_evaluation_v0_2"))
    parser.add_argument("--document-id", default="tsg-08-2026")
    parser.add_argument("--expected-pages", type=int, default=54)
    parser.add_argument("--expected-ocr-pages", type=int, default=53)
    return parser


if __name__ == "__main__":
    audit(build_parser().parse_args())
