"""Build body-free Section Structure Diagnostics reports from audit evidence."""

from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path


def load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def yes_no(value: bool) -> str:
    return "YES" if value else "NO"


def write_text(path: Path, value: str) -> None:
    temporary = path.with_suffix(path.suffix + ".partial")
    if temporary.exists():
        raise RuntimeError("Refusing to overwrite an existing partial report")
    temporary.write_text(value.rstrip() + "\n", encoding="utf-8")
    temporary.replace(path)


def sample_rollup(document: dict) -> tuple[dict, dict]:
    by_stratum: dict[str, Counter[str]] = {}
    patterns: Counter[str] = Counter()
    for sample in document["qa_samples"]:
        by_stratum.setdefault(sample["stratum"], Counter())[sample["classification"]] += 1
        signature = sample["pattern_signature"]
        pattern = (
            f"{signature['prefix_pattern']}|depth={signature['arabic_depth']}|"
            f"len={signature['length_bucket']}|colon={str(signature['ends_with_colon']).lower()}|"
            f"sentence={str(signature['sentence_terminal']).lower()}"
        )
        patterns[pattern] += 1
    return (
        {key: dict(sorted(value.items())) for key, value in sorted(by_stratum.items())},
        dict(patterns.most_common(12)),
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--evidence", type=Path, required=True)
    parser.add_argument("--word-audit", type=Path, required=True)
    parser.add_argument("--requirements-ooxml", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()

    evidence = load_json(args.evidence)
    word_audit = load_json(args.word_audit)
    ooxml = load_json(args.requirements_ooxml)
    args.output_dir.mkdir(parents=True, exist_ok=True)

    documents = {item["document_type"]: item for item in evidence["documents"]}
    word_documents = {
        item["document_type"]: item
        for item in word_audit["documents"]
        if item.get("opened_read_only")
    }
    requirements = evidence["requirements"]
    design = documents["detailed_design"]
    test = documents["test_or_acceptance"]
    citation_can_remain = all(item["citation_page_mapping_valid"] for item in evidence["documents"])
    word_sidecar_feasible = (
        len(word_documents) == len(evidence["documents"])
        and all(item.get("opened_read_only") for item in word_documents.values())
        and all(item.get("source_sha256") == item.get("staged_sha256") for item in word_documents.values())
    )
    recommended_strategy = "WORD_FIRST" if word_sidecar_feasible else "HYBRID"
    ready_for_repair = (
        requirements["failure_cause"] != "OTHER"
        and design["oversegmented"] != "INCONCLUSIVE"
        and test["oversegmented"] != "INCONCLUSIVE"
        and word_sidecar_feasible
        and citation_can_remain
    )

    minimal_changes = [
        {
            "area": "new source structure extractor",
            "change": "Add a local WordStructureExtractor that emits a hash-only sidecar from read-only Word COM/OOXML metadata.",
        },
        {
            "area": "section resolver",
            "change": "Let SectionAwareTextSplitter consume an optional sidecar and prefer mapped Word Outline/Heading anchors before PDF heuristics.",
        },
        {
            "area": "PDF heuristic guardrails",
            "change": "Reject table/list/body/field candidates using existing Docling block labels and sentence/length checks; do not broadly accept parenthesized Arabic items.",
        },
        {
            "area": "provenance and deterministic IDs",
            "change": "Persist section source, mapping status/confidence, parent_section_id, and deterministic section IDs while preserving physical PDF page citations.",
        },
        {
            "area": "tests",
            "change": "Add synthetic unit fixtures for Outline anchors, split headings, tables, numbered steps, hierarchy, page mapping, and fallback behavior.",
        },
    ]

    qa_documents = []
    for document in evidence["documents"]:
        by_stratum, patterns = sample_rollup(document)
        qa_documents.append(
            {
                "document_id": document["document_id"],
                "document_type": document["document_type"],
                "pages": document["pages"],
                "current_section_count": document["current_section_count"],
                "classification_counts": document["classification_counts"],
                "real_heading_ratio": document["real_heading_ratio"],
                "false_heading_ratio": document["false_heading_ratio"],
                "conservative_max_real_heading_count": document["conservative_max_real_heading_count"],
                "conservative_min_false_heading_count": document["conservative_min_false_heading_count"],
                "conservative_min_false_heading_ratio": document["conservative_min_false_heading_ratio"],
                "unknown_ratio": document["unknown_ratio"],
                "oversegmented": document["oversegmented"],
                "heading_misses": document["heading_misses"],
                "parent_hierarchy": document["parent_hierarchy"],
                "sampling_coverage": document["sampling_coverage"],
                "sample_classifications_by_stratum": by_stratum,
                "sanitized_sample_pattern_counts": patterns,
                "qa_samples": document["qa_samples"],
                "body_text_included": False,
            }
        )

    summary = {
        "schema_version": 1,
        "decisions": {
            "REQUIREMENTS_FAILURE_CAUSE": requirements["failure_cause"],
            "REQUIREMENTS_WORD_HAS_STRUCTURE": requirements["word_has_structure"],
            "DETAIL_DESIGN_OVERSEGMENTED": design["oversegmented"],
            "TEST_DOC_OVERSEGMENTED": test["oversegmented"],
            "WORD_STRUCTURE_SIDECAR_FEASIBLE": yes_no(word_sidecar_feasible),
            "RECOMMENDED_SECTION_STRATEGY": recommended_strategy,
            "CITATION_PAGE_MAPPING_CAN_REMAIN": yes_no(citation_can_remain),
            "READY_FOR_SECTION_REPAIR": yes_no(ready_for_repair),
        },
        "requirements_failure_analysis": requirements,
        "section_quality": qa_documents,
        "minimal_code_changes": minimal_changes,
        "quality_gate": {
            "requirements_not_all_fallback": True,
            "heading_precision_review_required": True,
            "heading_miss_review_required": True,
            "false_heading_types_reviewed": [
                "NUMBERED_LIST_ITEM",
                "TABLE_ROW",
                "FIELD_LABEL",
                "BODY_SENTENCE",
                "UNKNOWN",
            ],
            "parent_hierarchy_review_required": True,
            "physical_pdf_page_mapping_required": True,
            "fallback_retained": True,
        },
        "online_models_called": False,
        "embedding_or_retrieval_run": False,
        "body_text_included": False,
    }
    summary_path = args.output_dir / "section_quality_summary.json"
    write_text(summary_path, json.dumps(summary, ensure_ascii=False, indent=2))

    req_lines = [
        "# Requirements Section Fallback Failure Analysis",
        "",
        "## Conclusion",
        "",
        f"REQUIREMENTS_FAILURE_CAUSE = {requirements['failure_cause']}",
        "",
        f"REQUIREMENTS_WORD_HAS_STRUCTURE = {requirements['word_has_structure']}",
        "",
        "Primary finding: the Word source contains a small, explicit Outline structure, but that semantic metadata is not carried into the canonical PDF text model. The visible anchor text is preserved, while the current detector sees only text patterns and therefore creates no sections.",
        "",
        "A broad regex fix would be unsafe. The document also contains many parenthesized Arabic requirement items that are not Word Outline headings. Treating every such item as a heading would replace one failure with severe over-segmentation.",
        "",
        "## Word structure evidence",
        "",
        f"- Non-empty paragraphs: {requirements['word_nonempty_paragraphs']}",
        f"- Heading Style paragraphs: {requirements['word_heading_style_paragraphs']}",
        f"- Outline-level paragraphs: {requirements['word_outline_level_paragraphs']}",
        f"- Automatic-numbering paragraphs: {requirements['word_automatic_numbering_paragraphs']}",
        f"- TOC fields: {requirements['word_toc_field_count']}",
        f"- Multilevel-numbering definitions: {requirements['word_multilevel_numbering_definitions']}",
        f"- Paragraphs inside tables: {requirements['word_paragraphs_in_tables']}",
        f"- Parenthesized Arabic items: {requirements['word_parenthesized_arabic_items']}",
        f"- Current detector matches on Word paragraphs: {requirements['word_current_detector_matches']}",
        "",
        "The Word structure is classified PARTIAL: five Heading/Outline anchors exist, but there is no TOC or automatic/multilevel numbering structure.",
        "",
        "## Word to PDF evidence",
        "",
        f"- Word paragraphs exactly preserved as PDF lines: {requirements['word_paragraphs_exactly_preserved_as_pdf_lines']}/{requirements['word_nonempty_paragraphs']}",
        f"- Exact-line preservation ratio: {requirements['word_to_pdf_exact_line_ratio']:.2%}",
        f"- Outline anchors exactly preserved in PDF: {requirements['outline_anchors_exactly_preserved_in_pdf']}/{requirements['word_outline_level_paragraphs']}",
        f"- Outline anchors split across PDF lines: {requirements['outline_anchors_split_across_pdf_lines']}",
        f"- Outline anchors moved into PDF tables: {requirements['outline_anchors_entered_pdf_tables']}",
        f"- Parenthesized Arabic items visible in PDF: {requirements['pdf_parenthesized_arabic_items']}",
        f"- Numbering preserved: {yes_no(requirements['numbering_preserved'])}",
        f"- Outline-anchor order inversions: {requirements['outline_anchor_order_inversions']}",
        f"- Parsed PDF tables: {requirements['pdf_parsed_table_count']}",
        f"- Body-free Outline heading-miss QA samples: {len(requirements['heading_miss_qa_samples'])}",
        "",
        "## Cause classification",
        "",
        f"Primary cause: **{requirements['failure_cause']}**.",
        "",
        "Contributing cause: **REGEX_NOT_COVERED**. The current parenthesized-heading regex accepts Chinese numerals but not Arabic numerals. This is not the primary repair path because most parenthesized Arabic lines are requirement items rather than real headings.",
        "",
        "Rejected causes:",
        "",
        "- `LINE_SPLIT`: rejected when Outline anchors remain intact on single PDF lines.",
        "- `TABLE_BASED_STRUCTURE`: rejected when neither the Word source nor PDF parser places the Outline anchors in tables.",
        "- `DOCUMENT_HAS_NO_REAL_HEADINGS`: rejected because five Word Outline anchors exist.",
        "",
        "No source body text is included in this report.",
    ]
    write_text(args.output_dir / "requirements_failure_analysis.md", "\n".join(req_lines))

    diagnostic_lines = [
        "# R&D V2 Section Structure Diagnostics",
        "",
        "## Decision summary",
        "",
        f"REQUIREMENTS_FAILURE_CAUSE = {requirements['failure_cause']}",
        "",
        f"REQUIREMENTS_WORD_HAS_STRUCTURE = {requirements['word_has_structure']}",
        "",
        f"DETAIL_DESIGN_OVERSEGMENTED = {design['oversegmented']}",
        "",
        f"TEST_DOC_OVERSEGMENTED = {test['oversegmented']}",
        "",
        f"WORD_STRUCTURE_SIDECAR_FEASIBLE = {yes_no(word_sidecar_feasible)}",
        "",
        f"RECOMMENDED_SECTION_STRATEGY = {recommended_strategy}",
        "",
        f"CITATION_PAGE_MAPPING_CAN_REMAIN = {yes_no(citation_can_remain)}",
        "",
        "MINIMAL_CODE_CHANGES = Word structure extractor; optional sidecar resolver; PDF heuristic guardrails; deterministic provenance; synthetic structure QA tests",
        "",
        f"READY_FOR_SECTION_REPAIR = {yes_no(ready_for_repair)}",
        "",
        "## Method",
        "",
        "The audit matched SHA256-only Word paragraph records to the existing canonical-PDF parsed and chunked artifacts. It classified every current section using Word Heading/Outline/List/Table metadata plus existing Docling block labels. Deterministic stratified samples cover the front, middle, back, table-dense, and numbered-list-dense regions. Reports contain counts and sanitized patterns only.",
        "",
        "Classification priority is conservative: Word Heading/Outline and Docling semantic headings count as `REAL_HEADING`; table membership, list semantics, non-structural numbered paragraphs, field labels, and sentence-like body blocks count as false-heading categories; unresolved cases remain `UNKNOWN`.",
        "",
        "## Word structure inventory",
        "",
        "| document_type | pages | non-empty paragraphs | heading style | outline | automatic numbering | numbered structural | tables | paragraphs in tables | TOC |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for doc_type in ("requirements", "detailed_design", "test_or_acceptance"):
        word = word_documents[doc_type]
        diagnostic_lines.append(
            f"| {doc_type} | {word['computed_pages']} | {word['nonempty_paragraph_count']} | "
            f"{word['heading_style_paragraphs']} | {word['outline_level_paragraphs']} | "
            f"{word['automatic_numbering_paragraphs']} | {word['numbered_structural_paragraphs']} | "
            f"{word['table_count']} | {word['paragraphs_in_tables']} | {word['toc_count']} |"
        )
    diagnostic_lines.extend(
        [
            "",
            "## Current Section quality",
            "",
            "| document_type | pages | current sections | sections/page | directly confirmed real | numbered list | table row | field label | body sentence | unknown | direct false ratio | conservative minimum false | decision | heading misses |",
            "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|---:|",
        ]
    )
    for doc_type in ("requirements", "detailed_design", "test_or_acceptance"):
        item = documents[doc_type]
        counts = item["classification_counts"]
        diagnostic_lines.append(
            f"| {doc_type} | {item['pages']} | {item['current_section_count']} | {item['sections_per_page']:.2f} | "
            f"{counts.get('REAL_HEADING', 0)} | {counts.get('NUMBERED_LIST_ITEM', 0)} | "
            f"{counts.get('TABLE_ROW', 0)} | {counts.get('FIELD_LABEL', 0)} | "
            f"{counts.get('BODY_SENTENCE', 0)} | {counts.get('UNKNOWN', 0)} | "
            f"{item['false_heading_ratio']:.2%} | {item['conservative_min_false_heading_count']} "
            f"({item['conservative_min_false_heading_ratio']:.2%}) | {item['oversegmented']} | {item['heading_misses']} |"
        )
    diagnostic_lines.extend(
        [
            "",
            "A non-zero section count is not treated as success. Direct classifications are conservative exact-hash/block-label evidence and may undercount real headings when Word automatic numbering changes the displayed PDF string. The over-segmentation decision therefore uses a stronger lower bound: even if every Word structural candidate plus every directly confirmed semantic heading were real, the remaining section count is still false. The exact classifications and sanitized pattern signatures are available in `section_quality_summary.json`.",
            "",
            f"Requirements has no current sections to stratify. Its QA sample therefore consists of all {len(requirements['heading_miss_qa_samples'])} Word Outline anchors; every sample records only ordinal, page, style/outline metadata, sanitized pattern, and PDF/detector status.",
            "",
            "## Stratified QA coverage",
            "",
            "| document_type | stratum | candidate sections | sampled | sample classifications |",
            "|---|---|---:|---:|---|",
        ]
    )
    for document in qa_documents:
        for stratum, coverage in document["sampling_coverage"].items():
            counts = document["sample_classifications_by_stratum"].get(stratum, {})
            rendered = ", ".join(f"{key}={value}" for key, value in sorted(counts.items())) or "none"
            diagnostic_lines.append(
                f"| {document['document_type']} | {stratum} | {coverage['candidate_count']} | "
                f"{coverage['sample_count']} | {rendered} |"
            )
    diagnostic_lines.extend(
        [
            "",
            "## Parent hierarchy and page mapping",
            "",
            "| document_type | hierarchy jumps | path-depth mismatches | sections without children | invalid child parent | citation physical pages | fallback chunks |",
            "|---|---:|---:|---:|---:|---|---:|",
        ]
    )
    for doc_type in ("requirements", "detailed_design", "test_or_acceptance"):
        item = documents[doc_type]
        hierarchy = item["parent_hierarchy"]
        diagnostic_lines.append(
            f"| {doc_type} | {hierarchy['hierarchy_level_jumps']} | {hierarchy['path_depth_mismatches']} | "
            f"{hierarchy['sections_without_child_chunks']} | {hierarchy['invalid_child_parent_mappings']} | "
            f"{yes_no(item['citation_page_mapping_valid'])} | {item['fallback_chunk_count']} |"
        )
    diagnostic_lines.extend(
        [
            "",
            "## Structure sidecar feasibility",
            "",
            "Word COM and the existing local Word-to-PDF pipeline are available. `python-docx`/OOXML is available for `.docx`; legacy `.doc` requires Word COM. The same local Word renderer can expose page-number anchors while the canonical PDF remains the immutable content and citation source.",
            "",
            "The feasible design is Word structure first, PDF text/layout mapping second, and the existing fallback chunker third. This preserves the physical PDF page citation contract and avoids expanding regex rules to absorb ordinary numbered content.",
            "",
            "## Scope compliance",
            "",
            "- Online LLM or conversion service called: NO",
            "- Embedding, FAISS, BM25, RRF, rerank, or Retrieval Evaluation run: NO",
            "- Hybrid parameters changed: NO",
            "- Citation, Trusted QA, Retrieval, or source/canonical documents modified: NO",
            "- Sensitive body text persisted in reports: NO",
        ]
    )
    write_text(args.output_dir / "structure_diagnostics_report.md", "\n".join(diagnostic_lines))

    repair_lines = [
        "# R&D V2 Minimal Section Repair Plan",
        "",
        "## Recommendation",
        "",
        f"RECOMMENDED_SECTION_STRATEGY = {recommended_strategy}",
        "",
        "Use a precedence chain rather than a larger universal regex: source-aware Word structure, then guarded PDF text/layout heuristics, then the existing fallback chunker.",
        "",
        "## Priority A Source-aware structure",
        "",
        "Extract only structural metadata from the hash-verified staged Word copy. Use Word Heading styles, Outline levels, list level/marker metadata, hierarchy, and local renderer page position. Do not persist body paragraphs.",
        "",
        "For legacy `.doc`, use local Word COM with macros forced off, links disabled, and read-only open. For `.docx`, prefer deterministic OOXML/python-docx extraction and use Word COM only when renderer page positions are needed.",
        "",
        "## Priority B Guarded PDF heuristics",
        "",
        "Map Word anchors to canonical PDF lines by normalized title hash and a narrow physical-page window. If mapping is ambiguous, require typography/layout evidence and mark the mapping low-confidence or unmapped. Reject candidates originating from tables, list items, field labels, and sentence-like body blocks unless independent heading evidence exists.",
        "",
        "Do not globally add parenthesized Arabic items to the heading regex. Requirements contains many such items but only a small Word Outline structure.",
        "",
        "## Priority C Existing fallback",
        "",
        "Retain the current legacy page chunker when neither source structure nor high-confidence PDF evidence is available. Record fallback usage explicitly; do not synthesize parent headings from every numbered line.",
        "",
        "## Minimal Structure Sidecar schema",
        "",
        "```json",
        "{",
        '  "document_id": "rdv2-...",',
        '  "source_file_hash": "sha256:...",',
        '  "normalized_pdf_id": "sha256:...",',
        '  "sections": [',
        "    {",
        '      "section_id": "sec-...",',
        '      "title_hash": "sha256:...",',
        '      "level": 1,',
        '      "parent_section_id": null,',
        '      "source": "word_outline",',
        '      "mapped_start_page": 1,',
        '      "mapped_end_page": 2,',
        '      "mapping_confidence": 0.98,',
        '      "mapping_status": "exact_hash_page_window"',
        "    }",
        "  ]",
        "}",
        "```",
        "",
        "Do not store normalized titles in the long-lived sidecar by default; keep only `title_hash`. A normalized title may exist ephemerally during local matching and must not enter logs or reports.",
        "",
        "Derive deterministic section IDs from the versioned tuple `(document_id, source, level, title_hash, same-title occurrence index)` and encode a stable SHA256 prefix. Parent IDs come from the Word outline/list stack or the guarded PDF heading stack.",
        "",
        "PDF physical pages remain the Citation Contract. The sidecar may map structure to pages, but it must not replace or renumber canonical PDF pages.",
        "",
        "## Minimal code changes",
        "",
    ]
    for index, change in enumerate(minimal_changes, 1):
        repair_lines.append(f"{index}. **{change['area']}:** {change['change']}")
    repair_lines.extend(
        [
            "",
            "## Section repair acceptance",
            "",
            "Use a small, human-reviewable, body-free QA sample for every document. The repair passes only when:",
            "",
            "- Requirements has mapped source Outline sections and is no longer entirely fallback.",
            "- Heading Precision is reviewed across front, middle, back, table-dense, and numbered-list-dense strata.",
            "- Heading misses and false-heading types are explicitly counted.",
            "- Parent hierarchy has no invalid child-parent references and hierarchy jumps are reviewed.",
            "- Every section maps to canonical physical PDF pages or carries an explicit unmapped/ambiguous status.",
            "- Fallback remains available and its use is counted.",
            "- No retrieval or Hybrid tuning begins until the repaired Section QA is accepted.",
            "",
            f"READY_FOR_SECTION_REPAIR = {yes_no(ready_for_repair)}",
        ]
    )
    write_text(args.output_dir / "structure_repair_plan.md", "\n".join(repair_lines))

    print(json.dumps(summary["decisions"], ensure_ascii=False))


if __name__ == "__main__":
    main()
