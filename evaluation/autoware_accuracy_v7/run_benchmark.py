"""Offline Chinese-only retrieval experiment; does not change online defaults."""

from __future__ import annotations

import argparse
import hashlib
import json
import platform
import sys
import time
from pathlib import Path
from typing import Any

from huggingface_hub import snapshot_download
from sentence_transformers import SentenceTransformer

from evaluation.autoware_accuracy_v7.quality_first_retrieval import (
    dense_rank,
    reciprocal_rank_fusion,
    retrieval_metrics,
    validate_case_set,
)

ROOT = Path(__file__).resolve().parents[2]
SERVICE = ROOT / "versioned-rag-service"
CORPUS = SERVICE / "public_corpus_autoware"
HERE = Path(__file__).resolve().parent
CASES_PATH = HERE / "cases.jsonl"
RESULTS = HERE / "results"
DEV_REPORT = RESULTS / "dev-comparison.json"
SELECTION_LOCK = HERE / "selection_lock.json"
HOLDOUT_MARKER = RESULTS / "holdout-execution.json"
HOLDOUT_REPORT = RESULTS / "holdout-comparison.json"
MODEL_ID = "BAAI/bge-small-zh-v1.5"
MODEL_REVISION = "7999e1d3359715c523056ef9478215996d62a620"
QUERY_PREFIX = "为这个句子生成表示以用于检索相关文章："
TOP_KS = (5, 10, 20)
RRF_K = 60
RRF_POOLS = (20, 50, 100)
RERANK_CANDIDATE_K = 100
BASELINE = "bm25_global"

sys.path.insert(0, str(SERVICE))
from src.public_knowledge import PublicKnowledgeIndex  # noqa: E402


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes().replace(b"\r\n", b"\n")).hexdigest()


def _jsonl(path: Path) -> list[dict[str, Any]]:
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8-sig").splitlines()
        if line.strip()
    ]


def _previous_eval_labels(known_sources: set[str]) -> tuple[set[str], set[str]]:
    queries: set[str] = set()
    sources: set[str] = set()

    def visit(value: Any) -> None:
        if isinstance(value, dict):
            for key, nested in value.items():
                if key in {"query", "question", "user_query"} and isinstance(nested, str):
                    queries.add(nested)
                visit(nested)
        elif isinstance(value, list):
            for nested in value:
                visit(nested)
        elif isinstance(value, str) and value in known_sources:
            sources.add(value)

    for path in (ROOT / "evaluation").glob("**/*.jsonl"):
        if path.resolve() == CASES_PATH.resolve():
            continue
        for line in path.read_text(encoding="utf-8-sig").splitlines():
            if not line.strip():
                continue
            try:
                visit(json.loads(line))
            except json.JSONDecodeError:
                continue
    return queries, sources


def load_and_validate() -> tuple[list[dict[str, Any]], dict[str, Any], PublicKnowledgeIndex]:
    cases = _jsonl(CASES_PATH)
    index = PublicKnowledgeIndex(root=CORPUS)
    known_sources = {str(row.get("document_id", "")) for row in index.chunks}
    previous_queries, previous_sources = _previous_eval_labels(known_sources)
    summary = validate_case_set(
        cases,
        known_sources=known_sources,
        old_queries=previous_queries,
        old_sources=previous_sources,
    )
    manifest = json.loads((CORPUS / "corpus_manifest.json").read_text(encoding="utf-8"))
    source_rows = {
        f"{row['version']}:{row['language']}:{row['document_key']}": row
        for row in manifest["sources"]
    }
    for case in cases:
        for source_id in case["required_sources"]:
            source = source_rows.get(source_id)
            if source is None:
                raise ValueError(f"label missing from corpus manifest: {source_id}")
            text = (CORPUS / source["local_path"]).read_text(encoding="utf-8")
            if len(text.strip()) < 100:
                raise ValueError(f"gold source too short to support a claim: {source_id}")
    return cases, summary, index


def _scope_indices(index: PublicKnowledgeIndex) -> list[int]:
    return [
        i for i, row in enumerate(index.chunks)
        if row.get("version") == "docs-main" and row.get("language") == "zh"
    ]


def _passage_text(row: dict[str, Any], *, contextual: bool) -> str:
    if not contextual:
        return str(row.get("content", ""))
    headings = " > ".join(str(value) for value in row.get("heading_path", []) if value)
    return "\n".join(
        value for value in (
            f"文档标题：{row.get('document_title', '')}",
            f"文档路径：{row.get('document_key', '')}",
            f"章节：{headings}",
            str(row.get("content", "")),
        ) if value.strip()
    )


def _fingerprint(model_path: Path) -> dict[str, Any]:
    model_files = {}
    for path in sorted(model_path.rglob("*")):
        if path.is_file():
            model_files[str(path.relative_to(model_path))] = _sha256(path)
    return {
        "cases_sha256": _sha256(CASES_PATH),
        "corpus_manifest_sha256": _sha256(CORPUS / "corpus_manifest.json"),
        "chunks_sha256": _sha256(CORPUS / "chunks.json"),
        "baseline_index_sha256": _sha256(CORPUS / "dense_vectors.npy"),
        "retrieval_policy_sha256": _sha256(CORPUS / "retrieval_policy.json"),
        "public_index_code_sha256": _sha256(SERVICE / "src" / "public_knowledge.py"),
        "runner_sha256": _sha256(Path(__file__)),
        "model_id": MODEL_ID,
        "model_revision": MODEL_REVISION,
        "model_files_sha256": model_files,
        "python": platform.python_version(),
        "numpy": __import__("numpy").__version__,
        "sentence_transformers": __import__("sentence_transformers").__version__,
    }


def _rank_dense(
    query_vectors: dict[str, Any],
    scope_rows: list[dict[str, Any]],
    passage_vectors: dict[str, Any],
    *,
    query: str,
    field: str,
) -> list[dict[str, Any]]:
    from numpy import asarray

    return dense_rank(
        asarray(query_vectors[field][query], dtype="float32"),
        scope_rows,
        asarray(passage_vectors[field], dtype="float32"),
        version="docs-main",
        language="zh",
        top_k=len(scope_rows),
    )


def _rank_bm25(index: PublicKnowledgeIndex, scope_indices: list[int], query: str, *, fielded: bool = False) -> list[dict[str, Any]]:
    scores = index._bm25_fields(query) if fielded else index._bm25(query)
    ordered = sorted(scope_indices, key=lambda i: (-float(scores[i]), str(index.chunks[i]["chunk_id"])))
    return [
        {
            **index.chunks[i],
            "rank": rank,
            "retrieval_score": float(scores[i]),
            "retrieval_policy": "bm25_fields" if fielded else "bm25",
            "retrieval_sources": ["lexical"],
        }
        for rank, i in enumerate(ordered, start=1)
    ]


def _prepare_dense(index: PublicKnowledgeIndex, cases: list[dict[str, Any]], model_path: Path) -> tuple[dict, dict, dict]:
    import numpy as np

    model = SentenceTransformer(str(model_path), device="cpu")
    scope_indices = _scope_indices(index)
    scope_rows = [index.chunks[i] for i in scope_indices]
    cache_key = hashlib.sha256(
        f"{_sha256(CORPUS / 'chunks.json')}:{MODEL_ID}:{MODEL_REVISION}:title-heading-body-v1".encode()
    ).hexdigest()
    cache_meta_path = RESULTS / f"dense-vectors-{cache_key}.json"
    cache_body_path = RESULTS / f"dense-body-{cache_key}.npy"
    cache_context_path = RESULTS / f"dense-context-{cache_key}.npy"
    passage_vectors = {}
    cache_valid = all(path.exists() for path in (cache_meta_path, cache_body_path, cache_context_path))
    if cache_valid:
        try:
            cache_meta = json.loads(cache_meta_path.read_text(encoding="utf-8"))
            cache_valid = cache_meta.get("cache_key") == cache_key and cache_meta.get("scope_chunk_count") == len(scope_rows)
        except (OSError, json.JSONDecodeError):
            cache_valid = False
    if cache_valid:
        passage_vectors["body"] = np.load(cache_body_path, allow_pickle=False)
        passage_vectors["context"] = np.load(cache_context_path, allow_pickle=False)
    else:
        bodies = [_passage_text(row, contextual=False) for row in scope_rows]
        contexts = [_passage_text(row, contextual=True) for row in scope_rows]
        for name, texts in (("body", bodies), ("context", contexts)):
            vectors = model.encode(
                texts,
                batch_size=32,
                normalize_embeddings=True,
                convert_to_numpy=True,
                show_progress_bar=True,
            )
            passage_vectors[name] = np.asarray(vectors, dtype="float32")
        RESULTS.mkdir(parents=True, exist_ok=True)
        np.save(cache_body_path, passage_vectors["body"])
        np.save(cache_context_path, passage_vectors["context"])
        cache_meta_path.write_text(
            json.dumps({"cache_key": cache_key, "scope_chunk_count": len(scope_rows)}, indent=2) + "\n",
            encoding="utf-8", newline="\n",
        )
    query_values = list(dict.fromkeys(case["query"] for case in cases))
    query_vectors = model.encode(
        [QUERY_PREFIX + query for query in query_values],
        batch_size=32,
        normalize_embeddings=True,
        convert_to_numpy=True,
        show_progress_bar=True,
    )
    query_map = {
        field: {query: vector for query, vector in zip(query_values, query_vectors)}
        for field in ("body", "context")
    }
    return query_map, passage_vectors, {
        "scope_chunk_count": len(scope_rows),
        "passage_embedding_cache_hit": cache_valid,
        "passage_embedding_cache_key": cache_key,
    }


def _strategies(
    index: PublicKnowledgeIndex,
    cases: list[dict[str, Any]],
    scope_indices: list[int],
    query_vectors: dict,
    passage_vectors: dict,
    scope_rows: list[dict[str, Any]],
    names: set[str],
) -> dict[str, dict[str, list[dict[str, Any]]]]:
    output: dict[str, dict[str, list[dict[str, Any]]]] = {name: {} for name in names}
    for case in cases:
        query = case["query"]
        lexical = _rank_bm25(index, scope_indices, query)
        fielded = _rank_bm25(index, scope_indices, query, fielded=True)
        dense_body = _rank_dense(query_vectors, scope_rows, passage_vectors, query=query, field="body")
        dense_context = _rank_dense(query_vectors, scope_rows, passage_vectors, query=query, field="context")
        scope_position = {row["chunk_id"]: position for position, row in enumerate(scope_rows)}
        candidate_pool = lexical[:RERANK_CANDIDATE_K]
        candidate_vectors = {
            field: passage_vectors[field][[scope_position[row["chunk_id"]] for row in candidate_pool]]
            for field in ("body", "context")
        }
        reranked_body = dense_rank(
            query_vectors["body"][query], candidate_pool, candidate_vectors["body"],
            version="docs-main", language="zh", top_k=max(TOP_KS),
        )
        reranked_context = dense_rank(
            query_vectors["context"][query], candidate_pool, candidate_vectors["context"],
            version="docs-main", language="zh", top_k=max(TOP_KS),
        )
        reranked_body = [{**row, "retrieval_policy": "bm25_top100_bge_body_rerank"} for row in reranked_body]
        reranked_context = [{**row, "retrieval_policy": "bm25_top100_bge_context_rerank"} for row in reranked_context]
        all_rankings = {
            "bm25_global": lexical,
            "bm25_fields_global": fielded,
            "bge_body": dense_body,
            "bge_context": dense_context,
            "bm25_bge_body_rerank_top100": reranked_body,
            "bm25_bge_context_rerank_top100": reranked_context,
            "bm25_candidate_pool_top100": candidate_pool,
        }
        for pool_size in RRF_POOLS:
            all_rankings[f"rrf_context_{pool_size}"] = reciprocal_rank_fusion(
                [lexical[:pool_size], dense_context[:pool_size]],
                top_k=max(TOP_KS),
                rrf_k=RRF_K,
            )
        for name in names:
            output[name][case["case_id"]] = all_rankings[name]
    return output


def _report(
    *,
    cases: list[dict[str, Any]],
    case_summary: dict[str, Any],
    index: PublicKnowledgeIndex,
    model_path: Path,
    names: set[str],
    purpose: str,
    selected_candidate: str | None = None,
) -> dict[str, Any]:
    scope_indices = _scope_indices(index)
    scope_rows = [index.chunks[i] for i in scope_indices]
    started = time.perf_counter()
    query_vectors, passage_vectors, dense_summary = _prepare_dense(index, cases, model_path)
    embedding_seconds = time.perf_counter() - started
    started = time.perf_counter()
    results = _strategies(index, cases, scope_indices, query_vectors, passage_vectors, scope_rows, names)
    retrieval_seconds = time.perf_counter() - started
    ranked = {}
    per_case = {}
    for name, rows in results.items():
        ranked[name] = retrieval_metrics(cases, rows, ks=TOP_KS)
        per_case[name] = {
            case_id: [
                {
                    "rank": hit.get("rank"),
                    "document_id": hit.get("document_id"),
                    "chunk_id": hit.get("chunk_id"),
                    "version": hit.get("version"),
                    "language": hit.get("language"),
                    "score": hit.get("retrieval_score"),
                    "retrieval_sources": hit.get("retrieval_sources"),
                }
                for hit in rows[:20]
            ]
            for case_id, rows in rows.items()
        }
    candidate_pool_metrics = None
    if "bm25_candidate_pool_top100" in results:
        candidate_pool_metrics = retrieval_metrics(
            cases, results["bm25_candidate_pool_top100"], ks=(RERANK_CANDIDATE_K,),
        )
    return {
        "schema_version": 1,
        "status": "complete",
        "purpose": purpose,
        "scope": {"version": "docs-main", "language": "zh", "chunks": len(scope_rows)},
        "case_summary": case_summary,
        "strategies": ranked,
        "bm25_top100_candidate_pool": candidate_pool_metrics,
        "dense_index": dense_summary,
        "per_case_top20": per_case,
        "selected_candidate": selected_candidate,
        "model": {"id": MODEL_ID, "revision": MODEL_REVISION, "query_prefix": QUERY_PREFIX},
        "fingerprint": _fingerprint(model_path),
        "runtime_diagnostic": {
            "dense_embedding_setup_and_encode_seconds": round(embedding_seconds, 3),
            "retrieval_compare_seconds": round(retrieval_seconds, 3),
            "note": "One local CPU run for engineering context only; latency does not influence candidate selection.",
        },
        "limitations": [
            "Single-curator evaluation, not an independently authored blind test.",
            "Gold labels are required-source recall labels; they do not score answer factuality, citation entailment, hallucination, or Agent change-review correctness.",
            "Two no-answer cases are boundary probes only; they are too few to calibrate abstention or a similarity threshold.",
            "Image/chart evidence is outside this text-only benchmark.",
            "The Chinese docs-main snapshot is community translation material with known translation-quality risks; retrieval metrics cannot validate the source text itself.",
            "Cross-encoder reranking was not tested because a pinned reranker is not cached locally; no model downloads or paid API calls were used.",
            "The tested BM25→BGE reranker is a bi-encoder cosine reordering stage; it is not a cross-encoder reranker.",
            "Local corpus-only retrieval strategies were compared; production model generation and end-to-end answers were not run.",
        ],
    }


def run_dev() -> dict[str, Any]:
    cases, summary, index = load_and_validate()
    model_path = Path(snapshot_download(MODEL_ID, revision=MODEL_REVISION, local_files_only=True))
    names = {
        BASELINE, "bm25_fields_global", "bge_body", "bge_context",
        "bm25_bge_body_rerank_top100", "bm25_bge_context_rerank_top100",
        "bm25_candidate_pool_top100", *(f"rrf_context_{k}" for k in RRF_POOLS),
    }
    report = _report(
        cases=[case for case in cases if case["split"] == "dev"],
        case_summary={**summary, "evaluated_split": "dev"},
        index=index,
        model_path=model_path,
        names=names,
        purpose="Strategy exploration only; inspect DEV labels to select one candidate before HOLDOUT.",
    )
    RESULTS.mkdir(parents=True, exist_ok=True)
    DEV_REPORT.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")
    return report


def lock_candidate(candidate: str, rationale: str) -> dict[str, Any]:
    if candidate == BASELINE or not rationale.strip():
        raise ValueError("select one non-baseline candidate and record a rationale")
    if SELECTION_LOCK.exists() or HOLDOUT_MARKER.exists():
        raise ValueError("selection is already frozen; create a new benchmark version to change it")
    if not DEV_REPORT.exists():
        raise ValueError("run DEV comparison before selecting a candidate")
    report = json.loads(DEV_REPORT.read_text(encoding="utf-8"))
    if report.get("fingerprint", {}).get("cases_sha256") != _sha256(CASES_PATH):
        raise ValueError("DEV report no longer matches the current case set")
    if candidate not in report.get("strategies", {}):
        raise ValueError(f"candidate absent from frozen DEV report: {candidate}")
    lock = {
        "schema_version": 1,
        "status": "holdout_locked",
        "candidate": candidate,
        "rationale": rationale,
        "cases_sha256": _sha256(CASES_PATH),
        "dev_report_sha256": _sha256(DEV_REPORT),
        "fingerprint": report["fingerprint"],
        "note": "One pre-registered candidate plus the frozen BM25 baseline may be evaluated on HOLDOUT once.",
    }
    SELECTION_LOCK.write_text(json.dumps(lock, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")
    return lock


def run_holdout() -> dict[str, Any]:
    if not SELECTION_LOCK.exists() or HOLDOUT_MARKER.exists():
        raise ValueError("a selection lock is required and HOLDOUT can run only once")
    lock = json.loads(SELECTION_LOCK.read_text(encoding="utf-8"))
    if lock.get("status") != "holdout_locked" or lock.get("cases_sha256") != _sha256(CASES_PATH):
        raise ValueError("selection lock does not match the current case set")
    RESULTS.mkdir(parents=True, exist_ok=True)
    try:
        with HOLDOUT_MARKER.open("x", encoding="utf-8", newline="\n") as stream:
            stream.write(json.dumps({"status": "started", "selection_lock_sha256": _sha256(SELECTION_LOCK)}, indent=2) + "\n")
    except FileExistsError as exc:
        raise ValueError("HOLDOUT execution was already claimed") from exc
    try:
        cases, summary, index = load_and_validate()
        model_path = Path(snapshot_download(MODEL_ID, revision=MODEL_REVISION, local_files_only=True))
        selected = str(lock["candidate"])
        report = _report(
            cases=[case for case in cases if case["split"] == "holdout"],
            case_summary={**summary, "evaluated_split": "holdout"},
            index=index,
            model_path=model_path,
            names={BASELINE, selected},
            purpose="One-shot confirmation of one DEV-selected candidate against BM25 on group-disjoint HOLDOUT.",
            selected_candidate=selected,
        )
        report["selection_lock_sha256"] = _sha256(SELECTION_LOCK)
        HOLDOUT_REPORT.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")
        marker = json.loads(HOLDOUT_MARKER.read_text(encoding="utf-8"))
        marker.update({"status": "complete", "report_sha256": _sha256(HOLDOUT_REPORT)})
        HOLDOUT_MARKER.write_text(json.dumps(marker, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")
        return report
    except Exception as exc:
        marker = json.loads(HOLDOUT_MARKER.read_text(encoding="utf-8"))
        marker.update({"status": "failed_requires_new_benchmark_version", "error": type(exc).__name__})
        HOLDOUT_MARKER.write_text(json.dumps(marker, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")
        raise


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("dev", help="run all candidate retrieval strategies on DEV")
    lock_parser = subparsers.add_parser("lock", help="pre-register one candidate before HOLDOUT")
    lock_parser.add_argument("--candidate", required=True)
    lock_parser.add_argument("--rationale", required=True)
    subparsers.add_parser("holdout", help="run the pre-registered candidate and baseline once")
    args = parser.parse_args()
    if args.command == "dev":
        result = run_dev()
    elif args.command == "lock":
        result = lock_candidate(args.candidate, args.rationale)
    else:
        result = run_holdout()
    if args.command == "dev":
        result = {
            "status": result["status"],
            "purpose": result["purpose"],
            "scope": result["scope"],
            "case_summary": result["case_summary"],
            "strategies": result["strategies"],
            "bm25_top100_candidate_pool": result["bm25_top100_candidate_pool"],
            "dense_index": result["dense_index"],
            "report_path": str(DEV_REPORT),
        }
    elif args.command == "holdout":
        result = {
            "status": result["status"],
            "purpose": result["purpose"],
            "scope": result["scope"],
            "case_summary": result["case_summary"],
            "strategies": result["strategies"],
            "bm25_top100_candidate_pool": result["bm25_top100_candidate_pool"],
            "report_path": str(HOLDOUT_REPORT),
        }
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
