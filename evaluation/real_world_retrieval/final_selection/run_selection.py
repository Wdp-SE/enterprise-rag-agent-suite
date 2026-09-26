"""Run a bounded, DEV-first retrieval selection without touching deployed files."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import time
from pathlib import Path

from chunks import build_chunks, json_byte_size, variant_metadata
from metrics import by_category, score_hits, summarize
from offline import OfflineIndex


HERE = Path(__file__).resolve().parent
EVALUATION = HERE.parent
REPOSITORY = HERE.parents[2]
CORPUS = REPOSITORY / "versioned-rag-service" / "public_corpus"
RESULTS = HERE / "results.json"
SPLIT = HERE / "frozen_split.json"
LOCK = HERE / "selection_lock.json"


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _jsonl(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def frozen_inputs() -> tuple[dict, list[dict], dict[str, dict]]:
    split = _json(SPLIT)
    locations = {
        "queries.jsonl": EVALUATION / "queries.jsonl",
        "ground_truth.jsonl": EVALUATION / "ground_truth.jsonl",
        "corpus_manifest.json": CORPUS / "corpus_manifest.json",
    }
    for name, path in locations.items():
        if _sha256(path) != split["frozen_inputs_sha256"][name]:
            raise ValueError(f"frozen input hash changed: {name}")
    queries = _jsonl(locations["queries.jsonl"])
    truth = {row["id"]: row for row in _jsonl(locations["ground_truth.jsonl"])}
    all_ids = {row["id"] for row in queries}
    dev = set(split["dev_query_ids"])
    holdout = set(split["holdout_query_ids"])
    if dev & holdout or dev | holdout != all_ids or set(truth) != all_ids:
        raise ValueError("frozen query split is incomplete or overlapping")
    return split, queries, truth


def _selected(queries: list[dict], split: dict, cohort: str) -> list[dict]:
    ids = set(split[f"{cohort}_query_ids"])
    return [query for query in queries if query["id"] in ids]


def _evaluate(
    index: OfflineIndex,
    queries: list[dict],
    truth: dict[str, dict],
    *,
    strategy: str,
    top_k: int,
    weight: float = 0.5,
    cap: int | None = None,
) -> dict:
    rows = []
    for query in queries:
        hits, latency_ms = index.search(
            query["query"], version=query["version_scope"], strategy=strategy,
            top_k=top_k, bm25_weight=weight, max_chunks_per_document=cap,
        )
        rows.append(score_hits(query, truth[query["id"]], hits, latency_ms))
    return {"overall": summarize(rows), "by_category": by_category(rows), "rows": rows}


def _results() -> dict:
    if RESULTS.exists():
        result = _json(RESULTS)
        if result.get("split_sha256") != _sha256(SPLIT):
            raise ValueError("result split hash differs from frozen split")
        return result
    return {"split_sha256": _sha256(SPLIT), "stages": {}}


def _save(result: dict) -> None:
    RESULTS.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _index(variant: str) -> tuple[OfflineIndex, dict]:
    chunks = build_chunks(CORPUS, variant)
    metadata = {
        **variant_metadata(variant),
        "chunk_count": len(chunks),
        "chunks_json_bytes": json_byte_size(chunks),
    }
    return OfflineIndex(chunks), metadata


def _attach_neural(index: OfflineIndex) -> dict:
    from neural import MODEL_ID, MODEL_REVISION, NeuralEncoder

    started = time.perf_counter()
    encoder = NeuralEncoder()
    index.attach_neural(encoder)
    encoder.encode_queries(["DolphinScheduler 工作流参数如何传递？"])
    return {
        "model_id": MODEL_ID,
        "model_revision": MODEL_REVISION,
        "embedding_shape": list(index.neural_vectors.shape),
        "embedding_bytes": int(index.neural_vectors.nbytes),
        "load_and_index_seconds": round(time.perf_counter() - started, 2),
        "query_inference_in_latency": True,
        "model_load_and_index_excluded_from_query_latency": True,
    }


def _verify_a_parity(index: OfflineIndex, queries: list[dict]) -> None:
    from src.public_knowledge import PublicKnowledgeIndex

    production = PublicKnowledgeIndex()
    for query in queries:
        actual, _ = index.search(query["query"], version=query["version_scope"], strategy="bm25")
        expected = production.search(
            query["query"], version=query["version_scope"], language="all", policy="bm25"
        )
        if [row["chunk_id"] for row in actual] != [row["chunk_id"] for row in expected]:
            raise ValueError(f"offline A disagrees with production BM25: {query['id']}")


def run_chunk(split: dict, queries: list[dict], truth: dict[str, dict]) -> None:
    dev = _selected(queries, split, "dev")
    candidates = {}
    for variant in ("A", "B", "C"):
        index, metadata = _index(variant)
        if variant == "A":
            _verify_a_parity(index, dev)
        candidates[variant] = {
            "metadata": metadata,
            "dev": _evaluate(index, dev, truth, strategy="bm25", top_k=5),
        }
        print(variant, metadata["chunk_count"], candidates[variant]["dev"]["overall"])
    result = _results()
    result["stages"]["chunk_dev"] = {
        "retriever": "production-formula BM25",
        "top_k": 5,
        "marker_level_scoring": True,
        "candidates": candidates,
    }
    _save(result)


def run_retriever(split: dict, queries: list[dict], truth: dict[str, dict], variant: str) -> None:
    result = _results()
    if "chunk_dev" not in result["stages"]:
        raise ValueError("run DEV chunk comparison first")
    index, metadata = _index(variant)
    dev = _selected(queries, split, "dev")
    evaluations = {"bm25": _evaluate(index, dev, truth, strategy="bm25", top_k=5)}
    model_status: dict
    try:
        model_status = {"status": "AVAILABLE", **_attach_neural(index)}
    except Exception as exc:
        model_status = {"status": "NOT_REPRODUCIBLE", "error": f"{type(exc).__name__}: {exc}"}
    if model_status["status"] == "AVAILABLE":
        evaluations["neural_dense"] = _evaluate(index, dev, truth, strategy="neural_dense", top_k=5)
        for weight in (0.25, 0.5, 0.75):
            evaluations[f"hybrid_bm25_{weight:.2f}"] = _evaluate(
                index, dev, truth, strategy="hybrid", top_k=5, weight=weight
            )
    result["stages"]["retriever_dev"] = {
        "chunk": variant, "metadata": metadata,
        "model": model_status,
        "hybrid": "weighted reciprocal rank fusion, branch pool 50, rank constant 60",
        "evaluations": evaluations,
    }
    _save(result)
    for name, value in evaluations.items():
        print(name, value["overall"])
    print("model", model_status)


def _strategy_name(strategy: str, weight: float) -> str:
    return f"{strategy}_bm25_{weight:.2f}" if strategy == "hybrid" else strategy


def run_topk(
    split: dict, queries: list[dict], truth: dict[str, dict],
    variant: str, strategy: str, weight: float,
) -> None:
    result = _results()
    if "retriever_dev" not in result["stages"]:
        raise ValueError("run DEV retriever comparison first")
    index, _ = _index(variant)
    if strategy != "bm25":
        _attach_neural(index)
    dev = _selected(queries, split, "dev")
    evaluations = {
        str(top_k): _evaluate(index, dev, truth, strategy=strategy, top_k=top_k, weight=weight)
        for top_k in (3, 5, 8)
    }
    result["stages"].setdefault("topk_dev", {})[_strategy_name(strategy, weight)] = {
        "chunk": variant, "evaluations": evaluations,
    }
    _save(result)
    for top_k, value in evaluations.items():
        print(_strategy_name(strategy, weight), top_k, value["overall"])


def run_diversity(
    split: dict, queries: list[dict], truth: dict[str, dict],
    variant: str, strategy: str, weight: float, top_k: int, cap: int,
) -> None:
    result = _results()
    if "topk_dev" not in result["stages"]:
        raise ValueError("run DEV Top-K comparison first")
    index, _ = _index(variant)
    if strategy != "bm25":
        _attach_neural(index)
    dev = _selected(queries, split, "dev")
    evaluations = {
        "uncapped": _evaluate(index, dev, truth, strategy=strategy, top_k=top_k, weight=weight),
        f"cap_{cap}": _evaluate(index, dev, truth, strategy=strategy, top_k=top_k, weight=weight, cap=cap),
    }
    result["stages"]["diversity_dev"] = {
        "chunk": variant, "strategy": strategy, "weight": weight,
        "top_k": top_k, "cap": cap, "evaluations": evaluations,
    }
    _save(result)
    for name, value in evaluations.items():
        print(name, value["overall"])


def _matching_source(chunk: dict, source: dict) -> bool:
    return (
        chunk["document_key"] == source["document_key"]
        and chunk["version"] == source["version"]
        and chunk["locale"] == source["locale"]
        and chunk["heading"] == source["heading"]
        and source["evidence_marker"].casefold() in
        f"{chunk['heading']} {chunk['content']}".casefold()
    )


def _diagnose_cross_document(
    index: OfflineIndex, queries: list[dict], truth: dict[str, dict],
    *, strategy: str, top_k: int, weight: float, cap: int | None,
) -> list[dict]:
    analysis = []
    for query in queries:
        if query["category"] != "cross_document":
            continue
        raw, _ = index.search(
            query["query"], version=query["version_scope"], strategy=strategy,
            top_k=len(index.chunks), bm25_weight=weight,
        )
        final, _ = index.search(
            query["query"], version=query["version_scope"], strategy=strategy,
            top_k=len(index.chunks), bm25_weight=weight,
            max_chunks_per_document=cap,
        )
        sources = []
        for source in truth[query["id"]]["relevant"]:
            source_chunks = [chunk for chunk in index.chunks if _matching_source(chunk, source)]
            eligible_chunks = [
                chunk for chunk in source_chunks
                if query["version_scope"] == "all" or chunk["version"] == query["version_scope"]
            ]
            raw_rank = next((hit["rank"] for hit in raw if _matching_source(hit, source)), None)
            final_rank = next((hit["rank"] for hit in final if _matching_source(hit, source)), None)
            sources.append({
                "document_key": source["document_key"], "heading": source["heading"],
                "exists_in_index": bool(source_chunks),
                "eligible_after_scope": bool(eligible_chunks),
                "raw_rank": raw_rank, "final_rank": final_rank,
                "outside_final_top_k": final_rank is None or final_rank > top_k,
            })
        top_docs = [hit["document_id"] for hit in final[:top_k]]
        analysis.append({
            "id": query["id"], "cohort": "DEV" if query["id"] in _DEV_IDS else "HOLDOUT",
            "sources": sources,
            "top_k_document_ids": top_docs,
            "same_document_crowding": len(top_docs) != len(set(top_docs)),
            "both_sources_in_final_top_k": all(
                source["final_rank"] is not None and source["final_rank"] <= top_k
                for source in sources
            ),
        })
    return analysis


_DEV_IDS: set[str] = set()


def run_holdout(split: dict, queries: list[dict], truth: dict[str, dict]) -> None:
    result = _results()
    if "holdout_final" in result["stages"]:
        raise ValueError("HOLDOUT already evaluated; do not tune or repeat it")
    for prerequisite in ("chunk_dev", "retriever_dev", "topk_dev"):
        if prerequisite not in result["stages"]:
            raise ValueError(f"missing DEV stage: {prerequisite}")
    lock = _json(LOCK)
    if lock["frozen_split_sha256"] != _sha256(SPLIT):
        raise ValueError("selection lock uses another frozen split")
    if lock["dev_results_before_holdout_sha256"] != _sha256(RESULTS):
        raise ValueError("DEV results changed after selection was locked")
    variant = lock["chunk"]
    strategy = lock["strategy"]
    top_k = lock["top_k"]
    weight = lock.get("bm25_weight", 0.5)
    cap = lock.get("max_chunks_per_document")
    index, metadata = _index(variant)
    model = None
    if strategy != "bm25":
        model = _attach_neural(index)
    final = _evaluate(
        index, _selected(queries, split, "holdout"), truth,
        strategy=strategy, top_k=top_k, weight=weight, cap=cap,
    )
    global _DEV_IDS
    _DEV_IDS = set(split["dev_query_ids"])
    diagnostic = _diagnose_cross_document(
        index, queries, truth, strategy=strategy, top_k=top_k, weight=weight, cap=cap
    )
    result["stages"]["holdout_final"] = {
        "selection_lock_sha256": _sha256(LOCK), "metadata": metadata,
        "model": model, "evaluation": final,
    }
    _save(result)
    (HERE / "failure_analysis.json").write_text(
        json.dumps({"cross_document": diagnostic}, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print("HOLDOUT", final["overall"])
    print("cross_document", diagnostic)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("stage", choices=("chunk", "retriever", "topk", "diversity", "holdout"))
    parser.add_argument("--chunk", choices=("A", "B", "C"), default="A")
    parser.add_argument("--strategy", choices=("bm25", "neural_dense", "hybrid"), default="bm25")
    parser.add_argument("--weight", type=float, default=0.5)
    parser.add_argument("--top-k", type=int, default=5)
    parser.add_argument("--cap", type=int, default=2)
    args = parser.parse_args()
    split, queries, truth = frozen_inputs()
    if args.stage == "chunk":
        run_chunk(split, queries, truth)
    elif args.stage == "retriever":
        run_retriever(split, queries, truth, args.chunk)
    elif args.stage == "topk":
        run_topk(split, queries, truth, args.chunk, args.strategy, args.weight)
    elif args.stage == "diversity":
        run_diversity(split, queries, truth, args.chunk, args.strategy, args.weight, args.top_k, args.cap)
    else:
        run_holdout(split, queries, truth)


if __name__ == "__main__":
    main()
