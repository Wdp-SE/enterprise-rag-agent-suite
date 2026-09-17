"""Deterministic offline retention for cached Chinese OCR blocks.

The rule is intentionally small and domain-lightweight.  It combines block
confidence, common structured-document patterns, Chinese-text density, and
stable repeated page-margin geometry.  It does not perform OCR or semantic
inference.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
import statistics
import unicodedata
from collections import defaultdict
from typing import Dict, Iterable, List, Literal

from pydantic import BaseModel, ConfigDict, Field

from src.ocr_processing import PageOcrResult, RawOcrBlock, normalize_text_for_detection, sort_ocr_blocks


CLAUSE_PATTERN = re.compile(r"^(?:\d+(?:\.\d+){1,3}|第[一二三四五六七八九十百零〇两\d]+条)$")
CHAPTER_PATTERN = re.compile(r"^第[一二三四五六七八九十百零〇两\d]+[章节]$")
DATE_PATTERN = re.compile(r"\d{4}年\d{1,2}月\d{1,2}日")
PAGE_NUMBER_PATTERN = re.compile(r"^[-—]?\d{1,3}[-—]?[。.]?$")


class HybridRetentionConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    assembly_schema_version: str = "1"
    rule_version: str = "hybrid-zh-structured-v1"
    high_confidence_keep: float = Field(default=0.60, ge=0, le=1)
    low_confidence_floor: float = Field(default=0.50, ge=0, le=1)
    min_body_chinese_chars: int = Field(default=6, ge=1)
    min_body_chinese_ratio: float = Field(default=0.45, ge=0, le=1)
    repeated_page_ratio: float = Field(default=0.20, ge=0, le=1)
    repeated_position_stddev: float = Field(default=0.03, ge=0)
    page_margin_ratio: float = Field(default=0.12, ge=0, le=0.5)
    rotated_text_angle_degrees: float = Field(default=15.0, ge=0, le=90)
    render_scale: float = Field(default=3.0, gt=0)

    @property
    def assembly_config_sha256(self) -> str:
        encoded = json.dumps(
            self.model_dump(mode="json"),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        return hashlib.sha256(encoded).hexdigest()


class BlockRepeatStats(BaseModel):
    model_config = ConfigDict(extra="forbid")

    page_count: int
    page_numbers: List[int]
    mean_top: float
    top_stddev: float
    position_stable: bool


class RetentionDecision(BaseModel):
    model_config = ConfigDict(extra="forbid")

    keep: bool
    reason: Literal[
        "REPEATED_MARGIN_HEADER_FOOTER",
        "REPEATED_ROTATED_WATERMARK",
        "NUMERIC_PAGE_FOOTER",
        "HIGH_CONFIDENCE",
        "BELOW_CONFIDENCE_FLOOR",
        "UNUSUAL_CHARACTER_NOISE",
        "STRUCTURED_DATE",
        "STRUCTURED_CLAUSE",
        "STRUCTURED_CHAPTER",
        "CHINESE_BODY_TEXT",
        "NO_POSITIVE_SIGNAL",
    ]


class ReassembledPage(BaseModel):
    model_config = ConfigDict(extra="forbid")

    document_id: str
    page_number: int
    text: str
    source_type: str
    ocr_used: bool
    ocr_engine: str | None
    ocr_status: str
    file_sha256: str
    source_ocr_config_sha256: str
    assembly_config_sha256: str
    retained_block_indices: List[int]
    dropped_block_indices: List[int]
    decisions: List[RetentionDecision]


def normalize_block_text(text: str) -> str:
    return re.sub(r"\s+", "", normalize_text_for_detection(text)).casefold()


def find_empty_reassembled_pages(pages: Iterable[ReassembledPage]) -> List[int]:
    """Return physical page numbers whose retained text is empty.

    An empty assembled page is not silently accepted as a successful document
    page.  The caller must inspect the source page and either resolve the loss or
    keep the downstream corpus build blocked.
    """

    return sorted(page.page_number for page in pages if not page.text.strip())


def _relative_geometry(
    page: PageOcrResult,
    block: RawOcrBlock,
    render_scale: float,
) -> dict:
    width = max((page.page_width or 1.0) * render_scale, 1.0)
    height = max((page.page_height or 1.0) * render_scale, 1.0)
    xs = [point[0] for point in block.bbox]
    ys = [point[1] for point in block.bbox]
    angle = math.degrees(
        math.atan2(
            block.bbox[1][1] - block.bbox[0][1],
            block.bbox[1][0] - block.bbox[0][0],
        )
    )
    return {
        "top": min(ys) / height,
        "bottom": max(ys) / height,
        "angle": angle,
    }


def build_repeat_stats(
    pages: Iterable[PageOcrResult],
    config: HybridRetentionConfig,
) -> Dict[str, BlockRepeatStats]:
    page_list = list(pages)
    page_numbers_by_text: dict[str, set[int]] = defaultdict(set)
    top_positions_by_text: dict[str, list[float]] = defaultdict(list)
    for page in page_list:
        for block in page.raw_blocks:
            normalized = normalize_block_text(block.text)
            if not normalized:
                continue
            page_numbers_by_text[normalized].add(page.page_number)
            geometry = _relative_geometry(page, block, config.render_scale)
            top_positions_by_text[normalized].append(geometry["top"])
    result = {}
    for text, numbers in page_numbers_by_text.items():
        positions = top_positions_by_text[text]
        stddev = statistics.pstdev(positions)
        result[text] = BlockRepeatStats(
            page_count=len(numbers),
            page_numbers=sorted(numbers),
            mean_top=round(statistics.mean(positions), 6),
            top_stddev=round(stddev, 6),
            position_stable=len(positions) >= 3 and stddev <= config.repeated_position_stddev,
        )
    return result


def _character_signals(text: str) -> tuple[int, float, float]:
    normalized = normalize_text_for_detection(text)
    chars = [character for character in normalized if not character.isspace()]
    chinese = [character for character in chars if "\u4e00" <= character <= "\u9fff"]
    unusual = [
        character
        for character in chars
        if not character.isalnum()
        and not unicodedata.category(character).startswith("P")
        and character not in "()（）[]【】+-=.%‰/：:"
    ]
    denominator = max(1, len(chars))
    return len(chinese), len(chinese) / denominator, len(unusual) / denominator


def decide_block_retention(
    *,
    page: PageOcrResult,
    block: RawOcrBlock,
    total_pages: int,
    repeat_stats: Dict[str, BlockRepeatStats],
    config: HybridRetentionConfig,
) -> RetentionDecision:
    normalized = normalize_block_text(block.text)
    geometry = _relative_geometry(page, block, config.render_scale)
    repeated = repeat_stats.get(normalized)
    repeated_enough = bool(
        repeated
        and repeated.page_count >= max(3, math.ceil(total_pages * config.repeated_page_ratio))
        and repeated.position_stable
    )
    in_margin = (
        geometry["top"] <= config.page_margin_ratio
        or geometry["bottom"] >= 1 - config.page_margin_ratio
    )
    if repeated_enough and in_margin:
        return RetentionDecision(keep=False, reason="REPEATED_MARGIN_HEADER_FOOTER")
    if repeated_enough and abs(geometry["angle"]) >= config.rotated_text_angle_degrees:
        return RetentionDecision(keep=False, reason="REPEATED_ROTATED_WATERMARK")
    if geometry["bottom"] >= 1 - config.page_margin_ratio and PAGE_NUMBER_PATTERN.fullmatch(normalized):
        return RetentionDecision(keep=False, reason="NUMERIC_PAGE_FOOTER")
    if block.confidence >= config.high_confidence_keep:
        return RetentionDecision(keep=True, reason="HIGH_CONFIDENCE")
    if block.confidence < config.low_confidence_floor:
        return RetentionDecision(keep=False, reason="BELOW_CONFIDENCE_FLOOR")

    chinese_count, chinese_ratio, unusual_ratio = _character_signals(block.text)
    if unusual_ratio > 0.35:
        return RetentionDecision(keep=False, reason="UNUSUAL_CHARACTER_NOISE")
    if DATE_PATTERN.search(normalized):
        return RetentionDecision(keep=True, reason="STRUCTURED_DATE")
    if CLAUSE_PATTERN.fullmatch(normalized):
        return RetentionDecision(keep=True, reason="STRUCTURED_CLAUSE")
    if CHAPTER_PATTERN.fullmatch(normalized):
        return RetentionDecision(keep=True, reason="STRUCTURED_CHAPTER")
    if (
        chinese_count >= config.min_body_chinese_chars
        and chinese_ratio >= config.min_body_chinese_ratio
    ):
        return RetentionDecision(keep=True, reason="CHINESE_BODY_TEXT")
    return RetentionDecision(keep=False, reason="NO_POSITIVE_SIGNAL")


def reassemble_page(
    page: PageOcrResult,
    *,
    total_pages: int,
    repeat_stats: Dict[str, BlockRepeatStats],
    config: HybridRetentionConfig,
) -> ReassembledPage:
    if not page.ocr_used:
        return ReassembledPage(
            document_id=page.document_id,
            page_number=page.page_number,
            text=page.text,
            source_type=page.source_type,
            ocr_used=page.ocr_used,
            ocr_engine=page.ocr_engine,
            ocr_status=page.ocr_status.value,
            file_sha256=page.file_sha256,
            source_ocr_config_sha256=page.ocr_config_sha256,
            assembly_config_sha256=config.assembly_config_sha256,
            retained_block_indices=[],
            dropped_block_indices=[],
            decisions=[],
        )

    indexed_blocks = list(enumerate(page.raw_blocks))
    decisions_by_index = {
        index: decide_block_retention(
            page=page,
            block=block,
            total_pages=total_pages,
            repeat_stats=repeat_stats,
            config=config,
        )
        for index, block in indexed_blocks
    }
    retained_indices = [index for index, _ in indexed_blocks if decisions_by_index[index].keep]
    retained_blocks = [page.raw_blocks[index] for index in retained_indices]
    ordered_blocks = sort_ocr_blocks(retained_blocks)
    text = "\n".join(block.text.strip() for block in ordered_blocks if block.text.strip())
    return ReassembledPage(
        document_id=page.document_id,
        page_number=page.page_number,
        text=text,
        source_type=page.source_type,
        ocr_used=page.ocr_used,
        ocr_engine=page.ocr_engine,
        ocr_status=page.ocr_status.value,
        file_sha256=page.file_sha256,
        source_ocr_config_sha256=page.ocr_config_sha256,
        assembly_config_sha256=config.assembly_config_sha256,
        retained_block_indices=retained_indices,
        dropped_block_indices=[index for index, _ in indexed_blocks if index not in retained_indices],
        decisions=[decisions_by_index[index] for index, _ in indexed_blocks],
    )
