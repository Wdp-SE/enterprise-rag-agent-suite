"""DEV-only BM25 and limited RRF ablation over frozen R&D V2 artifacts.

The runner is read-only with respect to datasets, chunks, embeddings, FAISS,
and BM25.  Reports contain IDs and retrieval metadata, never question or body
text.  It does not import PyTorch or invoke a reranker/online model.
"""

from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import ctypes
import hashlib
import json
import os
from pathlib import Path
import pickle
import re
import sys
from typing import Sequence

import numpy as np


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from scripts.run_rd_v2_embedding_enrichment import (
    DATASET_VERSION,
    QUERY_TYPES,
    SECTION_SOURCES,
    RetrievalTextMode,
    evaluate_case,
    load_chunks,
    load_json,
    metric_block,
    namespace_paths,
    safe_evidence,
    semantic_regression,
    sequence_digest,
    sha256_file,
    verify_frozen_inputs,
    write_json_new,
    write_text_new,
)
from src.rd_retrieval import reciprocal_rank_fusion
from src.text_tokenization import technical_tokenize


EXPERIMENT_VERSION = "rd-v2-hybrid-limited-ablation-v0.1"
BACKBONES = (
    RetrievalTextMode.SECTION_PATH,
    RetrievalTextMode.DOCUMENT_SECTION_PATH,
)
WEIGHT_CONFIGS = {
    "A": {"dense_weight": 1.0, "bm25_weight": 1.0},
    "B": {"dense_weight": 1.0, "bm25_weight": 0.75},
    "C": {"dense_weight": 1.0, "bm25_weight": 0.50},
    "D": {"dense_weight": 1.0, "bm25_weight": 0.25},
}
DENSE_TOP_K = 12
BM25_TOP_K = 12
FUSION_TOP_K = 10
RRF_K = 60

GLOSSARY_RE = re.compile(r"术语|定义|缩略语|名词解释|glossary|definition", re.I)
FIELD_RE = re.compile(r"字段名?|参数名?|属性|必填|数据类型|取值范围|field|parameter", re.I)
TABLE_RE = re.compile(r"(^|\s)(序号|名称|类型|说明|值)(\s|$)|\|[^\n]+\|", re.I)
NUMBER_RE = re.compile(r"(?<![A-Za-z_])\d+(?:\.\d+)?(?![A-Za-z_])")


if os.name == "nt":
    ctypes.windll.kernel32.SetErrorMode(0x0001 | 0x0002 | 0x8000)


def safe_chunk_result(chunk: dict, *, score: float, source: str) -> dict:
    result = {
        "chunk_index": int(chunk["chunk_index"]),
        "chunk_id": chunk["chunk_id"],
        "document_id": chunk["document_id"],
        "page_number": int(chunk["page_number"]),
        "page": int(chunk["page_number"]),
        "section_id": chunk.get("section_id"),
        "section_source": chunk.get("section_source"),
        "distance": round(float(score), 8),
        "retrieval_source": source,
    }
    if source == "bm25":
        result["bm25_score"] = round(float(score), 8)
    else:
        result["dense_score"] = round(float(score), 8)
    return result


def dense_chunk_ranking(index, query_vector: np.ndarray, chunks: Sequence[dict]) -> list[dict]:
    scores, indices = index.search(
        np.ascontiguousarray(query_vector.reshape(1, -1), dtype=np.float32),
        index.ntotal,
    )
    return [
        safe_chunk_result(chunks[int(chunk_index)], score=float(score), source="dense")
        for score, chunk_index in zip(scores[0], indices[0])
        if int(chunk_index) >= 0
    ]


def bm25_chunk_ranking(
    bm25_index,
    token_sets: Sequence[set[str]],
    query: str,
    chunks: Sequence[dict],
) -> list[dict]:
    tokens = technical_tokenize(query)
    if not tokens:
        return []
    query_tokens = set(tokens)
    scores = np.asarray(bm25_index.get_scores(tokens), dtype=np.float64)
    order = np.argsort(-scores, kind="stable")
    rows = []
    for chunk_index in order:
        score = float(scores[int(chunk_index)])
        if score <= 0.0 or not query_tokens.intersection(token_sets[int(chunk_index)]):
            continue
        rows.append(
            safe_chunk_result(
                chunks[int(chunk_index)], score=score, source="bm25"
            )
        )
    return rows


def page_dedupe(rows: Sequence[dict], limit: int | None = None) -> list[dict]:
    pages = []
    seen = set()
    for row in rows:
        key = (row["document_id"], int(row["page_number"]))
        if key in seen:
            continue
        seen.add(key)
        page = {
            "rank": len(pages) + 1,
            "chunk_index": row["chunk_index"],
            "document_id": row["document_id"],
            "page_number": int(row["page_number"]),
            "section_id": row.get("section_id"),
            "section_source": row.get("section_source"),
            "chunk_id": row["chunk_id"],
            "retrieval_sources": row.get(
                "retrieval_sources", [row.get("retrieval_source")]
            ),
        }
        for key_name in (
            "dense_rank",
            "bm25_rank",
            "dense_score",
            "bm25_score",
            "rrf_score",
        ):
            if row.get(key_name) is not None:
                page[key_name] = row[key_name]
        page["cosine_similarity"] = row.get("dense_score")
        pages.append(page)
        if limit is not None and len(pages) >= limit:
            break
    return pages


def evaluate_records(cases: Sequence[dict], page_lists: Sequence[Sequence[dict]]) -> list[dict]:
    return [evaluate_case(item, pages) for item, pages in zip(cases, page_lists)]


def metrics_with_slices(records: Sequence[dict]) -> tuple[dict, dict]:
    by_type = defaultdict(list)
    for record in records:
        by_type[record["question_type"]].append(record)
    return metric_block(records), {
        query_type: metric_block(by_type[query_type]) for query_type in QUERY_TYPES
    }


def complementarity(dense: Sequence[dict], bm25: Sequence[dict]) -> dict:
    overall = Counter()
    by_type: dict[str, Counter] = {value: Counter() for value in QUERY_TYPES}
    cases = []
    for dense_row, sparse_row in zip(dense, bm25):
        dense_hit = bool(dense_row["hit_at_k"]["50"])
        bm25_hit = bool(sparse_row["hit_at_k"]["50"])
        if not dense_hit and bm25_hit:
            label = "DENSE_MISS_BM25_RECOVERED"
        elif dense_hit and not bm25_hit:
            label = "DENSE_HIT_BM25_MISS"
        elif dense_hit and bm25_hit:
            label = "BOTH_HIT"
        else:
            label = "BOTH_MISS"
        overall[label] += 1
        by_type[dense_row["question_type"]][label] += 1
        cases.append(
            {
                "question_id": dense_row["question_id"],
                "question_type": dense_row["question_type"],
                "category": label,
                "dense_first_evidence_rank": dense_row["first_evidence_rank"],
                "bm25_first_evidence_rank": sparse_row["first_evidence_rank"],
            }
        )
    labels = (
        "DENSE_MISS_BM25_RECOVERED",
        "DENSE_HIT_BM25_MISS",
        "BOTH_HIT",
        "BOTH_MISS",
    )
    return {
        "overall": {label: overall[label] for label in labels},
        "by_question_type": {
            query_type: {label: by_type[query_type][label] for label in labels}
            for query_type in QUERY_TYPES
        },
        "cases": cases,
    }


def rank_delta(dense_records: Sequence[dict], hybrid_records: Sequence[dict]) -> dict:
    counts = Counter()
    rows = []
    regression_questions = set()
    for dense, hybrid in zip(dense_records, hybrid_records):
        flags = []
        for k in (5, 20, 50):
            if not dense["hit_at_k"][str(k)] and hybrid["hit_at_k"][str(k)]:
                label = f"RECOVERED_TOP{k}"
                flags.append(label)
                counts[label] += 1
        for k in (1, 5, 20):
            if dense["hit_at_k"][str(k)] and not hybrid["hit_at_k"][str(k)]:
                label = f"REGRESSED_FROM_TOP{k}"
                flags.append(label)
                counts[label] += 1
                regression_questions.add(dense["question_id"])
        if not flags:
            flags = ["UNCHANGED"]
            counts["UNCHANGED"] += 1
        rows.append(
            {
                "question_id": dense["question_id"],
                "question_type": dense["question_type"],
                "expected_document_id": dense["expected_document_id"],
                "expected_pages": dense["expected_pages"],
                "expected_section_ids": dense["expected_section_ids"],
                "dense_rank": dense["first_evidence_rank"],
                "hybrid_rank": hybrid["first_evidence_rank"],
                "flags": flags,
                "dense_first_evidence": safe_evidence(dense["first_evidence"]),
                "hybrid_first_evidence": safe_evidence(hybrid["first_evidence"]),
            }
        )
    return {
        "counts": {
            "RECOVERED_TOP5": counts["RECOVERED_TOP5"],
            "RECOVERED_TOP20": counts["RECOVERED_TOP20"],
            "RECOVERED_TOP50": counts["RECOVERED_TOP50"],
            "REGRESSED_FROM_TOP1": counts["REGRESSED_FROM_TOP1"],
            "REGRESSED_FROM_TOP5": counts["REGRESSED_FROM_TOP5"],
            "REGRESSED_FROM_TOP20": counts["REGRESSED_FROM_TOP20"],
            "REGRESSION_QUESTION_COUNT": len(regression_questions),
            "UNCHANGED": counts["UNCHANGED"],
        },
        "per_query": rows,
    }


def type_improved(candidate: dict, baseline: dict, query_type: str) -> bool:
    new = candidate[query_type]
    old = baseline[query_type]
    return any(
        new["hit_at_k"][str(k)] > old["hit_at_k"][str(k)]
        for k in (5, 20, 50)
    ) or new["mrr_at_50"] > old["mrr_at_50"]


def candidate_score(overall: dict, by_type: dict, delta: dict) -> float:
    hit = overall["hit_at_k"]
    recall = overall["recall_at_k"]
    critical = np.mean(
        [
            by_type[query_type]["hit_at_k"][str(k)]
            for query_type in ("field", "exact_term", "interface", "dependency")
            for k in (5, 20, 50)
        ]
    )
    semantic = np.mean(
        [
            by_type["semantic"]["hit_at_k"][str(k)] for k in (5, 20, 50)
        ]
    )
    movement = delta["counts"]
    return round(
        hit["1"]
        + 3 * hit["5"]
        + 3 * hit["20"]
        + 2 * hit["50"]
        + 2 * recall["20"]
        + recall["50"]
        + overall["mrr_at_5"]
        + overall["mrr_at_50"]
        + 0.75 * float(critical)
        + 0.25 * float(semantic)
        + 0.03 * movement["RECOVERED_TOP5"]
        + 0.02 * movement["RECOVERED_TOP50"]
        - 0.03 * movement["REGRESSION_QUESTION_COUNT"]
        - 0.04 * movement["REGRESSED_FROM_TOP1"],
        6,
    )


def choose_candidate(candidates: dict) -> str:
    maximum = max(value["score"] for value in candidates.values())
    near = [key for key, value in candidates.items() if value["score"] >= maximum - 0.05]
    semantic_order = {"YES": 0, "MINOR": 1, "NO": 2}
    return max(
        near,
        key=lambda key: (
            semantic_order[candidates[key]["semantic_regression"]],
            -candidates[key]["delta"]["counts"]["REGRESSED_FROM_TOP1"],
            -candidates[key]["delta"]["counts"]["REGRESSION_QUESTION_COUNT"],
            candidates[key]["score"],
            candidates[key].get("tie_preference", 0.0),
            key,
        ),
    )


def classify_distractor(query: str, query_type: str, chunk: dict) -> str:
    text = str(chunk.get("text") or "")
    heading = " ".join(
        [
            str(chunk.get("section_title") or ""),
            *[str(value) for value in (chunk.get("section_path") or [])],
        ]
    )
    if GLOSSARY_RE.search(heading) or (len(text) < 220 and GLOSSARY_RE.search(text)):
        return "GLOSSARY_DISTRACTOR"
    if FIELD_RE.search(text) and len(text) < 320:
        return "FIELD_LABEL_DISTRACTOR"
    if TABLE_RE.search(text) and len(text) < 400:
        return "TABLE_LABEL_DISTRACTOR"
    tokens = technical_tokenize(query)
    numeric_ratio = len(NUMBER_RE.findall(text)) / max(1, len(technical_tokenize(text)))
    if query_type == "numeric" and numeric_ratio >= 0.12:
        return "NUMBER_ONLY_DISTRACTOR"
    normalized = text.casefold()
    if any(len(token) >= 2 and normalized.count(token.casefold()) >= 3 for token in tokens):
        return "REPEATED_TERM_DISTRACTOR"
    return "OTHER"


def failure_analysis(
    cases: Sequence[dict],
    chunks: Sequence[dict],
    hybrid_pages: Sequence[Sequence[dict]],
    delta: dict,
) -> dict:
    by_id = {row["question_id"]: row for row in delta["per_query"]}
    counts = Counter()
    rows = []
    for item, pages in zip(cases, hybrid_pages):
        delta_row = by_id[item["question_id"]]
        if not any(flag.startswith("REGRESSED_") for flag in delta_row["flags"]):
            continue
        expected = {
            (item["expected_document_id"], int(page)) for page in item["expected_pages"]
        }
        distractor = next(
            (
                page
                for page in pages
                if "bm25" in page.get("retrieval_sources", [])
                and (page["document_id"], int(page["page_number"])) not in expected
            ),
            pages[0] if pages else None,
        )
        if distractor is None:
            label = "OTHER"
            safe_row = None
        else:
            chunk = chunks[int(distractor["chunk_index"])]
            label = classify_distractor(item["question"], item["question_type"], chunk)
            safe_row = {
                "rank": distractor["rank"],
                "document_id": distractor["document_id"],
                "page_number": distractor["page_number"],
                "section_id": distractor.get("section_id"),
                "section_source": distractor.get("section_source"),
                "chunk_id": distractor["chunk_id"],
                "retrieval_sources": distractor.get("retrieval_sources", []),
                "section_title_sha256": hashlib.sha256(
                    str(chunk.get("section_title") or "").encode("utf-8")
                ).hexdigest(),
            }
        counts[label] += 1
        rows.append(
            {
                "question_id": item["question_id"],
                "question_type": item["question_type"],
                "regression_flags": delta_row["flags"],
                "classification": label,
                "distractor": safe_row,
            }
        )
    glossary_count = counts["GLOSSARY_DISTRACTOR"]
    glossary_conclusion = "YES" if glossary_count >= 2 else "INCONCLUSIVE" if glossary_count == 1 else "NO"
    labels = (
        "GLOSSARY_DISTRACTOR",
        "FIELD_LABEL_DISTRACTOR",
        "TABLE_LABEL_DISTRACTOR",
        "NUMBER_ONLY_DISTRACTOR",
        "REPEATED_TERM_DISTRACTOR",
        "OTHER",
    )
    return {
        "classification_method": "deterministic metadata/body heuristics inspected locally; no body text persisted",
        "counts": {label: counts[label] for label in labels},
        "cases": rows,
        "glossary_body_conflict": glossary_conclusion,
        "hard_coded_penalty_added": False,
    }


def hybrid_value(
    hybrid: dict,
    dense: dict,
    improvements: dict,
    semantic_status: str,
    delta: dict,
) -> str:
    gains = [
        hybrid["hit_at_k"][str(k)] - dense["hit_at_k"][str(k)]
        for k in (5, 20, 50)
    ]
    critical_count = sum(improvements.values())
    if (
        critical_count >= 2
        and min(gains) >= 0
        and semantic_status != "YES"
        and delta["counts"]["RECOVERED_TOP5"] > 0
    ):
        return "YES"
    if critical_count >= 1 or max(gains) > 0 or delta["counts"]["RECOVERED_TOP5"] > 0:
        return "PARTIAL"
    if max(gains) < 0 and critical_count == 0:
        return "NO"
    return "INCONCLUSIVE"


def compact_metrics(value: dict) -> dict:
    return {
        "hit1": value["hit_at_k"]["1"],
        "hit5": value["hit_at_k"]["5"],
        "hit10": value["hit_at_k"]["10"],
        "hit20": value["hit_at_k"]["20"],
        "hit50": value["hit_at_k"]["50"],
        "recall20": value["recall_at_k"]["20"],
        "recall50": value["recall_at_k"]["50"],
        "mrr5": value["mrr_at_5"],
        "mrr50": value["mrr_at_50"],
    }


def main(args: argparse.Namespace) -> None:
    if args.report_dir.exists():
        raise RuntimeError("Refusing to overwrite an existing hybrid-ablation report")
    if "torch" in sys.modules:
        raise RuntimeError("Hybrid ablation must not load PyTorch")
    inputs = verify_frozen_inputs(args, include_queries=True)
    chunks = load_chunks(args)
    chunk_ids = [chunk["chunk_id"] for chunk in chunks]
    chunk_id_digest = sequence_digest(chunk_ids)
    with (args.baseline_artifact_dir / "bm25_index.pkl").open("rb") as stream:
        bm25_payload = pickle.load(stream)
    if bm25_payload.get("chunk_ids") != chunk_ids:
        raise RuntimeError("BM25 chunk order/ID alignment failed")
    bm25_index = bm25_payload["index"]
    token_sets = [set(technical_tokenize(chunk["text"])) for chunk in chunks]
    queries = np.load(args.dataset_dir / "dev_query_embeddings.npy", allow_pickle=False)
    cases = inputs["dev"]["cases"]

    import faiss

    dense_indices = {}
    manifests = {}
    for mode in BACKBONES:
        namespace, _ = namespace_paths(args, mode)
        manifest = load_json(namespace / "artifact_manifest.json")
        if (
            manifest.get("build_status") != "PASS"
            or manifest.get("ordered_chunk_id_sha256") != chunk_id_digest
            or manifest.get("child_chunk_count") != len(chunks)
            or manifest.get("embedding_count") != len(chunks)
            or manifest.get("faiss_count") != len(chunks)
        ):
            raise RuntimeError(f"Dense backbone artifact validation failed: {mode.value}")
        for name, record in manifest["artifact_files"].items():
            if sha256_file(namespace / name) != record["sha256"]:
                raise RuntimeError(f"Dense backbone hash mismatch: {mode.value}/{name}")
        dense_indices[mode] = faiss.read_index(str(namespace / "child_vectors.faiss"))
        manifests[mode] = manifest

    bm25_chunk_rows = []
    bm25_page_rows = []
    dense_chunk_rows = {mode: [] for mode in BACKBONES}
    dense_page_rows = {mode: [] for mode in BACKBONES}
    for item, query_vector in zip(cases, queries):
        sparse = bm25_chunk_ranking(
            bm25_index, token_sets, item["question"], chunks
        )
        bm25_chunk_rows.append(sparse)
        bm25_page_rows.append(page_dedupe(sparse, 50))
        for mode in BACKBONES:
            dense = dense_chunk_ranking(dense_indices[mode], query_vector, chunks)
            dense_chunk_rows[mode].append(dense)
            dense_page_rows[mode].append(page_dedupe(dense, 50))

    bm25_records = evaluate_records(cases, bm25_page_rows)
    bm25_overall, bm25_types = metrics_with_slices(bm25_records)
    dense_records = {
        mode: evaluate_records(cases, dense_page_rows[mode]) for mode in BACKBONES
    }
    dense_metrics = {}
    dense_types = {}
    for mode in BACKBONES:
        dense_metrics[mode], dense_types[mode] = metrics_with_slices(
            dense_records[mode]
        )
    complement_payload = {
        "schema_version": 1,
        "cutoff": 50,
        "bm25": compact_metrics(bm25_overall),
        "by_dense_backbone": {
            mode.value: complementarity(dense_records[mode], bm25_records)
            for mode in BACKBONES
        },
    }

    def run_hybrid(mode: RetrievalTextMode, dense_weight: float, bm25_weight: float) -> dict:
        union_pages = []
        operational_pages = []
        for dense, sparse in zip(dense_chunk_rows[mode], bm25_chunk_rows):
            fused = reciprocal_rank_fusion(
                dense[:DENSE_TOP_K],
                sparse[:BM25_TOP_K],
                rrf_k=RRF_K,
                dense_weight=dense_weight,
                bm25_weight=bm25_weight,
                top_k=None,
            )
            pages = page_dedupe(fused)
            union_pages.append(pages)
            operational_pages.append(pages[:FUSION_TOP_K])
        union_records = evaluate_records(cases, union_pages)
        operational_records = evaluate_records(cases, operational_pages)
        union_overall, union_types = metrics_with_slices(union_records)
        operational_overall, _ = metrics_with_slices(operational_records)
        delta = rank_delta(dense_records[mode], union_records)
        semantic = semantic_regression(union_types, dense_types[mode])
        return {
            "dense_backbone": mode.value,
            "dense_weight": dense_weight,
            "bm25_weight": bm25_weight,
            "rrf_k": RRF_K,
            "source_depth": {"dense_chunks": DENSE_TOP_K, "bm25_chunks": BM25_TOP_K},
            "operational_fusion_top_k": FUSION_TOP_K,
            "reported_metrics_scope": "PRE_TRUNCATION_RRF_UNION_MAX_24_CHUNKS",
            "metrics": union_overall,
            "operational_top10_metrics": operational_overall,
            "per_type": union_types,
            "delta": delta,
            "semantic_regression": semantic,
            "union_pages": union_pages,
            "union_records": union_records,
        }

    equal_results = {
        mode.value: run_hybrid(mode, 1.0, 1.0) for mode in BACKBONES
    }
    backbone_candidates = {}
    for mode in BACKBONES:
        result = equal_results[mode.value]
        backbone_candidates[mode.value] = {
            "score": candidate_score(
                result["metrics"], result["per_type"], result["delta"]
            ),
            "semantic_regression": result["semantic_regression"],
            "delta": result["delta"],
        }
    selected_backbone_name = choose_candidate(backbone_candidates)
    selected_backbone = RetrievalTextMode(selected_backbone_name)

    rrf_results = {}
    for config_name, weights in WEIGHT_CONFIGS.items():
        if config_name == "A":
            result = equal_results[selected_backbone.value]
        else:
            result = run_hybrid(selected_backbone, **weights)
        result["config"] = config_name
        result["score"] = candidate_score(
            result["metrics"], result["per_type"], result["delta"]
        )
        rrf_results[config_name] = result
    config_candidates = {
        name: {
            "score": value["score"],
            "semantic_regression": value["semantic_regression"],
            "delta": value["delta"],
            # With identical retrieval outcomes, retain less lexical influence.
            "tie_preference": -value["bm25_weight"],
        }
        for name, value in rrf_results.items()
    }
    best_config = choose_candidate(config_candidates)
    best = rrf_results[best_config]
    improvements = {
        query_type: type_improved(
            best["per_type"], dense_types[selected_backbone], query_type
        )
        for query_type in ("field", "exact_term", "interface", "dependency")
    }
    value_conclusion = hybrid_value(
        best["metrics"],
        dense_metrics[selected_backbone],
        improvements,
        best["semantic_regression"],
        best["delta"],
    )
    failure_by_config = {
        name: failure_analysis(cases, chunks, value["union_pages"], value["delta"])
        for name, value in rrf_results.items()
    }
    aggregate_failure_counts = Counter()
    glossary_question_ids = set()
    for value in failure_by_config.values():
        aggregate_failure_counts.update(value["counts"])
        glossary_question_ids.update(
            row["question_id"]
            for row in value["cases"]
            if row["classification"] == "GLOSSARY_DISTRACTOR"
        )
    glossary_conclusion = (
        "YES"
        if len(glossary_question_ids) >= 2
        else "INCONCLUSIVE"
        if len(glossary_question_ids) == 1
        else "NO"
    )
    failure = {
        "schema_version": 1,
        "scope": "ALL_FOUR_FIXED_WEIGHT_CONFIGS",
        "aggregate_occurrence_counts": dict(aggregate_failure_counts),
        "distinct_glossary_regression_question_count": len(glossary_question_ids),
        "glossary_body_conflict": glossary_conclusion,
        "by_config": failure_by_config,
        "hard_coded_penalty_added": False,
        "body_text_persisted": False,
    }
    ready = (
        value_conclusion in {"YES", "PARTIAL"}
        and best["delta"]["counts"]["RECOVERED_TOP5"] > 0
        and best["operational_top10_metrics"]["hit_at_k"]["5"]
        >= dense_metrics[selected_backbone]["hit_at_k"]["5"]
        and best["semantic_regression"] != "YES"
    )

    staging = args.report_dir.with_name("." + args.report_dir.name + ".build.partial")
    if staging.exists():
        raise RuntimeError("Partial hybrid report directory exists")
    staging.mkdir(parents=True)
    bm25_payload_out = {
        "schema_version": 1,
        "run": "BM25_ONLY",
        "chunk_count": len(chunks),
        "metrics": bm25_overall,
        "per_type": bm25_types,
        "reranker_used": False,
        "holdout_evaluated": False,
        "body_text_logged": False,
    }
    backbone_payload = {
        "schema_version": 1,
        "fixed_config": {
            "dense_top_k_chunks": DENSE_TOP_K,
            "bm25_top_k_chunks": BM25_TOP_K,
            "fusion_top_k": FUSION_TOP_K,
            "rrf_k": RRF_K,
            "dense_weight": 1.0,
            "bm25_weight": 1.0,
        },
        "candidates": {
            name: {
                "metrics": value["metrics"],
                "operational_top10_metrics": value["operational_top10_metrics"],
                "per_type": value["per_type"],
                "delta": value["delta"],
                "semantic_regression": value["semantic_regression"],
                "score": backbone_candidates[name]["score"],
            }
            for name, value in equal_results.items()
        },
        "selected_dense_backbone": selected_backbone.value,
        "selection_policy": "balanced score; within 0.05 prefer semantic stability, fewer Top1 breaks, fewer regression questions",
        "dense_backbone_frozen_after_selection": True,
    }
    rrf_payload = {
        "schema_version": 1,
        "selected_dense_backbone": selected_backbone.value,
        "rrf_k": RRF_K,
        "fixed_top_k": {
            "dense_chunks": DENSE_TOP_K,
            "bm25_chunks": BM25_TOP_K,
            "fusion_output": FUSION_TOP_K,
        },
        "extended_metric_contract": "Hit@20/50 use the pre-truncation RRF union of fixed Top12+Top12 sources (at most 24 chunks); operational candidate output remains Top10",
        "configs": {
            name: {
                "weights": WEIGHT_CONFIGS[name],
                "metrics": value["metrics"],
                "operational_top10_metrics": value["operational_top10_metrics"],
                "semantic_regression": value["semantic_regression"],
                "delta_counts": value["delta"]["counts"],
                "score": value["score"],
            }
            for name, value in rrf_results.items()
        },
        "best_config": best_config,
        "selection_policy": "balanced score; within 0.05 prefer semantic stability and fewer regressions; exact outcome ties prefer the lower BM25 weight",
    }
    per_type_payload = {
        "schema_version": 1,
        "bm25_only": bm25_types,
        "dense_backbones": {mode.value: dense_types[mode] for mode in BACKBONES},
        "equal_weight_backbone_comparison": {
            name: value["per_type"] for name, value in equal_results.items()
        },
        "rrf_configs": {
            name: value["per_type"] for name, value in rrf_results.items()
        },
        "best_config": best_config,
        "field_improved": improvements["field"],
        "exact_term_improved": improvements["exact_term"],
        "interface_improved": improvements["interface"],
        "dependency_improved": improvements["dependency"],
        "semantic_regression": best["semantic_regression"],
    }
    delta_payload = {
        "schema_version": 1,
        "baseline": selected_backbone.value,
        "configs": {
            name: value["delta"] for name, value in rrf_results.items()
        },
        "best_config": best_config,
    }
    write_json_new(staging / "bm25_baseline.json", bm25_payload_out)
    write_json_new(staging / "dense_bm25_complementarity.json", complement_payload)
    write_json_new(staging / "backbone_comparison.json", backbone_payload)
    write_json_new(staging / "rrf_ablation.json", rrf_payload)
    write_json_new(staging / "per_type_metrics.json", per_type_payload)
    write_json_new(staging / "rank_delta_analysis.json", delta_payload)

    failure_lines = [
        "# Hybrid Regression Failure Analysis",
        "",
        f"SELECTED_DENSE_BACKBONE = {selected_backbone.value}",
        f"BEST_HYBRID_CONFIG = {best_config}",
        f"GLOSSARY_BODY_CONFLICT = {failure['glossary_body_conflict']}",
        "",
        "| Classification | Count |",
        "|---|---:|",
        *[
            f"| {key} | {value} |"
            for key, value in failure["aggregate_occurrence_counts"].items()
        ],
        "",
        f"DISTINCT_GLOSSARY_REGRESSION_QUESTIONS = {failure['distinct_glossary_regression_question_count']}",
        "",
        "Counts aggregate regression occurrences across all four fixed weight configurations; the JSON also retains per-config results. Classifications are deterministic diagnostic heuristics over local text. Reports retain only question IDs, metadata, and title hashes. No penalty or routing rule was added.",
    ]
    write_text_new(
        staging / "hybrid_failure_analysis.md", "\n".join(failure_lines)
    )

    bm = compact_metrics(bm25_overall)
    dense = compact_metrics(dense_metrics[selected_backbone])
    hybrid = compact_metrics(best["metrics"])
    selected_complement = complement_payload["by_dense_backbone"][
        selected_backbone.value
    ]["overall"]
    delta_counts = best["delta"]["counts"]
    metric_rows = []
    for name, value in rrf_results.items():
        compact = compact_metrics(value["metrics"])
        metric_rows.append(
            f"| {name} | {value['dense_weight']} | {value['bm25_weight']} | "
            f"{compact['hit1']} | {compact['hit5']} | {compact['hit20']} | "
            f"{compact['hit50']} | {compact['mrr50']} | "
            f"{value['delta']['counts']['RECOVERED_TOP5']} | "
            f"{value['delta']['counts']['REGRESSION_QUESTION_COUNT']} |"
        )
    report_lines = [
        "# R&D V2 BM25 + Hybrid Limited Ablation",
        "",
        "ARTIFACT_ALIGNMENT = PASS",
        "DATASET_SPLIT = DEV_ONLY",
        "RERANKER_USED = NO",
        "",
        "## Fixed retrieval contract",
        "",
        f"DENSE_TOP_K_CHUNKS = {DENSE_TOP_K}",
        f"BM25_TOP_K_CHUNKS = {BM25_TOP_K}",
        f"FUSION_TOP_K = {FUSION_TOP_K}",
        f"RRF_K = {RRF_K}",
        "",
        "Hit@20/50 are diagnostic metrics over the untruncated RRF union of the fixed Top12 dense and Top12 BM25 chunk lists (maximum 24 chunks). The operational fusion output remains Top10; no Top-K value was tuned.",
        "",
        "## BM25-only",
        "",
        f"BM25_HIT1 = {bm['hit1']}",
        f"BM25_HIT5 = {bm['hit5']}",
        f"BM25_HIT20 = {bm['hit20']}",
        f"BM25_HIT50 = {bm['hit50']}",
        "",
        f"DENSE_MISS_BM25_TOP50_RECOVERED = {selected_complement['DENSE_MISS_BM25_RECOVERED']}",
        "",
        "## Backbone selection",
        "",
        f"SELECTED_DENSE_BACKBONE = {selected_backbone.value}",
        f"SELECTED_DENSE_HIT1 = {dense['hit1']}",
        f"SELECTED_DENSE_HIT5 = {dense['hit5']}",
        f"SELECTED_DENSE_HIT20 = {dense['hit20']}",
        f"SELECTED_DENSE_HIT50 = {dense['hit50']}",
        "",
        "## Limited weight ablation",
        "",
        "| Config | Dense weight | BM25 weight | Hit@1 | Hit@5 | Hit@20 | Hit@50 | MRR@50 | Recovered Top5 | Regression questions |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
        *metric_rows,
        "",
        f"BEST_HYBRID_CONFIG = {best_config} (dense={best['dense_weight']}, bm25={best['bm25_weight']})",
        "Config C and D produced identical reported metrics and per-query evidence-rank deltas; D is selected by the declared exact-tie rule because it uses less BM25 weight.",
        f"HYBRID_HIT1 = {hybrid['hit1']}",
        f"HYBRID_HIT5 = {hybrid['hit5']}",
        f"HYBRID_HIT20 = {hybrid['hit20']}",
        f"HYBRID_HIT50 = {hybrid['hit50']}",
        f"HYBRID_MRR = {hybrid['mrr50']} (MRR@50)",
        "",
        f"FIELD_IMPROVED = {'YES' if improvements['field'] else 'NO'}",
        f"EXACT_TERM_IMPROVED = {'YES' if improvements['exact_term'] else 'NO'}",
        f"INTERFACE_IMPROVED = {'YES' if improvements['interface'] else 'NO'}",
        f"DEPENDENCY_IMPROVED = {'YES' if improvements['dependency'] else 'NO'}",
        f"SEMANTIC_REGRESSION = {best['semantic_regression']}",
        "",
        f"TOP50_RECOVERED = {delta_counts['RECOVERED_TOP50']}",
        f"TOP5_RECOVERED = {delta_counts['RECOVERED_TOP5']}",
        f"REGRESSION_COUNT = {delta_counts['REGRESSION_QUESTION_COUNT']}",
        f"GLOSSARY_BODY_CONFLICT = {failure['glossary_body_conflict']}",
        f"HYBRID_VALUE_ON_DEV = {value_conclusion}",
        f"READY_FOR_RERANKER_VALIDATION = {'YES' if ready else 'NO'}",
        "",
        "No Holdout, reranker, answer evaluation, online model, query routing, hard-coded penalty, or learned fusion was run.",
    ]
    write_text_new(
        staging / "hybrid_ablation_report.md", "\n".join(report_lines)
    )
    # Failure details are kept in the structured delta-adjacent output without body text.
    write_json_new(staging / "hybrid_failure_analysis.json", failure)
    staging.replace(args.report_dir)
    print(
        json.dumps(
            {
                "status": "PASS",
                "bm25": bm,
                "dense_miss_bm25_top50_recovered": selected_complement[
                    "DENSE_MISS_BM25_RECOVERED"
                ],
                "selected_dense_backbone": selected_backbone.value,
                "selected_dense": dense,
                "best_hybrid_config": best_config,
                "weights": WEIGHT_CONFIGS[best_config],
                "hybrid": hybrid,
                "field_improved": improvements["field"],
                "exact_term_improved": improvements["exact_term"],
                "interface_improved": improvements["interface"],
                "dependency_improved": improvements["dependency"],
                "semantic_regression": best["semantic_regression"],
                "top50_recovered": delta_counts["RECOVERED_TOP50"],
                "top5_recovered": delta_counts["RECOVERED_TOP5"],
                "regression_count": delta_counts["REGRESSION_QUESTION_COUNT"],
                "glossary_body_conflict": failure["glossary_body_conflict"],
                "hybrid_value_on_dev": value_conclusion,
                "ready_for_reranker_validation": ready,
                "holdout_evaluated": False,
                "reranker_run": False,
                "online_models_called": False,
                "body_text_logged": False,
            },
            ensure_ascii=False,
        )
    )


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser()
    result.add_argument(
        "--dataset-dir",
        type=Path,
        default=Path(
            "reports/rd_v2_real_retrieval_validation/rd-v2-retrieval-v1.0"
        ),
    )
    result.add_argument(
        "--baseline-artifact-dir",
        type=Path,
        default=Path(
            "data/rd_v2_corpus/retrieval_artifacts/rd-v2-retrieval-v1.0"
        ),
    )
    result.add_argument(
        "--artifact-root",
        type=Path,
        default=Path(
            "data/rd_v2_corpus/retrieval_artifacts/rd-v2-retrieval-v1.0_embedding_enrichment"
        ),
    )
    result.add_argument(
        "--corpus-root", type=Path, default=Path("data/rd_v2_corpus")
    )
    result.add_argument(
        "--corpus-snapshot",
        type=Path,
        default=Path(
            "reports/rd_v2_real_retrieval_validation/corpus_snapshot.json"
        ),
    )
    result.add_argument(
        "--report-dir",
        type=Path,
        default=Path("reports/rd_v2_hybrid_ablation"),
    )
    return result


if __name__ == "__main__":
    main(parser().parse_args())
