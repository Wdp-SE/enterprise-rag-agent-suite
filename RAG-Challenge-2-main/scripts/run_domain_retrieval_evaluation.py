"""Run the frozen Domain Corpus v0.1 retrieval/citation baseline.

This runner intentionally does not generate answers or choose a confidence
threshold. By default it evaluates normalized vector retrieval only. The
optional ``--rerank`` switch exists for a separately budgeted rerank run.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import date
from pathlib import Path

import faiss

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.evaluation import (
    classify_failures,
    evaluate_citations,
    evaluate_retrieval,
    load_corpus_manifest,
    load_evaluation_dataset,
    write_evaluation_report,
)
from src.retrieval import HybridRetriever, VectorRetriever
from src.vector_utils import faiss_index_has_unit_norm_vectors
from src.versioning import VersionResolver


def _json_dump(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _ingestion_statistics(corpus_root: Path) -> dict:
    documents_dir = corpus_root / "databases" / "chunked_reports"
    vector_dir = corpus_root / "databases" / "vector_dbs"
    document_stats = []
    page_count = 0
    chunk_count = 0
    for path in sorted(documents_dir.glob("*.json")):
        document = json.loads(path.read_text(encoding="utf-8"))
        pages = document["content"].get("pages", [])
        chunks = document["content"].get("chunks", [])
        page_count += len(pages)
        chunk_count += len(chunks)
        index_path = vector_dir / f"{document['metainfo']['document_id']}.faiss"
        index = faiss.read_index(str(index_path)) if index_path.is_file() else None
        document_stats.append(
            {
                "document_id": document["metainfo"]["document_id"],
                "pages": len(pages),
                "chunks": len(chunks),
                "index_vectors": index.ntotal if index is not None else 0,
                "unit_norm_index": (
                    faiss_index_has_unit_norm_vectors(index)
                    if index is not None
                    else False
                ),
            }
        )
    return {
        "documents": len(document_stats),
        "pages": page_count,
        "chunks": chunk_count,
        "all_indexes_unit_norm": bool(document_stats) and all(
            item["unit_norm_index"] for item in document_stats
        ),
        "per_document": document_stats,
    }


def run(args: argparse.Namespace) -> None:
    # Keep FAISS paths relative on Windows. Some faiss-cpu builds cannot open
    # non-ASCII absolute paths even though the same files are readable through
    # a relative path from the project root.
    corpus_root = args.corpus_root
    report_dir = args.report_dir
    manifest = load_corpus_manifest(args.manifest, verify_source_files=True)
    items = load_evaluation_dataset(args.dataset)
    if args.question_id:
        wanted = set(args.question_id)
        items = [item for item in items if item.question_id in wanted]
        missing = wanted - {item.question_id for item in items}
        if missing:
            raise ValueError(f"unknown question ids: {sorted(missing)}")

    documents_dir = corpus_root / "databases" / "chunked_reports"
    vector_dir = corpus_root / "databases" / "vector_dbs"
    additional_corpora = []
    if args.version_governance:
        historical_documents = (
            args.historical_corpus_root / "databases" / "chunked_reports"
        )
        historical_vectors = args.historical_corpus_root / "databases" / "vector_dbs"
        additional_corpora.append((historical_vectors, historical_documents))
    if args.rerank:
        retriever = HybridRetriever(
            vector_dir,
            documents_dir,
            embedding_provider=args.embedding_provider,
            embedding_model=args.embedding_model,
            rerank_provider=args.rerank_provider,
            rerank_model=args.rerank_model,
            additional_corpora=additional_corpora,
        )
    else:
        retriever = VectorRetriever(
            vector_dir,
            documents_dir,
            embedding_provider=args.embedding_provider,
            embedding_model=args.embedding_model,
            additional_corpora=additional_corpora,
        )

    version_resolver = (
        VersionResolver(
            manifest,
            as_of_date=date.fromisoformat(args.version_as_of_date),
        )
        if args.version_governance
        else None
    )

    results_by_question = {}
    serializable_results = []
    version_traces_by_question = {}
    for item in items:
        started = time.perf_counter()
        version_plan = (
            version_resolver.resolve(
                item.question,
                available_document_ids=retriever.document_ids,
            )
            if version_resolver is not None
            else None
        )
        if args.rerank:
            results = retriever.retrieve(
                query=item.question,
                llm_reranking_sample_size=args.rerank_sample_size,
                top_n=args.top_k,
                return_parent_pages=True,
                per_document_top_k=args.rerank_sample_size,
                version_plan=version_plan,
            )
        else:
            results = retriever.retrieve(
                query=item.question,
                top_n=args.top_k,
                per_document_top_k=args.per_document_top_k,
                return_parent_pages=True,
                version_plan=version_plan,
            )
        latency_ms = round((time.perf_counter() - started) * 1000, 3)
        results_by_question[item.question_id] = results
        if version_plan is not None:
            trace = version_plan.trace(
                question_id=item.question_id
            )
            manifest_ids = {document.document_id for document in manifest.documents}
            available_ids = set(retriever.document_ids)
            for expected_id in item.expected_document_ids:
                if expected_id not in manifest_ids:
                    trace["issues"].append(f"DATASET_SOURCE_MISSING:{expected_id}")
                elif expected_id not in available_ids:
                    trace["issues"].append(f"INDEX_ASSET_MISSING:{expected_id}")
            trace["issues"] = list(dict.fromkeys(trace["issues"]))
            version_traces_by_question[item.question_id] = trace
        serializable_results.append(
            {
                "question_id": item.question_id,
                "question_type": item.question_type,
                "answerable": item.answerable,
                "latency_ms": latency_ms,
                "results": [
                    {
                        "rank": rank,
                        "document_id": result.get("document_id"),
                        "document_title": result.get("document_title"),
                        "page_number": result.get("page"),
                        "chunk_id": result.get("chunk_id"),
                        "cosine_similarity": result.get("distance"),
                        "rerank_score": result.get("relevance_score"),
                        "combined_score": result.get("combined_score"),
                        "original_score": result.get("original_score"),
                        "version_action": result.get("version_action"),
                        "version_adjustment": result.get("version_adjustment"),
                        "final_pre_rerank_score": result.get("final_pre_rerank_score"),
                        "document_number": result.get("document_number"),
                        "version": result.get("version"),
                        "status": result.get("status"),
                        "text_preview": result.get("text", "")[:240],
                    }
                    for rank, result in enumerate(results, start=1)
                ],
            }
        )

    retrieval_metrics = evaluate_retrieval(items, results_by_question, ks=(1, 3, 5))
    retrieval_citations = {
        question_id: [
            {
                "document_id": result.get("document_id"),
                "page_number": result.get("page"),
            }
            for result in results[: args.top_k]
        ]
        for question_id, results in results_by_question.items()
    }
    citation_metrics = evaluate_citations(
        items,
        retrieval_citations,
        evaluation_mode="retrieval_evidence_citation_potential",
    )
    parse_blocked = {
        document.document_id
        for document in manifest.documents
        if document.parse_status in {"OCR_REQUIRED", "PARSE_FAILED"}
    }
    failures = classify_failures(
        items,
        results_by_question,
        citations_by_question=retrieval_citations,
        parse_blocked_document_ids=parse_blocked,
        version_traces_by_question=version_traces_by_question,
    )
    ingestion_stats = _ingestion_statistics(corpus_root)

    _json_dump(
        report_dir / "retrieval_results.json",
        {
            "mode": "vector_plus_rerank" if args.rerank else "normalized_vector",
            "embedding_provider": args.embedding_provider,
            "embedding_model": args.embedding_model,
            "rerank_provider": args.rerank_provider if args.rerank else None,
            "rerank_model": args.rerank_model if args.rerank else None,
            "top_k": args.top_k,
            "per_document_top_k": args.per_document_top_k,
            "questions": serializable_results,
            "version_governance_enabled": args.version_governance,
            "version_traces": list(version_traces_by_question.values()),
        },
    )
    _json_dump(report_dir / "ingestion_statistics.json", ingestion_stats)
    write_evaluation_report(
        report_dir,
        corpus_manifest=manifest,
        dataset=items,
        retrieval_metrics=retrieval_metrics,
        citation_metrics=citation_metrics,
        answer_metrics=None,
        failure_cases=failures,
        ingestion_statistics=ingestion_stats,
        run_notes=[
            "No confidence threshold or reject policy was selected.",
            "Citation metrics in this run measure whether retrieved evidence pages hit ground truth; they are not generated-answer citation semantics.",
            "Documents marked OCR_REQUIRED were retained in the frozen corpus but excluded from the default index.",
            (
                "Version governance used deterministic manifest eligibility and traceable pre-rerank adjustments."
                if args.version_governance
                else "Version governance was disabled; historical assets were not loaded."
            ),
        ],
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--corpus-root", type=Path, default=Path("data/domain_corpus")
    )
    parser.add_argument(
        "--manifest",
        type=Path,
        default=Path("data/domain_corpus/domain_corpus_manifest.json"),
    )
    parser.add_argument(
        "--dataset",
        type=Path,
        default=Path("data/evaluation/domain_eval_v0_1.jsonl"),
    )
    parser.add_argument(
        "--report-dir",
        type=Path,
        default=Path("reports/domain_evaluation_v0_1"),
    )
    parser.add_argument("--top-k", type=int, default=5)
    parser.add_argument("--per-document-top-k", type=int, default=8)
    parser.add_argument("--embedding-provider", default="dashscope")
    parser.add_argument("--embedding-model", default="text-embedding-v1")
    parser.add_argument("--rerank", action="store_true")
    parser.add_argument("--rerank-provider", default="dashscope")
    parser.add_argument("--rerank-model", default="qwen-turbo")
    parser.add_argument("--rerank-sample-size", type=int, default=8)
    parser.add_argument("--question-id", action="append")
    parser.add_argument("--version-governance", action="store_true")
    parser.add_argument(
        "--historical-corpus-root",
        type=Path,
        default=Path("data/domain_corpus_v0_2/historical_retrieval_assets"),
    )
    parser.add_argument("--version-as-of-date", default="2026-09-01")
    return parser


if __name__ == "__main__":
    run(build_parser().parse_args())
