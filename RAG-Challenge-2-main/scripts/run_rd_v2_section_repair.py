"""Apply Word-first structure repair to the representative corpus only.

The script consumes existing local merged PDF artifacts and mapped sidecars. It
does not parse PDFs again and never invokes embedding, retrieval, or an online
model. Console output and evidence are body-free.
"""

from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import re
import sys


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.sectioning import SectionAwareTextSplitter, classify_heading_candidate
from src.word_structure import FALLBACK, heading_match_key


def load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_json_atomic(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".partial")
    if temporary.exists() or path.exists():
        raise RuntimeError("Refusing to overwrite an existing repaired structure artifact")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    temporary.replace(path)


def page_band(page: int, page_count: int) -> str:
    ratio = page / max(page_count, 1)
    if ratio <= 0.20:
        return "front"
    if 0.40 <= ratio <= 0.60:
        return "middle"
    if ratio >= 0.80:
        return "end"
    return "intermediate"


def deterministic_sample(pool: list[dict], stratum: str, limit: int = 12) -> list[dict]:
    return sorted(
        pool,
        key=lambda item: hashlib.sha256(
            f"{stratum}|{item['section_id']}".encode("utf-8")
        ).hexdigest(),
    )[:limit]


def build_qa(
    *,
    document_id: str,
    document_type: str,
    page_count: int,
    before_sections: list[dict],
    after_sections: list[dict],
    merged_pages: list[dict],
    word_records: list[dict],
) -> dict:
    accepted = [item for item in after_sections if item.get("heading_source") != FALLBACK]
    number_counts: Counter[int] = Counter()
    candidate_classifications: Counter[str] = Counter()
    table_hashes = {
        (int(item.get("page_number") or 0), item.get("normalized_text_sha256"))
        for item in word_records
        if item.get("in_table") and int(item.get("page_number") or 0) > 0
    }
    for page in merged_pages:
        page_number = int(page["page"])
        for line in str(page.get("text", "")).splitlines():
            normalized_line = re.sub(r"\s+", " ", line).strip()
            line_hash = hashlib.sha256(normalized_line.encode("utf-8")).hexdigest()
            classification = classify_heading_candidate(
                line, in_table=(page_number, line_hash) in table_hashes
            )
            candidate_classifications[classification] += 1
            if classification in {"NUMBERED_LIST_ITEM", "TEST_STEP"}:
                number_counts[page_number] += 1
    table_counts: Counter[int] = Counter(
        int(item.get("page_number") or 0)
        for item in word_records
        if item.get("in_table") and int(item.get("page_number") or 0) > 0
    )
    table_pages = {
        page for page, _ in sorted(table_counts.items(), key=lambda pair: (-pair[1], pair[0]))[:20]
    }
    numbered_pages = {
        page for page, _ in sorted(number_counts.items(), key=lambda pair: (-pair[1], pair[0]))[:20]
    }

    candidates = []
    for section in accepted:
        candidates.append(
            {
                "section_id": section["section_id"],
                "page_number": int(section["start_page"]),
                "page_band": page_band(int(section["start_page"]), page_count),
                "classification": "REAL_HEADING",
                "source": section["heading_source"],
                "level": int(section["level"]),
                "mapping_status": section.get("mapping_status"),
                "body_text_included": False,
            }
        )
    pools = {
        "front": [item for item in candidates if item["page_band"] == "front"],
        "middle": [item for item in candidates if item["page_band"] == "middle"],
        "end": [item for item in candidates if item["page_band"] == "end"],
        "table_dense": [
            item for item in candidates if any(abs(item["page_number"] - page) <= 1 for page in table_pages)
        ],
        "numbering_dense": [
            item for item in candidates if any(abs(item["page_number"] - page) <= 1 for page in numbered_pages)
        ],
    }
    samples = []
    coverage = {}
    for stratum, pool in pools.items():
        chosen = deterministic_sample(pool, stratum)
        coverage[stratum] = {"candidate_count": len(pool), "sample_count": len(chosen)}
        for item in chosen:
            samples.append(
                {
                    "sample_id": hashlib.sha256(
                        f"qa|{stratum}|{item['section_id']}".encode("utf-8")
                    ).hexdigest()[:16],
                    "stratum": stratum,
                    **{key: value for key, value in item.items() if key != "section_id"},
                }
            )
    audited_headings = len(samples)
    real_headings = sum(item["classification"] == "REAL_HEADING" for item in samples)

    after_keys = [
        (int(item["start_page"]), heading_match_key(str(item.get("title", ""))))
        for item in accepted
    ]
    rejected_counts: Counter[str] = Counter()
    for section in before_sections:
        page_number = int(section.get("start_page", 0))
        key = heading_match_key(str(section.get("title", "")))
        if any(
            candidate_key == key and abs(candidate_page - page_number) <= 2
            for candidate_page, candidate_key in after_keys
        ):
            continue
        rejected_counts[classify_heading_candidate(str(section.get("title", "")))] += 1

    return {
        "document_id": document_id,
        "document_type": document_type,
        "sampling_coverage": coverage,
        "samples": samples,
        "audited_heading_count": audited_headings,
        "audited_real_heading_count": real_headings,
        "heading_precision": round(real_headings / audited_headings, 6)
        if audited_headings
        else None,
        "candidate_classification_counts": dict(sorted(candidate_classifications.items())),
        "rejected_previous_candidate_classifications": dict(sorted(rejected_counts.items())),
        "body_text_included": False,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--corpus-root", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--sidecar-dir", type=Path, required=True)
    parser.add_argument("--word-audit", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--resolved-sidecar-dir", type=Path, required=True)
    parser.add_argument("--evidence-output", type=Path, required=True)
    args = parser.parse_args()

    corpus_root = args.corpus_root.resolve()
    manifest = load_json(args.manifest)
    audit = load_json(args.word_audit)
    audit_by_id = {item["document_id"]: item for item in audit["documents"]}
    document_rows = []
    qa_rows = []

    for metadata in manifest["documents"]:
        if metadata.get("status") != "success":
            continue
        document_id = metadata["document_id"]
        source_root = Path(manifest["source_root"])
        source = source_root / metadata["source_relative_path"]
        staged = corpus_root / metadata["staged_relative_path"]
        pdf = corpus_root / metadata["normalized_relative_path"]
        source_ok = sha256(source) == metadata["source_sha256"]
        staged_ok = sha256(staged) == metadata["source_sha256"]
        pdf_ok = sha256(pdf) == metadata["normalized_sha256"]

        merged_path = corpus_root / "normalized" / "merged" / document_id / f"{document_id}.json"
        before_path = corpus_root / "normalized" / "chunked" / document_id / f"{document_id}.json"
        sidecar_path = args.sidecar_dir / f"{document_id}.json"
        merged = load_json(merged_path)
        before = load_json(before_path)
        sidecar = load_json(sidecar_path)
        splitter = SectionAwareTextSplitter(
            child_chunk_size=180,
            child_chunk_overlap=30,
            structure_sidecar=sidecar,
        )
        repaired = splitter._split_report(merged)
        repaired_path = args.output_dir / document_id / f"{document_id}.json"
        write_json_atomic(repaired_path, repaired)

        pages = repaired["content"].get("pages", [])
        sections = repaired["content"].get("sections", [])
        chunks = repaired["content"].get("chunks", [])
        before_sections = before["content"].get("sections", [])
        section_ids = {item["section_id"] for item in sections}
        parent_child_valid = bool(chunks) and all(
            item.get("parent_id") == item.get("section_id")
            and item.get("parent_id") in section_ids
            and item.get("document_id") == document_id
            for item in chunks
        )
        section_tree_valid = all(
            item.get("parent_section_id") is None
            or item.get("parent_section_id") in section_ids
            for item in sections
        )
        page_count = sidecar["alignment"]["physical_page_count"]
        citation_valid = all(
            1 <= int(item.get("page_number", item.get("page", 0))) <= page_count
            and int(item.get("page_number", item.get("page", 0))) == int(item.get("page", 0))
            for item in chunks
        )
        detection = repaired["content"].get("section_detection", {})
        resolved_sidecar = {
            "schema_version": 1,
            "document_id": document_id,
            "source_file_hash": sidecar["source_file_hash"],
            "normalized_pdf_id": sidecar["normalized_pdf_id"],
            "extractor_version": sidecar["extractor_version"],
            "sections": [
                {
                    "section_id": section["section_id"],
                    "normalized_title": section["title"],
                    "title_hash": section["title_hash"],
                    "level": section["level"],
                    "parent_section_id": section.get("parent_section_id"),
                    "order": index,
                    "source": section["heading_source"],
                    "mapped_start_page": section["start_page"],
                    "mapped_end_page": section["end_page"],
                    "mapping_status": section.get("mapping_status")
                    or ("FALLBACK_REGION" if section["heading_source"] == FALLBACK else "PDF_HEURISTIC"),
                }
                for index, section in enumerate(sections, start=1)
            ],
            "source_enum": ["WORD_OUTLINE", "PDF_HEURISTIC", "FALLBACK"],
            "citation_source": "canonical_pdf_physical_pages",
            "body_text_included": False,
            "online_services_used": False,
        }
        write_json_atomic(
            args.resolved_sidecar_dir / f"{document_id}.json", resolved_sidecar
        )
        qa = build_qa(
            document_id=document_id,
            document_type=metadata["document_type"],
            page_count=page_count,
            before_sections=before_sections,
            after_sections=sections,
            merged_pages=pages,
            word_records=audit_by_id[document_id].get("paragraph_records", []),
        )
        qa_rows.append(qa)
        document_rows.append(
            {
                "document_id": document_id,
                "document_type": metadata["document_type"],
                "pages": page_count,
                "section_count_before": len(before_sections),
                "section_count_after": len(sections),
                "word_heading_count": int(detection.get("word_heading_count", 0)),
                "pdf_heading_count": int(detection.get("pdf_heading_count", 0)),
                "fallback_section_count": int(detection.get("fallback_section_count", 0)),
                "unresolved_word_count": int(detection.get("unresolved_word_count", 0)),
                "section_detection_mode": detection.get("mode"),
                "child_chunk_count": len(chunks),
                "parent_child_mapping_valid": parent_child_valid,
                "section_tree_valid": section_tree_valid,
                "citation_page_mapping_valid": citation_valid,
                "source_hash_unchanged": source_ok and staged_ok,
                "pdf_hash_unchanged": pdf_ok,
                "fallback_only": detection.get("mode") == "legacy_fallback",
                "heading_precision": qa["heading_precision"],
                "body_text_included": False,
            }
        )

    synthetic_pdf = SectionAwareTextSplitter()._split_report(
        {
            "metainfo": {"document_id": "synthetic-pdf"},
            "content": {"pages": [{"page": 1, "text": "# Synthetic Heading\nbody"}]},
        }
    )
    synthetic_fallback = SectionAwareTextSplitter()._split_report(
        {
            "metainfo": {"document_id": "synthetic-fallback"},
            "content": {"pages": [{"page": 1, "text": "ordinary body"}]},
        }
    )
    evidence = {
        "schema_version": 1,
        "documents": document_rows,
        "qa": qa_rows,
        "pdf_fallback_working": synthetic_pdf["content"]["section_detection"]["mode"] == "pdf_heuristic",
        "full_fallback_working": synthetic_fallback["content"]["section_detection"]["mode"] == "legacy_fallback",
        "online_models_called": False,
        "embedding_or_retrieval_run": False,
        "body_text_included": False,
    }
    write_json_atomic(args.evidence_output, evidence)
    print(
        json.dumps(
            {
                "documents": [
                    {
                        "document_id": item["document_id"],
                        "before": item["section_count_before"],
                        "after": item["section_count_after"],
                        "precision": item["heading_precision"],
                        "parent_child": item["parent_child_mapping_valid"],
                        "citation": item["citation_page_mapping_valid"],
                    }
                    for item in document_rows
                ],
                "body_text_logged": False,
            },
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
