"""Deterministic section detection and parent/child chunking for R&D documents.

The implementation is deliberately heuristic: it consumes the page model that
the existing PDF pipeline already produces, recognises common engineering
document headings, and falls back to the legacy page splitter when no heading
is found.  No LLM or external service is involved.
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import re
from typing import Dict, Iterable, List, Optional, Tuple

from src.document_metadata import normalize_document_metadata
from src.text_splitter import OCR_PAGE_METADATA_FIELDS, TextSplitter
from src.word_structure import (
    FALLBACK,
    PDF_HEURISTIC,
    WORD_OUTLINE,
    classify_pdf_candidate,
    heading_match_key,
    normalize_heading_text,
    title_hash,
)


SECTIONING_VERSION = "rd-v2-sectioning/2.0"


_CHINESE_NUMERALS = "零〇一二三四五六七八九十百千两"
_MARKDOWN_HEADING_RE = re.compile(r"^\s*(#{1,6})\s+(.+?)\s*$")
_ARABIC_HEADING_RE = re.compile(
    r"^\s*(\d+(?:\.\d+){0,5})(?:[.、])?\s+(.{1,100}?)\s*$"
)
_CHAPTER_HEADING_RE = re.compile(
    rf"^\s*第\s*([0-9{_CHINESE_NUMERALS}]+)\s*(章|节|部分)\s*(.*)$"
)
_CHINESE_HEADING_RE = re.compile(
    rf"^\s*([{_CHINESE_NUMERALS}]+)、\s*(.{{1,100}}?)\s*$"
)
_PAREN_HEADING_RE = re.compile(
    rf"^\s*[（(]([{_CHINESE_NUMERALS}]+)[）)]\s*(.{{1,100}}?)\s*$"
)
_APPENDIX_HEADING_RE = re.compile(
    r"^\s*(?:Appendix|附录)\s*([A-Za-z0-9一二三四五六七八九十]*)\s*[:：.-]?\s*(.{0,100})$",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class Heading:
    title: str
    level: int
    source: str


def _plausible_title(value: str) -> bool:
    title = value.strip().strip("#").strip()
    if not title or len(title) > 120:
        return False
    # Long prose sentences are much more likely to be body text than headings.
    if len(title) > 50 and title.endswith(("。", ".", "！", "!", "？", "?", "；", ";")):
        return False
    return True


def detect_heading(line: str) -> Optional[Heading]:
    """Recognise a guarded PDF heading without promoting bare list numbers."""
    raw = normalize_heading_text(line)
    classification, level = classify_pdf_candidate(raw)
    if classification == "REAL_HEADING" and level is not None:
        markdown = _MARKDOWN_HEADING_RE.match(raw)
        title = markdown.group(2).strip() if markdown else raw
        return Heading(title, level, PDF_HEURISTIC)
    return None


def classify_heading_candidate(line: str, *, in_table: bool = False) -> str:
    """Expose the repair classifier for body-free QA and regression tests."""
    return classify_pdf_candidate(line, in_table=in_table)[0]


def _stable_resolved_section_id(
    document_id: str,
    source: str,
    level: int,
    title: str,
    occurrence: int,
) -> str:
    payload = f"{document_id}|{source}|{level}|{title_hash(title)}|{occurrence}"
    return f"{document_id}:sec:{hashlib.sha256(payload.encode('utf-8')).hexdigest()[:16]}"


def _unresolved_intervals(sidecar_sections: list[dict]) -> list[tuple[tuple[int, int], tuple[int, int]]]:
    """Return PDF regions where unresolved Word anchors permit heuristics."""
    ordered = sorted(sidecar_sections, key=lambda item: int(item.get("order", 0)))
    intervals: list[tuple[tuple[int, int], tuple[int, int]]] = []
    for index, section in enumerate(ordered):
        if section.get("mapping_status") != "UNRESOLVED":
            continue
        previous = next(
            (item for item in reversed(ordered[:index]) if item.get("mapping_status") != "UNRESOLVED"),
            None,
        )
        following = next(
            (item for item in ordered[index + 1 :] if item.get("mapping_status") != "UNRESOLVED"),
            None,
        )
        lower = (
            (
                int(previous["mapped_start_page"]),
                int(previous.get("mapped_line_start") or 0)
                + int(previous.get("mapped_line_span") or 1),
            )
            if previous
            else (1, 0)
        )
        upper = (
            (int(following["mapped_start_page"]), int(following.get("mapped_line_start") or 0))
            if following
            else (10**9, 10**9)
        )
        intervals.append((lower, upper))
    merged: list[tuple[tuple[int, int], tuple[int, int]]] = []
    for lower, upper in sorted(intervals):
        if merged and lower <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(merged[-1][1], upper))
        else:
            merged.append((lower, upper))
    return merged


def detect_sections(
    pages: Iterable[Dict],
    document_id: str,
    structure_sidecar: Optional[Dict] = None,
) -> Tuple[List[Dict], int]:
    """Resolve Word-first sections while preserving page-local PDF content."""
    sections: List[Dict] = []
    stack: Dict[int, Dict] = {}
    current: Optional[Dict] = None
    heading_count = 0
    occurrence_counts: Dict[Tuple[str, int, str], int] = {}
    created_heading_keys: set[Tuple[int, str]] = set()

    sidecar_sections = []
    if structure_sidecar and structure_sidecar.get("document_id") == document_id:
        sidecar_sections = list(structure_sidecar.get("sections", []))
    mapped_events = {
        (int(item["mapped_start_page"]), int(item.get("mapped_line_start") or 0)): item
        for item in sidecar_sections
        if item.get("mapping_status") not in {None, "UNMAPPED", "UNRESOLVED"}
        and item.get("mapped_start_page") is not None
    }
    mapped_word_keys = [
        (int(item["mapped_start_page"]), heading_match_key(item["normalized_title"]))
        for item in sidecar_sections
        if item.get("mapping_status") not in {None, "UNMAPPED", "UNRESOLVED"}
        and item.get("mapped_start_page") is not None
    ]
    unresolved_intervals = _unresolved_intervals(sidecar_sections)
    started_unresolved_intervals: set[int] = set()

    def unresolved_interval_index(page_number: int, line_index: int) -> Optional[int]:
        position = (page_number, line_index)
        return next(
            (
                index
                for index, (lower, upper) in enumerate(unresolved_intervals)
                if lower <= position <= upper
            ),
            None,
        )

    def new_section(
        title: str,
        level: int,
        page_number: int,
        source: str,
        declared_section_id: Optional[str] = None,
        declared_parent_id: Optional[str] = None,
        mapping_status: Optional[str] = None,
    ) -> Dict:
        nonlocal current
        title = normalize_heading_text(title)
        occurrence_key = (source, level, title_hash(title))
        occurrence_counts[occurrence_key] = occurrence_counts.get(occurrence_key, 0) + 1
        for existing_level in list(stack):
            if existing_level >= level:
                del stack[existing_level]
        derived_parent = stack[max(stack)]["section_id"] if stack else None
        known_ids = {item["section_id"] for item in sections}
        parent_section_id = (
            declared_parent_id if declared_parent_id in known_ids else derived_parent
        )
        section_id = declared_section_id or _stable_resolved_section_id(
            document_id,
            source,
            level,
            title,
            occurrence_counts[occurrence_key],
        )
        current = {
            "section_id": section_id,
            "document_id": document_id,
            "title": title,
            "title_hash": title_hash(title),
            "section_path": [
                stack[key]["title"] for key in sorted(stack) if key < level
            ]
            + [title],
            "level": level,
            "parent_section_id": parent_section_id,
            "start_page": page_number,
            "end_page": page_number,
            "heading_source": source,
            "mapping_status": mapping_status,
            "_page_parts": {},
        }
        sections.append(current)
        if source != FALLBACK:
            stack[level] = current
        return current

    ordered_pages = sorted(pages, key=lambda item: int(item.get("page", 0)))
    for page in ordered_pages:
        page_number = int(page["page"])
        for line_index, line in enumerate(str(page.get("text", "")).splitlines()):
            interval_index = unresolved_interval_index(page_number, line_index)
            word_heading = mapped_events.get((page_number, line_index))
            # Guarded PDF headings (parser H1/H2, chapter, appendix, or Chinese
            # hierarchy) are independent evidence and may supplement Word.
            # Bare Arabic numbering never reaches this path as REAL_HEADING.
            heading = detect_heading(line) if word_heading is None else None
            if heading is not None and any(
                candidate_key == heading_match_key(heading.title)
                and abs(candidate_page - page_number) <= 2
                for candidate_page, candidate_key in mapped_word_keys
            ):
                heading = None
            if heading is not None and (
                page_number,
                heading_match_key(heading.title),
            ) in created_heading_keys:
                heading = None
            if word_heading is not None:
                heading_count += 1
                current = new_section(
                    word_heading["normalized_title"],
                    int(word_heading["level"]),
                    page_number,
                    WORD_OUTLINE,
                    declared_section_id=word_heading["section_id"],
                    declared_parent_id=word_heading.get("parent_section_id"),
                    mapping_status=word_heading.get("mapping_status"),
                )
                created_heading_keys.add(
                    (page_number, heading_match_key(word_heading["normalized_title"]))
                )
            elif heading is not None:
                heading_count += 1
                if interval_index is not None:
                    started_unresolved_intervals.add(interval_index)
                current = new_section(
                    heading.title, heading.level, page_number, heading.source
                )
                created_heading_keys.add(
                    (page_number, heading_match_key(heading.title))
                )
            elif (
                interval_index is not None
                and interval_index not in started_unresolved_intervals
            ):
                started_unresolved_intervals.add(interval_index)
                current = new_section(
                    "Unresolved structure region", 0, page_number, FALLBACK
                )
            elif current is None:
                current = new_section(
                    "Document preamble", 0, page_number, FALLBACK
                )

            current["end_page"] = page_number
            page_parts = current["_page_parts"].setdefault(page_number, [])
            if line.strip():
                page_parts.append(line.rstrip())

    for section in sections:
        page_texts = {
            page_number: "\n".join(parts).strip()
            for page_number, parts in section["_page_parts"].items()
            if "\n".join(parts).strip()
        }
        section["_page_parts"] = page_texts
        section["text"] = "\n\n".join(page_texts.values())
    return sections, heading_count


class SectionAwareTextSplitter(TextSplitter):
    """Add parent sections and retrieval children to the legacy chunk schema."""

    def __init__(
        self,
        child_chunk_size: int = 300,
        child_chunk_overlap: int = 50,
        structure_sidecar: Optional[Dict] = None,
    ):
        self.child_chunk_size = child_chunk_size
        self.child_chunk_overlap = child_chunk_overlap
        self.structure_sidecar = structure_sidecar

    @staticmethod
    def _public_section(section: Dict) -> Dict:
        return {key: value for key, value in section.items() if key != "_page_parts"}

    def _split_report(
        self,
        file_content: Dict[str, object],
        serialized_tables_report_path=None,
        structure_sidecar: Optional[Dict] = None,
    ) -> Dict[str, object]:
        file_content["metainfo"] = normalize_document_metadata(
            file_content.get("metainfo")
        )
        document_id = file_content["metainfo"]["document_id"]
        pages = file_content["content"].get("pages", [])
        active_sidecar = structure_sidecar or self.structure_sidecar
        sections, heading_count = detect_sections(pages, document_id, active_sidecar)
        if heading_count == 0:
            result = super()._split_report(file_content, serialized_tables_report_path)
            result["content"]["section_detection"] = {
                "mode": "legacy_fallback",
                "heading_count": 0,
                "word_heading_count": 0,
                "pdf_heading_count": 0,
                "unresolved_word_count": len(active_sidecar.get("sections", []))
                if active_sidecar
                else 0,
            }
            result["content"]["sections"] = []
            return result

        page_by_number = {int(page["page"]): page for page in pages}
        chunks: List[Dict] = []
        chunk_id = 0
        for section in sections:
            section_child_ids = []
            for page_number, page_text in section["_page_parts"].items():
                source_page = page_by_number[page_number]
                source_page["document_id"] = document_id
                source_page.setdefault("page_number", page_number)
                child_page = {**source_page, "text": page_text}
                page_chunks = self._split_page(
                    child_page,
                    chunk_size=self.child_chunk_size,
                    chunk_overlap=self.child_chunk_overlap,
                )
                for child_index, chunk in enumerate(page_chunks):
                    stable_chunk_id = f"{document_id}:{chunk_id}"
                    chunk.update(
                        {
                            "id": chunk_id,
                            "chunk_id": stable_chunk_id,
                            "document_id": document_id,
                            "type": "content",
                            "section_id": section["section_id"],
                            "parent_id": section["section_id"],
                            "section_title": section["title"],
                            "section_path": list(section["section_path"]),
                            "section_level": section["level"],
                            "section_source": section["heading_source"],
                            "parent_section_id": section.get("parent_section_id"),
                            "section_child_index": child_index,
                        }
                    )
                    chunks.append(chunk)
                    section_child_ids.append(stable_chunk_id)
                    chunk_id += 1
            section["child_chunk_ids"] = section_child_ids

        # Keep serialized-table compatibility without allowing an optional
        # table artifact to abort section-aware ingestion.
        if serialized_tables_report_path is not None:
            try:
                import json

                with open(serialized_tables_report_path, "r", encoding="utf-8") as stream:
                    serialized_report = json.load(stream)
                tables_by_page = self._get_serialized_tables_by_page(
                    serialized_report.get("tables", [])
                )
                page_sections = {}
                for section in sections:
                    for page_number in section["_page_parts"]:
                        page_sections[page_number] = section
                for page_number, tables in sorted(tables_by_page.items()):
                    section = page_sections.get(page_number)
                    if section is None:
                        continue
                    source_page = page_by_number[page_number]
                    for table in tables:
                        stable_chunk_id = f"{document_id}:{chunk_id}"
                        table.update(
                            {
                                "id": chunk_id,
                                "chunk_id": stable_chunk_id,
                                "document_id": document_id,
                                "page_number": page_number,
                                "type": "serialized_table",
                                "section_id": section["section_id"],
                                "parent_id": section["section_id"],
                                "section_title": section["title"],
                                "section_path": list(section["section_path"]),
                                "section_level": section["level"],
                                "section_source": section["heading_source"],
                                "parent_section_id": section.get("parent_section_id"),
                            }
                        )
                        for field in OCR_PAGE_METADATA_FIELDS:
                            if field in source_page:
                                table[field] = source_page[field]
                        chunks.append(table)
                        section["child_chunk_ids"].append(stable_chunk_id)
                        chunk_id += 1
            except FileNotFoundError:
                pass

        file_content["content"]["chunks"] = chunks
        file_content["content"]["sections"] = [
            self._public_section(section) for section in sections
        ]
        file_content["content"]["section_detection"] = {
            "mode": "word_first" if any(
                item["heading_source"] == WORD_OUTLINE for item in sections
            ) else "pdf_heuristic",
            "heading_count": heading_count,
            "word_heading_count": sum(
                item["heading_source"] == WORD_OUTLINE for item in sections
            ),
            "pdf_heading_count": sum(
                item["heading_source"] == PDF_HEURISTIC for item in sections
            ),
            "fallback_section_count": sum(
                item["heading_source"] == FALLBACK for item in sections
            ),
            "unresolved_word_count": sum(
                item.get("mapping_status") == "UNRESOLVED"
                for item in (active_sidecar or {}).get("sections", [])
            ),
        }
        return file_content
