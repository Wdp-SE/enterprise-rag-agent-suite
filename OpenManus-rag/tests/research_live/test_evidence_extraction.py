from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest
from pypdf import PdfWriter

from app.research.evidence_extraction import (
    EvidenceExtractionError,
    HtmlEvidenceExtractor,
    PdfEvidenceExtractor,
)
from app.research.evidence_store import EvidenceStore
from app.research.live_models import AcquisitionMethod, AcquiredSource
from app.research.models import SourceLevel


NOW = datetime(2026, 8, 28, tzinfo=timezone.utc)


def minimal_text_pdf(text: str) -> bytes:
    escaped = text.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
    stream = f"BT /F1 12 Tf 72 720 Td ({escaped}) Tj ET".encode("ascii")
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >>",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
        b"<< /Length " + str(len(stream)).encode("ascii") + b" >>\nstream\n" + stream + b"\nendstream",
    ]
    data = bytearray(b"%PDF-1.4\n")
    offsets = [0]
    for number, obj in enumerate(objects, start=1):
        offsets.append(len(data))
        data.extend(f"{number} 0 obj\n".encode("ascii"))
        data.extend(obj)
        data.extend(b"\nendobj\n")
    xref = len(data)
    data.extend(f"xref\n0 {len(objects) + 1}\n".encode("ascii"))
    data.extend(b"0000000000 65535 f \n")
    for offset in offsets[1:]:
        data.extend(f"{offset:010d} 00000 n \n".encode("ascii"))
    data.extend(
        f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode("ascii")
    )
    return bytes(data)


def acquired(tmp_path: Path, data: bytes, media_type: str, name: str) -> AcquiredSource:
    path = tmp_path / "research_runs/run/raw_sources" / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    import hashlib

    return AcquiredSource(
        search_result_id="sr_11111111111111111111",
        title="Fixture source",
        organization="fixture.gov.cn",
        source_url=f"https://fixture.gov.cn/{name}",
        final_url=f"https://fixture.gov.cn/{name}",
        source_type="pdf" if media_type == "application/pdf" else "webpage",
        source_level=SourceLevel.TIER1,
        media_type=media_type,
        acquisition_method=AcquisitionMethod.HTTP,
        retrieved_at=NOW,
        local_file=path.relative_to(tmp_path).as_posix(),
        raw_file_hash=hashlib.sha256(data).hexdigest(),
    )


def test_html_evidence_uses_sections_and_full_paragraph_groups(tmp_path: Path) -> None:
    data = b"""<!doctype html><html><head><title>Fixture</title></head><body><article>
    <h1>First section</h1><p>First complete fact paragraph.</p><p>Context for the first fact.</p>
    <h2>Second section</h2><p>Second complete fact paragraph.</p>
    <script>not evidence</script></article></body></html>"""
    source = acquired(tmp_path, data, "text/html", "source.html")

    evidence = HtmlEvidenceExtractor().extract(source, workspace_root=tmp_path)

    assert [item.section for item in evidence] == ["First section", "Second section"]
    assert "Context for the first fact" in evidence[0].content
    assert all("not evidence" not in item.content for item in evidence)
    assert all(item.local_file == source.local_file for item in evidence)


def test_text_pdf_evidence_is_page_located_and_persistable(tmp_path: Path) -> None:
    data = minimal_text_pdf(
        "A complete public-source paragraph contains enough context for extraction and review."
    )
    source = acquired(tmp_path, data, "application/pdf", "source.pdf")

    evidence = PdfEvidenceExtractor().extract(source, workspace_root=tmp_path)
    store = EvidenceStore(tmp_path, "research_runs/run/evidence/evidence.json")
    for item in evidence:
        store.add(item)
    store.save()
    loaded = EvidenceStore(tmp_path, "research_runs/run/evidence/evidence.json").load()

    assert evidence[0].page_number == 1
    assert "complete public-source paragraph" in evidence[0].content
    assert len(loaded) == len(evidence)


def test_scan_pdf_is_marked_unsupported_without_ocr(tmp_path: Path) -> None:
    path = tmp_path / "blank.pdf"
    writer = PdfWriter()
    writer.add_blank_page(width=612, height=792)
    writer.write(path)
    source = acquired(tmp_path, path.read_bytes(), "application/pdf", "scan.pdf")

    with pytest.raises(EvidenceExtractionError) as raised:
        PdfEvidenceExtractor().extract(source, workspace_root=tmp_path)

    assert raised.value.code.value == "UNSUPPORTED_SCAN_PDF"


def test_empty_html_is_rejected(tmp_path: Path) -> None:
    source = acquired(
        tmp_path,
        b"<html><body><script>only script</script></body></html>",
        "text/html",
        "empty.html",
    )

    with pytest.raises(EvidenceExtractionError) as raised:
        HtmlEvidenceExtractor().extract(source, workspace_root=tmp_path)

    assert raised.value.code.value == "EMPTY_CONTENT"

