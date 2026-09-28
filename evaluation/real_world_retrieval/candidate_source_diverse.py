"""Compare the optional source-diverse BM25 candidate on V2 DEV only.

This experiment intentionally never evaluates HOLDOUT or changes the
published retrieval policy. Source coverage and evidence-marker coverage are
reported separately: a correct document alone may still return the wrong
section for an answer.
"""

from __future__ import annotations

import hashlib
import json
import math
import sys
import time
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
V2_ROOT = Path(__file__).resolve().parent / "quality_v2"
SERVICE_ROOT = REPO_ROOT / "versioned-rag-service"
sys.path.insert(0, str(SERVICE_ROOT))

from src.public_knowledge import PublicKnowledgeIndex  # noqa: E402


def _dev_rows(name: str, dev_ids: set[str]) -> list[dict]:
    return [
        row
        for line in (V2_ROOT / name).read_text(encoding="utf-8").splitlines()
        if line.strip()
        for row in [json.loads(line)]
        if row["query_id"] in dev_ids
    ]


def _source_id(hit: dict) -> str:
    return f"{hit['version']}|{hit['language']}|{hit['document_key']}"


def _has_marker(hit: dict, markers: list[str]) -> bool:
    text = " ".join((
        hit.get("document_title", ""), hit.get("heading", ""),
        " ".join(hit.get("heading_path", [])), hit.get("content", ""),
    )).casefold()
    return any(marker.casefold() in text for marker in markers)


def _p95(values: list[float]) -> float:
    return sorted(values)[math.ceil(0.95 * len(values)) - 1]


def evaluate(index: PublicKnowledgeIndex, queries: list[dict], truths: dict[str, dict], policy: str) -> dict:
    # Warm both strategies before measuring, as the published BM25 number is warm.
    for row in queries:
        index.search(
            row["query"], top_k=5, version=row["version_scope"],
            language=row["language"], policy=policy,
        )
    cases = []
    latencies = []
    for row in queries:
        started = time.perf_counter()
        hits = index.search(
            row["query"], top_k=5, version=row["version_scope"],
            language=row["language"], policy=policy,
        )
        latencies.append((time.perf_counter() - started) * 1000)
        truth = truths[row["query_id"]]
        required = set(truth["required_source_ids"])
        returned = {_source_id(hit) for hit in hits}
        marker_sources = {
            source for source in required
            if any(_source_id(hit) == source and _has_marker(hit, truth["expected_markers"][source]) for hit in hits)
        }
        cases.append({
            "query_id": row["query_id"], "category": row["category"],
            "answerable": bool(truth["answerable"]),
            "required_source_count": len(required),
            "found_source_count": len(required & returned),
            "marker_source_count": len(marker_sources),
            "distinct_returned_source_count": len(returned),
        })
    answerable = [row for row in cases if row["answerable"]]
    multi = [row for row in answerable if row["required_source_count"] > 1]
    return {
        "policy": policy,
        "dev_count": len(cases),
        "answerable_count": len(answerable),
        "any_source_hit": sum(row["found_source_count"] > 0 for row in answerable),
        "all_required_sources_hit": sum(row["found_source_count"] == row["required_source_count"] for row in answerable),
        "multi_source_complete": sum(row["found_source_count"] == row["required_source_count"] for row in multi),
        "multi_source_count": len(multi),
        "marker_sources_found": sum(row["marker_source_count"] for row in answerable),
        "required_sources_total": sum(row["required_source_count"] for row in answerable),
        "mean_distinct_returned_sources": round(sum(row["distinct_returned_source_count"] for row in cases) / len(cases), 3),
        "warm_p95_ms": round(_p95(latencies), 3),
        "cases": cases,
    }


def main() -> None:
    dev_ids = set(json.loads((V2_ROOT / "frozen_split.json").read_text(encoding="utf-8"))["dev"])
    queries = _dev_rows("queries.jsonl", dev_ids)
    truths = {row["query_id"]: row for row in _dev_rows("ground_truth.jsonl", dev_ids)}
    if len(queries) != 20 or set(truths) != {row["query_id"] for row in queries}:
        raise ValueError("V2 DEV split is incomplete")
    index = PublicKnowledgeIndex()
    results = [evaluate(index, queries, truths, policy) for policy in ("bm25", "bm25_source_diverse")]
    changes = []
    for before, after in zip(results[0]["cases"], results[1]["cases"]):
        if (before["found_source_count"], before["marker_source_count"]) != (
            after["found_source_count"], after["marker_source_count"]
        ):
            changes.append({
                "query_id": before["query_id"],
                "before_sources": before["found_source_count"],
                "after_sources": after["found_source_count"],
                "before_marker_sources": before["marker_source_count"],
                "after_marker_sources": after["marker_source_count"],
            })
    for result in results:
        del result["cases"]
    print(json.dumps({
        "split": "quality_v2/dev_only",
        "manifest_sha256": hashlib.sha256((index.root / "corpus_manifest.json").read_bytes()).hexdigest(),
        "candidate_source_sha256": hashlib.sha256(
            (SERVICE_ROOT / "src" / "public_knowledge.py").read_bytes()
        ).hexdigest(),
        "results": results,
        "changed_cases": changes,
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
