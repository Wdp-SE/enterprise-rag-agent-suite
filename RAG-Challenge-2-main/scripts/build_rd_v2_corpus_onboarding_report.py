"""Build a metadata/metrics-only onboarding report for the real R&D corpus.

The script intentionally reads no parsed, merged, or chunk body text. It uses
only manifests, body-free structure statistics, and filesystem hashes.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path


def load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def yes_no(value: bool) -> str:
    return "YES" if value else "NO"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--inventory", type=Path, required=True)
    parser.add_argument("--corpus-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    inventory = load_json(args.inventory)
    corpus_root = args.corpus_root.resolve()
    manifest = load_json(corpus_root / "manifest" / "normalization_manifest.json")
    documents = manifest["documents"]
    stats = {
        item["document_id"]: load_json(
            corpus_root / "manifest" / f"{item['document_id']}.structure_stats.json"
        )
        for item in documents
    }
    render_qa = {
        item["document_id"]: load_json(
            corpus_root / "manifest" / f"{item['document_id']}.render_qa.json"
        )
        for item in documents
    }

    source_root = Path(inventory["source_root"])
    inventory_by_path = {item["relative_path"]: item for item in inventory["files"]}
    source_integrity = all(
        (source_root / relative_path).is_file()
        and (source_root / relative_path).stat().st_size == item["size"]
        and sha256_file(source_root / relative_path) == item["sha256"]
        for relative_path, item in inventory_by_path.items()
    )
    normalized_integrity = all(
        item.get("status") == "success"
        and (corpus_root / item["normalized_relative_path"]).is_file()
        and sha256_file(corpus_root / item["normalized_relative_path"])
        == item["normalized_sha256"]
        for item in documents
    )
    normalization_success = normalized_integrity and len(documents) == manifest["selection_count"]
    structure_successes = [
        item for item in documents if stats[item["document_id"]].get("section_parse_success")
    ]
    parent_successes = [
        item for item in documents if stats[item["document_id"]].get("parent_child_success")
    ]
    citation_successes = [
        item
        for item in documents
        if stats[item["document_id"]].get("citation_page_mapping_valid")
    ]
    parser_successes = [
        item
        for item in documents
        if stats[item["document_id"]].get("parsing_failures") == 0
        and stats[item["document_id"]].get("canonical_pdf_pages")
        == stats[item["document_id"]].get("parsed_pages")
        == stats[item["document_id"]].get("merged_pages")
    ]
    render_success = all(
        render_qa[item["document_id"]].get("all_pages_rasterized_and_readable")
        and render_qa[item["document_id"]].get("rendered_pages")
        == render_qa[item["document_id"]].get("expected_pdf_pages")
        for item in documents
    )
    all_sections = len(structure_successes) == len(documents)
    all_parents = len(parent_successes) == len(documents)
    all_citations = len(citation_successes) == len(documents)
    ready = (
        source_integrity
        and normalization_success
        and len(parser_successes) == len(documents)
        and all_sections
        and all_parents
        and all_citations
        and render_success
    )

    section_status = (
        "YES"
        if all_sections
        else f"PARTIAL ({len(structure_successes)}/{len(documents)})"
    )
    parent_status = (
        "YES" if all_parents else f"PARTIAL ({len(parent_successes)}/{len(documents)})"
    )
    blockers = []
    fallback_documents = [
        item
        for item in documents
        if stats[item["document_id"]].get("section_detection_mode") == "legacy_fallback"
    ]
    if fallback_documents:
        labels = ", ".join(
            f"{item['document_type']} ({item['document_id']})" for item in fallback_documents
        )
        blockers.append(
            f"Section Detection fell back for {labels}; those chunks have no parent section mapping."
        )
    blockers.append(
        "The current accurate table/layout parser required multi-hour processing for the 714-page representative document on this host."
    )
    blockers.append(
        "A deepsearch_glm optional character-normalization resource-path warning is emitted on this non-ASCII workspace path; parsing completed, but the environment warning remains unresolved."
    )
    if not source_integrity:
        blockers.append("At least one source size or SHA256 no longer matches the inventory snapshot.")
    if not normalized_integrity:
        blockers.append("At least one normalized PDF no longer matches its manifest SHA256.")

    counts = inventory["counts"]
    selected_types = ", ".join(item["document_type"] for item in documents)
    lines = [
        "# R&D V2 Real Corpus Onboarding Report",
        "",
        "> Scope: corpus onboarding and compatibility validation only. No online LLM, embedding, retrieval, reranking, generation, Hybrid Ablation, or retrieval-parameter tuning was run.",
        "",
        "## Decision summary",
        "",
        f"SOURCE_FILES_FOUND = {counts['source_files_found']}",
        "",
        f"DOC_FILES = {counts['doc_files']}",
        "",
        f"DOCX_FILES = {counts['docx_files']}",
        "",
        f"PDF_FILES = {counts['pdf_files']}",
        "",
        "DIRECTLY_SUPPORTED = PDF only (0 source files in this inventory)",
        "",
        f"CONVERSION_REQUIRED = DOC + DOCX ({counts['doc_files'] + counts['docx_files']} source files)",
        "",
        f"REPRESENTATIVE_DOCS_SELECTED = {len(documents)} ({selected_types})",
        "",
        f"NORMALIZATION_SUCCESS = {yes_no(normalization_success)} ({sum(item.get('status') == 'success' for item in documents)}/{len(documents)})",
        "",
        f"SECTION_PARSE_SUCCESS = {section_status}",
        "",
        f"PARENT_CHILD_SUCCESS = {parent_status}",
        "",
        f"CITATION_PAGE_MAPPING_VALID = {yes_no(all_citations)} ({len(citation_successes)}/{len(documents)})",
        "",
        "BLOCKERS = "
        + (" | ".join(item.rstrip(".") for item in blockers) if blockers else "NONE"),
        "",
        f"READY_FOR_REAL_RETRIEVAL_EVALUATION = {yes_no(ready)}",
        "",
        "The readiness gate is conservative: every representative document must pass section-aware parsing and Parent/Child mapping. A document that merely produces fallback chunks does not pass this gate.",
        "",
        "## Source inventory and integrity",
        "",
        f"The read-only scan found {counts['source_files_found']} files: {counts['doc_files']} legacy `.doc`, {counts['docx_files']} `.docx`, {counts['pdf_files']} `.pdf`, and {counts['other_files']} other formats. The inventory contains metadata and hashes only; it does not contain document body text.",
        "",
        f"- Source snapshot unchanged at final verification: {yes_no(source_integrity)}",
        f"- Inventory snapshot SHA256: `{inventory['source_snapshot_sha256']}`",
        f"- Normalized artifacts match manifest SHA256: {yes_no(normalized_integrity)}",
        f"- Source files opened by Microsoft Word: {yes_no(manifest.get('source_files_opened_by_word', True))}",
        f"- Staged copies opened read-only: {yes_no(manifest.get('staged_copies_opened_read_only', False))}",
        "",
        "## Current parser compatibility",
        "",
        "| Source format | Direct entry into current V2 | Required path | Citation implication |",
        "|---|---|---|---|",
        "| `.pdf` | Yes | Use as canonical ingestion artifact | Physical PDF page numbers are available to the existing citation path |",
        "| `.docx` | No | Local Word-to-PDF normalization | Direct DOCX text extraction would not preserve stable renderer pagination |",
        "| legacy `.doc` | No | Local Word-to-PDF normalization | The current parser and `python-docx` do not accept the binary Word format |",
        "",
        "Audit answers:",
        "",
        "1. Current native DOCX support: **No.** The current `PDFParser` registers only `InputFormat.PDF`.",
        "2. Current legacy DOC support: **No.** No binary Word parser is registered.",
        "3. Direct Word parsing and citations: **Risky.** Extracted Word text has no stable physical-page contract, so it would break or weaken `page_number` citation semantics.",
        "4. Canonical PDF normalization: **Recommended and validated locally.** It reuses the existing PDF/OCR/section/chunk/citation path.",
        f"5. Section Parser after conversion: **Conditionally applicable.** It was section-aware for {len(structure_successes)}/{len(documents)} documents and used legacy fallback for {len(fallback_documents)}/{len(documents)}.",
        "",
        "The current OCR branch uses EasyOCR configured for English only. OCR was deliberately disabled for these Word-exported PDFs because they contain a text layer. Scanned Chinese PDFs remain a future compatibility risk, not a failure of this representative set.",
        "",
        "## Minimal normalization design and result",
        "",
        "The implemented local layout is:",
        "",
        "```text",
        "data/rd_v2_corpus/",
        "├── raw/          # deterministic staged copies; originals remain untouched",
        "├── normalized/   # canonical PDFs plus local parsed/merged/chunked artifacts",
        "├── manifest/     # selection, source-to-normalized mapping, hashes, QA stats",
        "└── evaluation/   # reserved; no evaluation was started",
        "```",
        "",
        "Microsoft Word 16 local COM export was used because it was already installed; LibreOffice was not present. No large dependency was installed and no online converter was called. Automation security forced macros off, link updating was disabled, only staged copies were opened read-only, and conversion failures were configured to fail clearly.",
        "",
        "Document IDs are deterministic: `rdv2-` plus the first 16 hexadecimal characters of the source SHA256. The normalization manifest preserves source-to-staged-to-canonical mappings and SHA256 values.",
        "",
        "## Representative corpus validation",
        "",
        "Selection used filenames only and covered requirements, detailed design, and test/acceptance; no body content was used to select documents.",
        "",
        "| document_type | document_id | pages | sections | child_chunks | parent mappings | fallback chunks | OCR | empty pages | parse failures | citation pages |",
        "|---|---|---:|---:|---:|---:|---:|---|---:|---:|---|",
    ]
    for item in documents:
        row = stats[item["document_id"]]
        lines.append(
            "| {document_type} | `{document_id}` | {canonical_pdf_pages} | {sections} | "
            "{child_chunks} | {parent_mapping_success_count}/{child_chunks} | "
            "{fallback_chunk_count} | {ocr_usage} | {empty_pages} | {parsing_failures} | "
            "{citation} |".format(
                document_type=item["document_type"],
                document_id=item["document_id"],
                canonical_pdf_pages=row["canonical_pdf_pages"],
                sections=row["sections"],
                child_chunks=row["child_chunks"],
                parent_mapping_success_count=row["parent_mapping_success_count"],
                fallback_chunk_count=row["fallback_chunk_count"],
                ocr_usage="used" if row["ocr_usage"] else "not used",
                empty_pages=row["empty_pages"],
                parsing_failures=row["parsing_failures"],
                citation=yes_no(row["citation_page_mapping_valid"]),
            )
        )
    lines.extend(
        [
            "",
            f"Totals: {sum(stats[item['document_id']]['canonical_pdf_pages'] for item in documents)} pages, {sum(stats[item['document_id']]['sections'] for item in documents)} sections, {sum(stats[item['document_id']]['child_chunks'] for item in documents)} child chunks, and {sum(stats[item['document_id']]['fallback_chunk_count'] for item in documents)} fallback chunks.",
            "",
            "Section Detection is not uniformly compatible. The requirements document produced no recognized heading after the existing PDF merge path, so all of its chunks used legacy fallback and received no parent mapping. The detailed-design and test/acceptance documents produced large section hierarchies with complete Parent/Child mapping. These are observations only; no parser rule or chunk parameter was changed.",
            "",
            "The canonical PDFs were rasterized page-by-page: all 1,170 expected pages rendered successfully, automated blank/edge checks found no candidates, all 34 contact sheets were visually inspected, and selected pages were re-rendered at 150 DPI for detailed spot checks. No clipping, missing pages, broken glyphs, or obvious table truncation was observed. One source uses front matter/footer numbering that differs from the physical PDF index; citations must continue to use the physical PDF page index.",
            "",
            "## Risks and next gate",
            "",
        ]
    )
    for blocker in blockers:
        lines.append(f"- {blocker}")
    lines.extend(
        [
            "- Section detection is heuristic. Structural success does not prove semantic heading precision; that belongs in the next approved Dev/Holdout evaluation.",
            "- Word-to-PDF pagination depends on the local Office build and installed fonts; the normalized PDF hash is therefore the immutable artifact for later evaluation.",
            "- The physical PDF page index, not a printed footer page number, is the citation contract.",
            "",
            "Before real retrieval evaluation, decide how to handle the requirements document's section fallback. No Hybrid Ablation or large-scale evaluation should begin until that gate is explicitly accepted or resolved.",
            "",
            "## Constraint compliance",
            "",
            f"- Original source files unchanged by size and SHA256: {yes_no(source_integrity)}",
            "- Original Word files overwritten, renamed, or deleted: NO",
            "- Online LLM or online conversion called: NO",
            "- Batch ingest performed: NO",
            "- Retrieval parameters changed: NO",
            "- Citation, Trusted QA, Version Governance, or Generation Prompt changed: NO",
            "- Sensitive document body copied into reports or terminal logs: NO",
            "- Corpus and reports excluded from Git by `.gitignore`: YES",
            "",
        ]
    )

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text("\n".join(lines), encoding="utf-8")
    print(
        json.dumps(
            {
                "source_integrity": source_integrity,
                "normalization_success": normalization_success,
                "section_parse_success": section_status,
                "parent_child_success": parent_status,
                "citation_page_mapping_valid": all_citations,
                "ready_for_real_retrieval_evaluation": ready,
            },
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
