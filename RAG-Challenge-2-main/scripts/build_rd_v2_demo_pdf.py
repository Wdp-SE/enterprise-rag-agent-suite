"""Build the public, synthetic R&D specification used by the V2 prototype."""

from __future__ import annotations

import argparse
from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import (
    PageBreak,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)


PAGES = [
    (
        "1 Overview",
        [
            "This specification defines the R&amp;D Document Intelligence Platform. It covers ingestion, section-aware indexing, retrieval, export, reliability, security, and acceptance controls.",
            "The platform is designed for long requirements, design, interface, test, and acceptance documents. Every answer must remain traceable to a document identifier and a physical page number.",
            "Release identifier: RAG-RD-V2. Document status: prototype specification.",
        ],
    ),
    (
        "1.1 Data Processing Goals",
        [
            "Module RD-DATA-01 normalizes source records, preserves document_id and page_number, removes transport-only wrappers, and emits normalized_blocks.",
            "Its main responsibility is to turn parser output into stable evidence records without losing source provenance. It does not generate answers and it does not decide whether a question is answerable.",
            "The module accepts PDF parser blocks and OCR blocks through the same normalization contract.",
        ],
    ),
    (
        "2 Architecture",
        [
            "The request path is gateway, ingestion coordinator, parser, RD-DATA-01 normalizer, section detector, RD-INDEX-02 indexer, retrieval service, and answer service.",
            "The export worker is isolated from online retrieval. Monitoring observes both the ingestion and export paths, but monitoring does not own business records.",
            "Dense retrieval and sparse retrieval are independent candidate producers. Their raw scores are not directly added.",
        ],
    ),
    (
        "2.1 Ingestion Interface",
        [
            "POST /api/v2/ingest creates an asynchronous ingestion job.",
            "Required request fields are source_uri and document_id. Optional fields are language and force_ocr.",
            "A successful request returns job_id and accepted_at. The job_id is used to poll ingestion state.",
            "The interface rejects a blank source_uri before any parser work starts.",
        ],
    ),
    (
        "2.2 Indexing Contract",
        [
            "RD-INDEX-02 consumes normalized_blocks emitted by RD-DATA-01. It creates child embeddings, a FAISS IndexFlatIP index, and a local BM25 sparse index.",
            "Every child record retains chunk_id, parent_id, section_id, document_id, and page_number.",
            "The section detector output is consumed before embedding so that a child never crosses a detected section boundary.",
        ],
    ),
    (
        "3 Export Service",
        [
            "POST /api/export starts export operation EXPORT-ASYNC-07. The operation returns an export_job_id rather than a binary file in the initial response.",
            "The worker reads validated answer records and citation records, then writes a portable JSON package.",
            "GET /api/export/{export_job_id} returns the current export status.",
        ],
    ),
    (
        "3.1 Export Request Fields",
        [
            "The timeout_ms field controls the maximum export wait. Its default value is 30000 milliseconds and its allowed upper bound is 120000 milliseconds.",
            "The export_format field accepts json or markdown. The include_sources field defaults to true.",
            "Requests above the timeout_ms upper bound fail validation and do not enter the worker queue.",
        ],
    ),
    (
        "4 Performance Requirements",
        [
            "PERF-RD-100 requires sustained retrieval throughput of 1000 req/s for cached query embeddings.",
            "The maximum supported concurrent user count is 240. Under the reference workload, retrieval p95 latency must remain at or below 800 ms.",
            "The reference workload uses five evidence results and a 1800 token context budget.",
        ],
    ),
    (
        "5 Reliability and Failure Handling",
        [
            "Transient index write failures use retry_count 3 and initial backoff_ms 500. After retries are exhausted, the job moves to dead-letter queue DLQ-RD.",
            "A failed document does not prevent other documents in the same batch from completing.",
            "Section detection failure is non-fatal: ingestion falls back to the legacy page chunker and records legacy_fallback in the artifact.",
        ],
    ),
    (
        "6 Security Controls",
        [
            "The ingestion endpoint requires OAuth scope rag:ingest. The export endpoint requires scope rag:export.",
            "Stored source objects use AES-256 encryption. Service logs may include identifiers and hashes but must not include source document text or access tokens.",
            "External model calls are prohibited for restricted source documents unless an approved data boundary explicitly permits them.",
        ],
    ),
    (
        "7 Acceptance Criteria",
        [
            "AC-RAG-01 requires page-level Hit@3 of at least 0.85 on the frozen answerable retrieval set.",
            "AC-RAG-02 requires citation membership validation success of 100 percent for accepted generated answers.",
            "AC-RAG-03 requires retrieval p95 latency no greater than 800 ms under the reference workload.",
            "Ground truth must remain frozen during a comparison run; it may not be edited to improve reported metrics.",
        ],
    ),
    (
        "Appendix A Glossary",
        [
            "RD-DATA-01: source normalization module.",
            "RD-INDEX-02: section-aware dense and sparse indexing module.",
            "EXPORT-ASYNC-07: asynchronous export operation.",
            "normalized_blocks: provenance-preserving output consumed by the indexer.",
            "timeout_ms: maximum export wait in milliseconds.",
        ],
    ),
]


def _page_footer(canvas, document):
    canvas.saveState()
    canvas.setStrokeColor(colors.HexColor("#CBD5E1"))
    canvas.line(22 * mm, 16 * mm, 188 * mm, 16 * mm)
    canvas.setFillColor(colors.HexColor("#64748B"))
    canvas.setFont("Helvetica", 8)
    canvas.drawString(22 * mm, 10 * mm, "RAG-RD-V2 - Synthetic public prototype corpus")
    canvas.drawRightString(188 * mm, 10 * mm, f"Page {document.page}")
    canvas.restoreState()


def build_pdf(output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    styles = getSampleStyleSheet()
    title_style = ParagraphStyle(
        "Title",
        parent=styles["Title"],
        fontName="Helvetica-Bold",
        fontSize=23,
        leading=28,
        textColor=colors.HexColor("#0F172A"),
        alignment=TA_CENTER,
        spaceAfter=8 * mm,
    )
    heading_style = ParagraphStyle(
        "Section",
        parent=styles["Heading1"],
        fontName="Helvetica-Bold",
        fontSize=18,
        leading=22,
        textColor=colors.HexColor("#155E75"),
        spaceAfter=7 * mm,
    )
    body_style = ParagraphStyle(
        "Body",
        parent=styles["BodyText"],
        fontName="Helvetica",
        fontSize=11,
        leading=17,
        textColor=colors.HexColor("#1E293B"),
        spaceAfter=5 * mm,
    )
    label_style = ParagraphStyle(
        "Label",
        parent=styles["BodyText"],
        fontName="Helvetica-Bold",
        fontSize=8,
        leading=10,
        textColor=colors.white,
    )

    document = SimpleDocTemplate(
        str(output_path),
        pagesize=A4,
        rightMargin=22 * mm,
        leftMargin=22 * mm,
        topMargin=22 * mm,
        bottomMargin=24 * mm,
        title="R&D Document Intelligence Platform Specification",
        author="Synthetic prototype corpus",
    )
    story = []
    for page_index, (heading, paragraphs) in enumerate(PAGES):
        if page_index == 0:
            story.append(Paragraph("R&amp;D Document Intelligence Platform", title_style))
            badge = Table(
                [[Paragraph("PROTOTYPE SPECIFICATION - RAG-RD-V2", label_style)]],
                colWidths=[82 * mm],
            )
            badge.setStyle(
                TableStyle(
                    [
                        ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#0E7490")),
                        ("ALIGN", (0, 0), (-1, -1), "CENTER"),
                        ("TOPPADDING", (0, 0), (-1, -1), 6),
                        ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
                        ("BOX", (0, 0), (-1, -1), 0.5, colors.HexColor("#0E7490")),
                    ]
                )
            )
            story.extend([badge, Spacer(1, 14 * mm)])
        story.append(Paragraph(heading, heading_style))
        for paragraph in paragraphs:
            story.append(Paragraph(paragraph, body_style))
        if page_index < len(PAGES) - 1:
            story.append(PageBreak())
    document.build(story, onFirstPage=_page_footer, onLaterPages=_page_footer)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("output/pdf/rd_v2_demo_specification.pdf"),
    )
    args = parser.parse_args()
    build_pdf(args.output)
    print(args.output)


if __name__ == "__main__":
    main()
