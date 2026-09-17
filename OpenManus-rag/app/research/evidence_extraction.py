"""Deterministic HTML and text-PDF extraction into traceable Evidence."""

from __future__ import annotations

import re
from pathlib import Path

from bs4 import BeautifulSoup
from pypdf import PdfReader
from pypdf.errors import PdfReadError

from app.research.live_models import AcquiredSource, ResearchErrorCode
from app.research.models import Evidence, normalize_text


class EvidenceExtractionError(RuntimeError):
    def __init__(
        self,
        code: ResearchErrorCode,
        message: str,
        *,
        source_url: str,
    ):
        super().__init__(message)
        self.code = code
        self.source_url = source_url


def _source_path(workspace_root: str | Path, source: AcquiredSource) -> Path:
    root = Path(workspace_root).resolve()
    path = (root / source.local_file).resolve()
    if not path.is_relative_to(root) or not path.is_file() or path.is_symlink():
        raise EvidenceExtractionError(
            ResearchErrorCode.EVIDENCE_EXTRACTION_FAILED,
            "archived raw source is missing or unsafe",
            source_url=source.source_url,
        )
    return path


def _paragraphs(text: str) -> list[str]:
    blocks = re.split(r"(?:\r?\n\s*){2,}", text)
    normalized = [normalize_text(block) for block in blocks]
    return [block for block in normalized if block]


def _group_paragraphs(paragraphs: list[str], max_chars: int) -> list[str]:
    chunks: list[str] = []
    current: list[str] = []
    current_size = 0
    for paragraph in paragraphs:
        if current and current_size + len(paragraph) + 1 > max_chars:
            chunks.append(" ".join(current))
            current = []
            current_size = 0
        if len(paragraph) > max_chars:
            if current:
                chunks.append(" ".join(current))
                current = []
                current_size = 0
            for start in range(0, len(paragraph), max_chars):
                chunks.append(paragraph[start : start + max_chars])
            continue
        current.append(paragraph)
        current_size += len(paragraph) + 1
    if current:
        chunks.append(" ".join(current))
    return chunks


class HtmlEvidenceExtractor:
    def __init__(self, *, max_chunk_chars: int = 1600):
        self.max_chunk_chars = max_chunk_chars

    def extract(
        self,
        source: AcquiredSource,
        *,
        workspace_root: str | Path,
    ) -> list[Evidence]:
        if source.media_type != "text/html":
            raise EvidenceExtractionError(
                ResearchErrorCode.EVIDENCE_EXTRACTION_FAILED,
                "HTML extractor received a non-HTML source",
                source_url=source.source_url,
            )
        path = _source_path(workspace_root, source)
        try:
            html = path.read_text(encoding="utf-8-sig")
            soup = BeautifulSoup(html, "html.parser")
        except (OSError, UnicodeDecodeError, ValueError) as exc:
            raise EvidenceExtractionError(
                ResearchErrorCode.EVIDENCE_EXTRACTION_FAILED,
                f"HTML parsing failed: {exc}",
                source_url=source.source_url,
            ) from exc

        for node in soup(["script", "style", "nav", "footer", "header", "noscript", "svg"]):
            node.decompose()
        root = soup.find("main") or soup.find("article") or soup.body or soup
        document_title = normalize_text(
            (soup.title.get_text(" ", strip=True) if soup.title else "") or source.title
        )
        sections: list[tuple[str, list[str]]] = []
        section = document_title
        section_paragraphs: list[str] = []

        def flush() -> None:
            nonlocal section_paragraphs
            if section_paragraphs:
                sections.append((section, section_paragraphs))
                section_paragraphs = []

        for node in root.find_all(["h1", "h2", "h3", "h4", "h5", "h6", "p", "li"]):
            text = normalize_text(node.get_text(" ", strip=True))
            if not text:
                continue
            if node.name and node.name.startswith("h"):
                flush()
                section = text
            else:
                section_paragraphs.append(text)
        flush()

        evidence: list[Evidence] = []
        for heading, values in sections:
            for content in _group_paragraphs(values, self.max_chunk_chars):
                evidence.append(
                    Evidence(
                        title=document_title,
                        content=content,
                        organization=source.organization,
                        source_url=source.final_url,
                        source_type=source.source_type,
                        retrieved_at=source.retrieved_at,
                        local_file=source.local_file,
                        section=heading,
                        source_level=source.source_level,
                    )
                )
        if not evidence:
            raise EvidenceExtractionError(
                ResearchErrorCode.EMPTY_CONTENT,
                "HTML contains no meaningful paragraph content",
                source_url=source.source_url,
            )
        return evidence


class PdfEvidenceExtractor:
    def __init__(self, *, max_chunk_chars: int = 1600, min_total_chars: int = 30):
        self.max_chunk_chars = max_chunk_chars
        self.min_total_chars = min_total_chars

    def extract(
        self,
        source: AcquiredSource,
        *,
        workspace_root: str | Path,
    ) -> list[Evidence]:
        if source.media_type != "application/pdf":
            raise EvidenceExtractionError(
                ResearchErrorCode.EVIDENCE_EXTRACTION_FAILED,
                "PDF extractor received a non-PDF source",
                source_url=source.source_url,
            )
        path = _source_path(workspace_root, source)
        try:
            reader = PdfReader(path)
            pages = [page.extract_text() or "" for page in reader.pages]
        except (OSError, PdfReadError, ValueError) as exc:
            raise EvidenceExtractionError(
                ResearchErrorCode.EVIDENCE_EXTRACTION_FAILED,
                f"PDF parsing failed: {exc}",
                source_url=source.source_url,
            ) from exc

        total_text = normalize_text(" ".join(pages))
        if len(total_text) < self.min_total_chars:
            raise EvidenceExtractionError(
                ResearchErrorCode.UNSUPPORTED_SCAN_PDF,
                "PDF has no sufficient directly extractable text",
                source_url=source.source_url,
            )

        evidence: list[Evidence] = []
        for page_number, page_text in enumerate(pages, start=1):
            values = _paragraphs(page_text)
            for content in _group_paragraphs(values, self.max_chunk_chars):
                evidence.append(
                    Evidence(
                        title=source.title,
                        content=content,
                        organization=source.organization,
                        source_url=source.final_url,
                        source_type=source.source_type,
                        retrieved_at=source.retrieved_at,
                        local_file=source.local_file,
                        page_number=page_number,
                        source_level=source.source_level,
                    )
                )
        if not evidence:
            raise EvidenceExtractionError(
                ResearchErrorCode.EMPTY_CONTENT,
                "PDF yielded no Evidence chunks",
                source_url=source.source_url,
            )
        return evidence


class CompositeEvidenceExtractor:
    def __init__(
        self,
        html_extractor: HtmlEvidenceExtractor | None = None,
        pdf_extractor: PdfEvidenceExtractor | None = None,
    ):
        self.html_extractor = html_extractor or HtmlEvidenceExtractor()
        self.pdf_extractor = pdf_extractor or PdfEvidenceExtractor()

    def extract(self, source: AcquiredSource, *, workspace_root: str | Path) -> list[Evidence]:
        if source.media_type == "text/html":
            return self.html_extractor.extract(source, workspace_root=workspace_root)
        if source.media_type == "application/pdf":
            return self.pdf_extractor.extract(source, workspace_root=workspace_root)
        raise EvidenceExtractionError(
            ResearchErrorCode.EVIDENCE_EXTRACTION_FAILED,
            f"unsupported acquired media type: {source.media_type}",
            source_url=source.source_url,
        )

