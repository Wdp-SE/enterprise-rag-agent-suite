"""Create a metadata-only inventory for the real R&D V2 onboarding corpus.

This utility never opens documents through a parser and never emits document
body text. It reads only filesystem metadata plus file bytes for SHA256.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path


SUPPORTED_EXTENSIONS = {".doc", ".docx", ".pdf"}


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def infer_document_type(filename: str) -> str:
    lowered = filename.lower()
    rules = (
        (("需求", "技术指标", "requirement"), "requirements"),
        (("详细设计", "detailed design"), "detailed_design"),
        (("概要设计", "总体设计", "high-level design"), "high_level_design"),
        (("接口", "api", "interface"), "interface_specification"),
        (("测试", "验收", "test", "acceptance"), "test_or_acceptance"),
    )
    for needles, label in rules:
        if any(needle in lowered for needle in needles):
            return label
    return "unknown"


def support_for(extension: str) -> tuple[bool, str]:
    if extension == ".pdf":
        return False, "direct_pdf_supported"
    if extension == ".docx":
        return True, "conversion_required_current_parser_pdf_only"
    if extension == ".doc":
        return True, "conversion_required_legacy_binary_word"
    return True, "unsupported_requires_manual_review"


def build_inventory(source_root: Path) -> dict:
    files = []
    for path in sorted(source_root.rglob("*"), key=lambda item: str(item).casefold()):
        if path.is_symlink() or not path.is_file():
            continue
        extension = path.suffix.lower()
        conversion_required, parser_status = support_for(extension)
        files.append(
            {
                "file_name": path.name,
                "relative_path": path.relative_to(source_root).as_posix(),
                "extension": extension or "[none]",
                "size": path.stat().st_size,
                "sha256": sha256_file(path),
                "document_type": infer_document_type(path.name),
                "conversion_required": conversion_required,
                "parser_support_status": parser_status,
            }
        )

    counts = {
        "source_files_found": len(files),
        "doc_files": sum(item["extension"] == ".doc" for item in files),
        "docx_files": sum(item["extension"] == ".docx" for item in files),
        "pdf_files": sum(item["extension"] == ".pdf" for item in files),
        "other_files": sum(item["extension"] not in SUPPORTED_EXTENSIONS for item in files),
    }
    snapshot = hashlib.sha256()
    for item in files:
        snapshot.update(item["relative_path"].encode("utf-8"))
        snapshot.update(str(item["size"]).encode("ascii"))
        snapshot.update(item["sha256"].encode("ascii"))
    return {
        "schema_version": 1,
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "source_root": str(source_root.resolve()),
        "source_snapshot_sha256": snapshot.hexdigest(),
        "counts": counts,
        "files": files,
        "content_extracted": False,
    }


def markdown_for(inventory: dict) -> str:
    counts = inventory["counts"]
    lines = [
        "# R&D V2 Real Corpus Source Inventory",
        "",
        "This is a metadata-only inventory. No document body text was extracted or copied into this report.",
        "",
        f"- SOURCE_FILES_FOUND: {counts['source_files_found']}",
        f"- DOC_FILES: {counts['doc_files']}",
        f"- DOCX_FILES: {counts['docx_files']}",
        f"- PDF_FILES: {counts['pdf_files']}",
        f"- OTHER_FILES: {counts['other_files']}",
        f"- SOURCE_SNAPSHOT_SHA256: `{inventory['source_snapshot_sha256']}`",
        "",
        "| file_name | extension | size | sha256 | document_type | conversion_required | parser_support_status |",
        "|---|---:|---:|---|---|---:|---|",
    ]
    for item in inventory["files"]:
        name = item["file_name"].replace("|", "\\|")
        lines.append(
            f"| {name} | {item['extension']} | {item['size']} | `{item['sha256']}` | "
            f"{item['document_type']} | {str(item['conversion_required']).lower()} | "
            f"{item['parser_support_status']} |"
        )
    lines.extend(
        [
            "",
            "## Inventory policy",
            "",
            "- Source files were read only for filesystem metadata and streaming SHA256.",
            "- No parser was invoked and no document body text was written to either inventory file.",
            "- Symbolic links are excluded rather than followed outside the source root.",
            "",
        ]
    )
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source-root", type=Path, required=True)
    parser.add_argument("--report-root", type=Path, required=True)
    args = parser.parse_args()

    source_root = args.source_root.resolve()
    if not source_root.is_dir():
        raise SystemExit("Source root is not a readable directory")

    inventory = build_inventory(source_root)
    args.report_root.mkdir(parents=True, exist_ok=True)
    (args.report_root / "source_inventory.json").write_text(
        json.dumps(inventory, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    (args.report_root / "source_inventory.md").write_text(
        markdown_for(inventory), encoding="utf-8"
    )
    print(json.dumps(inventory["counts"], ensure_ascii=False))
    print(f"source_snapshot_sha256={inventory['source_snapshot_sha256']}")


if __name__ == "__main__":
    main()
