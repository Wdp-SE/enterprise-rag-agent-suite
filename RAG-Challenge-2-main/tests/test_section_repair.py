import copy
import hashlib
from pathlib import Path
import zipfile

from src.sectioning import (
    SectionAwareTextSplitter,
    classify_heading_candidate,
    detect_sections,
)
from src.word_structure import (
    FALLBACK,
    HeadingPageMapper,
    WordStructureExtractor,
    build_structure_sidecar,
    normalize_heading_text,
)


def _sidecar(headings, document_id="doc-a"):
    return build_structure_sidecar(
        document_id=document_id,
        source_file_hash="a" * 64,
        normalized_pdf_id="sha256:" + "b" * 64,
        headings=headings,
        extractor="SYNTHETIC_TEST",
    )


def _report(*pages, document_id="doc-a"):
    return {
        "metainfo": {"document_id": document_id, "title": "Synthetic", "source": "fixture.pdf"},
        "content": {
            "pages": [
                {"page": index, "text": value}
                for index, value in enumerate(pages, start=1)
            ]
        },
    }


def _write_docx_fixture(path: Path):
    document_xml = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">
  <w:body>
    <w:p><w:pPr><w:pStyle w:val="Heading1"/></w:pPr><w:r><w:t>Architecture</w:t></w:r></w:p>
    <w:p><w:r><w:t>Ordinary body.</w:t></w:r></w:p>
  </w:body>
</w:document>"""
    styles_xml = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<w:styles xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">
  <w:style w:type="paragraph" w:styleId="Normal"><w:name w:val="Normal"/></w:style>
  <w:style w:type="paragraph" w:styleId="Heading1"><w:name w:val="heading 1"/><w:basedOn w:val="Normal"/><w:pPr><w:outlineLvl w:val="0"/></w:pPr></w:style>
</w:styles>"""
    with zipfile.ZipFile(path, "w") as package:
        package.writestr("word/document.xml", document_xml)
        package.writestr("word/styles.xml", styles_xml)


def test_docx_heading_extraction(tmp_path):
    path = tmp_path / "fixture.docx"
    _write_docx_fixture(path)
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    result = WordStructureExtractor().extract_docx(
        path,
        document_id="doc-a",
        source_file_hash=digest,
        normalized_pdf_id="sha256:" + "b" * 64,
    )
    assert len(result["sections"]) == 1
    assert result["sections"][0]["level"] == 1
    assert result["extractor"] == "DOCX_OOXML"


def test_legacy_doc_com_record_path_filters_table_rows():
    records = [
        {
            "normalized_title": "Architecture",
            "level": 1,
            "source_page_hint": 1,
            "heading_style": True,
            "outline_candidate": True,
            "in_table": False,
        },
        {
            "normalized_title": "Table label",
            "level": 2,
            "heading_style": True,
            "outline_candidate": True,
            "in_table": True,
        },
    ]
    result = WordStructureExtractor().from_com_records(
        records,
        document_id="doc-a",
        source_file_hash="a" * 64,
        normalized_pdf_id="sha256:" + "b" * 64,
    )
    assert len(result["sections"]) == 1
    assert result["extractor"] == "WORD_COM_READ_ONLY"


def test_section_ids_are_deterministic_and_unique_for_duplicate_titles():
    headings = [
        {"normalized_title": "Interface", "level": 1},
        {"normalized_title": "Interface", "level": 1},
    ]
    first = _sidecar(headings)
    second = _sidecar(headings)
    assert [item["section_id"] for item in first["sections"]] == [
        item["section_id"] for item in second["sections"]
    ]
    assert len({item["section_id"] for item in first["sections"]}) == 2


def test_heading_normalization_handles_width_case_and_whitespace():
    assert normalize_heading_text("  ＡＰＩ\tDesign  ").casefold() == "api design"


def test_sequential_page_alignment_uses_heading_order():
    sidecar = _sidecar(
        [
            {"normalized_title": "Repeated", "level": 1},
            {"normalized_title": "Repeated", "level": 1},
        ]
    )
    mapped = HeadingPageMapper().map(
        sidecar,
        [{"page": 1, "text": "Repeated\nbody"}, {"page": 2, "text": "Repeated\nbody"}],
    )
    assert [item["mapped_start_page"] for item in mapped["sections"]] == [1, 2]
    assert mapped["alignment"]["sequential_order_valid"] is True


def test_split_heading_title_alignment():
    sidecar = _sidecar([{"normalized_title": "1.2 Interface Design", "level": 2}])
    mapped = HeadingPageMapper().map(
        sidecar, [{"page": 1, "text": "1.2\nInterface Design\nbody"}]
    )
    assert mapped["sections"][0]["mapping_status"].startswith("SPLIT_")


def test_numbering_joined_with_title_alignment():
    sidecar = _sidecar([{"normalized_title": "Interface Design", "level": 2}])
    mapped = HeadingPageMapper().map(
        sidecar, [{"page": 1, "text": "1.2 Interface Design\nbody"}]
    )
    assert mapped["sections"][0]["mapping_status"] == "NUMBERING_NORMALIZED"


def test_unresolved_mapping_never_guesses_a_page():
    sidecar = _sidecar([{"normalized_title": "Missing heading", "level": 1}])
    mapped = HeadingPageMapper().map(sidecar, [{"page": 1, "text": "ordinary body"}])
    section = mapped["sections"][0]
    assert section["mapping_status"] == "UNRESOLVED"
    assert section["mapped_start_page"] is None


def test_parenthesized_numbered_list_is_not_heading():
    assert classify_heading_candidate("(1) Enter a value") == "NUMBERED_LIST_ITEM"


def test_multilevel_numbering_is_not_heading_without_independent_evidence():
    assert classify_heading_candidate("1.2.3 Retry Policy") == "NUMBERED_LIST_ITEM"


def test_test_step_is_not_heading():
    assert classify_heading_candidate("Test Step 3: submit request") == "TEST_STEP"


def test_table_row_is_not_heading_even_with_markdown_marker():
    assert classify_heading_candidate("## Field", in_table=True) == "TABLE_ROW"


def test_parser_h3_body_marker_is_not_heading():
    assert classify_heading_candidate("### Ordinary paragraph") == "UNKNOWN"


def test_word_first_precedence_over_pdf_heuristic():
    sidecar = _sidecar([{"normalized_title": "1.2 Word title", "level": 1}])
    mapped = HeadingPageMapper().map(sidecar, [{"page": 1, "text": "1.2 Word title\nbody"}])
    sections, heading_count = detect_sections(
        [{"page": 1, "text": "1.2 Word title\nbody"}], "doc-a", mapped
    )
    assert heading_count == 1
    assert sections[0]["heading_source"] == "WORD_OUTLINE"


def test_pdf_heading_duplicate_near_mapped_word_anchor_is_suppressed():
    sidecar = _sidecar([{"normalized_title": "Appendix A", "level": 1}])
    pages = [
        {"page": 1, "text": "Appendix A\nbody"},
        {"page": 2, "text": "Appendix A\nbody"},
    ]
    mapped = HeadingPageMapper().map(sidecar, pages)
    sections, heading_count = detect_sections(pages, "doc-a", mapped)
    assert heading_count == 1
    assert len([item for item in sections if item["heading_source"] != FALLBACK]) == 1


def test_repeated_pdf_heading_on_same_page_is_suppressed():
    pages = [{"page": 1, "text": "Appendix A\nbody\nAppendix A\nbody"}]
    sections, heading_count = detect_sections(pages, "doc-a")
    assert heading_count == 1
    assert len(sections) == 1


def test_pdf_heuristic_remains_available_without_word_source():
    sections, heading_count = detect_sections(
        [{"page": 1, "text": "# Architecture\nbody"}], "doc-a"
    )
    assert heading_count == 1
    assert sections[0]["heading_source"] == "PDF_HEURISTIC"


def test_full_fallback_remains_available():
    result = SectionAwareTextSplitter()._split_report(_report("ordinary body only"))
    assert result["content"]["section_detection"]["mode"] == "legacy_fallback"
    assert result["content"]["chunks"]


def test_parent_child_mapping_is_complete_with_word_sidecar():
    sidecar = _sidecar(
        [
            {"normalized_title": "Architecture", "level": 1},
            {"normalized_title": "Interface", "level": 2},
        ]
    )
    pages = [
        {"page": 1, "text": "Architecture\nbody"},
        {"page": 2, "text": "Interface\nbody"},
    ]
    mapped = HeadingPageMapper().map(copy.deepcopy(sidecar), pages)
    result = SectionAwareTextSplitter(structure_sidecar=mapped)._split_report(
        _report("Architecture\nbody", "Interface\nbody")
    )
    section_ids = {item["section_id"] for item in result["content"]["sections"]}
    assert all(
        item["parent_id"] == item["section_id"] in section_ids
        for item in result["content"]["chunks"]
    )


def test_citation_page_contract_is_unchanged():
    sidecar = _sidecar([{"normalized_title": "Architecture", "level": 1}])
    mapped = HeadingPageMapper().map(
        sidecar, [{"page": 1, "text": "Architecture\nbody"}]
    )
    result = SectionAwareTextSplitter(structure_sidecar=mapped)._split_report(
        _report("Architecture\nbody")
    )
    assert all(
        item["document_id"] == "doc-a" and item["page_number"] == item["page"] == 1
        for item in result["content"]["chunks"]
    )
    assert result["content"]["sections"][0]["heading_source"] != FALLBACK
