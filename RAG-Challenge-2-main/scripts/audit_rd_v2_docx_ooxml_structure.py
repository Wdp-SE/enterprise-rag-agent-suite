"""Inspect DOCX structure without persisting or printing document body text."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import zipfile
from collections import Counter
from pathlib import Path
from xml.etree import ElementTree as ET


W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
HEADING_NAME_RE = re.compile(r"(?i)(?:heading\s*[1-9]|标题\s*[1-9])")
ARABIC_RE = re.compile(r"^\s*(\d+(?:\.\d+){0,5})(?:[.、])?\s+(.{1,100}?)\s*$")
CHAPTER_RE = re.compile(r"^\s*第\s*([0-9零〇一二三四五六七八九十百千两]+)\s*(章|节|部分)\s*(.*)$")
CHINESE_RE = re.compile(r"^\s*([零〇一二三四五六七八九十百千两]+)、\s*(.{1,100}?)\s*$")
PAREN_CHINESE_RE = re.compile(r"^\s*[（(]([零〇一二三四五六七八九十百千两]+)[）)]\s*(.{1,100}?)\s*$")
APPENDIX_RE = re.compile(r"^\s*(?:Appendix|附录)\s*([A-Za-z0-9一二三四五六七八九十]*)\s*[:：.-]?\s*(.{0,100})$", re.I)


def normalize(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip()


def digest(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


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


def current_detector_match(text: str) -> bool:
    return bool(
        ARABIC_RE.match(text)
        or CHAPTER_RE.match(text)
        or CHINESE_RE.match(text)
        or PAREN_CHINESE_RE.match(text)
        or APPENDIX_RE.match(text)
    )


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


def attr(element: ET.Element | None, name: str) -> str | None:
    if element is None:
        return None
    return element.get(W + name)


def classify_style(style_id: str | None, name: str | None) -> str:
    combined = " ".join(item for item in (style_id, name) if item)
    if HEADING_NAME_RE.search(combined):
        return "HEADING"
    if re.search(r"(?i)^\s*(title|标题)\s*$", combined):
        return "TITLE"
    if re.search(r"(?i)toc|目录", combined):
        return "TOC"
    if re.search(r"(?i)caption|题注", combined):
        return "CAPTION"
    if re.search(r"(?i)normal|正文|body\s*text", combined):
        return "BODY"
    return "CUSTOM" if combined else "UNKNOWN"


def paragraph_text(paragraph: ET.Element) -> str:
    return normalize("".join(node.text or "" for node in paragraph.iter(W + "t")))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--document-id", required=True)
    parser.add_argument("--expected-sha256", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    file_hash = hashlib.sha256(args.input.read_bytes()).hexdigest()
    if file_hash != args.expected_sha256:
        raise SystemExit("Input DOCX hash does not match the source manifest")

    with zipfile.ZipFile(args.input) as package:
        document = ET.fromstring(package.read("word/document.xml"))
        styles_root = ET.fromstring(package.read("word/styles.xml"))
        numbering_root = (
            ET.fromstring(package.read("word/numbering.xml"))
            if "word/numbering.xml" in package.namelist()
            else None
        )

    styles: dict[str, dict] = {}
    for style in styles_root.findall(W + "style"):
        style_id = attr(style, "styleId") or ""
        ppr = style.find(W + "pPr")
        styles[style_id] = {
            "name": attr(style.find(W + "name"), "val"),
            "based_on": attr(style.find(W + "basedOn"), "val"),
            "outline": attr(ppr.find(W + "outlineLvl"), "val") if ppr is not None else None,
            "num_id": attr(ppr.find(f"{W}numPr/{W}numId"), "val") if ppr is not None else None,
            "ilvl": attr(ppr.find(f"{W}numPr/{W}ilvl"), "val") if ppr is not None else None,
        }

    def resolve_style(style_id: str | None) -> dict:
        resolved = {"outline": None, "num_id": None, "ilvl": None, "style_class": "UNKNOWN"}
        seen = set()
        current = style_id
        while current and current not in seen and current in styles:
            seen.add(current)
            value = styles[current]
            if resolved["outline"] is None:
                resolved["outline"] = value["outline"]
            if resolved["num_id"] is None:
                resolved["num_id"] = value["num_id"]
                resolved["ilvl"] = value["ilvl"]
            candidate = classify_style(current, value["name"])
            if candidate != "CUSTOM" and candidate != "UNKNOWN":
                resolved["style_class"] = candidate
            current = value["based_on"]
        if resolved["style_class"] == "UNKNOWN" and style_id:
            resolved["style_class"] = "CUSTOM"
        return resolved

    table_paragraph_ids = {
        id(paragraph)
        for table in document.iter(W + "tbl")
        for paragraph in table.iter(W + "p")
    }
    paragraphs = list(document.iter(W + "p"))
    records = []
    style_counts: Counter[str] = Counter()
    prefix_counts: Counter[str] = Counter()
    outline_counts: Counter[str] = Counter()
    numbered_count = 0
    multilevel_paragraphs = 0
    heading_style_count = 0
    outline_count = 0
    structural_in_table = 0
    detector_matches = 0
    split_run_candidates = 0
    number_only_then_text = 0
    prior_number_only = False

    for ordinal, paragraph in enumerate(paragraphs, 1):
        text = paragraph_text(paragraph)
        if not text:
            continue
        ppr = paragraph.find(W + "pPr")
        style_id = attr(ppr.find(W + "pStyle"), "val") if ppr is not None else None
        resolved = resolve_style(style_id)
        direct_outline = attr(ppr.find(W + "outlineLvl"), "val") if ppr is not None else None
        outline = direct_outline if direct_outline is not None else resolved["outline"]
        direct_num_id = attr(ppr.find(f"{W}numPr/{W}numId"), "val") if ppr is not None else None
        direct_ilvl = attr(ppr.find(f"{W}numPr/{W}ilvl"), "val") if ppr is not None else None
        num_id = direct_num_id if direct_num_id is not None else resolved["num_id"]
        ilvl = direct_ilvl if direct_ilvl is not None else resolved["ilvl"]
        style_class = resolved["style_class"]
        is_outline = outline is not None and outline not in {"9", "10"}
        is_numbered = num_id not in {None, "0"}
        in_table = id(paragraph) in table_paragraph_ids
        pattern = prefix_pattern(text)
        detector_match = current_detector_match(text)
        run_texts = [normalize("".join(node.text or "" for node in run.iter(W + "t"))) for run in paragraph.findall(W + "r")]
        run_texts = [item for item in run_texts if item]
        split_run = len(run_texts) > 1 and bool(re.fullmatch(r"[（(]?[0-9一二三四五六七八九十]+[.、）)]?", run_texts[0]))
        number_only = bool(re.fullmatch(r"[（(]?[0-9一二三四五六七八九十]+(?:\.[0-9]+)*[.、）)]?", text))
        if prior_number_only and not number_only:
            number_only_then_text += 1
        prior_number_only = number_only

        style_counts[style_class] += 1
        prefix_counts[pattern] += 1
        outline_counts[str(outline) if outline is not None else "body"] += 1
        numbered_count += int(is_numbered)
        multilevel_paragraphs += int(is_numbered and ilvl not in {None, "0"})
        heading_style_count += int(style_class == "HEADING")
        outline_count += int(is_outline)
        structural_in_table += int(in_table and (is_numbered or is_outline or style_class == "HEADING" or pattern != "NONE"))
        detector_matches += int(detector_match)
        split_run_candidates += int(split_run)
        records.append(
            {
                "ordinal": ordinal,
                "normalized_text_sha256": digest(text),
                "text_length_bucket": length_bucket(len(text)),
                "style_class": style_class,
                "outline_level": int(outline) if outline is not None and outline.isdigit() else None,
                "automatic_numbering": is_numbered,
                "numbering_level": int(ilvl) if ilvl is not None and ilvl.isdigit() else None,
                "prefix_pattern": pattern,
                "in_table": in_table,
                "current_detector_match": detector_match,
                "number_title_split_across_runs": split_run,
                "ends_with_colon": text.endswith((":", "：")),
                "sentence_terminal": text.endswith(("。", ".", "；", ";")),
            }
        )

    abstract_definitions = 0
    multilevel_definitions = 0
    level_count_distribution: Counter[str] = Counter()
    if numbering_root is not None:
        for abstract in numbering_root.findall(W + "abstractNum"):
            abstract_definitions += 1
            levels = abstract.findall(W + "lvl")
            level_count_distribution[str(len(levels))] += 1
            multi_type = attr(abstract.find(W + "multiLevelType"), "val")
            if len(levels) > 1 or multi_type in {"multilevel", "hybridMultilevel"}:
                multilevel_definitions += 1

    instr_text = " ".join(node.text or "" for node in document.iter(W + "instrText"))
    payload = {
        "schema_version": 1,
        "document_id": args.document_id,
        "source_sha256": file_hash,
        "inspection_mode": "direct_ooxml_read_only",
        "paragraph_count": len(paragraphs),
        "nonempty_paragraph_count": len(records),
        "table_count": sum(1 for _ in document.iter(W + "tbl")),
        "paragraphs_in_tables": sum(record["in_table"] for record in records),
        "heading_style_paragraphs": heading_style_count,
        "outline_level_paragraphs": outline_count,
        "automatic_numbering_paragraphs": numbered_count,
        "multilevel_numbered_paragraphs": multilevel_paragraphs,
        "structural_candidates_in_tables": structural_in_table,
        "toc_field_count": len(re.findall(r"\bTOC\b", instr_text, re.I)),
        "numbering_abstract_definitions": abstract_definitions,
        "multilevel_numbering_definitions": multilevel_definitions,
        "numbering_level_count_distribution": dict(sorted(level_count_distribution.items())),
        "current_detector_matches_on_word_paragraphs": detector_matches,
        "number_title_split_across_runs": split_run_candidates,
        "number_only_then_text_paragraph_pairs": number_only_then_text,
        "style_class_counts": dict(sorted(style_counts.items())),
        "outline_level_counts": dict(sorted(outline_counts.items())),
        "prefix_pattern_counts": dict(sorted(prefix_counts.items())),
        "paragraph_records": records,
        "body_text_persisted": False,
        "online_services_used": False,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    temporary = args.output.with_suffix(args.output.suffix + ".partial")
    if temporary.exists() or args.output.exists():
        raise SystemExit("Refusing to overwrite an existing OOXML audit artifact")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(args.output)
    print(
        json.dumps(
            {key: payload[key] for key in (
                "paragraph_count",
                "table_count",
                "heading_style_paragraphs",
                "outline_level_paragraphs",
                "automatic_numbering_paragraphs",
                "toc_field_count",
                "current_detector_matches_on_word_paragraphs",
            )},
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
