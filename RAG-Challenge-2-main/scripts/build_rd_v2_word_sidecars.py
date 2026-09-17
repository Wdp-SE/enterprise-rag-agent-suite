"""Build mapped Word structure sidecars without logging source text."""

from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import sys


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.word_structure import HeadingPageMapper, WordStructureExtractor


def load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_json_atomic(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".partial")
    if temporary.exists() or path.exists():
        raise RuntimeError("Refusing to overwrite an existing structure sidecar artifact")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    temporary.replace(path)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--corpus-root", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--legacy-com", type=Path, required=True)
    parser.add_argument("--sidecar-dir", type=Path, required=True)
    parser.add_argument("--word-summary", type=Path, required=True)
    parser.add_argument("--alignment-summary", type=Path, required=True)
    args = parser.parse_args()

    corpus_root = args.corpus_root.resolve()
    manifest = load_json(args.manifest)
    legacy = load_json(args.legacy_com)
    legacy_by_id = {item["document_id"]: item for item in legacy.get("documents", [])}
    extractor = WordStructureExtractor()
    mapper = HeadingPageMapper()
    word_rows = []
    alignment_rows = []

    for metadata in manifest["documents"]:
        if metadata.get("status") != "success":
            continue
        document_id = metadata["document_id"]
        staged = (corpus_root / metadata["staged_relative_path"]).resolve()
        pdf = (corpus_root / metadata["normalized_relative_path"]).resolve()
        if sha256(staged) != metadata["source_sha256"]:
            raise RuntimeError("Staged Word hash mismatch")
        if sha256(pdf) != metadata["normalized_sha256"]:
            raise RuntimeError("Canonical PDF hash mismatch")
        normalized_pdf_id = f"sha256:{metadata['normalized_sha256']}"
        extension = metadata["source_extension"].lower()
        if extension == ".docx":
            sidecar = extractor.extract_docx(
                staged,
                document_id=document_id,
                source_file_hash=metadata["source_sha256"],
                normalized_pdf_id=normalized_pdf_id,
            )
        elif extension == ".doc":
            raw = legacy_by_id.get(document_id)
            if not raw or not raw.get("opened_read_only") or not raw.get("macros_forced_disabled"):
                raise RuntimeError("Reliable read-only legacy Word extraction is unavailable")
            if raw.get("source_file_hash") != metadata["source_sha256"]:
                raise RuntimeError("Legacy Word extraction hash mismatch")
            sidecar = extractor.from_com_records(
                raw.get("headings", []),
                document_id=document_id,
                source_file_hash=metadata["source_sha256"],
                normalized_pdf_id=normalized_pdf_id,
            )
        else:
            raise RuntimeError("Unsupported representative Word extension")

        merged_path = (
            corpus_root
            / "normalized"
            / "merged"
            / document_id
            / f"{document_id}.json"
        )
        pages = load_json(merged_path)["content"]["pages"]
        sidecar = mapper.map(sidecar, pages)
        write_json_atomic(args.sidecar_dir / f"{document_id}.json", sidecar)

        sections = sidecar["sections"]
        word_rows.append(
            {
                "document_id": document_id,
                "document_type": metadata["document_type"],
                "extractor": sidecar["extractor"],
                "extractor_version": sidecar["extractor_version"],
                "word_anchor_count": len(sections),
                "level_counts": dict(sorted(Counter(str(item["level"]) for item in sections).items())),
                "deterministic_section_ids_unique": len({item["section_id"] for item in sections}) == len(sections),
                "source_hash_verified": sidecar["source_file_hash"] == metadata["source_sha256"],
                "body_text_included": False,
            }
        )
        alignment_rows.append(
            {
                "document_id": document_id,
                "document_type": metadata["document_type"],
                **sidecar["alignment"],
                "canonical_pdf_hash_verified": sidecar["normalized_pdf_id"] == normalized_pdf_id,
                "unresolved_pages_guessed": False,
                "body_text_included": False,
            }
        )

    write_json_atomic(
        args.word_summary,
        {
            "schema_version": 1,
            "documents": word_rows,
            "online_services_used": False,
            "macros_executed": False,
            "body_text_included": False,
        },
    )
    write_json_atomic(
        args.alignment_summary,
        {
            "schema_version": 1,
            "documents": alignment_rows,
            "citation_source": "canonical_pdf_physical_pages",
            "unresolved_policy": "PDF_HEURISTIC_THEN_FALLBACK_NO_PAGE_GUESSING",
            "body_text_included": False,
        },
    )
    print(
        json.dumps(
            {
                "documents": [
                    {
                        "document_id": item["document_id"],
                        "anchors": item["word_anchor_count"],
                        "mapped": next(
                            row["mapped_count"]
                            for row in alignment_rows
                            if row["document_id"] == item["document_id"]
                        ),
                    }
                    for item in word_rows
                ],
                "body_text_logged": False,
            },
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
