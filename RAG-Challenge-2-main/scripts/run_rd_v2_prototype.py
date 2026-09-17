"""Prepare and evaluate the R&D Document RAG V2 prototype.

The retrieval comparison is intentionally answer-generation free.  It uses a
frozen synthetic technical specification, page-level ground truth, the existing
DashScope embedding/FAISS path, and the new local BM25/RRF path.
"""

from __future__ import annotations

import argparse
from collections import defaultdict
import json
import os
import sys
import time
from pathlib import Path
from statistics import mean

import faiss
from docling.backend.pypdfium2_backend import PyPdfiumDocumentBackend


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.pdf_parsing import PDFParser
from src.pipeline import Pipeline, RunConfig
from src.rd_retrieval import RDHybridRetriever, RDRetrievalConfig
from src.retrieval import VectorRetriever
from src.vector_utils import faiss_index_has_unit_norm_vectors


def _write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def prepare_corpus(corpus_root: Path, *, offline_parse: bool = False) -> None:
    # The verified host already has the pinned Docling artifacts cached.  Fresh
    # hosts can omit --offline-parse and allow the normal model download.
    if offline_parse:
        os.environ.setdefault("HF_HUB_OFFLINE", "1")
    pdf_dir = corpus_root / "pdf_reports"
    pdf_paths = sorted(pdf_dir.glob("*.pdf"))
    if not pdf_paths:
        raise FileNotFoundError(
            f"No PDF found in {pdf_dir}. Run scripts/build_rd_v2_demo_pdf.py first."
        )
    pipeline = Pipeline(
        corpus_root,
        run_config=RunConfig(
            routing_mode="generic",
            retrieval_mode="rd_hybrid",
            section_aware_chunking=True,
            child_chunk_size=70,
            child_chunk_overlap=10,
            use_bm25_db=True,
            llm_reranking=False,
            submission_file=False,
        ),
    )
    parser = PDFParser(
        # The pinned DoclingParseV2 native backend cannot resolve resource paths
        # containing non-ASCII characters on this Windows checkout.  PyPdfium
        # is already a supported backend in the existing parser abstraction and
        # keeps the rest of the parsing/merging pipeline unchanged.
        pdf_backend=PyPdfiumDocumentBackend,
        output_dir=pipeline.paths.parsed_reports_path,
        csv_metadata_path=pipeline.paths.subset_path,
        do_ocr=False,
    )
    parser.debug_data_path = pipeline.paths.parsed_reports_debug_path
    parser.parse_and_export(input_doc_paths=pdf_paths)
    # Keep Docling and FAISS in separate processes on Windows.  The follow-up
    # --rebuild-indexes command performs section chunking and both indexes.
    pipeline.merge_reports()
    pipeline.export_reports_to_markdown()


def rebuild_indexes(corpus_root: Path) -> None:
    """Re-run V2 chunking and both indexes from an existing merged artifact."""
    pipeline = Pipeline(
        corpus_root,
        run_config=RunConfig(
            routing_mode="generic",
            retrieval_mode="rd_hybrid",
            section_aware_chunking=True,
            child_chunk_size=70,
            child_chunk_overlap=10,
            use_bm25_db=True,
            llm_reranking=False,
            submission_file=False,
        ),
    )
    merged = sorted(pipeline.paths.merged_reports_path.glob("*.json"))
    if not merged:
        raise FileNotFoundError(
            f"No merged report found in {pipeline.paths.merged_reports_path}"
        )
    pipeline.chunk_reports()
    pipeline.create_vector_dbs()
    pipeline.create_bm25_db()


def _rank_record(results: list[dict], expected_pages: set[int]) -> dict:
    first_rank = next(
        (
            rank
            for rank, result in enumerate(results, start=1)
            if int(result.get("page", -1)) in expected_pages
        ),
        None,
    )
    return {
        "first_relevant_rank": first_rank,
        "reciprocal_rank": round(1 / first_rank, 6) if first_rank else 0.0,
        "hit_at_1": int(first_rank is not None and first_rank <= 1),
        "hit_at_3": int(first_rank is not None and first_rank <= 3),
        "hit_at_5": int(first_rank is not None and first_rank <= 5),
    }


def _summarize(records: list[dict]) -> dict:
    if not records:
        return {"evaluated_questions": 0, "hit_at_1": None, "hit_at_3": None, "hit_at_5": None, "mrr": None}
    return {
        "evaluated_questions": len(records),
        "hit_at_1": round(mean(item["hit_at_1"] for item in records), 6),
        "hit_at_3": round(mean(item["hit_at_3"] for item in records), 6),
        "hit_at_5": round(mean(item["hit_at_5"] for item in records), 6),
        "mrr": round(mean(item["reciprocal_rank"] for item in records), 6),
    }


def _compact(result: dict, rank: int) -> dict:
    return {
        "rank": rank,
        "document_id": result.get("document_id"),
        "page_number": result.get("page"),
        "chunk_id": result.get("chunk_id"),
        "section_id": result.get("section_id"),
        "section_path": result.get("section_path"),
        "dense_score": result.get("dense_score", result.get("distance")),
        "bm25_score": result.get("bm25_score"),
        "rrf_score": result.get("rrf_score"),
        "retrieval_sources": result.get("retrieval_sources", ["dense"]),
        "context_role": result.get("context_role"),
        "text_preview": result.get("text", "")[:220],
    }


def _ingestion_stats(corpus_root: Path) -> dict:
    documents_dir = corpus_root / "databases" / "chunked_reports"
    vectors_dir = corpus_root / "databases" / "vector_dbs"
    documents = []
    for path in sorted(documents_dir.glob("*.json")):
        document = json.loads(path.read_text(encoding="utf-8"))
        document_id = document["metainfo"]["document_id"]
        index_path = vectors_dir / f"{document_id}.faiss"
        index = faiss.read_index(str(index_path))
        sections = document["content"].get("sections", [])
        chunks = document["content"].get("chunks", [])
        documents.append(
            {
                "document_id": document_id,
                "pages": len(document["content"].get("pages", [])),
                "sections": len(sections),
                "chunks": len(chunks),
                "child_parent_mappings": sum(
                    bool(chunk.get("section_id") and chunk.get("parent_id"))
                    for chunk in chunks
                ),
                "section_detection": document["content"].get("section_detection"),
                "index_vectors": index.ntotal,
                "unit_norm_index": faiss_index_has_unit_norm_vectors(index),
                "bm25_index_exists": (
                    corpus_root / "databases" / "bm25_dbs" / f"{document_id}.pkl"
                ).is_file(),
            }
        )
    return {"document_count": len(documents), "documents": documents}


def evaluate(args: argparse.Namespace) -> dict:
    corpus_root = args.corpus_root
    databases = corpus_root / "databases"
    items = json.loads(args.dataset.read_text(encoding="utf-8"))
    rd_config = RDRetrievalConfig(
        dense_top_k=args.dense_top_k,
        bm25_top_k=args.bm25_top_k,
        fusion_top_k=args.fusion_top_k,
        rerank_top_k=args.top_k,
        rrf_k=args.rrf_k,
        dense_weight=args.dense_weight,
        bm25_weight=args.bm25_weight,
        neighbor_children=args.neighbor_children,
        context_max_tokens=args.context_max_tokens,
    )
    dense = VectorRetriever(
        databases / "vector_dbs",
        databases / "chunked_reports",
        embedding_provider=args.embedding_provider,
        embedding_model=args.embedding_model,
    )
    hybrid = RDHybridRetriever(
        databases / "vector_dbs",
        databases / "chunked_reports",
        embedding_provider=args.embedding_provider,
        embedding_model=args.embedding_model,
        config=rd_config,
        use_reranker=False,
    )

    mode_records = defaultdict(list)
    category_records = defaultdict(lambda: defaultdict(list))
    question_results = []
    improvements = []
    unchanged = []
    regressions = []
    bm25_contributions = []
    context_contributions = []

    for item in items:
        expected_pages = {int(page) for page in item["expected_pages"]}
        started = time.perf_counter()
        dense_results = dense.retrieve(
            item["question"],
            top_n=args.top_k,
            per_document_top_k=args.dense_top_k,
            return_parent_pages=False,
        )
        dense_latency = round((time.perf_counter() - started) * 1000, 3)

        started = time.perf_counter()
        hybrid_primary = hybrid.retrieve(
            item["question"], top_n=args.top_k, expand_context=False
        )
        hybrid_latency = round((time.perf_counter() - started) * 1000, 3)
        hybrid_expanded = hybrid.context_expander.expand(hybrid_primary)

        dense_rank = _rank_record(dense_results, expected_pages)
        hybrid_rank = _rank_record(hybrid_primary, expected_pages)
        expanded_rank = _rank_record(hybrid_expanded, expected_pages)
        if item["answerable"]:
            for mode, record in (
                ("generic_dense", dense_rank),
                ("rd_hybrid", hybrid_rank),
            ):
                mode_records[mode].append(record)
                category_records[mode][item["category"]].append(record)

            delta = hybrid_rank["reciprocal_rank"] - dense_rank["reciprocal_rank"]
            case = {
                "id": item["id"],
                "category": item["category"],
                "question": item["question"],
                "dense_rank": dense_rank["first_relevant_rank"],
                "hybrid_rank": hybrid_rank["first_relevant_rank"],
            }
            if delta > 0:
                improvements.append(case)
            elif delta < 0:
                regressions.append(case)
            else:
                unchanged.append(case)

            relevant_hybrid = next(
                (
                    result
                    for result in hybrid_primary
                    if int(result.get("page", -1)) in expected_pages
                ),
                None,
            )
            if relevant_hybrid and "bm25" in relevant_hybrid.get("retrieval_sources", []):
                if (
                    relevant_hybrid.get("dense_rank") is None
                    or relevant_hybrid.get("bm25_rank", 10**9)
                    < relevant_hybrid.get("dense_rank", 10**9)
                ):
                    bm25_contributions.append(
                        {
                            **case,
                            "chunk_id": relevant_hybrid.get("chunk_id"),
                            "dense_candidate_rank": relevant_hybrid.get("dense_rank"),
                            "bm25_candidate_rank": relevant_hybrid.get("bm25_rank"),
                        }
                    )
            primary_keys = {result.get("chunk_id") for result in hybrid_primary}
            added_relevant = [
                result
                for result in hybrid_expanded
                if result.get("chunk_id") not in primary_keys
                and int(result.get("page", -1)) in expected_pages
            ]
            if added_relevant:
                context_contributions.append(
                    {
                        **case,
                        "added_chunk_ids": [
                            result.get("chunk_id") for result in added_relevant
                        ],
                        "roles": sorted(
                            {result.get("context_role") for result in added_relevant}
                        ),
                    }
                )

        question_results.append(
            {
                **item,
                "latency_ms": {
                    "generic_dense": dense_latency,
                    "rd_hybrid": hybrid_latency,
                },
                "ranks": {
                    "generic_dense": dense_rank,
                    "rd_hybrid": hybrid_rank,
                    "rd_hybrid_expanded": expanded_rank,
                },
                "generic_dense": [
                    _compact(result, rank)
                    for rank, result in enumerate(dense_results, start=1)
                ],
                "rd_hybrid": [
                    _compact(result, rank)
                    for rank, result in enumerate(hybrid_primary, start=1)
                ],
                "rd_hybrid_expanded": [
                    _compact(result, rank)
                    for rank, result in enumerate(hybrid_expanded, start=1)
                ],
            }
        )

    metrics = {mode: _summarize(records) for mode, records in mode_records.items()}
    by_category = {
        mode: {
            category: _summarize(records)
            for category, records in categories.items()
        }
        for mode, categories in category_records.items()
    }
    unanswerable = [item for item in question_results if not item["answerable"]]
    payload = {
        "prototype": "R&D Document RAG V2",
        "corpus": "Synthetic public engineering specification; no restricted data",
        "question_count": len(items),
        "answerable_question_count": sum(item["answerable"] for item in items),
        "unanswerable_question_count": len(unanswerable),
        "embedding_provider": args.embedding_provider,
        "embedding_model": args.embedding_model,
        "reranker_used": False,
        "configuration": rd_config.__dict__,
        "ingestion": _ingestion_stats(corpus_root),
        "metrics": metrics,
        "metrics_by_category": by_category,
        "cases": {
            "improvements": improvements,
            "unchanged": unchanged,
            "regressions": regressions,
            "bm25_contributions": bm25_contributions,
            "context_expansion_contributions": context_contributions,
        },
        "context_expansion": {
            "questions_with_added_relevant_evidence": len(context_contributions),
            "ranking_metrics_reported": False,
            "note": "Expanded evidence is ordered for prompt assembly, not as an independent retrieval ranking.",
        },
        "unanswerable_behavior": [
            {
                "id": item["id"],
                "dense_result_count": len(item["generic_dense"]),
                "hybrid_result_count": len(item["rd_hybrid"]),
                "rejection_threshold_selected": False,
            }
            for item in unanswerable
        ],
        "questions": question_results,
    }
    _write_json(args.report_dir / "evaluation_results.json", payload)
    return payload


def write_markdown(report_dir: Path, payload: dict) -> None:
    dense = payload["metrics"]["generic_dense"]
    hybrid = payload["metrics"]["rd_hybrid"]

    def metric_row(name: str, values: dict) -> str:
        return (
            f"| {name} | {values['hit_at_1']:.3f} | {values['hit_at_3']:.3f} | "
            f"{values['hit_at_5']:.3f} | {values['mrr']:.3f} |"
        )

    lines = [
        "# R&D Document RAG V2 Prototype Retrieval Evaluation",
        "",
        f"Corpus: {payload['corpus']}",
        "",
        f"Questions: {payload['question_count']} total, {payload['answerable_question_count']} answerable, {payload['unanswerable_question_count']} unanswerable.",
        "",
        "Unanswerable items are excluded from Hit/MRR and no cosine rejection threshold is selected.",
        "",
        "| Mode | Hit@1 | Hit@3 | Hit@5 | MRR |",
        "|---|---:|---:|---:|---:|",
        metric_row("generic_dense", dense),
        metric_row("rd_hybrid", hybrid),
        "",
        f"Improved cases: {len(payload['cases']['improvements'])}",
        f"Unchanged cases: {len(payload['cases']['unchanged'])}",
        f"Regressed cases: {len(payload['cases']['regressions'])}",
        f"BM25 traceable contributions: {len(payload['cases']['bm25_contributions'])}",
        f"Questions where bounded expansion added relevant sibling evidence: {len(payload['cases']['context_expansion_contributions'])}",
        "Context-expanded evidence is prompt assembly order, so separate Hit/MRR is intentionally not reported.",
        "",
        "The complete ranks, evidence metadata, latency, and case lists are in `evaluation_results.json`.",
    ]
    (report_dir / "evaluation_summary.md").write_text(
        "\n".join(lines) + "\n", encoding="utf-8"
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--corpus-root", type=Path, default=Path("data/rd_v2_prototype")
    )
    parser.add_argument(
        "--dataset",
        type=Path,
        default=Path("data/rd_v2_prototype/evaluation.json"),
    )
    parser.add_argument(
        "--report-dir", type=Path, default=Path("reports/rd_v2_prototype")
    )
    parser.add_argument("--prepare", action="store_true")
    parser.add_argument("--offline-parse", action="store_true")
    parser.add_argument("--rebuild-indexes", action="store_true")
    parser.add_argument("--embedding-provider", default="dashscope")
    parser.add_argument("--embedding-model", default="text-embedding-v1")
    parser.add_argument("--top-k", type=int, default=5)
    parser.add_argument("--dense-top-k", type=int, default=12)
    parser.add_argument("--bm25-top-k", type=int, default=12)
    parser.add_argument("--fusion-top-k", type=int, default=10)
    parser.add_argument("--rrf-k", type=int, default=60)
    parser.add_argument("--dense-weight", type=float, default=1.0)
    parser.add_argument("--bm25-weight", type=float, default=1.0)
    parser.add_argument("--neighbor-children", type=int, default=1)
    parser.add_argument("--context-max-tokens", type=int, default=1800)
    return parser


def main() -> None:
    args = build_parser().parse_args()
    if args.prepare:
        prepare_corpus(args.corpus_root, offline_parse=args.offline_parse)
        # Docling and FAISS may load incompatible OpenMP runtimes in one Windows
        # process.  Keep preparation and evaluation as two safe CLI invocations.
        print(
            "PDF parse/merge complete. Run --rebuild-indexes, then run without a build flag to evaluate."
        )
        return
    if args.rebuild_indexes:
        rebuild_indexes(args.corpus_root)
        print("Index rebuild complete. Run again without --rebuild-indexes to evaluate.")
        return
    payload = evaluate(args)
    write_markdown(args.report_dir, payload)
    print(json.dumps(payload["metrics"], indent=2))


if __name__ == "__main__":
    main()
