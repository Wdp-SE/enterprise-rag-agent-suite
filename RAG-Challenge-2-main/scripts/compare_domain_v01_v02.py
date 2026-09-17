"""Write an evidence-only Domain Corpus v0.1 versus v0.2 comparison."""

from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path


def _load(root: Path, filename: str):
    return json.loads((root / filename).read_text(encoding="utf-8"))


def _citation_subset(metrics: dict, prefix: str) -> dict:
    rows = [
        row for row in metrics.get("per_question", [])
        if row.get("question_id", "").startswith(prefix)
    ]
    claims = sum(row.get("citation_count", 0) for row in rows)
    document_correct = sum(row.get("document_correct_claims", 0) for row in rows)
    page_correct = sum(row.get("page_correct_claims", 0) for row in rows)
    return {
        "questions": len(rows),
        "claimed_citations": claims,
        "document_citation_accuracy": round(document_correct / claims, 6) if claims else None,
        "page_citation_accuracy": round(page_correct / claims, 6) if claims else None,
        "document_citation_hit_rate": round(
            sum(bool(row.get("document_hit")) for row in rows) / len(rows), 6
        ) if rows else None,
        "page_citation_hit_rate": round(
            sum(bool(row.get("page_hit")) for row in rows) / len(rows), 6
        ) if rows else None,
    }


def _metric_view(root: Path) -> dict:
    retrieval = _load(root, "retrieval_metrics.json")
    citation = _load(root, "citation_metrics.json")
    ingestion = _load(root, "ingestion_statistics.json")
    failures = _load(root, "failure_cases.json")
    return {
        "indexed_documents": ingestion["documents"],
        "indexed_pages": ingestion["pages"],
        "chunks": ingestion["chunks"],
        "hit_at_k": retrieval["overall"]["hit_at_k"],
        "recall_at_k": retrieval["overall"]["recall_at_k"],
        "mrr": retrieval["overall"]["mrr"],
        "document_citation_accuracy": citation["document_citation_accuracy"],
        "page_citation_accuracy": citation["page_citation_accuracy"],
        "document_citation_hit_rate": citation["document_citation_hit_rate"],
        "page_citation_hit_rate": citation["page_citation_hit_rate"],
        "version_temporal_retrieval": retrieval["by_question_type"].get("version_temporal"),
        "version_temporal_citation": _citation_subset(citation, "version-"),
        "failure_taxonomy": dict(sorted(Counter(
            failure["failure_type"] for failure in failures
        ).items())),
    }


def _delta(old, new):
    if isinstance(old, (int, float)) and isinstance(new, (int, float)):
        return round(new - old, 6)
    return None


def compare(args: argparse.Namespace) -> None:
    v01 = _metric_view(args.v01)
    v02 = _metric_view(args.v02)
    payload = {
        "v0.1": v01,
        "v0.2": v02,
        "delta": {
            "indexed_documents": _delta(v01["indexed_documents"], v02["indexed_documents"]),
            "indexed_pages": _delta(v01["indexed_pages"], v02["indexed_pages"]),
            "chunks": _delta(v01["chunks"], v02["chunks"]),
            "hit_at_k": {
                key: _delta(v01["hit_at_k"][key], v02["hit_at_k"][key])
                for key in v01["hit_at_k"]
            },
            "recall_at_k": {
                key: _delta(v01["recall_at_k"][key], v02["recall_at_k"][key])
                for key in v01["recall_at_k"]
            },
            "mrr": _delta(v01["mrr"], v02["mrr"]),
            "document_citation_accuracy": _delta(
                v01["document_citation_accuracy"], v02["document_citation_accuracy"]
            ),
            "page_citation_accuracy": _delta(
                v01["page_citation_accuracy"], v02["page_citation_accuracy"]
            ),
        },
        "interpretation_boundary": [
            "The run evaluates retrieval and retrieval-evidence citation potential only.",
            "No answer LLM, confidence gate, version resolver, or temporal query planner was used.",
            "Metric changes are observations, not proof of causation by OCR alone.",
        ],
    }
    json_path = args.v02 / "v0_1_vs_v0_2.json"
    json_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    rows = []
    for label, old, new in (
        ("Indexed documents", v01["indexed_documents"], v02["indexed_documents"]),
        ("Indexed pages", v01["indexed_pages"], v02["indexed_pages"]),
        ("Chunks", v01["chunks"], v02["chunks"]),
        ("Hit@1", v01["hit_at_k"]["1"], v02["hit_at_k"]["1"]),
        ("Hit@3", v01["hit_at_k"]["3"], v02["hit_at_k"]["3"]),
        ("Hit@5", v01["hit_at_k"]["5"], v02["hit_at_k"]["5"]),
        ("Recall@1", v01["recall_at_k"]["1"], v02["recall_at_k"]["1"]),
        ("Recall@3", v01["recall_at_k"]["3"], v02["recall_at_k"]["3"]),
        ("Recall@5", v01["recall_at_k"]["5"], v02["recall_at_k"]["5"]),
        ("MRR", v01["mrr"], v02["mrr"]),
        ("Document citation accuracy", v01["document_citation_accuracy"], v02["document_citation_accuracy"]),
        ("Page citation accuracy", v01["page_citation_accuracy"], v02["page_citation_accuracy"]),
    ):
        rows.append(f"| {label} | {old} | {new} | {_delta(old, new)} |")
    version_old = v01["version_temporal_retrieval"]
    version_new = v02["version_temporal_retrieval"]
    markdown = "\n".join(
        [
            "# Domain Corpus v0.1 vs v0.2",
            "",
            "This is a retrieval/citation-only comparison. No answer LLM was run.",
            "",
            "| Metric | v0.1 | v0.2 | Delta |",
            "|---|---:|---:|---:|",
            *rows,
            "",
            "## Version / temporal subset",
            "",
            f"- v0.1 retrieval: `{json.dumps(version_old, ensure_ascii=False)}`",
            f"- v0.2 retrieval: `{json.dumps(version_new, ensure_ascii=False)}`",
            f"- v0.1 citation: `{json.dumps(v01['version_temporal_citation'], ensure_ascii=False)}`",
            f"- v0.2 citation: `{json.dumps(v02['version_temporal_citation'], ensure_ascii=False)}`",
            "",
            "## Failure taxonomy",
            "",
            f"- v0.1: `{json.dumps(v01['failure_taxonomy'], ensure_ascii=False)}`",
            f"- v0.2: `{json.dumps(v02['failure_taxonomy'], ensure_ascii=False)}`",
            "",
            "## Interpretation boundary",
            "",
            "OCR removes the parse blocker for TSG 08—2026. Remaining historical-version failures must not be attributed to OCR when TSG 08—2017 remains outside the default ACTIVE index and Version Governance is intentionally absent.",
        ]
    )
    (args.v02 / "v0_1_vs_v0_2.md").write_text(markdown, encoding="utf-8")
    print(json.dumps(payload["delta"], ensure_ascii=False, indent=2))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    parser.add_argument("--v01", type=Path, default=Path("reports/domain_evaluation_v0_1"))
    parser.add_argument("--v02", type=Path, default=Path("reports/domain_evaluation_v0_2"))
    return parser


if __name__ == "__main__":
    compare(build_parser().parse_args())
