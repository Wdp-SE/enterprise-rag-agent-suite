"""Serialize an evaluation bundle and concise Markdown summary."""

from __future__ import annotations

import json
from collections import Counter
from pathlib import Path
from typing import Iterable, Optional

from src.evaluation.corpus import CorpusManifest
from src.evaluation.dataset import EvaluationItem
from src.evaluation.failure import FailureCase


def _write_json(path: Path, payload: object) -> None:
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def write_evaluation_report(
    output_dir: Path | str,
    *,
    corpus_manifest: CorpusManifest,
    dataset: Iterable[EvaluationItem],
    retrieval_metrics: dict,
    citation_metrics: dict,
    answer_metrics: Optional[dict],
    failure_cases: Iterable[FailureCase],
    ingestion_statistics: Optional[dict] = None,
    run_notes: Optional[list[str]] = None,
) -> Path:
    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)
    items = list(dataset)
    failures = list(failure_cases)
    ingestion_statistics = ingestion_statistics or {}
    run_notes = run_notes or []

    _write_json(output / "corpus_manifest.json", corpus_manifest.model_dump())
    _write_json(output / "retrieval_metrics.json", retrieval_metrics)
    _write_json(output / "citation_metrics.json", citation_metrics)
    _write_json(output / "answer_metrics.json", answer_metrics or {
        "status": "NOT_RUN",
        "reason": "Formal answer evaluation has not been executed.",
    })
    _write_json(
        output / "failure_cases.json",
        [failure.model_dump(mode="json") for failure in failures],
    )

    type_counts = Counter(item.question_type for item in items)
    failure_counts = Counter(failure.failure_type.value for failure in failures)
    overall = retrieval_metrics.get("overall", {})
    hit = overall.get("hit_at_k", {})
    recall = overall.get("recall_at_k", {})
    citation_doc = citation_metrics.get("document_citation_accuracy")
    citation_page = citation_metrics.get("page_citation_accuracy")
    active_documents = [
        document for document in corpus_manifest.documents
        if document.included_in_default_index
    ]

    summary = [
        f"# Domain Evaluation v{corpus_manifest.corpus_version}",
        "",
        "## Corpus",
        "",
        f"- Frozen source documents: {len(corpus_manifest.documents)}",
        f"- Default indexed documents: {len(active_documents)}",
        f"- Source PDF pages: {sum(document.pages_total for document in corpus_manifest.documents)}",
        f"- Indexed pages: {ingestion_statistics.get('pages', 'UNKNOWN')}",
        f"- Indexed chunks: {ingestion_statistics.get('chunks', 'UNKNOWN')}",
        "",
        "## Dataset",
        "",
        f"- Questions: {len(items)}",
    ]
    summary.extend(
        f"- {question_type}: {count}"
        for question_type, count in sorted(type_counts.items())
    )
    summary.extend(
        [
            "",
            "## Retrieval",
            "",
            f"- Hit@1: {hit.get('1')}",
            f"- Hit@3: {hit.get('3')}",
            f"- Hit@5: {hit.get('5')}",
            f"- Recall@1: {recall.get('1')}",
            f"- Recall@3: {recall.get('3')}",
            f"- Recall@5: {recall.get('5')}",
            f"- MRR: {overall.get('mrr')}",
            "",
            "## Citation",
            "",
            f"- Evaluation mode: {citation_metrics.get('evaluation_mode')}",
            f"- Document Citation Accuracy: {citation_doc}",
            f"- Page Citation Accuracy: {citation_page}",
            "",
            "## Answer",
            "",
            f"- Status: {'RUN' if answer_metrics else 'NOT_RUN'}",
            f"- Answerable Accuracy: {(answer_metrics or {}).get('answerable_accuracy')}",
            f"- Unanswerable Refusal Rate: {(answer_metrics or {}).get('unanswerable_refusal_rate')}",
            f"- Key Point Coverage: {(answer_metrics or {}).get('key_point_coverage')}",
            "",
            "## Failure distribution",
            "",
        ]
    )
    if failure_counts:
        summary.extend(f"- {name}: {count}" for name, count in sorted(failure_counts.items()))
    else:
        summary.append("- No classified failures")
    if run_notes:
        summary.extend(["", "## Run notes", ""])
        summary.extend(f"- {note}" for note in run_notes)

    summary_path = output / "evaluation_summary.md"
    summary_path.write_text("\n".join(summary) + "\n", encoding="utf-8")
    return summary_path
