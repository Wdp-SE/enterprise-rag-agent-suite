"""Diagnose section quality without persisting or printing source body text."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import re
import zipfile
from collections import Counter, defaultdict
from pathlib import Path
from xml.etree import ElementTree as ET


os.environ.setdefault("HF_HUB_OFFLINE", "1")
os.environ.setdefault("TRANSFORMERS_OFFLINE", "1")
os.environ.setdefault("DO_NOT_TRACK", "1")

W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
MARKDOWN_RE = re.compile(r"^\s*#{1,6}\s+")
ARABIC_PREFIX_RE = re.compile(r"^\s*(\d+(?:\.\d+){0,5})(?:[.、])?\s+")


def normalize(value: str) -> str:
    return re.sub(r"\s+", " ", value.replace("\u00a0", " ")).strip()


def plain_line(value: str) -> str:
    return normalize(MARKDOWN_RE.sub("", value))


def digest(value: str) -> str:
    return hashlib.sha256(normalize(value).encode("utf-8")).hexdigest()


def load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def length_bucket(length: int) -> str:
    if length <= 10:
        return "1_10"
    if length <= 30:
        return "11_30"
    if length <= 60:
        return "31_60"
    if length <= 120:
        return "61_120"
    return "121_PLUS"


def prefix_pattern(text: str) -> str:
    rules = (
        (r"^\s*\d+(?:\.\d+){1,5}[.、]?\s+", "ARABIC_HIERARCHY_SPACED"),
        (r"^\s*\d+(?:\.\d+){1,5}[.、]?(?=\S)", "ARABIC_HIERARCHY_TIGHT"),
        (r"^\s*\d+[.、]\s+", "ARABIC_SINGLE_SPACED"),
        (r"^\s*\d+[.、](?=\S)", "ARABIC_SINGLE_TIGHT"),
        (r"^\s*[（(]\d+[）)]", "PAREN_ARABIC"),
        (r"^\s*第\s*[0-9零〇一二三四五六七八九十百千两]+\s*(章|节|部分)", "CHAPTER"),
        (r"^\s*[零〇一二三四五六七八九十百千两]+、", "CHINESE_ENUMERATION"),
        (r"^\s*[（(][零〇一二三四五六七八九十百千两]+[）)]", "PAREN_CHINESE"),
        (r"^\s*[-•·●○■□◆◇]", "BULLET_LIKE"),
    )
    for pattern, label in rules:
        if re.match(pattern, text):
            return label
    return "NONE"


def pattern_signature(text: str) -> dict:
    match = ARABIC_PREFIX_RE.match(text)
    return {
        "prefix_pattern": prefix_pattern(text),
        "arabic_depth": match.group(1).count(".") + 1 if match else 0,
        "length_bucket": length_bucket(len(text)),
        "has_cjk": bool(re.search(r"[\u3400-\u9fff]", text)),
        "has_latin": bool(re.search(r"[A-Za-z]", text)),
        "has_digit": bool(re.search(r"\d", text)),
        "ends_with_colon": text.endswith((":", "：")),
        "sentence_terminal": text.endswith(("。", ".", "；", ";", "！", "!", "？", "?")),
    }


def build_pdf_indexes(parsed: dict, merged: dict) -> dict:
    block_types: dict[tuple[int, str], set[str]] = defaultdict(set)
    all_block_hashes: set[str] = set()
    table_hashes: dict[int, set[str]] = defaultdict(set)
    table_counts: Counter[int] = Counter()
    block_type_counts: Counter[str] = Counter()
    tables_by_id = {int(item["table_id"]): item for item in parsed.get("tables", [])}

    for page in parsed.get("content", []):
        page_number = int(page["page"])
        for block in page.get("content", []):
            block_type = str(block.get("type", "unknown"))
            block_type_counts[block_type] += 1
            if block_type == "table":
                table_counts[page_number] += 1
                table = tables_by_id.get(int(block.get("table_id", -1)))
                if table:
                    grid = table.get("json", {}).get("data", {}).get("grid", [])
                    for row in grid:
                        cells = [plain_line(str(cell.get("text", ""))) for cell in row]
                        cells = [cell for cell in cells if cell]
                        for cell in cells:
                            table_hashes[page_number].add(digest(cell))
                        if cells:
                            table_hashes[page_number].add(digest(" ".join(cells)))
                continue
            text = plain_line(str(block.get("text", "")))
            if not text:
                continue
            value_hash = digest(text)
            block_types[(page_number, value_hash)].add(block_type)
            all_block_hashes.add(value_hash)
            marker = plain_line(str(block.get("marker", "")))
            if marker:
                display_hash = digest(f"{marker} {text}")
                block_types[(page_number, display_hash)].add(block_type)
                all_block_hashes.add(display_hash)

    merged_lines_by_page: dict[int, list[str]] = {}
    all_line_hashes: set[str] = set()
    for page in merged.get("content", {}).get("pages", []):
        page_number = int(page["page"])
        lines = [plain_line(line) for line in str(page.get("text", "")).splitlines()]
        lines = [line for line in lines if line]
        merged_lines_by_page[page_number] = lines
        all_line_hashes.update(digest(line) for line in lines)

    return {
        "block_types": block_types,
        "all_block_hashes": all_block_hashes,
        "table_hashes": table_hashes,
        "table_counts": table_counts,
        "block_type_counts": block_type_counts,
        "merged_lines_by_page": merged_lines_by_page,
        "all_line_hashes": all_line_hashes,
    }


def word_matches(word_records: list[dict], title_hash: str, page_number: int) -> list[dict]:
    exact_page = [
        item
        for item in word_records
        if item.get("normalized_text_sha256") == title_hash
        and abs(int(item.get("page_number") or 0) - page_number) <= 1
    ]
    if exact_page:
        return exact_page
    return [item for item in word_records if item.get("normalized_text_sha256") == title_hash]


def classify_section(
    title: str,
    page_number: int,
    pdf: dict,
    word_records: list[dict],
) -> tuple[str, str, list[dict], set[str]]:
    title_hash = digest(title)
    matches = word_matches(word_records, title_hash, page_number)
    block_types = pdf["block_types"].get((page_number, title_hash), set())
    in_table = title_hash in pdf["table_hashes"].get(page_number, set())

    if any(item.get("heading_style") or item.get("outline_candidate") for item in matches):
        return "REAL_HEADING", "word_heading_or_outline", matches, block_types
    if block_types.intersection({"section_header", "page_header"}):
        return "REAL_HEADING", "pdf_semantic_heading", matches, block_types
    if in_table or any(item.get("in_table") for item in matches):
        return "TABLE_ROW", "table_membership", matches, block_types
    if "list_item" in block_types or any(item.get("automatic_numbering") for item in matches):
        return "NUMBERED_LIST_ITEM", "list_semantics", matches, block_types

    signature = pattern_signature(title)
    if matches:
        if any(item.get("prefix_pattern") != "NONE" for item in matches):
            return "NUMBERED_LIST_ITEM", "word_nonstructural_numbered_paragraph", matches, block_types
        if any(item.get("ends_with_colon") for item in matches):
            return "FIELD_LABEL", "word_colon_label", matches, block_types
        if any(item.get("sentence_terminal") for item in matches):
            return "BODY_SENTENCE", "word_body_sentence", matches, block_types
    if "paragraph" in block_types:
        if signature["ends_with_colon"]:
            return "FIELD_LABEL", "pdf_paragraph_colon_label", matches, block_types
        if signature["prefix_pattern"] != "NONE":
            return "NUMBERED_LIST_ITEM", "pdf_nonsemantic_numbered_paragraph", matches, block_types
        if signature["sentence_terminal"] or len(title) > 60:
            return "BODY_SENTENCE", "pdf_paragraph_sentence", matches, block_types
    if block_types.intersection({"text", "caption", "footnote"}):
        return "BODY_SENTENCE", "pdf_body_block", matches, block_types
    return "UNKNOWN", "insufficient_structural_evidence", matches, block_types


def band_for(page: int, pages: int) -> str:
    ratio = page / max(pages, 1)
    if ratio <= 0.2:
        return "front"
    if 0.4 <= ratio <= 0.6:
        return "middle"
    if ratio >= 0.8:
        return "back"
    return "intermediate"


def sample_rows(rows: list[dict], pages: int, table_counts: Counter[int]) -> tuple[list[dict], dict]:
    number_counts = Counter(item["page_number"] for item in rows if item["pattern_signature"]["prefix_pattern"] != "NONE")
    section_pages = {item["page_number"] for item in rows}
    table_dense_pages = {
        page
        for page, _ in sorted(
            ((page, count) for page, count in table_counts.items() if page in section_pages),
            key=lambda pair: (-pair[1], pair[0]),
        )[:20]
    }
    numbered_dense_pages = {
        page for page, _ in sorted(number_counts.items(), key=lambda pair: (-pair[1], pair[0]))[:20]
    }
    pools = {
        "front": [item for item in rows if item["page_band"] == "front"],
        "middle": [item for item in rows if item["page_band"] == "middle"],
        "back": [item for item in rows if item["page_band"] == "back"],
        "table_dense": [item for item in rows if item["page_number"] in table_dense_pages],
        "numbered_list_dense": [item for item in rows if item["page_number"] in numbered_dense_pages],
    }
    samples = []
    coverage = {}
    for stratum, pool in pools.items():
        ordered = sorted(
            pool,
            key=lambda item: hashlib.sha256(
                f"{stratum}|{item['section_id']}".encode("utf-8")
            ).hexdigest(),
        )
        chosen = ordered[: min(12, len(ordered))]
        coverage[stratum] = {"candidate_count": len(pool), "sample_count": len(chosen)}
        for item in chosen:
            samples.append(
                {
                    "sample_id": hashlib.sha256(
                        f"qa|{stratum}|{item['section_id']}".encode("utf-8")
                    ).hexdigest()[:16],
                    "stratum": stratum,
                    "section_id": item["section_id"],
                    "page_number": item["page_number"],
                    "page_band": item["page_band"],
                    "classification": item["classification"],
                    "classification_evidence": item["classification_evidence"],
                    "heading_source": item["heading_source"],
                    "source_block_types": item["source_block_types"],
                    "word_structure_match": item["word_structure_match"],
                    "pattern_signature": item["pattern_signature"],
                    "body_text_included": False,
                }
            )
    return samples, coverage


def analyze_document(
    corpus_root: Path,
    metadata: dict,
    word_document: dict,
) -> dict:
    document_id = metadata["document_id"]
    parsed = load_json(corpus_root / "normalized" / "parsed" / document_id / f"{document_id}.json")
    merged = load_json(corpus_root / "normalized" / "merged" / document_id / f"{document_id}.json")
    chunked = load_json(corpus_root / "normalized" / "chunked" / document_id / f"{document_id}.json")
    structure_stats = load_json(corpus_root / "manifest" / f"{document_id}.structure_stats.json")
    pdf = build_pdf_indexes(parsed, merged)
    records = word_document.get("paragraph_records", [])
    sections = chunked.get("content", {}).get("sections", [])
    chunks = chunked.get("content", {}).get("chunks", [])

    rows = []
    class_counts: Counter[str] = Counter()
    evidence_counts: Counter[str] = Counter()
    level_counts: Counter[str] = Counter()
    hierarchy_jumps = 0
    path_depth_mismatches = 0
    sections_without_children = 0
    previous_level = None
    for section in sections:
        title = plain_line(str(section.get("title", "")))
        page_number = int(section.get("start_page", 0))
        classification, evidence, matches, block_types = classify_section(
            title, page_number, pdf, records
        )
        level = int(section.get("level", 0))
        if previous_level is not None and level > previous_level + 1:
            hierarchy_jumps += 1
        previous_level = level
        expected_min_path = 1 if level == 0 else level
        if len(section.get("section_path", [])) < expected_min_path:
            path_depth_mismatches += 1
        if not section.get("child_chunk_ids"):
            sections_without_children += 1
        level_counts[str(level)] += 1
        class_counts[classification] += 1
        evidence_counts[evidence] += 1
        rows.append(
            {
                "section_id": section.get("section_id"),
                "page_number": page_number,
                "page_band": band_for(page_number, structure_stats["canonical_pdf_pages"]),
                "classification": classification,
                "classification_evidence": evidence,
                "heading_source": section.get("heading_source", "unknown"),
                "source_block_types": sorted(block_types),
                "word_structure_match": bool(matches),
                "pattern_signature": pattern_signature(title),
            }
        )

    structural_records = [
        item for item in records if item.get("heading_style") or item.get("outline_candidate")
    ]
    # The current PDF parse does not retain a reliable table-block signal on every
    # page.  Word COM was opened read-only against staged, hash-identical copies and
    # supplies physical page numbers for structural candidates found inside tables.
    # Use that metadata only to choose the table-dense QA stratum; it does not alter
    # section detection, hierarchy, chunking, or citation page mapping.
    word_table_counts: Counter[int] = Counter(
        int(item.get("page_number") or 0)
        for item in records
        if item.get("in_table") and int(item.get("page_number") or 0) > 0
    )
    false_types = {"NUMBERED_LIST_ITEM", "TABLE_ROW", "FIELD_LABEL", "BODY_SENTENCE"}
    false_count = sum(class_counts[item] for item in false_types)
    real_count = class_counts["REAL_HEADING"]
    unknown_count = class_counts["UNKNOWN"]
    section_count = len(sections)
    false_ratio = false_count / section_count if section_count else 0.0
    real_ratio = real_count / section_count if section_count else 0.0
    unknown_ratio = unknown_count / section_count if section_count else 0.0
    conservative_max_real = min(section_count, len(structural_records) + real_count)
    conservative_min_false = max(0, section_count - conservative_max_real)
    conservative_min_false_ratio = (
        conservative_min_false / section_count if section_count else 0.0
    )
    if section_count == 0:
        oversegmented = "NO"
    elif conservative_min_false_ratio >= 0.20:
        oversegmented = "YES"
    elif unknown_ratio > 0.50:
        oversegmented = "INCONCLUSIVE"
    else:
        oversegmented = "NO"

    section_hashes = {
        digest(plain_line(str(item.get("title", "")))) for item in sections if item.get("title")
    }
    structural_visible_in_pdf = sum(
        item.get("normalized_text_sha256") in pdf["all_line_hashes"] for item in structural_records
    )
    structural_detected = sum(
        item.get("normalized_text_sha256") in section_hashes for item in structural_records
    )
    samples, sampling_coverage = sample_rows(
        rows,
        structure_stats["canonical_pdf_pages"],
        pdf["table_counts"] + word_table_counts,
    )

    parent_ids = {item.get("section_id") for item in sections}
    invalid_child_parents = sum(
        not item.get("parent_id") or item.get("parent_id") not in parent_ids for item in chunks
    )
    return {
        "document_id": document_id,
        "document_type": metadata["document_type"],
        "pages": structure_stats["canonical_pdf_pages"],
        "current_section_count": section_count,
        "sections_per_page": round(section_count / structure_stats["canonical_pdf_pages"], 4),
        "current_child_chunk_count": len(chunks),
        "classification_counts": dict(sorted(class_counts.items())),
        "classification_evidence_counts": dict(sorted(evidence_counts.items())),
        "real_heading_ratio": round(real_ratio, 6),
        "false_heading_ratio": round(false_ratio, 6),
        "conservative_max_real_heading_count": conservative_max_real,
        "conservative_min_false_heading_count": conservative_min_false,
        "conservative_min_false_heading_ratio": round(conservative_min_false_ratio, 6),
        "unknown_ratio": round(unknown_ratio, 6),
        "oversegmented": oversegmented,
        "word_structural_candidates": len(structural_records),
        "word_structural_candidates_visible_in_pdf": structural_visible_in_pdf,
        "word_structural_candidates_detected_as_sections": structural_detected,
        "heading_misses": max(0, structural_visible_in_pdf - structural_detected),
        "table_density_evidence": {
            "pdf_table_pages": len(pdf["table_counts"]),
            "word_table_pages_with_structural_candidates": len(word_table_counts),
            "usage": "sampling_only",
        },
        "parent_hierarchy": {
            "level_counts": dict(sorted(level_counts.items(), key=lambda pair: int(pair[0]))),
            "hierarchy_level_jumps": hierarchy_jumps,
            "path_depth_mismatches": path_depth_mismatches,
            "sections_without_child_chunks": sections_without_children,
            "invalid_child_parent_mappings": invalid_child_parents,
        },
        "pdf_block_type_counts": dict(sorted(pdf["block_type_counts"].items())),
        "table_dense_page_count": len([value for value in pdf["table_counts"].values() if value]),
        "sampling_coverage": sampling_coverage,
        "qa_samples": samples,
        "citation_page_mapping_valid": structure_stats["citation_page_mapping_valid"],
        "fallback_chunk_count": structure_stats["fallback_chunk_count"],
        "body_text_included": False,
    }


def read_docx_paragraphs(path: Path) -> list[str]:
    with zipfile.ZipFile(path) as package:
        document = ET.fromstring(package.read("word/document.xml"))
    return [
        normalize("".join(node.text or "" for node in paragraph.iter(W + "t")))
        for paragraph in document.iter(W + "p")
        if normalize("".join(node.text or "" for node in paragraph.iter(W + "t")))
    ]


def requirements_analysis(
    corpus_root: Path,
    metadata: dict,
    ooxml: dict,
    word_document: dict,
) -> dict:
    document_id = metadata["document_id"]
    staged = corpus_root / metadata["staged_relative_path"]
    paragraphs = read_docx_paragraphs(staged)
    merged = load_json(corpus_root / "normalized" / "merged" / document_id / f"{document_id}.json")
    parsed = load_json(corpus_root / "normalized" / "parsed" / document_id / f"{document_id}.json")
    pdf_lines = []
    for page in merged.get("content", {}).get("pages", []):
        pdf_lines.extend(
            plain_line(line) for line in str(page.get("text", "")).splitlines() if plain_line(line)
        )
    pdf_hashes = {digest(line) for line in pdf_lines}
    paragraph_hashes = [digest(item) for item in paragraphs]
    word_hash_counts = Counter(paragraph_hashes)
    pdf_hash_counts = Counter(digest(line) for line in pdf_lines)
    exact_matches = sum((word_hash_counts & pdf_hash_counts).values())
    outline_records = [
        item for item in ooxml["paragraph_records"] if item.get("outline_level") is not None
    ]
    outline_exact = sum(item["normalized_text_sha256"] in pdf_hashes for item in outline_records)
    outline_in_tables = 0
    parsed_table_hashes = set()
    for table in parsed.get("tables", []):
        for row in table.get("json", {}).get("data", {}).get("grid", []):
            for cell in row:
                text = plain_line(str(cell.get("text", "")))
                if text:
                    parsed_table_hashes.add(digest(text))
    outline_in_tables = sum(
        item["normalized_text_sha256"] in parsed_table_hashes for item in outline_records
    )

    split_matches = 0
    for item in outline_records:
        target = item["normalized_text_sha256"]
        if target in pdf_hashes:
            continue
        if any(digest(f"{pdf_lines[index]} {pdf_lines[index + 1]}") == target for index in range(len(pdf_lines) - 1)):
            split_matches += 1

    first_position_by_hash = {}
    for index, line in enumerate(pdf_lines):
        first_position_by_hash.setdefault(digest(line), index)
    outline_positions = [
        first_position_by_hash[item["normalized_text_sha256"]]
        for item in outline_records
        if item["normalized_text_sha256"] in first_position_by_hash
    ]
    outline_order_inversions = sum(
        outline_positions[index] < outline_positions[index - 1]
        for index in range(1, len(outline_positions))
    )
    paragraph_text_by_hash = {digest(item): item for item in paragraphs}
    com_records_by_hash: dict[str, list[dict]] = defaultdict(list)
    for item in word_document.get("paragraph_records", []):
        com_records_by_hash[item["normalized_text_sha256"]].append(item)
    outline_anchor_samples = []
    for item in outline_records:
        value_hash = item["normalized_text_sha256"]
        text = paragraph_text_by_hash.get(value_hash, "")
        com_match = com_records_by_hash.get(value_hash, [])
        outline_anchor_samples.append(
            {
                "sample_id": hashlib.sha256(
                    f"requirements-outline|{item['ordinal']}|{value_hash}".encode("utf-8")
                ).hexdigest()[:16],
                "source_word_ordinal": item["ordinal"],
                "word_page_number": int(com_match[0].get("page_number") or 0) if com_match else 0,
                "outline_level": item["outline_level"],
                "style_class": com_match[0].get("style_class", item.get("style_class")) if com_match else item.get("style_class"),
                "pattern_signature": pattern_signature(text) if text else None,
                "visible_as_exact_pdf_line": value_hash in pdf_hashes,
                "split_across_pdf_lines": (
                    value_hash not in pdf_hashes
                    and any(
                        digest(f"{pdf_lines[index]} {pdf_lines[index + 1]}") == value_hash
                        for index in range(len(pdf_lines) - 1)
                    )
                ),
                "detected_as_current_section": False,
                "classification": "HEADING_MISS",
                "body_text_included": False,
            }
        )

    word_paren = ooxml["prefix_pattern_counts"].get("PAREN_ARABIC", 0)
    pdf_paren = sum(prefix_pattern(line) == "PAREN_ARABIC" for line in pdf_lines)
    word_structure = "PARTIAL" if outline_records else "NO"
    if outline_records and outline_exact == len(outline_records):
        failure_cause = "WORD_STRUCTURE_LOST"
        contributing = ["REGEX_NOT_COVERED"]
    elif ooxml.get("structural_candidates_in_tables", 0) or outline_in_tables:
        failure_cause = "TABLE_BASED_STRUCTURE"
        contributing = ["REGEX_NOT_COVERED"]
    elif not outline_records and not ooxml.get("heading_style_paragraphs"):
        failure_cause = "DOCUMENT_HAS_NO_REAL_HEADINGS"
        contributing = ["REGEX_NOT_COVERED"] if word_paren else []
    else:
        failure_cause = "OTHER"
        contributing = []

    return {
        "document_id": document_id,
        "failure_cause": failure_cause,
        "contributing_causes": contributing,
        "word_has_structure": word_structure,
        "word_heading_style_paragraphs": word_document["heading_style_paragraphs"],
        "word_outline_level_paragraphs": word_document["outline_level_paragraphs"],
        "word_automatic_numbering_paragraphs": word_document["automatic_numbering_paragraphs"],
        "word_toc_field_count": word_document["toc_count"],
        "word_multilevel_numbering_definitions": ooxml["multilevel_numbering_definitions"],
        "word_paragraphs_in_tables": word_document["paragraphs_in_tables"],
        "word_parenthesized_arabic_items": word_paren,
        "word_current_detector_matches": ooxml["current_detector_matches_on_word_paragraphs"],
        "pdf_parsed_table_count": len(parsed.get("tables", [])),
        "word_nonempty_paragraphs": word_document["nonempty_paragraph_count"],
        "word_paragraphs_exactly_preserved_as_pdf_lines": exact_matches,
        "word_to_pdf_exact_line_ratio": round(exact_matches / len(paragraphs), 6) if paragraphs else 0.0,
        "outline_anchors_exactly_preserved_in_pdf": outline_exact,
        "outline_anchors_split_across_pdf_lines": split_matches,
        "outline_anchors_entered_pdf_tables": outline_in_tables,
        "pdf_parenthesized_arabic_items": pdf_paren,
        "numbering_preserved": pdf_paren >= word_paren and word_paren > 0,
        "outline_anchor_order_inversions": outline_order_inversions,
        "outline_anchor_order_preserved": outline_order_inversions == 0,
        "heading_miss_qa_samples": outline_anchor_samples,
        "body_text_included": False,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--corpus-root", type=Path, required=True)
    parser.add_argument("--word-audit", type=Path, required=True)
    parser.add_argument("--requirements-ooxml", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    corpus_root = args.corpus_root.resolve()
    manifest = load_json(corpus_root / "manifest" / "normalization_manifest.json")
    word_audit = load_json(args.word_audit)
    ooxml = load_json(args.requirements_ooxml)
    word_by_id = {item["document_id"]: item for item in word_audit["documents"]}
    documents = []
    for metadata in manifest["documents"]:
        documents.append(
            analyze_document(corpus_root, metadata, word_by_id[metadata["document_id"]])
        )
    requirements_meta = next(
        item for item in manifest["documents"] if item["document_type"] == "requirements"
    )
    requirements = requirements_analysis(
        corpus_root,
        requirements_meta,
        ooxml,
        word_by_id[requirements_meta["document_id"]],
    )
    payload = {
        "schema_version": 1,
        "diagnostic_scope": "section_structure_only",
        "requirements": requirements,
        "documents": documents,
        "online_models_called": False,
        "embedding_or_retrieval_run": False,
        "body_text_included": False,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    temporary = args.output.with_suffix(args.output.suffix + ".partial")
    if temporary.exists() or args.output.exists():
        raise SystemExit("Refusing to overwrite an existing section diagnostic artifact")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(args.output)
    print(
        json.dumps(
            {
                "requirements_failure_cause": requirements["failure_cause"],
                "requirements_word_has_structure": requirements["word_has_structure"],
                "documents": [
                    {
                        "document_type": item["document_type"],
                        "sections": item["current_section_count"],
                        "classification_counts": item["classification_counts"],
                        "oversegmented": item["oversegmented"],
                    }
                    for item in documents
                ],
            },
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
