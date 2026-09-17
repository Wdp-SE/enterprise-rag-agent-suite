"""Parse only runtime PDFs that do not yet have a successful JSON output."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))

from src.pdf_parsing import PDFParser


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("runtime_root", type=Path)
    parser.add_argument("--max-workers", type=int, default=2)
    parser.add_argument("--chunk-size", type=int, default=1)
    parser.add_argument(
        "--disable-ocr",
        action="store_true",
        help="Skip OCR for text-native PDFs when OCR fails on malformed image crops.",
    )
    parser.add_argument(
        "--document-id",
        action="append",
        help="Only parse the named PDF stem; may be supplied more than once.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    # Keep an ASCII junction path intact on Windows. ``resolve()`` expands the
    # junction back to the original non-ASCII workspace path, which the native
    # docling-parse v2 extension cannot open even though Python can.
    runtime_root = args.runtime_root.absolute()
    pdf_dir = runtime_root / "pdf_reports"
    output_dir = runtime_root / "debug_data" / "01_parsed_reports"
    debug_dir = runtime_root / "debug_data" / "01_parsed_reports_debug"
    completed = {path.stem for path in output_dir.glob("*.json")}
    pending = sorted(path for path in pdf_dir.glob("*.pdf") if path.stem not in completed)
    if args.document_id:
        requested = set(args.document_id)
        pending = [path for path in pending if path.stem in requested]

    print(f"completed={len(completed)} pending={len(pending)}")
    if not pending:
        return

    parser = PDFParser(
        output_dir=output_dir,
        csv_metadata_path=runtime_root / "subset.csv",
        do_ocr=not args.disable_ocr,
    )
    parser.debug_data_path = debug_dir
    parser.parse_and_export_parallel(
        input_doc_paths=pending,
        optimal_workers=args.max_workers,
        chunk_size=args.chunk_size,
    )


if __name__ == "__main__":
    main()
