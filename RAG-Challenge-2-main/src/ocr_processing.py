"""Minimal page-level OCR adapter for explicitly OCR-required PDF documents.

The adapter is intentionally separate from the default Docling parser.  It
detects usable native text page by page, uses EasyOCR only for pages that need
it, and caches each physical PDF page under a file/config hash identity.
"""

from __future__ import annotations

import hashlib
import importlib.metadata
import json
import math
import os
import re
import tempfile
import time
import unicodedata
from enum import Enum
from pathlib import Path
from typing import Callable, Iterable, List, Literal, Optional, Protocol, Sequence

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")


class OcrEnvironmentError(RuntimeError):
    """Raised when the approved local OCR runtime is unavailable."""


class OcrCacheError(RuntimeError):
    """Raised when a page cache exists but cannot be trusted."""


class OcrPageStatus(str, Enum):
    TEXT_NATIVE = "TEXT_NATIVE"
    OCR_REQUIRED = "OCR_REQUIRED"
    OCR_SUCCEEDED = "OCR_SUCCEEDED"
    OCR_FAILED = "OCR_FAILED"


class OcrDocumentStatus(str, Enum):
    NOT_REQUIRED = "NOT_REQUIRED"
    OCR_SUCCEEDED = "OCR_SUCCEEDED"
    OCR_PARTIAL = "OCR_PARTIAL"
    OCR_FAILED = "OCR_FAILED"


class OcrConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    cache_schema_version: str = "1"
    ocr_engine: Literal["easyocr"] = "easyocr"
    ocr_engine_version: str = "1.7.2"
    languages: List[str] = Field(default_factory=lambda: ["ch_sim", "en"])
    render_scale: float = Field(default=3.0, gt=0)
    native_text_min_chars: int = Field(default=20, ge=1)
    ocr_block_confidence_threshold: float = Field(default=0.60, ge=0, le=1)
    text_ordering_version: str = "bbox-top-left-v1"
    header_footer_cleanup_version: str = "repeated-margin-v1"

    @field_validator("languages")
    @classmethod
    def validate_languages(cls, value: List[str]) -> List[str]:
        normalized = [language.strip() for language in value if language.strip()]
        if not normalized:
            raise ValueError("languages cannot be empty")
        if len(normalized) != len(set(normalized)):
            raise ValueError("languages cannot contain duplicates")
        return normalized

    @property
    def config_sha256(self) -> str:
        payload = self.model_dump(mode="json")
        encoded = json.dumps(
            payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        ).encode("utf-8")
        return hashlib.sha256(encoded).hexdigest()


class RawOcrBlock(BaseModel):
    model_config = ConfigDict(extra="forbid")

    text: str
    confidence: float
    bbox: List[List[float]]

    @field_validator("bbox")
    @classmethod
    def validate_bbox(cls, value: List[List[float]]) -> List[List[float]]:
        if len(value) != 4 or any(len(point) != 2 for point in value):
            raise ValueError("bbox must contain four [x, y] points")
        return [[float(point[0]), float(point[1])] for point in value]


class PageOcrResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    document_id: str
    page_number: int = Field(ge=1)
    text: str
    source_type: Literal["NATIVE_TEXT", "OCR"]
    ocr_used: bool
    ocr_engine: Optional[str]
    ocr_status: OcrPageStatus
    file_sha256: str
    ocr_config_sha256: str
    meaningful_char_count: int = Field(ge=0)
    raw_blocks: List[RawOcrBlock] = Field(default_factory=list)
    page_width: Optional[float] = None
    page_height: Optional[float] = None
    cache_hit: bool = False
    error: Optional[str] = None

    @field_validator("file_sha256", "ocr_config_sha256")
    @classmethod
    def validate_sha256(cls, value: str) -> str:
        normalized = value.strip().lower()
        if not SHA256_PATTERN.fullmatch(normalized):
            raise ValueError("expected lowercase SHA-256")
        return normalized

    @model_validator(mode="after")
    def validate_state(self):
        if self.ocr_status == OcrPageStatus.TEXT_NATIVE:
            if self.ocr_used or self.source_type != "NATIVE_TEXT" or self.raw_blocks:
                raise ValueError("TEXT_NATIVE pages cannot contain OCR output")
        else:
            if not self.ocr_used or self.source_type != "OCR" or not self.ocr_engine:
                raise ValueError("OCR page states require OCR provenance")
        if self.ocr_status == OcrPageStatus.OCR_SUCCEEDED and not self.text.strip():
            raise ValueError("OCR_SUCCEEDED requires non-empty text")
        if self.ocr_status == OcrPageStatus.OCR_FAILED and not self.error:
            raise ValueError("OCR_FAILED requires an error")
        return self


class DocumentOcrResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    document_id: str
    file_sha256: str
    pages_total: int = Field(ge=0)
    processed_page_numbers: List[int]
    pages: List[PageOcrResult]
    native_pages: List[int]
    ocr_required_pages: List[int]
    ocr_success_pages: List[int]
    ocr_failed_pages: List[int]
    cache_hits: int = Field(ge=0)
    ocr_status: OcrDocumentStatus
    elapsed_ms: float = Field(ge=0)


class PageSource(Protocol):
    page_count: int

    def get_native_text(self, page_number: int) -> str: ...

    def render_page(self, page_number: int, scale: float): ...

    def get_page_size(self, page_number: int) -> tuple[float, float]: ...

    def close(self) -> None: ...


class OcrBackend(Protocol):
    @property
    def engine_name(self) -> str: ...

    def recognize(self, image) -> List[RawOcrBlock]: ...


def sha256_file(path: Path | str) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def normalize_text_for_detection(text: str) -> str:
    """Normalize text for conservative meaningful-character counting."""
    normalized = unicodedata.normalize("NFKC", text or "")
    cleaned = []
    for character in normalized:
        category = unicodedata.category(character)
        if category in {"Cc", "Cf"} and character not in {"\n", "\t"}:
            continue
        cleaned.append(character)
    normalized = "".join(cleaned)
    normalized = re.sub(r"[\t\f\v ]+", " ", normalized)
    normalized = re.sub(r" *\n *", "\n", normalized)
    normalized = re.sub(r"\n{3,}", "\n\n", normalized)
    return normalized.strip()


def meaningful_char_count(text: str) -> int:
    normalized = normalize_text_for_detection(text)
    return sum(character.isalnum() for character in normalized)


def page_requires_ocr(text: str, native_text_min_chars: int) -> bool:
    return meaningful_char_count(text) < native_text_min_chars


def _block_position(block: RawOcrBlock) -> tuple[float, float, str]:
    top = min(point[1] for point in block.bbox)
    left = min(point[0] for point in block.bbox)
    return (round(top, 6), round(left, 6), block.text)


def sort_ocr_blocks(blocks: Iterable[RawOcrBlock]) -> List[RawOcrBlock]:
    return sorted(blocks, key=_block_position)


def assemble_ocr_text(
    blocks: Iterable[RawOcrBlock], confidence_threshold: float
) -> str:
    eligible = [
        block
        for block in blocks
        if block.confidence >= confidence_threshold and block.text.strip()
    ]
    ordered = sort_ocr_blocks(eligible)
    return "\n".join(block.text.strip() for block in ordered)


def _filesystem_path(path: Path | str) -> Path:
    """Use Win32 extended paths for the required nested SHA-256 cache layout."""
    candidate = Path(path)
    if os.name != "nt":
        return candidate
    absolute = str(candidate.resolve())
    if absolute.startswith("\\\\?\\"):
        return Path(absolute)
    if absolute.startswith("\\\\"):
        return Path("\\\\?\\UNC\\" + absolute[2:])
    return Path("\\\\?\\" + absolute)


def write_json_atomic(path: Path, payload: dict) -> None:
    filesystem_path = _filesystem_path(path)
    filesystem_path.parent.mkdir(parents=True, exist_ok=True)
    temp_path: Optional[Path] = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=filesystem_path.parent,
            prefix=f".{filesystem_path.name}.",
            suffix=".tmp",
            delete=False,
        ) as stream:
            json.dump(payload, stream, ensure_ascii=False, indent=2)
            stream.flush()
            os.fsync(stream.fileno())
            temp_path = Path(stream.name)
        os.replace(temp_path, filesystem_path)
    finally:
        if temp_path is not None and temp_path.exists():
            temp_path.unlink()


class PdfiumPageSource:
    """Physical-page reader using the already-installed pypdfium2 runtime."""

    def __init__(self, pdf_path: Path | str):
        import pypdfium2 as pdfium

        self._document = pdfium.PdfDocument(str(pdf_path))
        self.page_count = len(self._document)

    def get_native_text(self, page_number: int) -> str:
        page = self._document[page_number - 1]
        text_page = page.get_textpage()
        try:
            return text_page.get_text_range() or ""
        finally:
            text_page.close()
            page.close()

    def render_page(self, page_number: int, scale: float):
        page = self._document[page_number - 1]
        try:
            return page.render(scale=scale).to_pil()
        finally:
            page.close()

    def get_page_size(self, page_number: int) -> tuple[float, float]:
        page = self._document[page_number - 1]
        try:
            width, height = page.get_size()
            return float(width), float(height)
        finally:
            page.close()

    def close(self) -> None:
        self._document.close()


class EasyOcrBackend:
    """Lazy local-only EasyOCR backend for simplified Chinese regulations."""

    def __init__(self, config: OcrConfig):
        if config.ocr_engine != "easyocr":
            raise OcrEnvironmentError(f"Unsupported OCR engine: {config.ocr_engine}")
        try:
            import easyocr
            import easyocr.config as easyocr_config
        except ImportError as exc:
            raise OcrEnvironmentError("EasyOCR is not installed") from exc

        installed_version = importlib.metadata.version("easyocr")
        if installed_version != config.ocr_engine_version:
            raise OcrEnvironmentError(
                f"EasyOCR version mismatch: expected {config.ocr_engine_version}, "
                f"found {installed_version}"
            )

        model_directory = Path(easyocr_config.MODULE_PATH) / "model"
        required_models = ["craft_mlt_25k.pth"]
        if "ch_sim" in config.languages:
            required_models.append("zh_sim_g2.pth")
        elif config.languages == ["en"]:
            required_models.append("english_g2.pth")
        missing = [name for name in required_models if not (model_directory / name).is_file()]
        if missing:
            raise OcrEnvironmentError(
                "Required EasyOCR model files are missing and automatic download is "
                f"disabled: {missing}"
            )

        self._reader = easyocr.Reader(
            list(config.languages),
            gpu=False,
            model_storage_directory=str(model_directory),
            download_enabled=False,
            verbose=False,
        )
        self._engine_name = f"easyocr-{installed_version}"

    @property
    def engine_name(self) -> str:
        return self._engine_name

    def recognize(self, image) -> List[RawOcrBlock]:
        import numpy as np

        result = self._reader.readtext(np.asarray(image), detail=1, paragraph=False)
        return [
            RawOcrBlock(text=str(text), confidence=float(confidence), bbox=bbox)
            for bbox, text, confidence in result
        ]


class PageOcrProcessor:
    def __init__(
        self,
        cache_root: Path | str,
        *,
        config: Optional[OcrConfig] = None,
        page_source_factory: Callable[[Path], PageSource] = PdfiumPageSource,
        ocr_backend_factory: Callable[[OcrConfig], OcrBackend] = EasyOcrBackend,
    ):
        self.cache_root = Path(cache_root)
        self.config = config or OcrConfig()
        self.page_source_factory = page_source_factory
        self.ocr_backend_factory = ocr_backend_factory
        self._ocr_backend: Optional[OcrBackend] = None

    def _cache_path(
        self, document_id: str, file_sha256: str, page_number: int
    ) -> Path:
        return (
            self.cache_root
            / document_id
            / file_sha256
            / self.config.config_sha256
            / "pages"
            / f"page_{page_number:04d}.json"
        )

    def _load_cache(
        self, document_id: str, file_sha256: str, page_number: int
    ) -> Optional[PageOcrResult]:
        path = self._cache_path(document_id, file_sha256, page_number)
        filesystem_path = _filesystem_path(path)
        if not filesystem_path.is_file():
            return None
        try:
            result = PageOcrResult.model_validate_json(
                filesystem_path.read_text(encoding="utf-8")
            )
        except Exception as exc:
            raise OcrCacheError(f"Invalid OCR page cache: {path}") from exc
        expected = (
            result.document_id == document_id
            and result.file_sha256 == file_sha256
            and result.ocr_config_sha256 == self.config.config_sha256
            and result.page_number == page_number
        )
        if not expected:
            raise OcrCacheError(f"OCR page cache identity mismatch: {path}")
        return result.model_copy(update={"cache_hit": True})

    def _save_cache(self, result: PageOcrResult) -> None:
        persisted = result.model_copy(update={"cache_hit": False})
        write_json_atomic(
            self._cache_path(
                persisted.document_id,
                persisted.file_sha256,
                persisted.page_number,
            ),
            persisted.model_dump(mode="json"),
        )

    def _get_ocr_backend(self) -> OcrBackend:
        if self._ocr_backend is None:
            self._ocr_backend = self.ocr_backend_factory(self.config)
        return self._ocr_backend

    def process_page(
        self,
        page_source: PageSource,
        *,
        document_id: str,
        file_sha256: str,
        page_number: int,
        retry_failed: bool = False,
    ) -> PageOcrResult:
        cached = self._load_cache(document_id, file_sha256, page_number)
        if cached is not None and not (
            cached.ocr_status == OcrPageStatus.OCR_FAILED and retry_failed
        ):
            return cached

        native_text = normalize_text_for_detection(
            page_source.get_native_text(page_number)
        )
        native_count = meaningful_char_count(native_text)
        width, height = page_source.get_page_size(page_number)
        if native_count >= self.config.native_text_min_chars:
            result = PageOcrResult(
                document_id=document_id,
                page_number=page_number,
                text=native_text,
                source_type="NATIVE_TEXT",
                ocr_used=False,
                ocr_engine=None,
                ocr_status=OcrPageStatus.TEXT_NATIVE,
                file_sha256=file_sha256,
                ocr_config_sha256=self.config.config_sha256,
                meaningful_char_count=native_count,
                page_width=width,
                page_height=height,
            )
            self._save_cache(result)
            return result

        backend = self._get_ocr_backend()
        raw_blocks: List[RawOcrBlock] = []
        try:
            image = page_source.render_page(page_number, self.config.render_scale)
            raw_blocks = sort_ocr_blocks(backend.recognize(image))
            text = assemble_ocr_text(
                raw_blocks, self.config.ocr_block_confidence_threshold
            )
            count = meaningful_char_count(text)
            if count == 0:
                raise RuntimeError("OCR returned no usable text above confidence threshold")
            result = PageOcrResult(
                document_id=document_id,
                page_number=page_number,
                text=text,
                source_type="OCR",
                ocr_used=True,
                ocr_engine=backend.engine_name,
                ocr_status=OcrPageStatus.OCR_SUCCEEDED,
                file_sha256=file_sha256,
                ocr_config_sha256=self.config.config_sha256,
                meaningful_char_count=count,
                raw_blocks=raw_blocks,
                page_width=width,
                page_height=height,
            )
        except Exception as exc:
            result = PageOcrResult(
                document_id=document_id,
                page_number=page_number,
                text="",
                source_type="OCR",
                ocr_used=True,
                ocr_engine=backend.engine_name,
                ocr_status=OcrPageStatus.OCR_FAILED,
                file_sha256=file_sha256,
                ocr_config_sha256=self.config.config_sha256,
                meaningful_char_count=0,
                raw_blocks=raw_blocks,
                page_width=width,
                page_height=height,
                error=f"{type(exc).__name__}: {exc}",
            )
        self._save_cache(result)
        return result

    def process_document(
        self,
        pdf_path: Path | str,
        *,
        document_id: str,
        page_numbers: Optional[Sequence[int]] = None,
        retry_failed: bool = False,
    ) -> DocumentOcrResult:
        started = time.perf_counter()
        path = Path(pdf_path)
        file_sha256 = sha256_file(path)
        source = self.page_source_factory(path)
        try:
            selected_pages = list(page_numbers or range(1, source.page_count + 1))
            if len(selected_pages) != len(set(selected_pages)):
                raise ValueError("page_numbers cannot contain duplicates")
            if any(page < 1 or page > source.page_count for page in selected_pages):
                raise ValueError("page_number is outside the physical PDF page range")
            results = [
                self.process_page(
                    source,
                    document_id=document_id,
                    file_sha256=file_sha256,
                    page_number=page_number,
                    retry_failed=retry_failed,
                )
                for page_number in selected_pages
            ]
        finally:
            source.close()

        native_pages = [
            page.page_number
            for page in results
            if page.ocr_status == OcrPageStatus.TEXT_NATIVE
        ]
        success_pages = [
            page.page_number
            for page in results
            if page.ocr_status == OcrPageStatus.OCR_SUCCEEDED
        ]
        failed_pages = [
            page.page_number
            for page in results
            if page.ocr_status == OcrPageStatus.OCR_FAILED
        ]
        required_pages = sorted([*success_pages, *failed_pages])
        if not required_pages:
            document_status = OcrDocumentStatus.NOT_REQUIRED
        elif failed_pages and success_pages:
            document_status = OcrDocumentStatus.OCR_PARTIAL
        elif failed_pages:
            document_status = OcrDocumentStatus.OCR_FAILED
        else:
            document_status = OcrDocumentStatus.OCR_SUCCEEDED

        return DocumentOcrResult(
            document_id=document_id,
            file_sha256=file_sha256,
            pages_total=source.page_count,
            processed_page_numbers=selected_pages,
            pages=results,
            native_pages=native_pages,
            ocr_required_pages=required_pages,
            ocr_success_pages=success_pages,
            ocr_failed_pages=failed_pages,
            cache_hits=sum(page.cache_hit for page in results),
            ocr_status=document_status,
            elapsed_ms=round((time.perf_counter() - started) * 1000, 3),
        )

    def reassemble_from_raw_blocks(
        self, result: PageOcrResult, *, config: Optional[OcrConfig] = None
    ) -> PageOcrResult:
        """Rebuild page text from cached blocks without invoking OCR again."""
        target_config = config or self.config
        if result.ocr_status != OcrPageStatus.OCR_SUCCEEDED:
            raise ValueError("Only successful OCR pages can be reassembled")
        text = assemble_ocr_text(
            result.raw_blocks, target_config.ocr_block_confidence_threshold
        )
        if not text:
            raise ValueError("Reassembly produced no usable text")
        return result.model_copy(
            update={
                "text": text,
                "meaningful_char_count": meaningful_char_count(text),
                "ocr_config_sha256": target_config.config_sha256,
                "cache_hit": True,
            }
        )


def repeated_text_candidates(
    pages: Iterable[PageOcrResult], *, minimum_ratio: float = 0.6
) -> List[str]:
    """Return deterministic high-frequency line candidates for audit only.

    This function does not delete text.  It supplies evidence for smoke/full
    validation so cleanup cannot silently remove legitimate regulation text.
    """
    page_list = list(pages)
    if not page_list:
        return []
    counts: dict[str, int] = {}
    representative: dict[str, str] = {}
    for page in page_list:
        seen = set()
        for line in page.text.splitlines():
            normalized = re.sub(r"\s+", "", line).casefold()
            if not normalized or normalized in seen:
                continue
            seen.add(normalized)
            counts[normalized] = counts.get(normalized, 0) + 1
            representative.setdefault(normalized, line.strip())
    minimum_pages = max(2, math.ceil(len(page_list) * minimum_ratio))
    return sorted(
        representative[key] for key, count in counts.items() if count >= minimum_pages
    )
