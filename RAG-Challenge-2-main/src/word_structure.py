"""Deterministic Word structure extraction and canonical-PDF page alignment.

Word is a structure source only.  Canonical PDF pages remain the content and
citation source.  The module never calls an online service and deliberately
extracts headings instead of document body paragraphs.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import re
import unicodedata
from xml.etree import ElementTree as ET
import zipfile


EXTRACTOR_VERSION = "rd-v2-word-structure/1.0"
WORD_OUTLINE = "WORD_OUTLINE"
PDF_HEURISTIC = "PDF_HEURISTIC"
FALLBACK = "FALLBACK"

W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
HEADING_STYLE_RE = re.compile(r"(?i)(?:heading\s*([1-9])|标题\s*([1-9]))")
MARKDOWN_HEADING_RE = re.compile(r"^\s*(#{1,6})\s+(.+?)\s*$")
ARABIC_HEADING_RE = re.compile(r"^\s*(\d+(?:\.\d+){1,5})(?:[.、])?\s+(.+?)\s*$")
SINGLE_ARABIC_RE = re.compile(r"^\s*\d+[.、]?\s+.+$")
PAREN_ARABIC_RE = re.compile(r"^\s*[（(]\d+[）)]\s*.+$")
CHAPTER_RE = re.compile(
    r"^\s*第\s*[0-9零〇一二三四五六七八九十百千两]+\s*(章|节|部分)\s*.*$"
)
CHINESE_ENUM_RE = re.compile(r"^\s*[零〇一二三四五六七八九十百千两]+、\s*.+$")
PAREN_CHINESE_RE = re.compile(
    r"^\s*[（(][零〇一二三四五六七八九十百千两]+[）)]\s*.+$"
)
APPENDIX_RE = re.compile(r"^\s*(?:appendix|附录)\b.*$", re.IGNORECASE)
FIELD_LABEL_RE = re.compile(r"^\s*[^。.!?！？；;]{1,40}[:：]\s*$")
TEST_STEP_RE = re.compile(
    r"(?i)^\s*(?:test\s*step|step\s*\d+|测试步骤|测试步|操作步骤|预期结果|实际结果)(?:\s|[:：])?.*$"
)
NUMBER_PREFIX_RE = re.compile(
    r"^\s*(?:"
    r"\d+(?:\.\d+)*(?:[.、])?|"
    r"[（(]\d+[）)]|"
    r"第\s*[0-9零〇一二三四五六七八九十百千两]+\s*(?:章|节|部分)|"
    r"[零〇一二三四五六七八九十百千两]+、|"
    r"[（(][零〇一二三四五六七八九十百千两]+[）)]"
    r")\s*"
)


def normalize_heading_text(value: str) -> str:
    """Normalize presentation differences without changing title meaning."""
    normalized = unicodedata.normalize("NFKC", str(value or ""))
    normalized = normalized.replace("\r", " ").replace("\x07", " ").replace("\x0b", " ")
    return re.sub(r"\s+", " ", normalized).strip()


def _match_key(value: str) -> str:
    return re.sub(r"\s+", "", normalize_heading_text(value)).casefold()


def _without_numbering(value: str) -> str:
    return NUMBER_PREFIX_RE.sub("", normalize_heading_text(value), count=1).strip()


def heading_match_key(value: str) -> str:
    """Return the public numbering-insensitive key used for PDF alignment QA."""
    return _match_key(_without_numbering(value))


def title_hash(value: str) -> str:
    return hashlib.sha256(normalize_heading_text(value).encode("utf-8")).hexdigest()


def _attr(element: ET.Element | None, name: str) -> str | None:
    return None if element is None else element.get(W + name)


def _paragraph_text(paragraph: ET.Element) -> str:
    return normalize_heading_text(
        "".join(node.text or "" for node in paragraph.iter(W + "t"))
    )


def _style_heading_level(style_id: str | None, style_name: str | None) -> int | None:
    combined = " ".join(value for value in (style_id, style_name) if value)
    match = HEADING_STYLE_RE.search(combined)
    if not match:
        return None
    return int(match.group(1) or match.group(2))


def _section_id(
    document_id: str, source: str, level: int, value_hash: str, occurrence: int
) -> str:
    payload = f"{document_id}|{source}|{level}|{value_hash}|{occurrence}"
    return f"{document_id}:sec:{hashlib.sha256(payload.encode('utf-8')).hexdigest()[:16]}"


def build_structure_sidecar(
    *,
    document_id: str,
    source_file_hash: str,
    normalized_pdf_id: str,
    headings: list[dict],
    extractor: str,
) -> dict:
    """Build a deterministic sidecar and derive the Word parent hierarchy."""
    occurrences: Counter[tuple[str, int, str]] = Counter()
    stack: dict[int, str] = {}
    sections: list[dict] = []
    for order, raw in enumerate(headings, start=1):
        normalized_title = normalize_heading_text(raw.get("normalized_title", ""))
        if not normalized_title:
            continue
        level = max(1, min(9, int(raw.get("level") or 1)))
        value_hash = title_hash(normalized_title)
        occurrence_key = (WORD_OUTLINE, level, value_hash)
        occurrences[occurrence_key] += 1
        section_id = _section_id(
            document_id,
            WORD_OUTLINE,
            level,
            value_hash,
            occurrences[occurrence_key],
        )
        for existing_level in list(stack):
            if existing_level >= level:
                del stack[existing_level]
        parent_section_id = stack[max(stack)] if stack else None
        stack[level] = section_id
        sections.append(
            {
                "section_id": section_id,
                "normalized_title": normalized_title,
                "title_hash": value_hash,
                "level": level,
                "parent_section_id": parent_section_id,
                "order": order,
                "source": WORD_OUTLINE,
                "mapped_start_page": None,
                "mapped_end_page": None,
                "mapping_status": "UNMAPPED",
                "source_page_hint": int(raw.get("source_page_hint") or 0),
                "source_ordinal": int(raw.get("source_ordinal") or order),
                "numbering_label": normalize_heading_text(raw.get("numbering_label", "")),
            }
        )
    return {
        "schema_version": 1,
        "document_id": document_id,
        "source_file_hash": source_file_hash,
        "normalized_pdf_id": normalized_pdf_id,
        "extractor_version": EXTRACTOR_VERSION,
        "extractor": extractor,
        "sections": sections,
        "body_text_included": False,
        "online_services_used": False,
    }


class WordStructureExtractor:
    """Extract Word Heading/Outline metadata from DOCX or sanitized COM rows."""

    def extract_docx(
        self,
        path: Path,
        *,
        document_id: str,
        source_file_hash: str,
        normalized_pdf_id: str,
    ) -> dict:
        actual_hash = hashlib.sha256(path.read_bytes()).hexdigest()
        if actual_hash != source_file_hash:
            raise ValueError("DOCX hash does not match the normalization manifest")
        with zipfile.ZipFile(path) as package:
            document = ET.fromstring(package.read("word/document.xml"))
            styles_root = ET.fromstring(package.read("word/styles.xml"))

        styles: dict[str, dict] = {}
        for style in styles_root.findall(W + "style"):
            style_id = _attr(style, "styleId") or ""
            ppr = style.find(W + "pPr")
            styles[style_id] = {
                "name": _attr(style.find(W + "name"), "val"),
                "based_on": _attr(style.find(W + "basedOn"), "val"),
                "outline": _attr(ppr.find(W + "outlineLvl"), "val")
                if ppr is not None
                else None,
                "num_id": _attr(ppr.find(f"{W}numPr/{W}numId"), "val")
                if ppr is not None
                else None,
                "ilvl": _attr(ppr.find(f"{W}numPr/{W}ilvl"), "val")
                if ppr is not None
                else None,
            }

        def resolve_style(style_id: str | None) -> dict:
            result = {"outline": None, "num_id": None, "ilvl": None, "heading_level": None}
            seen: set[str] = set()
            current = style_id
            while current and current not in seen and current in styles:
                seen.add(current)
                style = styles[current]
                if result["outline"] is None:
                    result["outline"] = style["outline"]
                if result["num_id"] is None:
                    result["num_id"] = style["num_id"]
                    result["ilvl"] = style["ilvl"]
                if result["heading_level"] is None:
                    result["heading_level"] = _style_heading_level(current, style["name"])
                current = style["based_on"]
            return result

        table_paragraphs = {
            id(paragraph)
            for table in document.iter(W + "tbl")
            for paragraph in table.iter(W + "p")
        }
        headings: list[dict] = []
        for ordinal, paragraph in enumerate(document.iter(W + "p"), start=1):
            value = _paragraph_text(paragraph)
            if not value or id(paragraph) in table_paragraphs:
                continue
            ppr = paragraph.find(W + "pPr")
            style_id = _attr(ppr.find(W + "pStyle"), "val") if ppr is not None else None
            resolved = resolve_style(style_id)
            direct_outline = _attr(ppr.find(W + "outlineLvl"), "val") if ppr is not None else None
            outline = direct_outline if direct_outline is not None else resolved["outline"]
            direct_ilvl = _attr(ppr.find(f"{W}numPr/{W}ilvl"), "val") if ppr is not None else None
            ilvl = direct_ilvl if direct_ilvl is not None else resolved["ilvl"]
            outline_level = int(outline) + 1 if outline is not None and outline.isdigit() and int(outline) < 9 else None
            style_level = resolved["heading_level"]
            if outline_level is None and style_level is None:
                continue
            level = outline_level or style_level or (int(ilvl) + 1 if ilvl and ilvl.isdigit() else 1)
            headings.append(
                {
                    "normalized_title": value,
                    "level": level,
                    "source_page_hint": 0,
                    "source_ordinal": ordinal,
                    "numbering_label": "",
                }
            )
        return build_structure_sidecar(
            document_id=document_id,
            source_file_hash=source_file_hash,
            normalized_pdf_id=normalized_pdf_id,
            headings=headings,
            extractor="DOCX_OOXML",
        )

    def from_com_records(
        self,
        records: list[dict],
        *,
        document_id: str,
        source_file_hash: str,
        normalized_pdf_id: str,
    ) -> dict:
        headings = []
        for item in records:
            if item.get("in_table") or not (
                item.get("heading_style") or item.get("outline_candidate")
            ):
                continue
            headings.append(
                {
                    "normalized_title": item.get("normalized_title", ""),
                    "level": item.get("level") or 1,
                    "source_page_hint": item.get("source_page_hint") or 0,
                    "source_ordinal": item.get("source_ordinal") or 0,
                    "numbering_label": item.get("numbering_label", ""),
                }
            )
        return build_structure_sidecar(
            document_id=document_id,
            source_file_hash=source_file_hash,
            normalized_pdf_id=normalized_pdf_id,
            headings=headings,
            extractor="WORD_COM_READ_ONLY",
        )


def classify_pdf_candidate(value: str, *, in_table: bool = False) -> tuple[str, int | None]:
    """Classify a PDF line without treating a bare number as heading proof."""
    text = normalize_heading_text(value)
    markdown = MARKDOWN_HEADING_RE.match(text)
    if markdown:
        text = markdown.group(2).strip()
        if in_table:
            return "TABLE_ROW", None
        # The existing merger uses H3 for ordinary paragraphs.  Only H1/H2
        # retain semantic heading weight in the PDF-only fallback.
        if len(markdown.group(1)) <= 2 and _plausible_title(text):
            return "REAL_HEADING", len(markdown.group(1))
        return "BODY_SENTENCE" if text.endswith(("。", ".", "；", ";")) else "UNKNOWN", None
    if in_table:
        return "TABLE_ROW", None
    if TEST_STEP_RE.match(text):
        return "TEST_STEP", None
    if PAREN_ARABIC_RE.match(text) or SINGLE_ARABIC_RE.match(text) or ARABIC_HEADING_RE.match(text):
        return "NUMBERED_LIST_ITEM", None
    if CHAPTER_RE.match(text):
        return "REAL_HEADING", 2 if "节" in text else 1
    if CHINESE_ENUM_RE.match(text):
        return "REAL_HEADING", 1
    if PAREN_CHINESE_RE.match(text):
        return "REAL_HEADING", 2
    if APPENDIX_RE.match(text) and _plausible_title(text):
        return "REAL_HEADING", 1
    if FIELD_LABEL_RE.match(text):
        return "FIELD_LABEL", None
    if len(text) > 80 or text.endswith(("。", ".", "！", "!", "？", "?", "；", ";")):
        return "BODY_SENTENCE", None
    return "UNKNOWN", None


def _plausible_title(value: str) -> bool:
    title = normalize_heading_text(value).strip("#").strip()
    return bool(
        title
        and len(title) <= 120
        and not (
            len(title) > 50
            and title.endswith(("。", ".", "！", "!", "？", "?", "；", ";"))
        )
    )


class HeadingPageMapper:
    """Map ordered Word headings onto parsed canonical-PDF physical pages."""

    MAX_JOINED_LINES = 3

    @staticmethod
    def _candidate_indexes(pages: list[dict]) -> tuple[dict[str, list[tuple]], dict[str, list[tuple]], dict[str, list[tuple]]]:
        exact: dict[str, list[tuple]] = defaultdict(list)
        compact: dict[str, list[tuple]] = defaultdict(list)
        no_number: dict[str, list[tuple]] = defaultdict(list)
        for page in sorted(pages, key=lambda item: int(item.get("page", 0))):
            page_number = int(page["page"])
            lines = str(page.get("text", "")).splitlines()
            for start in range(len(lines)):
                for span in range(1, min(HeadingPageMapper.MAX_JOINED_LINES, len(lines) - start) + 1):
                    value = normalize_heading_text(" ".join(lines[start : start + span]))
                    if not value or len(value) > 180:
                        continue
                    position = (page_number, start, span)
                    exact[value.casefold()].append(position)
                    compact[_match_key(value)].append(position)
                    stripped = _match_key(_without_numbering(value))
                    if stripped:
                        no_number[stripped].append(position)
        return exact, compact, no_number

    @staticmethod
    def _after(position: tuple[int, int, int], cursor: tuple[int, int]) -> bool:
        return (position[0], position[1]) >= cursor

    @staticmethod
    def _choose(
        candidates: list[tuple[int, int, int]],
        cursor: tuple[int, int],
        page_hint: int,
    ) -> tuple[int, int, int] | None:
        available = [item for item in candidates if HeadingPageMapper._after(item, cursor)]
        if not available:
            return None
        if page_hint > 0:
            local = [item for item in available if abs(item[0] - page_hint) <= 2]
            # A renderer page hint comes from the same local Word engine that
            # produced the canonical PDF.  Falling back to a distant repeated
            # title would be deterministic but not reliable, and can also move
            # the sequence cursor past many valid later anchors.
            if not local:
                return None
            available = local
            available.sort(key=lambda item: (abs(item[0] - page_hint), item[0], item[1], item[2]))
        else:
            available.sort(key=lambda item: (item[0], item[1], item[2]))
        return available[0]

    def map(self, sidecar: dict, pages: list[dict]) -> dict:
        mapped = deepcopy(sidecar)
        exact, compact, no_number = self._candidate_indexes(pages)
        cursor = (1, 0)
        max_page = max((int(item.get("page", 0)) for item in pages), default=0)
        for section in mapped.get("sections", []):
            value = normalize_heading_text(section["normalized_title"])
            numbering = normalize_heading_text(section.get("numbering_label", ""))
            joined = normalize_heading_text(f"{numbering} {value}") if numbering else value
            lookups = [
                ("EXACT", exact.get(joined.casefold(), [])),
                ("NORMALIZED", compact.get(_match_key(joined), [])),
                ("NUMBERING_NORMALIZED", no_number.get(_match_key(_without_numbering(joined)), [])),
            ]
            chosen = None
            status = "UNRESOLVED"
            for candidate_status, candidates in lookups:
                chosen = self._choose(
                    candidates, cursor, int(section.get("source_page_hint") or 0)
                )
                if chosen is not None:
                    status = "SPLIT_" + candidate_status if chosen[2] > 1 else candidate_status
                    break
            if chosen is None:
                section.update(
                    {
                        "mapped_start_page": None,
                        "mapped_end_page": None,
                        "mapped_line_start": None,
                        "mapped_line_span": None,
                        "mapping_status": "UNRESOLVED",
                    }
                )
                continue
            page_number, line_start, line_span = chosen
            section.update(
                {
                    "mapped_start_page": page_number,
                    "mapped_end_page": page_number,
                    "mapped_line_start": line_start,
                    "mapped_line_span": line_span,
                    "mapping_status": status,
                }
            )
            cursor = (page_number, line_start + line_span)

        sections = mapped.get("sections", [])
        mapped_sections = [item for item in sections if item["mapping_status"] != "UNRESOLVED"]
        for index, section in enumerate(mapped_sections):
            next_page = (
                int(mapped_sections[index + 1]["mapped_start_page"])
                if index + 1 < len(mapped_sections)
                else max_page
            )
            section["mapped_end_page"] = max(
                int(section["mapped_start_page"]), next_page
            )
        mapped["alignment"] = {
            "heading_count": len(sections),
            "mapped_count": len(mapped_sections),
            "unresolved_count": len(sections) - len(mapped_sections),
            "mapping_status_counts": dict(
                sorted(Counter(item["mapping_status"] for item in sections).items())
            ),
            "sequential_order_valid": all(
                (a["mapped_start_page"], a["mapped_line_start"])
                <= (b["mapped_start_page"], b["mapped_line_start"])
                for a, b in zip(mapped_sections, mapped_sections[1:])
            ),
            "physical_page_count": max_page,
        }
        return mapped


def load_sidecar(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))
