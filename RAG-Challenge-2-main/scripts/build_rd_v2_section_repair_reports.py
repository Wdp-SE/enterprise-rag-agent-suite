"""Build the body-free Section Structure Minimal Repair Sprint reports."""

from __future__ import annotations

import argparse
import json
from pathlib import Path


def load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def write_text_atomic(path: Path, value: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".partial")
    if temporary.exists():
        raise RuntimeError("Refusing to overwrite an existing partial section repair report")
    temporary.write_text(value.rstrip() + "\n", encoding="utf-8")
    temporary.replace(path)


def write_json_atomic(path: Path, value: object) -> None:
    write_text_atomic(path, json.dumps(value, ensure_ascii=False, indent=2))


def yn(value: bool) -> str:
    return "YES" if value else "NO"


def pct(value: float | None) -> str:
    return "N/A" if value is None else f"{value * 100:.2f}%"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--evidence", type=Path, required=True)
    parser.add_argument("--word-summary", type=Path, required=True)
    parser.add_argument("--alignment-summary", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()

    evidence = load_json(args.evidence)
    word_summary = load_json(args.word_summary)
    alignment_summary = load_json(args.alignment_summary)
    docs = {item["document_type"]: item for item in evidence["documents"]}
    words = {item["document_type"]: item for item in word_summary["documents"]}
    aligns = {item["document_type"]: item for item in alignment_summary["documents"]}
    qas = {item["document_type"]: item for item in evidence["qa"]}
    requirements = docs["requirements"]
    design = docs["detailed_design"]
    test = docs["test_or_acceptance"]

    parent_child = all(item["parent_child_mapping_valid"] for item in docs.values())
    section_tree = all(item["section_tree_valid"] for item in docs.values())
    citation = all(item["citation_page_mapping_valid"] for item in docs.values())
    source_hash = all(item["source_hash_unchanged"] for item in docs.values())
    pdf_hash = all(item["pdf_hash_unchanged"] for item in docs.values())
    word_first = all(
        item["section_detection_mode"] == "word_first" and item["word_heading_count"] > 0
        for item in docs.values()
    )
    pdf_fallback = bool(evidence["pdf_fallback_working"])
    full_fallback = bool(evidence["full_fallback_working"])
    precision_ok = all(
        item["heading_precision"] is not None and item["heading_precision"] >= 0.90
        for item in (design, test)
    )
    requirements_ok = (
        words["requirements"]["word_anchor_count"] == 5
        and aligns["requirements"]["mapped_count"] == 5
        and not requirements["fallback_only"]
    )
    blockers = []
    if not requirements_ok:
        blockers.append("Requirements Word anchors were not fully extracted/mapped or remained fallback-only")
    if not precision_ok:
        blockers.append("Detailed Design or Test audited Heading Precision is below 90%")
    if not parent_child or not section_tree:
        blockers.append("Parent/Child or section-tree integrity is incomplete")
    if not citation:
        blockers.append("Physical-page Citation mapping is invalid")
    if not source_hash or not pdf_hash:
        blockers.append("Source Word or canonical PDF hash changed")
    if not word_first or not pdf_fallback or not full_fallback:
        blockers.append("Word-first, PDF heuristic fallback, or full fallback path failed")
    ready = not blockers

    decisions = {
        "REQUIREMENTS_WORD_ANCHORS_EXTRACTED": words["requirements"]["word_anchor_count"],
        "REQUIREMENTS_WORD_ANCHORS_MAPPED": aligns["requirements"]["mapped_count"],
        "REQUIREMENTS_FALLBACK_ONLY": yn(requirements["fallback_only"]),
        "DETAIL_DESIGN_SECTION_COUNT_BEFORE": design["section_count_before"],
        "DETAIL_DESIGN_SECTION_COUNT_AFTER": design["section_count_after"],
        "DETAIL_DESIGN_HEADING_PRECISION": pct(design["heading_precision"]),
        "TEST_SECTION_COUNT_BEFORE": test["section_count_before"],
        "TEST_SECTION_COUNT_AFTER": test["section_count_after"],
        "TEST_HEADING_PRECISION": pct(test["heading_precision"]),
        "PARENT_CHILD_MAPPING": "100%" if parent_child else "INCOMPLETE",
        "CITATION_PAGE_MAPPING_VALID": yn(citation),
        "SOURCE_HASH_UNCHANGED": yn(source_hash),
        "PDF_HASH_UNCHANGED": yn(pdf_hash),
        "WORD_FIRST_STRUCTURE_WORKING": yn(word_first),
        "PDF_FALLBACK_WORKING": yn(pdf_fallback),
        "READY_FOR_REAL_RETRIEVAL_EVALUATION": yn(ready),
    }
    section_quality = {
        "schema_version": 1,
        "decisions": decisions,
        "documents": evidence["documents"],
        "qa": evidence["qa"],
        "blockers": blockers,
        "full_fallback_working": full_fallback,
        "online_models_called": False,
        "embedding_or_retrieval_run": False,
        "body_text_included": False,
    }
    write_json_atomic(args.output_dir / "word_sidecar_summary.json", word_summary)
    write_json_atomic(args.output_dir / "page_alignment_summary.json", alignment_summary)
    write_json_atomic(args.output_dir / "section_quality_after.json", section_quality)

    report = [
        "# R&D V2 Section Structure Minimal Repair",
        "",
        "## Outcome",
        "",
    ]
    report.extend(f"{key} = {value}" for key, value in decisions.items())
    report.extend(
        [
            "",
            "## Implementation",
            "",
            "The repaired path extracts Word Heading/Outline metadata into a deterministic sidecar, aligns ordered headings to canonical-PDF physical lines, resolves mapped Word sections first, permits only independent high-confidence PDF semantic headings, applies local fallback to unresolved Word regions, and retains the legacy page chunker when no reliable heading exists.",
            "",
            "Canonical PDF remains the content and Citation source. The Citation identity remains `(document_id, page_number)`.",
            "",
            "Pure Arabic numbering at any depth is no longer sufficient heading evidence. The guarded classifier distinguishes `REAL_HEADING`, `NUMBERED_LIST_ITEM`, `TABLE_ROW`, `FIELD_LABEL`, `TEST_STEP`, `BODY_SENTENCE`, and `UNKNOWN`.",
            "",
            "## Per-document result",
            "",
            "| document_type | sections before | sections after | Word headings | PDF headings | fallback sections | unresolved Word | audited precision | Parent/Child | Citation pages |",
            "|---|---:|---:|---:|---:|---:|---:|---:|---|---|",
        ]
    )
    for item in evidence["documents"]:
        report.append(
            "| {document_type} | {section_count_before} | {section_count_after} | "
            "{word_heading_count} | {pdf_heading_count} | {fallback_section_count} | "
            "{unresolved_word_count} | {precision} | {parent} | {citation} |".format(
                **item,
                precision=pct(item["heading_precision"]),
                parent=yn(item["parent_child_mapping_valid"]),
                citation=yn(item["citation_page_mapping_valid"]),
            )
        )
    report.extend(
        [
            "",
            "## Integrity and scope",
            "",
            f"- Section tree integrity valid: {yn(section_tree)}",
            f"- Full legacy fallback working: {yn(full_fallback)}",
            f"- Blockers: {'NONE' if not blockers else '; '.join(blockers)}",
            "- Source Word modified: NO",
            "- Canonical PDF modified: NO",
            "- Embedding, FAISS, BM25, RRF, Hybrid Ablation, Retrieval Evaluation, rerank, generation, or online LLM invoked: NO",
            "- Citation, Trusted QA, Version Governance, or Generation Prompt modified: NO",
        ]
    )
    write_text_atomic(args.output_dir / "section_repair_report.md", "\n".join(report))

    qa_report = [
        "# R&D V2 Section QA After Repair",
        "",
        "The QA artifact is body-free. Samples are deterministic and expose only classification, source, level, physical page, and mapping status.",
        "",
        "## Stratified audited samples",
        "",
        "| document_type | stratum | candidates | sampled | REAL_HEADING | precision |",
        "|---|---|---:|---:|---:|---:|",
    ]
    for qa in evidence["qa"]:
        for stratum, coverage in qa["sampling_coverage"].items():
            samples = [item for item in qa["samples"] if item["stratum"] == stratum]
            real = sum(item["classification"] == "REAL_HEADING" for item in samples)
            precision = real / len(samples) if samples else None
            qa_report.append(
                f"| {qa['document_type']} | {stratum} | {coverage['candidate_count']} | "
                f"{coverage['sample_count']} | {real} | {pct(precision)} |"
            )
    qa_report.extend(["", "## Rejected previous candidates", ""])
    for qa in evidence["qa"]:
        counts = qa["rejected_previous_candidate_classifications"]
        rendered = ", ".join(f"{key}={value}" for key, value in counts.items()) or "none"
        qa_report.append(f"- {qa['document_type']}: {rendered}")
    qa_report.extend(["", "## Full candidate classification scan", ""])
    for qa in evidence["qa"]:
        counts = qa["candidate_classification_counts"]
        rendered = ", ".join(f"{key}={value}" for key, value in counts.items()) or "none"
        qa_report.append(f"- {qa['document_type']}: {rendered}")
    qa_report.extend(
        [
            "",
            "## Acceptance",
            "",
            f"- Detailed Design Heading Precision >= 90%: {yn(design['heading_precision'] is not None and design['heading_precision'] >= 0.90)}",
            f"- Test / Acceptance Heading Precision >= 90%: {yn(test['heading_precision'] is not None and test['heading_precision'] >= 0.90)}",
            f"- Parent/Child mapping complete: {yn(parent_child)}",
            f"- Physical-page Citation mapping valid: {yn(citation)}",
            f"- Requirements no longer fallback-only: {yn(not requirements['fallback_only'])}",
        ]
    )
    write_text_atomic(args.output_dir / "section_qa_report.md", "\n".join(qa_report))
    print(json.dumps(decisions, ensure_ascii=False))


if __name__ == "__main__":
    main()
