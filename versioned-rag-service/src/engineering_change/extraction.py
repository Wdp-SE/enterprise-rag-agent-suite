"""Organization adapters and deterministic DOCX engineering-item extraction."""

from __future__ import annotations

import hashlib
import re
from pathlib import Path
from typing import Iterable

from docx import Document
from docx.oxml.ns import qn
from docx.table import Table
from docx.text.paragraph import Paragraph

from .models import (
    EngineeringItem,
    IdentifierMatch,
    OrganizationProfile,
    ParsedEngineeringSection,
    content_hash,
    normalize_text,
)


HEADING = re.compile(r"^(?:Heading|标题)\s*([1-6])$", re.IGNORECASE)


def _body_blocks(document) -> Iterable[Paragraph | Table]:
    for child in document.element.body.iterchildren():
        if child.tag.endswith("}p"):
            yield Paragraph(child, document)
        elif child.tag.endswith("}tbl"):
            yield Table(child, document)


def _heading_level(paragraph: Paragraph) -> int | None:
    match = HEADING.match(paragraph.style.name or "")
    if match:
        return int(match.group(1))
    properties = paragraph._p.pPr
    outline = properties.find(qn("w:outlineLvl")) if properties is not None else None
    if outline is None:
        return None
    value = int(outline.get(qn("w:val"))) + 1
    return value if 1 <= value <= 6 else None


class IdentifierExtractor:
    def extract(self, text: str, profile: OrganizationProfile) -> list[IdentifierMatch]:
        matches: list[IdentifierMatch] = []
        seen: set[tuple[int, int, str]] = set()
        for item_type, patterns in profile.identifier_patterns.items():
            for pattern in patterns:
                for match in re.finditer(pattern, text, flags=re.IGNORECASE):
                    identifier = normalize_text(match.group(0)).upper()
                    identity = (match.start(), match.end(), identifier)
                    if identity in seen:
                        continue
                    seen.add(identity)
                    matches.append(IdentifierMatch(
                        external_identifier=identifier,
                        item_type=item_type,
                        start=match.start(),
                        end=match.end(),
                    ))
        return sorted(matches, key=lambda item: (item.start, item.end, item.external_identifier))


class DocxEngineeringParser:
    """Parse the supported Heading/Paragraph/Table subset into section records."""

    def parse(self, path: str | Path, profile: OrganizationProfile) -> list[ParsedEngineeringSection]:
        source = Path(path).resolve()
        if source.suffix.lower() != ".docx" or not source.is_file():
            raise ValueError("source must be an existing .docx file")
        document = Document(source)
        heading_stack: list[tuple[int, str]] = []
        current_path: list[str] = []
        content_by_path: dict[tuple[str, ...], list[str]] = {}
        order: list[tuple[str, ...]] = []
        complex_paths: set[tuple[str, ...]] = set()
        for block in _body_blocks(document):
            if isinstance(block, Paragraph):
                level = _heading_level(block)
                text = normalize_text(block.text)
                if level is not None and text:
                    while heading_stack and heading_stack[-1][0] >= level:
                        heading_stack.pop()
                    heading_stack.append((level, profile.canonical_section(text)))
                    current_path = [item[1] for item in heading_stack]
                    continue
                if not text:
                    continue
                if not current_path:
                    current_path = ["ROOT"]
                key = tuple(current_path)
                if key not in content_by_path:
                    content_by_path[key] = []
                    order.append(key)
                content_by_path[key].append(text)
                if block._p.xpath(".//w:drawing|.//w:pict|.//m:oMath"):
                    complex_paths.add(key)
            else:
                if not current_path:
                    current_path = ["ROOT"]
                key = tuple(current_path)
                if key not in content_by_path:
                    content_by_path[key] = []
                    order.append(key)
                for row in block.rows:
                    cells = [normalize_text(cell.text) for cell in row.cells]
                    if any(cells):
                        content_by_path[key].append(" | ".join(cells))
                if any(cell._tc.xpath(".//w:drawing|.//w:pict|.//m:oMath") for row in block.rows for cell in row.cells):
                    complex_paths.add(key)
        sections: list[ParsedEngineeringSection] = []
        for position, key in enumerate(order, start=1):
            content = "\n".join(content_by_path[key]).strip()
            if not content:
                continue
            identity = "/".join(key).casefold()
            complex_content = key in complex_paths
            sections.append(ParsedEngineeringSection(
                section_id=f"sec_{hashlib.sha256(identity.encode('utf-8')).hexdigest()[:16]}",
                section_path=list(key),
                content=content,
                metadata={
                    "position": position,
                    "complex_content_present": complex_content,
                    "requires_manual_complex_content_review": complex_content,
                },
            ))
        if not sections:
            raise ValueError("DOCX has no supported engineering content")
        return sections


class EngineeringItemFactory:
    def __init__(self, extractor: IdentifierExtractor):
        self.extractor = extractor

    def build(
        self,
        *,
        sections: list[ParsedEngineeringSection],
        profile: OrganizationProfile,
        project_id: str,
        document_id: str,
        version_id: str,
        document_type: str,
    ) -> list[EngineeringItem]:
        default_type = profile.document_type(document_type)
        result: list[EngineeringItem] = []
        seen: set[tuple[str, str]] = set()
        for section in sections:
            for match in self.extractor.extract(section.content, profile):
                identity = (section.section_id, match.external_identifier)
                if identity in seen:
                    continue
                seen.add(identity)
                id_parts = {
                    "organization_id": profile.organization_id,
                    "project_id": project_id,
                    "document_id": document_id,
                    "version_id": version_id,
                    "section_id": section.section_id,
                    "external_identifier": match.external_identifier,
                }
                result.append(EngineeringItem(
                    item_id=EngineeringItem.stable_id(id_parts),
                    item_type=match.item_type,
                    organization_id=profile.organization_id,
                    project_id=normalize_text(project_id),
                    document_id=normalize_text(document_id),
                    version_id=normalize_text(version_id),
                    section_id=section.section_id,
                    external_identifier=match.external_identifier,
                    title=f"{match.external_identifier} · {section.section_path[-1]}",
                    content=section.content,
                    content_hash=content_hash(section.content),
                    metadata={
                        **section.metadata,
                        "section_path": section.section_path,
                        "source_document_type": document_type,
                        "default_document_item_type": default_type.value,
                    },
                ))
        return result

