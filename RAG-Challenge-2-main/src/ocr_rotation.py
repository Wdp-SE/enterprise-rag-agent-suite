"""Exceptional page-level rotation recovery for cached OCR workflows.

The module is deliberately outside the default PDF parser and normal OCR path.
It only runs for an explicitly suspected page whose normal OCR has already run
but whose hybrid-retained text is empty or nearly empty.  Candidate selection
uses generic, deterministic text-quality signals and never domain phrases.
"""

from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Callable, Dict, List, Literal, Optional, Sequence, Tuple

import numpy as np
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from src.ocr_processing import (
    EasyOcrBackend,
    OcrBackend,
    OcrCacheError,
    OcrConfig,
    OcrPageStatus,
    PageOcrResult,
    PageSource,
    PdfiumPageSource,
    RawOcrBlock,
    SHA256_PATTERN,
    _filesystem_path,
    meaningful_char_count,
    normalize_text_for_detection,
    sha256_file,
    sort_ocr_blocks,
    write_json_atomic,
)
from src.ocr_retention import (
    CHAPTER_PATTERN,
    CLAUSE_PATTERN,
    DATE_PATTERN,
    BlockRepeatStats,
    HybridRetentionConfig,
    ReassembledPage,
    RetentionDecision,
    build_repeat_stats,
    decide_block_retention,
)


RotationDegree = Literal[90, 270]


class OrientationStatus(str, Enum):
    OCR_ORIENTATION_NORMAL = "OCR_ORIENTATION_NORMAL"
    OCR_ORIENTATION_SUSPECTED = "OCR_ORIENTATION_SUSPECTED"
    OCR_ROTATION_NOT_TRIGGERED = "OCR_ROTATION_NOT_TRIGGERED"
    OCR_ROTATION_RECOVERED = "OCR_ROTATION_RECOVERED"
    OCR_ROTATION_FAILED = "OCR_ROTATION_FAILED"


class RotationRecoveryConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: str = "1"
    candidate_degrees: Tuple[RotationDegree, ...] = (90, 270)
    trigger_max_meaningful_chars: int = Field(default=5, ge=0)
    minimum_recovered_chars: int = Field(default=20, ge=1)
    minimum_retained_blocks: int = Field(default=3, ge=1)
    minimum_chinese_ratio: float = Field(default=0.20, ge=0, le=1)
    maximum_garbled_ratio: float = Field(default=0.85, ge=0, le=1)
    minimum_improvement_chars: int = Field(default=15, ge=1)
    image_minimum_stddev: float = Field(default=1.0, ge=0)
    image_minimum_foreground_ratio: float = Field(default=0.0005, ge=0, le=1)
    image_background_delta: float = Field(default=12.0, gt=0)
    tie_break_preferred_rotation: RotationDegree = 90

    @model_validator(mode="after")
    def validate_candidates(self):
        if self.candidate_degrees != (90, 270):
            raise ValueError("The first rotation recovery version only supports 90 and 270")
        if self.tie_break_preferred_rotation not in self.candidate_degrees:
            raise ValueError("tie-break rotation must be one of candidate_degrees")
        return self

    @property
    def config_sha256(self) -> str:
        encoded = json.dumps(
            self.model_dump(mode="json"),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        return hashlib.sha256(encoded).hexdigest()


class RenderedPageEvidence(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    has_content: bool
    grayscale_stddev: float = Field(ge=0)
    foreground_ratio: float = Field(ge=0, le=1)


class RotationCandidateResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    document_id: str
    page_number: int = Field(ge=1)
    rotation_attempted: bool = True
    rotation_degrees: RotationDegree
    rotation_recovered: bool
    orientation_status: OrientationStatus
    file_sha256: str
    ocr_config_sha256: str
    rotation_config_sha256: str
    retention_config_sha256: str
    ocr_engine: str
    raw_blocks: List[RawOcrBlock]
    retained_blocks: List[RawOcrBlock]
    retained_block_indices: List[int]
    dropped_block_indices: List[int]
    retention_decisions: List[RetentionDecision]
    assembled_text: str
    meaningful_char_count: int = Field(ge=0)
    chinese_character_ratio: float = Field(ge=0, le=1)
    structured_text_count: int = Field(ge=0)
    garbled_ratio: float = Field(ge=0, le=1)
    quality_score: float
    cache_hit: bool = False
    error: Optional[str] = None

    @field_validator(
        "file_sha256",
        "ocr_config_sha256",
        "rotation_config_sha256",
        "retention_config_sha256",
    )
    @classmethod
    def validate_sha256(cls, value: str) -> str:
        normalized = value.strip().lower()
        if not SHA256_PATTERN.fullmatch(normalized):
            raise ValueError("expected lowercase SHA-256")
        return normalized

    @model_validator(mode="after")
    def validate_state(self):
        expected = (
            OrientationStatus.OCR_ROTATION_RECOVERED
            if self.rotation_recovered
            else OrientationStatus.OCR_ROTATION_FAILED
        )
        if self.orientation_status != expected:
            raise ValueError("rotation_recovered and orientation_status disagree")
        if self.rotation_recovered and not self.assembled_text.strip():
            raise ValueError("a recovered rotation requires assembled text")
        return self


class RotationRecoveryResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    document_id: str
    page_number: int = Field(ge=1)
    rotation_attempted: bool
    rotation_degrees: List[RotationDegree]
    rotation_recovered: bool
    orientation_status: OrientationStatus
    normal_meaningful_char_count: int = Field(ge=0)
    rendered_page: Optional[RenderedPageEvidence]
    candidates: List[RotationCandidateResult]
    selected_rotation_degrees: Optional[RotationDegree]
    selected_candidate: Optional[RotationCandidateResult]
    cache_paths: Dict[str, str]
    ocr_invocation_count: int = Field(ge=0)
    other_page_ocr_invocation_count: int = Field(default=0, ge=0)
    normal_cache_preserved: bool = True
    error: Optional[str] = None


@dataclass(frozen=True)
class _RotationBlockPage:
    page_number: int
    raw_blocks: List[RawOcrBlock]
    page_width: float
    page_height: float


def rendered_page_evidence(image, config: RotationRecoveryConfig) -> RenderedPageEvidence:
    grayscale = np.asarray(image.convert("L"), dtype=np.float32)
    if grayscale.size == 0:
        return RenderedPageEvidence(
            has_content=False, grayscale_stddev=0.0, foreground_ratio=0.0
        )
    border = np.concatenate(
        [grayscale[0, :], grayscale[-1, :], grayscale[:, 0], grayscale[:, -1]]
    )
    background = float(np.median(border))
    stddev = float(np.std(grayscale))
    foreground_ratio = float(
        np.mean(np.abs(grayscale - background) >= config.image_background_delta)
    )
    return RenderedPageEvidence(
        has_content=(
            stddev >= config.image_minimum_stddev
            and foreground_ratio >= config.image_minimum_foreground_ratio
        ),
        grayscale_stddev=round(stddev, 6),
        foreground_ratio=round(foreground_ratio, 8),
    )


def rotation_preconditions_met(
    normal_page: PageOcrResult,
    assembled_page: ReassembledPage,
    orientation_status: OrientationStatus,
    config: RotationRecoveryConfig,
) -> bool:
    return bool(
        orientation_status == OrientationStatus.OCR_ORIENTATION_SUSPECTED
        and normal_page.page_number == assembled_page.page_number
        and normal_page.ocr_used
        and normal_page.source_type == "OCR"
        and normal_page.ocr_status == OcrPageStatus.OCR_SUCCEEDED
        and normal_page.raw_blocks
        and meaningful_char_count(assembled_page.text)
        <= config.trigger_max_meaningful_chars
    )


def should_attempt_rotation(
    normal_page: PageOcrResult,
    assembled_page: ReassembledPage,
    orientation_status: OrientationStatus,
    rendered_page: RenderedPageEvidence,
    config: RotationRecoveryConfig,
) -> bool:
    return rotation_preconditions_met(
        normal_page, assembled_page, orientation_status, config
    ) and rendered_page.has_content


def _text_quality(text: str) -> tuple[float, float]:
    normalized = normalize_text_for_detection(text)
    visible = [character for character in normalized if not character.isspace()]
    alphanumeric = [character for character in visible if character.isalnum()]
    chinese = [character for character in alphanumeric if "\u4e00" <= character <= "\u9fff"]
    unusual = [
        character
        for character in visible
        if not character.isalnum()
        and not unicodedata.category(character).startswith("P")
        and character not in "()（）[]【】+-=.%‰/：:℃"
    ]
    return (
        len(chinese) / max(1, len(alphanumeric)),
        len(unusual) / max(1, len(visible)),
    )


def _structured_text_count(blocks: Sequence[RawOcrBlock]) -> int:
    count = 0
    for block in blocks:
        compact = re.sub(r"\s+", "", normalize_text_for_detection(block.text))
        if (
            DATE_PATTERN.search(compact)
            or CLAUSE_PATTERN.fullmatch(compact)
            or CHAPTER_PATTERN.fullmatch(compact)
        ):
            count += 1
    return count


def build_rotation_candidate(
    *,
    document_id: str,
    page_number: int,
    rotation_degrees: RotationDegree,
    file_sha256: str,
    ocr_config: OcrConfig,
    rotation_config: RotationRecoveryConfig,
    retention_config: HybridRetentionConfig,
    ocr_engine: str,
    raw_blocks: Sequence[RawOcrBlock],
    page_width: float,
    page_height: float,
    total_pages: int,
    repeat_stats: Dict[str, BlockRepeatStats],
    error: Optional[str] = None,
) -> RotationCandidateResult:
    ordered_raw = sort_ocr_blocks(raw_blocks)
    page = _RotationBlockPage(
        page_number=page_number,
        raw_blocks=ordered_raw,
        page_width=page_width,
        page_height=page_height,
    )
    decisions = [
        decide_block_retention(
            page=page,
            block=block,
            total_pages=total_pages,
            repeat_stats=repeat_stats,
            config=retention_config,
        )
        for block in ordered_raw
    ]
    retained_indices = [index for index, decision in enumerate(decisions) if decision.keep]
    retained_blocks = sort_ocr_blocks([ordered_raw[index] for index in retained_indices])
    assembled_text = "\n".join(
        block.text.strip() for block in retained_blocks if block.text.strip()
    )
    char_count = meaningful_char_count(assembled_text)
    chinese_ratio, unusual_ratio = _text_quality(assembled_text)
    dropped_ratio = (
        (len(ordered_raw) - len(retained_indices)) / len(ordered_raw)
        if ordered_raw
        else 1.0
    )
    garbled_ratio = min(1.0, max(unusual_ratio, dropped_ratio))
    structured_count = _structured_text_count(retained_blocks)
    quality_score = (
        char_count
        + len(retained_blocks) * 4
        + structured_count * 8
        + chinese_ratio * 20
        - garbled_ratio * 20
    )
    recovered = bool(
        error is None
        and char_count >= rotation_config.minimum_recovered_chars
        and len(retained_blocks) >= rotation_config.minimum_retained_blocks
        and chinese_ratio >= rotation_config.minimum_chinese_ratio
        and garbled_ratio <= rotation_config.maximum_garbled_ratio
    )
    return RotationCandidateResult(
        document_id=document_id,
        page_number=page_number,
        rotation_degrees=rotation_degrees,
        rotation_recovered=recovered,
        orientation_status=(
            OrientationStatus.OCR_ROTATION_RECOVERED
            if recovered
            else OrientationStatus.OCR_ROTATION_FAILED
        ),
        file_sha256=file_sha256,
        ocr_config_sha256=ocr_config.config_sha256,
        rotation_config_sha256=rotation_config.config_sha256,
        retention_config_sha256=retention_config.assembly_config_sha256,
        ocr_engine=ocr_engine,
        raw_blocks=ordered_raw,
        retained_blocks=retained_blocks,
        retained_block_indices=retained_indices,
        dropped_block_indices=[
            index for index in range(len(ordered_raw)) if index not in retained_indices
        ],
        retention_decisions=decisions,
        assembled_text=assembled_text,
        meaningful_char_count=char_count,
        chinese_character_ratio=round(chinese_ratio, 6),
        structured_text_count=structured_count,
        garbled_ratio=round(garbled_ratio, 6),
        quality_score=round(quality_score, 6),
        error=error,
    )


def select_rotation_candidate(
    candidates: Sequence[RotationCandidateResult],
    *,
    normal_meaningful_char_count: int,
    config: RotationRecoveryConfig,
) -> Optional[RotationCandidateResult]:
    eligible = [
        candidate
        for candidate in candidates
        if candidate.rotation_recovered
        and candidate.meaningful_char_count - normal_meaningful_char_count
        >= config.minimum_improvement_chars
    ]
    if not eligible:
        return None
    preferred = config.tie_break_preferred_rotation
    return sorted(
        eligible,
        key=lambda candidate: (
            -candidate.quality_score,
            0 if candidate.rotation_degrees == preferred else 1,
            candidate.rotation_degrees,
        ),
    )[0]


def replace_reassembled_page(
    pages: Sequence[ReassembledPage], candidate: RotationCandidateResult
) -> List[ReassembledPage]:
    if not candidate.rotation_recovered:
        raise ValueError("Only a recovered rotation candidate can replace assembled text")
    found = False
    result = []
    for page in pages:
        if page.page_number != candidate.page_number:
            result.append(page)
            continue
        if page.document_id != candidate.document_id:
            raise ValueError("rotation candidate document_id does not match assembled page")
        found = True
        result.append(
            page.model_copy(
                update={
                    "text": candidate.assembled_text,
                    "ocr_engine": candidate.ocr_engine,
                    "source_ocr_config_sha256": candidate.ocr_config_sha256,
                    "assembly_config_sha256": candidate.retention_config_sha256,
                    "retained_block_indices": candidate.retained_block_indices,
                    "dropped_block_indices": candidate.dropped_block_indices,
                    "decisions": candidate.retention_decisions,
                }
            )
        )
    if not found:
        raise ValueError("rotation candidate page_number is absent from assembled pages")
    return result


class RotationOcrProcessor:
    def __init__(
        self,
        cache_root: Path | str,
        *,
        ocr_config: Optional[OcrConfig] = None,
        rotation_config: Optional[RotationRecoveryConfig] = None,
        retention_config: Optional[HybridRetentionConfig] = None,
        page_source_factory: Callable[[Path], PageSource] = PdfiumPageSource,
        ocr_backend_factory: Callable[[OcrConfig], OcrBackend] = EasyOcrBackend,
    ):
        self.cache_root = Path(cache_root)
        self.ocr_config = ocr_config or OcrConfig()
        self.rotation_config = rotation_config or RotationRecoveryConfig()
        self.retention_config = retention_config or HybridRetentionConfig()
        self.page_source_factory = page_source_factory
        self.ocr_backend_factory = ocr_backend_factory
        self._ocr_backend: Optional[OcrBackend] = None

    def candidate_cache_path(
        self,
        document_id: str,
        file_sha256: str,
        page_number: int,
        rotation_degrees: RotationDegree,
    ) -> Path:
        return (
            self.cache_root
            / document_id
            / file_sha256
            / self.ocr_config.config_sha256
            / "rotation_pages"
            / self.rotation_config.config_sha256
            / f"page_{page_number:04d}_rot{rotation_degrees}.json"
        )

    def _load_candidate(
        self,
        document_id: str,
        file_sha256: str,
        page_number: int,
        rotation_degrees: RotationDegree,
    ) -> Optional[RotationCandidateResult]:
        path = self.candidate_cache_path(
            document_id, file_sha256, page_number, rotation_degrees
        )
        filesystem_path = _filesystem_path(path)
        if not filesystem_path.is_file():
            return None
        try:
            result = RotationCandidateResult.model_validate_json(
                filesystem_path.read_text(encoding="utf-8")
            )
        except Exception as exc:
            raise OcrCacheError(f"Invalid rotation OCR cache: {path}") from exc
        expected = bool(
            result.document_id == document_id
            and result.file_sha256 == file_sha256
            and result.page_number == page_number
            and result.rotation_degrees == rotation_degrees
            and result.ocr_config_sha256 == self.ocr_config.config_sha256
            and result.rotation_config_sha256 == self.rotation_config.config_sha256
            and result.retention_config_sha256
            == self.retention_config.assembly_config_sha256
        )
        if not expected:
            raise OcrCacheError(f"Rotation OCR cache identity mismatch: {path}")
        return result.model_copy(update={"cache_hit": True})

    def _save_candidate(self, result: RotationCandidateResult) -> None:
        persisted = result.model_copy(update={"cache_hit": False})
        write_json_atomic(
            self.candidate_cache_path(
                persisted.document_id,
                persisted.file_sha256,
                persisted.page_number,
                persisted.rotation_degrees,
            ),
            persisted.model_dump(mode="json"),
        )

    def _get_ocr_backend(self) -> OcrBackend:
        if self._ocr_backend is None:
            self._ocr_backend = self.ocr_backend_factory(self.ocr_config)
        return self._ocr_backend

    def _not_triggered(
        self,
        *,
        normal_page: PageOcrResult,
        normal_count: int,
        rendered_page: Optional[RenderedPageEvidence],
        error: str,
    ) -> RotationRecoveryResult:
        return RotationRecoveryResult(
            document_id=normal_page.document_id,
            page_number=normal_page.page_number,
            rotation_attempted=False,
            rotation_degrees=[],
            rotation_recovered=False,
            orientation_status=OrientationStatus.OCR_ROTATION_NOT_TRIGGERED,
            normal_meaningful_char_count=normal_count,
            rendered_page=rendered_page,
            candidates=[],
            selected_rotation_degrees=None,
            selected_candidate=None,
            cache_paths={},
            ocr_invocation_count=0,
            error=error,
        )

    def recover_page(
        self,
        pdf_path: Path | str,
        *,
        normal_page: PageOcrResult,
        assembled_page: ReassembledPage,
        orientation_status: OrientationStatus,
        context_pages: Sequence[PageOcrResult],
    ) -> RotationRecoveryResult:
        normal_count = meaningful_char_count(assembled_page.text)
        if not rotation_preconditions_met(
            normal_page, assembled_page, orientation_status, self.rotation_config
        ):
            return self._not_triggered(
                normal_page=normal_page,
                normal_count=normal_count,
                rendered_page=None,
                error="ROTATION_PRECONDITIONS_NOT_MET",
            )

        path = Path(pdf_path)
        actual_hash = sha256_file(path)
        if actual_hash != normal_page.file_sha256:
            raise ValueError("PDF file hash does not match the normal OCR page cache")
        source = self.page_source_factory(path)
        try:
            if normal_page.page_number > source.page_count:
                raise ValueError("page_number is outside the physical PDF page range")
            image = source.render_page(
                normal_page.page_number, self.ocr_config.render_scale
            )
            rendered = rendered_page_evidence(image, self.rotation_config)
            if not should_attempt_rotation(
                normal_page,
                assembled_page,
                orientation_status,
                rendered,
                self.rotation_config,
            ):
                return self._not_triggered(
                    normal_page=normal_page,
                    normal_count=normal_count,
                    rendered_page=rendered,
                    error="RENDERED_PAGE_HAS_NO_CONTENT",
                )

            repeat_stats = build_repeat_stats(context_pages, self.retention_config)
            candidates: List[RotationCandidateResult] = []
            cache_paths: Dict[str, str] = {}
            invocations = 0
            for degrees in self.rotation_config.candidate_degrees:
                cache_path = self.candidate_cache_path(
                    normal_page.document_id,
                    actual_hash,
                    normal_page.page_number,
                    degrees,
                )
                cache_paths[str(degrees)] = str(cache_path)
                cached = self._load_candidate(
                    normal_page.document_id,
                    actual_hash,
                    normal_page.page_number,
                    degrees,
                )
                if cached is not None:
                    candidates.append(cached)
                    continue

                backend = self._get_ocr_backend()
                raw_blocks: List[RawOcrBlock] = []
                candidate_error = None
                try:
                    rotated_image = image.rotate(degrees, expand=True)
                    invocations += 1
                    raw_blocks = backend.recognize(rotated_image)
                except Exception as exc:
                    candidate_error = f"{type(exc).__name__}: {exc}"
                candidate = build_rotation_candidate(
                    document_id=normal_page.document_id,
                    page_number=normal_page.page_number,
                    rotation_degrees=degrees,
                    file_sha256=actual_hash,
                    ocr_config=self.ocr_config,
                    rotation_config=self.rotation_config,
                    retention_config=self.retention_config,
                    ocr_engine=backend.engine_name,
                    raw_blocks=raw_blocks,
                    page_width=image.height / self.ocr_config.render_scale,
                    page_height=image.width / self.ocr_config.render_scale,
                    total_pages=len(context_pages),
                    repeat_stats=repeat_stats,
                    error=candidate_error,
                )
                self._save_candidate(candidate)
                candidates.append(candidate)
        finally:
            source.close()

        selected = select_rotation_candidate(
            candidates,
            normal_meaningful_char_count=normal_count,
            config=self.rotation_config,
        )
        recovered = selected is not None
        return RotationRecoveryResult(
            document_id=normal_page.document_id,
            page_number=normal_page.page_number,
            rotation_attempted=True,
            rotation_degrees=list(self.rotation_config.candidate_degrees),
            rotation_recovered=recovered,
            orientation_status=(
                OrientationStatus.OCR_ROTATION_RECOVERED
                if recovered
                else OrientationStatus.OCR_ROTATION_FAILED
            ),
            normal_meaningful_char_count=normal_count,
            rendered_page=rendered,
            candidates=candidates,
            selected_rotation_degrees=(selected.rotation_degrees if selected else None),
            selected_candidate=selected,
            cache_paths=cache_paths,
            ocr_invocation_count=invocations,
            error=None if recovered else "NO_ROTATION_CANDIDATE_PASSED_QUALITY",
        )
