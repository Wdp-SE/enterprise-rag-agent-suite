"""Rasterize a local Word-exported QA PDF for visual inspection."""

from __future__ import annotations

import argparse
from pathlib import Path

import pypdfium2 as pdfium


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("pdf", type=Path)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)
    document = pdfium.PdfDocument(str(args.pdf))
    for number, page in enumerate(document, start=1):
        target = args.output_dir / f"page-{number}.png"
        page.render(scale=2).to_pil().save(target)
    print(f"PDF_PAGES_RENDERED={len(document)}")


if __name__ == "__main__":
    main()
