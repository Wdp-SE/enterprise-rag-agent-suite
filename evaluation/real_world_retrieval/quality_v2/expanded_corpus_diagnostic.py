"""Regression probe for an expanded corpus using the frozen V2 questions.

The V2 HOLDOUT has already been seen. Results here diagnose effects of adding
sources and must not be used to select or tune a new retrieval policy.
"""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
REPO_ROOT = ROOT.parents[2]
SERVICE_ROOT = REPO_ROOT / "versioned-rag-service"
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(SERVICE_ROOT))

from evaluation.real_world_retrieval.quality_v2.metrics_audit import audit_case, summarize_cases  # noqa: E402
from src.public_knowledge import PublicKnowledgeIndex  # noqa: E402


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _rows(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def verify_frozen_question_inputs(root: Path = ROOT) -> dict:
    lock = json.loads((root / "selection_lock.json").read_text(encoding="utf-8"))
    for filename in ("queries.jsonl", "ground_truth.jsonl", "frozen_split.json"):
        if _sha256(root / filename) != lock["sha256"][filename]:
            raise ValueError(f"frozen evaluation input changed: {filename}")
    return lock


def run_diagnostic(root: Path = ROOT, index: PublicKnowledgeIndex | None = None) -> dict:
    lock = verify_frozen_question_inputs(root)
    index = index or PublicKnowledgeIndex()
    manifest_path = index.root / "corpus_manifest.json"
    current_manifest_hash = _sha256(manifest_path)
    if current_manifest_hash == lock["sha256"]["corpus_manifest.json"]:
        raise ValueError("corpus is unchanged; use the frozen V2 report instead")
    queries = _rows(root / "queries.jsonl")
    truth = {row["query_id"]: row for row in _rows(root / "ground_truth.jsonl")}
    split = json.loads((root / "frozen_split.json").read_text(encoding="utf-8"))
    chunks = {row["chunk_id"]: row for row in index.chunks}
    by_split = {}
    for split_name, query_ids in split.items():
        cases = []
        for query in queries:
            if query["query_id"] not in query_ids:
                continue
            hits = index.search(
                query["query"], top_k=5, version=query["version_scope"],
                language=query["language"], policy="bm25",
            )
            ranking = {
                "query_id": query["query_id"],
                "ranked_chunk_ids": [hit["chunk_id"] for hit in hits],
                "ranked_source_ids": [
                    f"{hit['version']}|{hit['language']}|{hit['document_key']}" for hit in hits
                ],
            }
            cases.append({"category": query["category"], **audit_case(ranking, truth[query["query_id"]], chunks)})
        by_split[split_name] = {"summary": summarize_cases(cases), "cases": cases}
    return {
        "purpose": "regression_diagnostic_only_not_new_holdout_or_policy_selection",
        "policy": "bm25",
        "frozen_questions_sha256": lock["sha256"]["queries.jsonl"],
        "frozen_ground_truth_sha256": lock["sha256"]["ground_truth.jsonl"],
        "old_corpus_manifest_sha256": lock["sha256"]["corpus_manifest.json"],
        "expanded_corpus_manifest_sha256": current_manifest_hash,
        "source_count": len(index.manifest["sources"]),
        "chunk_count": len(index.chunks),
        "splits": by_split,
    }


def main() -> None:
    print(json.dumps(run_diagnostic(), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
