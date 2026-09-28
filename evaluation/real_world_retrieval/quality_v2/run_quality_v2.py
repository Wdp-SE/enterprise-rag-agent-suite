from __future__ import annotations

import argparse
import hashlib
import json
import math
import sys
import time
from collections import defaultdict
from pathlib import Path


EVAL_ROOT = Path(__file__).resolve().parent
REPO_ROOT = EVAL_ROOT.parents[2]
SERVICE_ROOT = REPO_ROOT / "versioned-rag-service"
CORPUS_ROOT = SERVICE_ROOT / "public_corpus"
CORPUS_MANIFEST = CORPUS_ROOT / "corpus_manifest.json"
PUBLIC_KNOWLEDGE_SOURCE = SERVICE_ROOT / "src" / "public_knowledge.py"
sys.path.insert(0, str(SERVICE_ROOT))

from src.public_knowledge import BM25_FIELD_WEIGHTS, PublicKnowledgeIndex  # noqa: E402


LOCKED_FILENAMES = (
    "queries.jsonl",
    "ground_truth.jsonl",
    "frozen_split.json",
)


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _jsonl(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def complete_source_recall(ranked_source_ids: list[str], required_source_ids: set[str]) -> bool:
    return bool(required_source_ids) and required_source_ids.issubset(ranked_source_ids)


def source_ranking_metrics(ranked_source_ids: list[str], expected_source_ids: set[str], top_k: int = 5) -> dict:
    unique_sources = list(dict.fromkeys(ranked_source_ids))[:top_k]
    ranks = [position for position, source_id in enumerate(unique_sources, start=1) if source_id in expected_source_ids]
    dcg = sum(1 / math.log2(rank + 1) for rank in ranks)
    ideal = sum(1 / math.log2(rank + 1) for rank in range(1, min(len(expected_source_ids), top_k) + 1))
    return {
        "recall_at_5": bool(expected_source_ids & set(unique_sources)),
        "reciprocal_rank": 1 / ranks[0] if ranks else 0.0,
        "ndcg_at_5": dcg / ideal if ideal else 0.0,
        "complete_source_recall": complete_source_recall(unique_sources, expected_source_ids),
    }


def assign_split(queries: list[dict]) -> dict[str, list[str]]:
    grouped: dict[str, list[dict]] = defaultdict(list)
    for query in queries:
        grouped[query["category"]].append(query)
    split: dict[str, list[str]] = {"dev": [], "holdout": []}
    for category, rows in sorted(grouped.items()):
        if len(rows) % 2:
            raise ValueError(f"category must have an even query count: {category}")
        ordered = sorted(
            rows,
            key=lambda row: hashlib.sha256(
                f"quality-v2:{category}:{row['query_id']}".encode("utf-8")
            ).digest(),
        )
        split["dev"].extend(row["query_id"] for row in ordered[::2])
        split["holdout"].extend(row["query_id"] for row in ordered[1::2])
    for name in split:
        split[name].sort()
    return split


def _locked_paths(root: Path, corpus_manifest_path: Path) -> dict[str, Path]:
    return {
        **{name: root / name for name in LOCKED_FILENAMES},
        "corpus_manifest.json": corpus_manifest_path,
    }


def freeze_inputs(
    root: Path = EVAL_ROOT,
    *,
    corpus_manifest_path: Path = CORPUS_MANIFEST,
) -> dict:
    lock_path = root / "selection_lock.json"
    split_path = root / "frozen_split.json"
    if lock_path.exists() or split_path.exists():
        raise FileExistsError("frozen V2 inputs already exist; they cannot be replaced")
    queries = _jsonl(root / "queries.jsonl")
    ids = [row["query_id"] for row in queries]
    if len(ids) != len(set(ids)):
        raise ValueError("query IDs must be unique")
    split = assign_split(queries)
    if set(split["dev"]) | set(split["holdout"]) != set(ids):
        raise ValueError("DEV/HOLDOUT split does not cover the query set")
    split_path.write_text(json.dumps(split, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")
    hashes = {
        name: _sha256(path.read_bytes())
        for name, path in _locked_paths(root, corpus_manifest_path).items()
    }
    lock = {
        "format_version": 1,
        "source_id_format": "version|language|document_key",
        "sha256": hashes,
    }
    lock_path.write_text(json.dumps(lock, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")
    return lock


def load_locked_inputs(
    root: Path = EVAL_ROOT,
    *,
    corpus_manifest_path: Path = CORPUS_MANIFEST,
) -> dict:
    paths = _locked_paths(root, corpus_manifest_path)
    lock = json.loads((root / "selection_lock.json").read_text(encoding="utf-8"))
    expected = lock.get("sha256")
    if not isinstance(expected, dict):
        raise ValueError("selection lock has no input hashes")
    actual = {name: _sha256(path.read_bytes()) for name, path in paths.items()}
    if actual != expected:
        changed = sorted(name for name in set(actual) | set(expected) if actual.get(name) != expected.get(name))
        raise ValueError("selection input hash mismatch: " + ", ".join(changed))
    queries = _jsonl(paths["queries.jsonl"])
    ground_truth_rows = _jsonl(paths["ground_truth.jsonl"])
    query_ids = [row["query_id"] for row in queries]
    truth_ids = [row["query_id"] for row in ground_truth_rows]
    if len(query_ids) != len(set(query_ids)) or set(query_ids) != set(truth_ids):
        raise ValueError("query and ground-truth IDs do not match")
    split = json.loads(paths["frozen_split.json"].read_text(encoding="utf-8"))
    dev, holdout = set(split.get("dev", [])), set(split.get("holdout", []))
    if dev & holdout or dev | holdout != set(query_ids):
        raise ValueError("frozen split must cover every query exactly once")
    manifest = json.loads(corpus_manifest_path.read_text(encoding="utf-8"))
    return {
        "queries": queries,
        "ground_truth": {row["query_id"]: row for row in ground_truth_rows},
        "split": split,
        "manifest": manifest,
        "lock": lock,
    }


def ensure_holdout_is_unrun(output_path: Path) -> None:
    if output_path.exists():
        raise FileExistsError(f"locked HOLDOUT result already exists: {output_path.name}")


def ensure_candidate_matches_dev(dev_result_path: Path, policy: str, candidate_sha256: str) -> None:
    result = json.loads(dev_result_path.read_text(encoding="utf-8"))
    if result.get("policy") != policy or result.get("candidate_sha256") != candidate_sha256:
        raise ValueError("candidate changed since DEV selection; rerun DEV before HOLDOUT")


def validate_ground_truth_markers(ground_truth_rows: list[dict], chunks: list[dict]) -> None:
    by_source: dict[str, list[dict]] = defaultdict(list)
    for chunk in chunks:
        by_source[_source_id(chunk)].append(chunk)
    for truth in ground_truth_rows:
        required = set(truth["required_source_ids"])
        markers = truth.get("expected_markers", {})
        if not isinstance(markers, dict) or set(markers) != required:
            raise ValueError(f"ground-truth marker sources do not match for {truth['query_id']}")
        for source_id, source_markers in markers.items():
            if not isinstance(source_markers, list) or not source_markers or source_id not in by_source:
                raise ValueError(f"ground-truth marker source is unavailable for {truth['query_id']}")
            source_text = "\n".join(
                " ".join([
                    chunk.get("document_title", ""), chunk.get("heading", ""),
                    " ".join(chunk.get("heading_path", [])), chunk.get("content", ""),
                ])
                for chunk in by_source[source_id]
            ).casefold()
            for marker in source_markers:
                if not isinstance(marker, str) or not marker.strip() or marker.casefold() not in source_text:
                    raise ValueError(f"ground-truth marker is not present in pinned source: {truth['query_id']}")


def _source_id(hit: dict) -> str:
    return f"{hit['version']}|{hit['language']}|{hit['document_key']}"


def _p95(values: list[float]) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    return ordered[max(0, math.ceil(0.95 * len(ordered)) - 1)]


def _aggregate(rows: list[dict]) -> dict:
    successful = [row for row in rows if not row.get("error")]
    answerable = [row for row in successful if row["answerable"]]
    multi = [row for row in answerable if len(row["expected_source_ids"]) > 1]
    no_answer = [row for row in successful if not row["answerable"]]
    latencies = [row["latency_ms"] for row in rows]
    scores = [row["top1_score"] for row in no_answer if row.get("top1_score") is not None]
    return {
        "query_count": len(rows),
        "error_count": sum(bool(row.get("error")) for row in rows),
        "answerable_count": len(answerable),
        "recall_at_5": sum(row["recall_at_5"] for row in answerable) / len(answerable) if answerable else None,
        "mrr": sum(row["reciprocal_rank"] for row in answerable) / len(answerable) if answerable else None,
        "ndcg_at_5": sum(row["ndcg_at_5"] for row in answerable) / len(answerable) if answerable else None,
        "multi_source_query_count": len(multi),
        "complete_multi_source_top5_recall": (
            sum(row["complete_source_recall"] for row in multi) / len(multi) if multi else None
        ),
        "citation_source_validity": (
            sum(row["valid_source_count"] for row in successful) / sum(row["hit_count"] for row in successful)
            if sum(row["hit_count"] for row in successful) else None
        ),
        "warm_p95_ms": _p95(latencies),
        "no_answer_top1_score_distribution": {
            "count": len(scores), "min": min(scores) if scores else None,
            "median": sorted(scores)[len(scores) // 2] if scores else None,
            "p95": _p95(scores), "max": max(scores) if scores else None,
        },
    }


def evaluate_policy(queries: list[dict], ground_truth: dict[str, dict], index: PublicKnowledgeIndex, policy: str) -> dict:
    warmed: list[dict] = []
    for query in queries:
        try:
            index.search(
                query["query"], top_k=5, version=query["version_scope"],
                language=query["language"], policy=policy,
            )
        except Exception:
            pass
    for query in queries:
        truth = ground_truth[query["query_id"]]
        expected = set(truth["required_source_ids"])
        started = time.perf_counter()
        try:
            hits = index.search(
                query["query"], top_k=5, version=query["version_scope"],
                language=query["language"], policy=policy,
            )
            error = None
        except Exception as exc:
            hits = []
            error = type(exc).__name__
        latency_ms = (time.perf_counter() - started) * 1000
        ranked = [_source_id(hit) for hit in hits]
        ranking_metrics = source_ranking_metrics(ranked, expected)
        warmed.append({
            "query_id": query["query_id"], "category": query["category"],
            "answerable": bool(truth["answerable"]),
            "expected_source_ids": sorted(expected), "ranked_source_ids": ranked,
            "ranked_chunk_ids": [hit["chunk_id"] for hit in hits],
            **ranking_metrics,
            "top1_score": float(hits[0]["retrieval_score"]) if hits else None,
            "hit_count": len(hits), "valid_source_count": len(ranked),
            "latency_ms": latency_ms, "error": error,
        })
    by_category: dict[str, list[dict]] = defaultdict(list)
    for row in warmed:
        by_category[row["category"]].append(row)
    return {
        "policy": policy,
        "overall": _aggregate(warmed),
        "by_category": {category: _aggregate(rows) for category, rows in sorted(by_category.items())},
        "cases": warmed,
    }


def run(split_name: str, policies: list[str], *, root: Path = EVAL_ROOT) -> list[Path]:
    loaded = load_locked_inputs(root)
    if split_name not in ("dev", "holdout"):
        raise ValueError("split must be dev or holdout")
    query_ids = set(loaded["split"][split_name])
    queries = [row for row in loaded["queries"] if row["query_id"] in query_ids]
    if split_name == "holdout" and (len(queries) != 20 or len(loaded["split"]["dev"]) != 20):
        raise ValueError("locked HOLDOUT must contain 20 cases after a 20-case DEV split")
    if len(loaded["queries"]) != 40 or len(queries) != 20:
        raise ValueError("V2 evaluation requires 40 queries and a 20-case split")
    output_root = root / "results"
    output_root.mkdir(parents=True, exist_ok=True)
    outputs = []
    candidate_sha256 = _sha256(PUBLIC_KNOWLEDGE_SOURCE.read_bytes())
    for policy in policies:
        path = output_root / f"{split_name}__{policy}.json"
        if split_name == "holdout":
            ensure_holdout_is_unrun(path)
            dev_path = output_root / f"dev__{policy}.json"
            ensure_candidate_matches_dev(dev_path, policy, candidate_sha256)
        index = PublicKnowledgeIndex()
        validate_ground_truth_markers(list(loaded["ground_truth"].values()), index.chunks)
        result = evaluate_policy(queries, loaded["ground_truth"], index, policy)
        payload = {
            "split": split_name,
            "policy": policy,
            "candidate_sha256": candidate_sha256,
            "input_hashes": loaded["lock"]["sha256"],
            "corpus_sha256": loaded["lock"]["sha256"]["corpus_manifest.json"],
            "bm25_fields_weights": BM25_FIELD_WEIGHTS if policy == "bm25_fields" else None,
            **result,
        }
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")
        outputs.append(path)
    return outputs


def main() -> None:
    parser = argparse.ArgumentParser(description="Locked V2 public retrieval quality comparison")
    parser.add_argument("--split", choices=("dev", "holdout"))
    parser.add_argument("--policies", default="bm25,bm25_fields")
    parser.add_argument("--freeze-inputs", action="store_true")
    args = parser.parse_args()
    if args.freeze_inputs:
        if args.split:
            parser.error("--freeze-inputs cannot be combined with --split")
        freeze_inputs()
        return
    if not args.split:
        parser.error("--split is required unless --freeze-inputs is used")
    policies = [value.strip() for value in args.policies.split(",") if value.strip()]
    if not policies or any(policy not in ("bm25", "bm25_fields") for policy in policies):
        parser.error("--policies supports only bm25,bm25_fields")
    for path in run(args.split, policies):
        print(path)


if __name__ == "__main__":
    main()
