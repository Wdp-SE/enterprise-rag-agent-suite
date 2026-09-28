"""Read-only audit of the frozen V2 rankings with correctly named metrics.

The original result files are historical evidence. This script reads them without
rerunning search or changing their recorded scores.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parent
CHUNKS_PATH = ROOT.parents[2] / "versioned-rag-service" / "public_corpus" / "chunks.json"


def _chunk_text(chunk: dict) -> str:
    return "\n".join(
        [
            str(chunk.get("document_title", "")),
            str(chunk.get("heading", "")),
            " / ".join(chunk.get("heading_path", [])),
            str(chunk.get("content", "")),
        ]
    ).casefold()


def _source_id(chunk: dict) -> str:
    return f"{chunk['version']}|{chunk['language']}|{chunk['document_key']}"


def audit_case(case: dict, truth: dict, chunks_by_id: dict[str, dict]) -> dict:
    ranked_sources = case["ranked_source_ids"][:5]
    ranked_chunk_ids = case["ranked_chunk_ids"][:5]
    if len(ranked_sources) != len(ranked_chunk_ids):
        raise ValueError(f"ranked source/chunk length differs for {case['query_id']}")
    by_source: dict[str, list[str]] = {}
    for source_id, chunk_id in zip(ranked_sources, ranked_chunk_ids):
        if chunk_id not in chunks_by_id:
            raise ValueError(f"missing ranked chunk {chunk_id} for {case['query_id']}")
        chunk = chunks_by_id[chunk_id]
        if _source_id(chunk) != source_id:
            raise ValueError(f"source does not match ranked chunk {chunk_id}")
        by_source.setdefault(source_id, []).append(_chunk_text(chunk))

    if not truth["answerable"]:
        return {
            "query_id": case["query_id"],
            "answerable": False,
            "source_hit_at_5": None,
            "source_recall_at_5": None,
            "complete_source_recall_at_5": None,
            "evidence_marker_recall_at_5": None,
            "unsupported_marker_source_ids": [],
            "required_source_count": 0,
            "found_source_count": 0,
            "required_marker_count": 0,
            "found_marker_count": 0,
        }

    required = set(truth["required_source_ids"])
    if not required:
        raise ValueError(f"answerable case has no required sources: {case['query_id']}")
    markers_by_source = truth["expected_markers"]
    if set(markers_by_source) != required:
        raise ValueError(f"marker/source mismatch for {case['query_id']}")
    found = required.intersection(by_source)
    marker_count = 0
    found_markers = 0
    unsupported = []
    for source_id, markers in markers_by_source.items():
        if not markers:
            raise ValueError(f"source has no evidence marker: {source_id}")
        marker_count += len(markers)
        source_texts = by_source.get(source_id, [])
        supported = sum(
            bool(marker.strip()) and any(marker.casefold() in text for text in source_texts)
            for marker in markers
        )
        found_markers += supported
        if supported < len(markers):
            unsupported.append(source_id)
    return {
        "query_id": case["query_id"],
        "answerable": True,
        "source_hit_at_5": bool(found),
        "source_recall_at_5": len(found) / len(required),
        "complete_source_recall_at_5": found == required,
        "evidence_marker_recall_at_5": found_markers / marker_count,
        "unsupported_marker_source_ids": sorted(unsupported),
        "required_source_count": len(required),
        "found_source_count": len(found),
        "required_marker_count": marker_count,
        "found_marker_count": found_markers,
    }


def summarize_cases(cases: list[dict]) -> dict:
    answerable = [case for case in cases if case["answerable"]]
    if not answerable:
        return {"answerable_count": 0}
    source_count = sum(case["required_source_count"] for case in answerable)
    marker_count = sum(case["required_marker_count"] for case in answerable)
    return {
        "answerable_count": len(answerable),
        "source_hit_at_5": sum(case["source_hit_at_5"] for case in answerable) / len(answerable),
        "macro_source_recall_at_5": sum(case["source_recall_at_5"] for case in answerable) / len(answerable),
        "micro_source_recall_at_5": sum(case["found_source_count"] for case in answerable) / source_count,
        "complete_source_recall_at_5": sum(case["complete_source_recall_at_5"] for case in answerable) / len(answerable),
        "macro_evidence_marker_recall_at_5": sum(case["evidence_marker_recall_at_5"] for case in answerable) / len(answerable),
        "micro_evidence_marker_recall_at_5": sum(case["found_marker_count"] for case in answerable) / marker_count,
    }


def audit_results(root: Path = ROOT, chunks_path: Path = CHUNKS_PATH) -> dict:
    chunks_bytes = chunks_path.read_bytes()
    chunks = json.loads(chunks_bytes)
    by_id = {chunk["chunk_id"]: chunk for chunk in chunks}
    if len(by_id) != len(chunks):
        raise ValueError("corpus has duplicate chunk IDs")
    ground_truth = {
        row["query_id"]: row
        for line in (root / "ground_truth.jsonl").read_text(encoding="utf-8").splitlines()
        if (row := json.loads(line))
    }
    output = {
        "metric_version": 2,
        "definitions": {
            "source_hit_at_5": "fraction of answerable questions with at least one required source in Top-5 chunks; this was previously labelled recall_at_5",
            "macro_source_recall_at_5": "mean per-question fraction of required sources present in Top-5 chunks",
            "micro_source_recall_at_5": "required sources found divided by all required sources",
            "evidence_marker_recall_at_5": "expected source markers found in their returned Top-5 chunks; this does not prove answer faithfulness",
        },
        "chunks_sha256": hashlib.sha256(chunks_bytes).hexdigest(),
        "rankings": {},
    }
    for path in sorted((root / "results").glob("*__*.json")):
        if path.name.startswith("metrics_audit"):
            continue
        result_bytes = path.read_bytes()
        result = json.loads(result_bytes)
        cases = [audit_case(case, ground_truth[case["query_id"]], by_id) for case in result["cases"]]
        if len(cases) != result["overall"]["query_count"]:
            raise ValueError(f"case count mismatch: {path.name}")
        original_hit = result["overall"].get("recall_at_5")
        corrected = summarize_cases(cases)
        if original_hit is not None and abs(corrected["source_hit_at_5"] - original_hit) > 1e-9:
            raise ValueError(f"historical hit score mismatch: {path.name}")
        output["rankings"][path.stem] = {
            "original_result_sha256": hashlib.sha256(result_bytes).hexdigest(),
            "summary": corrected,
            "cases": cases,
        }
    return output


def main() -> None:
    print(json.dumps(audit_results(), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
