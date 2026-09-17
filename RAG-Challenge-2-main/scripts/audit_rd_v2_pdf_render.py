"""Audit rasterized canonical PDF pages without extracting or logging text."""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

from PIL import Image, ImageDraw, ImageStat
from pypdf import PdfReader


PAGE_NUMBER_RE = re.compile(r"(\d+)$")


def page_number(path: Path) -> int:
    match = PAGE_NUMBER_RE.search(path.stem)
    if not match:
        raise ValueError("Rendered page filename does not end in a page number")
    return int(match.group(1))


def write_json_atomic(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".partial")
    if temporary.exists():
        raise RuntimeError("Refusing to overwrite partial render QA stats")
    temporary.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


def page_metrics(path: Path) -> dict:
    with Image.open(path) as source:
        source.load()
        width, height = source.size
        gray = source.convert("L")
        thumb = gray.copy()
        thumb.thumbnail((160, 220))
        pixels = list(thumb.getdata())
        ink_ratio = sum(value < 245 for value in pixels) / max(1, len(pixels))
        band = max(1, round(min(width, height) * 0.01))
        edge_regions = (
            gray.crop((0, 0, width, band)),
            gray.crop((0, height - band, width, height)),
            gray.crop((0, 0, band, height)),
            gray.crop((width - band, 0, width, height)),
        )
        edge_pixels = []
        for region in edge_regions:
            small = region.copy()
            small.thumbnail((200, 200))
            edge_pixels.extend(small.getdata())
        edge_ink_ratio = sum(value < 128 for value in edge_pixels) / max(
            1, len(edge_pixels)
        )
        extrema = ImageStat.Stat(thumb).extrema[0]
    return {
        "page_number": page_number(path),
        "width": width,
        "height": height,
        "ink_ratio": round(ink_ratio, 6),
        "edge_ink_ratio": round(edge_ink_ratio, 6),
        "grayscale_extrema": [int(extrema[0]), int(extrema[1])],
    }


def make_contact_sheets(page_paths: list[Path], output_dir: Path) -> list[str]:
    output_dir.mkdir(parents=True, exist_ok=True)
    columns, rows = 6, 6
    cell_width, cell_height = 290, 410
    label_height = 20
    per_sheet = columns * rows
    outputs = []
    for sheet_index, start in enumerate(range(0, len(page_paths), per_sheet), 1):
        subset = page_paths[start : start + per_sheet]
        canvas = Image.new(
            "RGB", (columns * cell_width, rows * cell_height), "white"
        )
        draw = ImageDraw.Draw(canvas)
        for offset, path in enumerate(subset):
            row, column = divmod(offset, columns)
            with Image.open(path) as source:
                page = source.convert("RGB")
                page.thumbnail((cell_width - 8, cell_height - label_height - 8))
                x = column * cell_width + (cell_width - page.width) // 2
                y = row * cell_height + label_height
                canvas.paste(page, (x, y))
            draw.text(
                (column * cell_width + 5, row * cell_height + 3),
                f"p{page_number(path)}",
                fill="black",
            )
        output = output_dir / f"contact-{sheet_index:03d}.jpg"
        canvas.save(output, format="JPEG", quality=82, optimize=True)
        outputs.append(output.name)
    return outputs


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--document-id", required=True)
    parser.add_argument("--pdf", type=Path, required=True)
    parser.add_argument("--render-dir", type=Path, required=True)
    parser.add_argument("--stats-out", type=Path, required=True)
    args = parser.parse_args()

    page_paths = sorted(args.render_dir.glob("page-*.png"), key=page_number)
    expected_pages = len(PdfReader(str(args.pdf)).pages)
    if len(page_paths) != expected_pages:
        raise SystemExit("Rendered page count does not match canonical PDF page count")

    unreadable_pages = []
    metrics = []
    for path in page_paths:
        try:
            metrics.append(page_metrics(path))
        except Exception:
            unreadable_pages.append(page_number(path))

    dimensions = {(item["width"], item["height"]) for item in metrics}
    blank_candidates = [
        item["page_number"] for item in metrics if item["ink_ratio"] < 0.001
    ]
    edge_candidates = [
        item["page_number"] for item in metrics if item["edge_ink_ratio"] > 0.08
    ]
    sheets = make_contact_sheets(page_paths, args.render_dir / "contact_sheets")
    payload = {
        "schema_version": 1,
        "document_id": args.document_id,
        "expected_pdf_pages": expected_pages,
        "rendered_pages": len(page_paths),
        "unreadable_pages": unreadable_pages,
        "blank_page_candidates": blank_candidates,
        "edge_ink_candidates": edge_candidates,
        "distinct_page_dimensions": [list(item) for item in sorted(dimensions)],
        "all_pages_rasterized_and_readable": (
            len(page_paths) == expected_pages and not unreadable_pages
        ),
        "contact_sheet_count": len(sheets),
        "contact_sheets": sheets,
        "body_text_extracted_or_logged": False,
    }
    write_json_atomic(args.stats_out, payload)
    print(
        json.dumps(
            {
                "document_id": args.document_id,
                "pages": expected_pages,
                "unreadable": len(unreadable_pages),
                "blank_candidates": len(blank_candidates),
                "edge_candidates": len(edge_candidates),
                "contact_sheets": len(sheets),
            }
        )
    )


if __name__ == "__main__":
    main()
