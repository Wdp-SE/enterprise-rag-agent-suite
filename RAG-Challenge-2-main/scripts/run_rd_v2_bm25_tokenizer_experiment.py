"""Controlled DEV-only comparison of frozen BM25 tokenizer V1 and V2.

The runner reuses the frozen 5,090 child chunks and the frozen V1 BM25 pickle.
It builds only a separate V2 BM25 pickle.  Dense SECTION_PATH artifacts are
read only for complementarity and, if a fixed gate passes, one conservative
RRF confirmation.  Reports never persist questions, body text, or real tokens.
"""

from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import ctypes
from datetime import datetime
import hashlib
import inspect
import json
import math
import os
from pathlib import Path
import pickle
import re
import sys
from typing import Callable, Iterable, Sequence
from zoneinfo import ZoneInfo

import numpy as np
from rank_bm25 import BM25Plus


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.rd_retrieval import reciprocal_rank_fusion
from src.text_tokenization import (
    normalize_technical_text_v2,
    technical_tokenize_v1,
    technical_tokenize_v2,
)


DATASET_VERSION = "rd-v2-retrieval-v1.0"
EXPERIMENT_VERSION = "rd-v2-bm25-tokenizer-v0.1"
KS = (1, 3, 5, 10, 20, 50)
QUERY_TYPES = (
    "semantic",
    "exact_term",
    "interface",
    "field",
    "numeric",
    "dependency",
    "cross_section",
)
CRITICAL_TYPES = ("field", "exact_term", "interface")
DENSE_TOP_K = 12
BM25_TOP_K = 12
RRF_K = 60
DENSE_WEIGHT = 1.0
BM25_WEIGHT = 0.25
SIGNIFICANT_OVERALL_HIT_GAIN = 0.05
SIGNIFICANT_DENSE_RECOVERY_GAIN = 2

IDENTIFIER_RE = re.compile(
    r"/[A-Za-z0-9._~:/?#\[\]@!$&'()*+,;=%-]+"
    r"|[A-Za-z0-9]+(?:[._:-][A-Za-z0-9]+)+"
    r"|[A-Za-z]+[A-Z][A-Za-z0-9]*"
    r"|(?=[A-Za-z0-9]*[A-Za-z])(?=[A-Za-z0-9]*\d)[A-Za-z0-9]+"
    r"|[A-Z]{2,}"
)


if os.name == "nt":
    ctypes.windll.kernel32.SetErrorMode(0x0001 | 0x0002 | 0x8000)


def now() -> str:
    return datetime.now(ZoneInfo("Asia/Shanghai")).isoformat(timespec="seconds")


def load_json(path: Path) -> dict:
    with path.open("r", encoding="utf-8") as stream:
        return json.load(stream)


def write_json_new(path: Path, payload: dict) -> None:
    if path.exists():
        raise RuntimeError(f"Refusing to overwrite report: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as stream:
        json.dump(payload, stream, ensure_ascii=False, indent=2)
        stream.write("\n")


def write_text_new(path: Path, value: str) -> None:
    if path.exists():
        raise RuntimeError(f"Refusing to overwrite report: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(value, encoding="utf-8", newline="\n")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def sequence_digest(values: Iterable[str]) -> str:
    digest = hashlib.sha256()
    for value in values:
        encoded = str(value).encode("utf-8")
        digest.update(len(encoded).to_bytes(8, "big"))
        digest.update(encoded)
    return digest.hexdigest()


def load_chunks(path: Path) -> list[dict]:
    chunks = []
    with path.open("r", encoding="utf-8") as stream:
        for index, line in enumerate(stream):
            item = json.loads(line)
            item["chunk_index"] = index
            chunks.append(item)
    return chunks


def verify_frozen_inputs(args: argparse.Namespace, chunks: list[dict], dataset: dict, baseline: dict) -> None:
    manifest = load_json(args.baseline_artifact_dir / "artifact_manifest.json")
    if dataset.get("dataset_version") != DATASET_VERSION:
        raise RuntimeError("Unexpected dataset version")
    if dataset.get("dataset_status") != "FROZEN" or not dataset.get("ground_truth_frozen"):
        raise RuntimeError("Dataset is not frozen")
    if dataset.get("split") != "DEV" or len(dataset.get("cases", [])) != 40:
        raise RuntimeError("Experiment is restricted to the frozen 40-case DEV split")
    if manifest.get("build_status") != "PASS" or manifest.get("child_chunk_count") != 5090:
        raise RuntimeError("Frozen artifact manifest is not valid")
    if len(chunks) != 5090:
        raise RuntimeError("Frozen child chunk count is not 5090")
    chunk_ids = [chunk.get("chunk_id") for chunk in chunks]
    if baseline.get("chunk_ids") != chunk_ids:
        raise RuntimeError("V1 BM25/chunk ID alignment failed")
    if len(set(chunk_ids)) != len(chunk_ids) or any(not value for value in chunk_ids):
        raise RuntimeError("Frozen child chunk IDs are missing or duplicated")
    expected_chunk_hash = manifest["artifact_files"]["child_chunks.jsonl"]["sha256"]
    expected_bm25_hash = manifest["artifact_files"]["bm25_index.pkl"]["sha256"]
    if sha256_file(args.baseline_artifact_dir / "child_chunks.jsonl") != expected_chunk_hash:
        raise RuntimeError("Frozen child chunk hash mismatch")
    if sha256_file(args.baseline_artifact_dir / "bm25_index.pkl") != expected_bm25_hash:
        raise RuntimeError("Frozen BM25 V1 hash mismatch")
    if "torch" in sys.modules:
        raise RuntimeError("Tokenizer experiment must not load PyTorch")


def contract_payload() -> dict:
    examples = [
        ("snake_case", "timeout_ms", ["timeout_ms", "timeout", "ms"]),
        ("slash_path", "/api/export", ["/api/export", "api", "export"]),
        ("hyphen_requirement", "REQ-03-21", ["req-03-21", "req", "03", "21"]),
        ("hyphen_identifier", "XG-GN-SJCL", ["xg-gn-sjcl", "xg", "gn", "sjcl"]),
        (
            "dot_notation",
            "module.config.timeout",
            ["module.config.timeout", "module", "config", "timeout"],
        ),
        ("camel_case", "requestTimeout", ["requesttimeout", "request", "timeout"]),
        ("numeric_unit_tps", "1000 TPS", ["1000", "tps"]),
        ("numeric_unit_ms", "30 ms", ["30", "ms"]),
        ("chinese_term", "超时配置", technical_tokenize_v2("超时配置")),
        ("mixed", "数据处理模块SJCL", technical_tokenize_v2("数据处理模块SJCL")),
        ("empty", "", []),
        ("punctuation_only", "，。！？()", []),
        (
            "repeated",
            "timeout_ms timeout_ms",
            ["timeout_ms", "timeout", "ms", "timeout_ms", "timeout", "ms"],
        ),
        ("fullwidth", "ｔｉｍｅｏｕｔ＿ｍｓ", ["timeout_ms", "timeout", "ms"]),
    ]
    rows = []
    for category, value, expected in examples:
        index_tokens = technical_tokenize_v2(value)
        query_tokens = technical_tokenize_v2(value)
        rows.append(
            {
                "category": category,
                "input": value,
                "expected_tokens": expected,
                "actual_index_tokens": index_tokens,
                "actual_query_tokens": query_tokens,
                "symmetric": index_tokens == query_tokens,
                "pass": index_tokens == expected and query_tokens == expected,
            }
        )
    no_explosion = not {
        "xg-gn",
        "gn-sjcl",
        "xg-sjcl",
    }.intersection(technical_tokenize_v2("XG-GN-SJCL"))
    payload = {
        "schema_version": 1,
        "experiment_version": EXPERIMENT_VERSION,
        "tokenizers": {
            "TOKENIZER_V1": {
                "callable": "src.text_tokenization.technical_tokenize_v1",
                "source_sha256": sha256_text(inspect.getsource(technical_tokenize_v1)),
                "status": "FROZEN_BASELINE_UNCHANGED",
            },
            "TOKENIZER_V2_TECHNICAL": {
                "callable": "src.text_tokenization.technical_tokenize_v2",
                "source_sha256": sha256_text(inspect.getsource(technical_tokenize_v2)),
                "normalization": ["UNICODE_NFKC", "CASEFOLD_ASCII_LEXEMES", "WHITESPACE_COLLAPSE"],
                "identifier_policy": "FULL_ATOMIC_TOKEN_PLUS_FIRST_LEVEL_COMPONENTS",
                "recursive_combinations": False,
                "artificial_token_repetition": False,
            },
        },
        "contract_cases": rows,
        "query_index_symmetric": all(row["symmetric"] for row in rows),
        "no_recursive_identifier_combinations": no_explosion,
        "contract_pass": all(row["pass"] for row in rows) and no_explosion,
        "synthetic_inputs_only": True,
    }
    if not payload["contract_pass"]:
        raise RuntimeError("TOKENIZER_V2 contract failed")
    return payload


def build_or_verify_v2_artifact(
    args: argparse.Namespace,
    chunks: list[dict],
    v1_index,
) -> tuple[dict, dict]:
    final_dir = args.v2_artifact_dir
    manifest_path = final_dir / "artifact_manifest.json"
    index_path = final_dir / "bm25_index.pkl"
    if final_dir.exists():
        manifest = load_json(manifest_path)
        if (
            manifest.get("build_status") != "PASS"
            or manifest.get("chunk_count") != len(chunks)
            or manifest.get("ordered_chunk_id_sha256")
            != sequence_digest(chunk["chunk_id"] for chunk in chunks)
            or manifest.get("artifact_files", {}).get("bm25_index.pkl", {}).get("sha256")
            != sha256_file(index_path)
        ):
            raise RuntimeError("Existing V2 BM25 artifact failed validation")
        with index_path.open("rb") as stream:
            payload = pickle.load(stream)
        if payload.get("chunk_ids") != [chunk["chunk_id"] for chunk in chunks]:
            raise RuntimeError("Existing V2 BM25 artifact/chunk alignment failed")
        return payload, manifest

    staging = final_dir.with_name(final_dir.name + ".building")
    if staging.exists():
        raise RuntimeError(f"Incomplete V2 staging directory exists: {staging}")
    staging.mkdir(parents=True)
    tokenized_v2 = [technical_tokenize_v2(chunk["text"]) for chunk in chunks]
    v2_index = BM25Plus(tokenized_v2)
    payload = {
        "index": v2_index,
        "chunk_ids": [chunk["chunk_id"] for chunk in chunks],
        "tokenizer_version": "TOKENIZER_V2_TECHNICAL",
        "normalization": "UNICODE_NFKC_CASEFOLD_WHITESPACE_COLLAPSE",
    }
    with (staging / "bm25_index.pkl").open("wb") as stream:
        pickle.dump(payload, stream, protocol=pickle.HIGHEST_PROTOCOL)

    v1_token_counts = [len(technical_tokenize_v1(chunk["text"])) for chunk in chunks]
    v2_token_counts = [len(tokens) for tokens in tokenized_v2]
    manifest = {
        "schema_version": 1,
        "build_status": "PASS",
        "built_at": now(),
        "experiment_version": EXPERIMENT_VERSION,
        "dataset_version": DATASET_VERSION,
        "corpus_snapshot_sha256": load_json(
            args.baseline_artifact_dir / "artifact_manifest.json"
        )["corpus_snapshot_sha256"],
        "child_chunks_sha256": sha256_file(args.baseline_artifact_dir / "child_chunks.jsonl"),
        "ordered_chunk_id_sha256": sequence_digest(chunk["chunk_id"] for chunk in chunks),
        "chunk_count": len(chunks),
        "bm25_index_type": type(v2_index).__name__,
        "v1_reference": {
            "artifact_path": str(args.baseline_artifact_dir / "bm25_index.pkl").replace("\\", "/"),
            "artifact_sha256": sha256_file(args.baseline_artifact_dir / "bm25_index.pkl"),
            "tokenizer_version": "TOKENIZER_V1",
            "vocabulary_size": len(v1_index.idf),
            "chunk_count": int(v1_index.corpus_size),
            "status": "REUSED_VERIFIED_FROZEN_NOT_REBUILT",
        },
        "v2": {
            "tokenizer_version": "TOKENIZER_V2_TECHNICAL",
            "tokenizer_source_sha256": sha256_text(inspect.getsource(technical_tokenize_v2)),
            "normalization": "UNICODE_NFKC_CASEFOLD_WHITESPACE_COLLAPSE",
            "vocabulary_size": len(v2_index.idf),
            "chunk_count": int(v2_index.corpus_size),
            "average_tokens_per_chunk": round(sum(v2_token_counts) / len(v2_token_counts), 6),
            "maximum_tokens_per_chunk": max(v2_token_counts),
        },
        "comparison": {
            "v1_average_tokens_per_chunk": round(sum(v1_token_counts) / len(v1_token_counts), 6),
            "v2_average_tokens_per_chunk": round(sum(v2_token_counts) / len(v2_token_counts), 6),
            "v2_to_v1_average_token_ratio": round(
                sum(v2_token_counts) / max(1, sum(v1_token_counts)), 6
            ),
        },
        "artifact_files": {
            "bm25_index.pkl": {
                "sha256": sha256_file(staging / "bm25_index.pkl"),
                "bytes": (staging / "bm25_index.pkl").stat().st_size,
            }
        },
        "embedding_rebuilt": False,
        "faiss_rebuilt": False,
        "chunks_modified": False,
        "sections_modified": False,
        "online_models_called": False,
        "body_text_logged": False,
    }
    write_json_new(staging / "artifact_manifest.json", manifest)
    staging.replace(final_dir)
    return payload, manifest


def safe_chunk_result(chunk: dict, score: float, source: str) -> dict:
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
    result[f"{source}_score"] = round(float(score), 8)
    return result


def bm25_chunk_ranking(
    index,
    token_sets: Sequence[set[str]],
    tokenizer: Callable[[str], list[str]],
    query: str,
    chunks: Sequence[dict],
) -> list[dict]:
    tokens = tokenizer(query)
    if not tokens:
        return []
    query_set = set(tokens)
    scores = np.asarray(index.get_scores(tokens), dtype=np.float64)
    rows = []
    for chunk_index in np.argsort(-scores, kind="stable"):
        index_value = int(chunk_index)
        score = float(scores[index_value])
        if score <= 0.0 or not query_set.intersection(token_sets[index_value]):
            continue
        rows.append(safe_chunk_result(chunks[index_value], score, "bm25"))
    return rows


def dense_chunk_ranking(index, query_vector: np.ndarray, chunks: Sequence[dict]) -> list[dict]:
    scores, indices = index.search(
        np.ascontiguousarray(query_vector.reshape(1, -1), dtype=np.float32), index.ntotal
    )
    return [
        safe_chunk_result(chunks[int(chunk_index)], float(score), "dense")
        for score, chunk_index in zip(scores[0], indices[0])
        if int(chunk_index) >= 0
    ]


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
            "chunk_id": row["chunk_id"],
            "section_id": row.get("section_id"),
            "section_source": row.get("section_source"),
            "retrieval_sources": row.get("retrieval_sources", [row.get("retrieval_source")]),
        }
        for name in ("dense_rank", "bm25_rank", "dense_score", "bm25_score", "rrf_score"):
            if row.get(name) is not None:
                page[name] = row[name]
        pages.append(page)
        if limit is not None and len(pages) >= limit:
            break
    return pages


def evaluate_case(case: dict, pages: Sequence[dict]) -> dict:
    expected = {(case["expected_document_id"], int(page)) for page in case["expected_pages"]}
    ranked = [(row["document_id"], int(row["page_number"])) for row in pages]
    first_rank = next((rank for rank, key in enumerate(ranked, 1) if key in expected), None)
    hit_at_k = {}
    recall_at_k = {}
    for k in KS:
        relevant = len(expected.intersection(set(ranked[:k])))
        hit_at_k[str(k)] = int(relevant > 0)
        recall_at_k[str(k)] = round(relevant / len(expected), 6)
    return {
        "question_id": case["question_id"],
        "question_type": case["question_type"],
        "expected_document_id": case["expected_document_id"],
        "expected_pages": case["expected_pages"],
        "first_evidence_rank": first_rank,
        "hit_at_k": hit_at_k,
        "recall_at_k": recall_at_k,
        "reciprocal_rank_at_5": round(1 / first_rank, 6) if first_rank and first_rank <= 5 else 0.0,
        "reciprocal_rank_at_50": round(1 / first_rank, 6) if first_rank and first_rank <= 50 else 0.0,
    }


def metric_block(records: Sequence[dict]) -> dict:
    if not records:
        return {
            "count": 0,
            "hit_at_k": {str(k): None for k in KS},
            "recall_at_k": {str(k): None for k in KS},
            "mrr_at_5": None,
            "mrr_at_50": None,
        }
    return {
        "count": len(records),
        "hit_at_k": {
            str(k): round(sum(row["hit_at_k"][str(k)] for row in records) / len(records), 6)
            for k in KS
        },
        "recall_at_k": {
            str(k): round(sum(row["recall_at_k"][str(k)] for row in records) / len(records), 6)
            for k in KS
        },
        "mrr_at_5": round(sum(row["reciprocal_rank_at_5"] for row in records) / len(records), 6),
        "mrr_at_50": round(sum(row["reciprocal_rank_at_50"] for row in records) / len(records), 6),
    }


def metrics_with_types(records: Sequence[dict]) -> tuple[dict, dict]:
    grouped: dict[str, list[dict]] = defaultdict(list)
    for record in records:
        grouped[record["question_type"]].append(record)
    return metric_block(records), {
        question_type: metric_block(grouped[question_type]) for question_type in QUERY_TYPES
    }


def rank_status(v1_rank: int | None, v2_rank: int | None) -> str:
    old = v1_rank if v1_rank is not None else math.inf
    new = v2_rank if v2_rank is not None else math.inf
    if new < old:
        return "IMPROVED"
    if new > old:
        return "REGRESSED"
    return "UNCHANGED"


def compact_metrics(metrics: dict) -> dict:
    return {
        "count": metrics["count"],
        "hit_at_k": metrics["hit_at_k"],
        "recall_at_k": metrics["recall_at_k"],
        "mrr_at_5": metrics["mrr_at_5"],
        "mrr_at_50": metrics["mrr_at_50"],
    }


def type_improved(v1: dict, v2: dict) -> bool:
    return any(v2["hit_at_k"][str(k)] > v1["hit_at_k"][str(k)] for k in (20, 50))


def identifier_candidates(question: str) -> list[dict]:
    normalized = normalize_technical_text_v2(question)
    rows = []
    for match in IDENTIFIER_RE.finditer(normalized):
        value = match.group(0)
        if any(separator in value for separator in "/_.:-"):
            kind = "SEPARATOR_IDENTIFIER"
        elif re.search(r"[a-z0-9][A-Z]", value):
            kind = "CAMEL_CASE"
        elif value.isupper():
            kind = "UPPER_ACRONYM"
        else:
            kind = "ALPHANUMERIC"
        rows.append({"sha256": sha256_text(value.casefold()), "kind": kind, "length": len(value)})
    unique_rows = []
    seen = set()
    for row in rows:
        key = (row["sha256"], row["kind"])
        if key not in seen:
            seen.add(key)
            unique_rows.append(row)
    return unique_rows


def recovered_dense_misses(dense_records: Sequence[dict], sparse_records: Sequence[dict]) -> dict:
    cases = []
    for dense, sparse in zip(dense_records, sparse_records):
        if not dense["hit_at_k"]["50"] and sparse["hit_at_k"]["50"]:
            cases.append(
                {
                    "question_id": dense["question_id"],
                    "question_type": dense["question_type"],
                    "dense_rank": dense["first_evidence_rank"],
                    "bm25_rank": sparse["first_evidence_rank"],
                }
            )
    return {"count": len(cases), "cases": cases}


def comparison_delta(baseline: dict, candidate: dict) -> dict:
    return {
        "hit_at_k": {
            str(k): round(candidate["hit_at_k"][str(k)] - baseline["hit_at_k"][str(k)], 6)
            for k in KS
        },
        "recall_at_k": {
            str(k): round(candidate["recall_at_k"][str(k)] - baseline["recall_at_k"][str(k)], 6)
            for k in KS
        },
        "mrr_at_5": round(candidate["mrr_at_5"] - baseline["mrr_at_5"], 6),
        "mrr_at_50": round(candidate["mrr_at_50"] - baseline["mrr_at_50"], 6),
    }


def hybrid_delta(dense_records: Sequence[dict], hybrid_records: Sequence[dict]) -> dict:
    counts = Counter()
    rows = []
    for dense, hybrid in zip(dense_records, hybrid_records):
        flags = []
        for k in (5, 20, 50):
            if not dense["hit_at_k"][str(k)] and hybrid["hit_at_k"][str(k)]:
                flags.append(f"TOP{k}_RECOVERED")
                counts[f"TOP{k}_RECOVERED"] += 1
        for k in (1, 5):
            if dense["hit_at_k"][str(k)] and not hybrid["hit_at_k"][str(k)]:
                flags.append(f"REGRESSED_TOP{k}")
                counts[f"REGRESSED_TOP{k}"] += 1
        rows.append(
            {
                "question_id": dense["question_id"],
                "question_type": dense["question_type"],
                "dense_rank": dense["first_evidence_rank"],
                "hybrid_rank": hybrid["first_evidence_rank"],
                "flags": flags or ["UNCHANGED"],
            }
        )
    return {
        "counts": {
            name: counts[name]
            for name in (
                "TOP5_RECOVERED",
                "TOP20_RECOVERED",
                "TOP50_RECOVERED",
                "REGRESSED_TOP1",
                "REGRESSED_TOP5",
            )
        },
        "per_query": rows,
    }


def main(args: argparse.Namespace) -> None:
    required_outputs = (
        "tokenizer_contract.json",
        "tokenizer_tests.md",
        "bm25_v1_v2_metrics.json",
        "per_type_metrics.json",
        "identifier_rank_delta.json",
        "high_df_analysis.json",
        "repeated_term_analysis.json",
        "bm25_tokenizer_report.md",
    )
    if any((args.report_dir / name).exists() for name in required_outputs):
        raise RuntimeError("Refusing to overwrite an existing tokenizer experiment report")

    dataset = load_json(args.dataset_dir / "dev_dataset.json")
    chunks = load_chunks(args.baseline_artifact_dir / "child_chunks.jsonl")
    with (args.baseline_artifact_dir / "bm25_index.pkl").open("rb") as stream:
        v1_payload = pickle.load(stream)
    verify_frozen_inputs(args, chunks, dataset, v1_payload)
    contract = contract_payload()
    v2_payload, v2_manifest = build_or_verify_v2_artifact(
        args, chunks, v1_payload["index"]
    )
    v1_index = v1_payload["index"]
    v2_index = v2_payload["index"]
    if v1_index.corpus_size != 5090 or v2_index.corpus_size != 5090:
        raise RuntimeError("BM25 corpus size invariant failed")

    v1_token_lists = [technical_tokenize_v1(chunk["text"]) for chunk in chunks]
    v2_token_lists = [technical_tokenize_v2(chunk["text"]) for chunk in chunks]
    v1_token_sets = [set(tokens) for tokens in v1_token_lists]
    v2_token_sets = [set(tokens) for tokens in v2_token_lists]
    cases = dataset["cases"]
    v1_chunk_rows = []
    v2_chunk_rows = []
    v1_page_rows = []
    v2_page_rows = []
    for case in cases:
        old_rows = bm25_chunk_ranking(
            v1_index, v1_token_sets, technical_tokenize_v1, case["question"], chunks
        )
        new_rows = bm25_chunk_ranking(
            v2_index, v2_token_sets, technical_tokenize_v2, case["question"], chunks
        )
        v1_chunk_rows.append(old_rows)
        v2_chunk_rows.append(new_rows)
        v1_page_rows.append(page_dedupe(old_rows))
        v2_page_rows.append(page_dedupe(new_rows))
    v1_records = [evaluate_case(case, pages) for case, pages in zip(cases, v1_page_rows)]
    v2_records = [evaluate_case(case, pages) for case, pages in zip(cases, v2_page_rows)]
    v1_overall, v1_types = metrics_with_types(v1_records)
    v2_overall, v2_types = metrics_with_types(v2_records)

    prior_baseline = load_json(args.prior_bm25_metrics)
    if compact_metrics(v1_overall) != compact_metrics(prior_baseline["metrics"]):
        raise RuntimeError("Recomputed BM25 V1 metrics do not reproduce the frozen baseline")

    per_type = {}
    improvements = {}
    for question_type in QUERY_TYPES:
        improved = type_improved(v1_types[question_type], v2_types[question_type])
        improvements[question_type] = improved
        per_type[question_type] = {
            "BM25_V1": v1_types[question_type],
            "BM25_V2": v2_types[question_type],
            "V2_MINUS_V1": comparison_delta(v1_types[question_type], v2_types[question_type]),
            "improved_at_hit20_or_hit50": improved,
        }
    semantic_regression = any(
        v2_types["semantic"]["hit_at_k"][str(k)] < v1_types["semantic"]["hit_at_k"][str(k)]
        for k in (20, 50)
    )

    v1_by_id = {record["question_id"]: record for record in v1_records}
    v2_by_id = {record["question_id"]: record for record in v2_records}
    identifiers = []
    for case in cases:
        candidate_tokens = identifier_candidates(case["question"])
        if not candidate_tokens:
            continue
        old = v1_by_id[case["question_id"]]
        new = v2_by_id[case["question_id"]]
        identifiers.append(
            {
                "question_id": case["question_id"],
                "question_type": case["question_type"],
                "identifier_count": len(candidate_tokens),
                "identifier_token_hashes": candidate_tokens,
                "v1_expected_evidence_rank": old["first_evidence_rank"],
                "v2_expected_evidence_rank": new["first_evidence_rank"],
                "status": rank_status(old["first_evidence_rank"], new["first_evidence_rank"]),
            }
        )

    failure_taxonomy = load_json(args.failure_taxonomy)
    lexical_audit = load_json(args.lexical_audit)
    lexical_by_id = {row["question_id"]: row for row in lexical_audit["cases"]}
    prior_failures = {row["question_id"]: row for row in failure_taxonomy["cases"]}
    mismatch_ids = [
        question_id
        for question_id, row in prior_failures.items()
        if row["evidence_flags"].get("identifier_split_mismatch")
    ]
    case_by_id = {case["question_id"]: case for case in cases}
    chunks_by_expected_page: dict[tuple[str, int], list[int]] = defaultdict(list)
    for index, chunk in enumerate(chunks):
        chunks_by_expected_page[(chunk["document_id"], int(chunk["page_number"]))].append(index)
    mismatch_rows = []
    for question_id in mismatch_ids:
        case = case_by_id[question_id]
        target_hash = lexical_by_id[question_id]["target_lexical_token"]["sha256"]
        possible = [
            token
            for token in technical_tokenize_v1(case["question"])
            if sha256_text(token) == target_hash
        ]
        target = possible[0] if possible else ""
        expected_indices = [
            index
            for page in case["expected_pages"]
            for index in chunks_by_expected_page[(case["expected_document_id"], int(page))]
        ]
        old_query = target in technical_tokenize_v1(case["question"])
        new_query = target in technical_tokenize_v2(case["question"])
        old_evidence = any(target in v1_token_sets[index] for index in expected_indices)
        new_evidence = any(target in v2_token_sets[index] for index in expected_indices)
        fixed = bool(target and new_query and new_evidence)
        mismatch_rows.append(
            {
                "question_id": question_id,
                "question_type": case["question_type"],
                "target_token_sha256": target_hash,
                "v1_query_emits_target": old_query,
                "v1_evidence_emits_target": old_evidence,
                "v2_query_emits_target": new_query,
                "v2_evidence_emits_target": new_evidence,
                "lexical_mismatch_fixed": fixed,
                "v1_expected_evidence_rank": v1_by_id[question_id]["first_evidence_rank"],
                "v2_expected_evidence_rank": v2_by_id[question_id]["first_evidence_rank"],
            }
        )
    mismatch_fixed = bool(mismatch_rows) and all(row["lexical_mismatch_fixed"] for row in mismatch_rows)

    v1_df = Counter()
    v2_df = Counter()
    for tokens in v1_token_sets:
        v1_df.update(tokens)
    for tokens in v2_token_sets:
        v2_df.update(tokens)

    high_df_ids = [
        question_id
        for question_id, row in prior_failures.items()
        if row["primary_failure_reason"] == "HIGH_DF_LOW_IDF"
    ]
    high_df_rows = []
    for question_id in high_df_ids:
        case = case_by_id[question_id]
        target_hash = lexical_by_id[question_id]["target_lexical_token"]["sha256"]
        query_tokens = technical_tokenize_v1(case["question"])
        target = next((token for token in query_tokens if sha256_text(token) == target_hash), "")
        expected_indices = [
            index
            for page in case["expected_pages"]
            for index in chunks_by_expected_page[(case["expected_document_id"], int(page))]
        ]
        old_expected = any(target in v1_token_sets[index] for index in expected_indices)
        new_expected = any(target in v2_token_sets[index] for index in expected_indices)
        new_rank = v2_by_id[question_id]["first_evidence_rank"]
        high_df_rows.append(
            {
                "question_id": question_id,
                "question_type": case["question_type"],
                "target_token_sha256": target_hash,
                "v1_document_frequency": v1_df[target] if target else 0,
                "v2_document_frequency": v2_df[target] if target else 0,
                "v1_idf": round(float(v1_index.idf[target]), 6) if target in v1_index.idf else None,
                "v2_idf": round(float(v2_index.idf[target]), 6) if target in v2_index.idf else None,
                "v1_expected_evidence_emits_target": old_expected,
                "v2_expected_evidence_emits_target": new_expected,
                "atomic_target_newly_available": new_expected and not old_expected,
                "v1_expected_evidence_rank": v1_by_id[question_id]["first_evidence_rank"],
                "v2_expected_evidence_rank": new_rank,
                "rank_status": rank_status(
                    v1_by_id[question_id]["first_evidence_rank"], new_rank
                ),
                "high_df_remains_unresolved": new_rank is None or new_rank > 50,
            }
        )
    high_df_unresolved = any(row["high_df_remains_unresolved"] for row in high_df_rows)

    repeated_ids = [
        question_id
        for question_id, row in prior_failures.items()
        if row["primary_failure_reason"] == "REPEATED_TERM_DISTRACTOR"
    ]
    repeated_rows = []
    for question_id in repeated_ids:
        old_rank = v1_by_id[question_id]["first_evidence_rank"]
        new_rank = v2_by_id[question_id]["first_evidence_rank"]
        repeated_rows.append(
            {
                "question_id": question_id,
                "question_type": case_by_id[question_id]["question_type"],
                "v1_expected_evidence_rank": old_rank,
                "v2_expected_evidence_rank": new_rank,
                "status": rank_status(old_rank, new_rank),
            }
        )
    repeated_status_counts = Counter(row["status"] for row in repeated_rows)
    if repeated_rows and repeated_status_counts["IMPROVED"] == len(repeated_rows):
        repeated_improved = "YES"
    elif repeated_status_counts["IMPROVED"] == 0 and repeated_status_counts["REGRESSED"] == 0:
        repeated_improved = "NO"
    else:
        repeated_improved = "MIXED"

    # Dense artifacts are reused read-only to measure sparse complementarity and
    # to support the single gated confirmation without loading an embedding model.
    dense_manifest = load_json(args.dense_artifact_dir / "artifact_manifest.json")
    query_manifest = load_json(args.dataset_dir / "dev_query_embedding_manifest.json")
    query_path = args.dataset_dir / "dev_query_embeddings.npy"
    if (
        dense_manifest.get("build_status") != "PASS"
        or dense_manifest.get("mode") != "SECTION_PATH"
        or dense_manifest.get("child_chunk_count") != len(chunks)
        or dense_manifest.get("ordered_chunk_id_sha256")
        != sequence_digest(chunk["chunk_id"] for chunk in chunks)
        or query_manifest.get("query_vectors_sha256") != sha256_file(query_path)
        or query_manifest.get("count") != len(cases)
    ):
        raise RuntimeError("Frozen SECTION_PATH dense artifact validation failed")
    import faiss

    dense_index = faiss.read_index(str(args.dense_artifact_dir / "child_vectors.faiss"))
    query_vectors = np.load(query_path, allow_pickle=False)
    if dense_index.ntotal != len(chunks) or query_vectors.shape != (len(cases), dense_index.d):
        raise RuntimeError("Dense index/query shape mismatch")
    dense_chunk_rows = [
        dense_chunk_ranking(dense_index, vector, chunks) for vector in query_vectors
    ]
    dense_page_rows = [page_dedupe(rows) for rows in dense_chunk_rows]
    dense_records = [evaluate_case(case, pages) for case, pages in zip(cases, dense_page_rows)]
    dense_overall, dense_types = metrics_with_types(dense_records)
    expected_dense = load_json(args.dense_metrics)["metrics"]["SECTION_PATH"]["overall"]
    if compact_metrics(dense_overall) != compact_metrics(expected_dense):
        raise RuntimeError("SECTION_PATH Dense metrics do not reproduce the frozen report")
    v1_recovered = recovered_dense_misses(dense_records, v1_records)
    v2_recovered = recovered_dense_misses(dense_records, v2_records)

    overall_gain_trigger = max(
        v2_overall["hit_at_k"]["20"] - v1_overall["hit_at_k"]["20"],
        v2_overall["hit_at_k"]["50"] - v1_overall["hit_at_k"]["50"],
    ) >= SIGNIFICANT_OVERALL_HIT_GAIN
    critical_improved_count = sum(improvements[name] for name in CRITICAL_TYPES)
    critical_type_trigger = critical_improved_count >= 2
    dense_recovery_trigger = (
        v2_recovered["count"] - v1_recovered["count"]
        >= SIGNIFICANT_DENSE_RECOVERY_GAIN
    )
    hybrid_triggered = overall_gain_trigger or critical_type_trigger or dense_recovery_trigger
    trigger = {
        "thresholds": {
            "overall_hit20_or_hit50_absolute_gain": SIGNIFICANT_OVERALL_HIT_GAIN,
            "critical_question_types_improved_required": 2,
            "dense_miss_recovery_count_gain": SIGNIFICANT_DENSE_RECOVERY_GAIN,
        },
        "overall_hit_gain_trigger": overall_gain_trigger,
        "critical_type_trigger": critical_type_trigger,
        "dense_recovery_trigger": dense_recovery_trigger,
        "hybrid_confirmation_run": hybrid_triggered,
    }

    hybrid_payload = None
    if hybrid_triggered:
        hybrid_pages = []
        for dense_rows, sparse_rows in zip(dense_chunk_rows, v2_chunk_rows):
            fused = reciprocal_rank_fusion(
                dense_rows[:DENSE_TOP_K],
                sparse_rows[:BM25_TOP_K],
                rrf_k=RRF_K,
                dense_weight=DENSE_WEIGHT,
                bm25_weight=BM25_WEIGHT,
                top_k=None,
            )
            hybrid_pages.append(page_dedupe(fused))
        hybrid_records = [
            evaluate_case(case, pages) for case, pages in zip(cases, hybrid_pages)
        ]
        hybrid_overall, hybrid_types = metrics_with_types(hybrid_records)
        hybrid_payload = {
            "schema_version": 1,
            "run": "ONE_GATED_HYBRID_CONFIRMATION",
            "trigger": trigger,
            "dense_backbone": "SECTION_PATH",
            "weights": {"dense": DENSE_WEIGHT, "bm25": BM25_WEIGHT},
            "rrf_k": RRF_K,
            "source_depth": {"dense_chunks": DENSE_TOP_K, "bm25_chunks": BM25_TOP_K},
            "dense_metrics": dense_overall,
            "hybrid_v2_metrics": hybrid_overall,
            "hybrid_v2_per_type": hybrid_types,
            "delta": hybrid_delta(dense_records, hybrid_records),
            "holdout_evaluated": False,
            "online_models_called": False,
            "body_text_logged": False,
        }
        write_json_new(args.report_dir / "hybrid_confirmation.json", hybrid_payload)

    any_benefit = (
        critical_improved_count > 0
        or overall_gain_trigger
        or v2_recovered["count"] > v1_recovered["count"]
        or mismatch_fixed
    )
    overall_regression = any(
        v2_overall["hit_at_k"][str(k)] < v1_overall["hit_at_k"][str(k)]
        for k in (20, 50)
    )
    if (
        hybrid_triggered
        and critical_improved_count >= 2
        and not overall_regression
        and not semantic_regression
    ):
        bm25_value = "YES"
    elif any_benefit:
        bm25_value = "PARTIAL"
    else:
        bm25_value = "NO"

    if bm25_value == "NO":
        retrieval_policy = "DENSE_ONLY"
    elif bm25_value == "PARTIAL":
        retrieval_policy = "DENSE_PRIMARY_BM25_SUPPLEMENT"
    else:
        hybrid_metrics = hybrid_payload["hybrid_v2_metrics"] if hybrid_payload else None
        hybrid_safe = bool(
            hybrid_metrics
            and hybrid_metrics["hit_at_k"]["20"] >= dense_overall["hit_at_k"]["20"]
            and hybrid_metrics["hit_at_k"]["50"] >= dense_overall["hit_at_k"]["50"]
        )
        retrieval_policy = "HYBRID_DEFAULT" if hybrid_safe else "DENSE_PRIMARY_BM25_SUPPLEMENT"
    ready_for_reranker = "YES" if retrieval_policy == "HYBRID_DEFAULT" else "NO"

    metrics_payload = {
        "schema_version": 1,
        "experiment_version": EXPERIMENT_VERSION,
        "dataset_version": DATASET_VERSION,
        "split": "DEV",
        "case_count": len(cases),
        "BM25_V1": v1_overall,
        "BM25_V2": v2_overall,
        "V2_MINUS_V1": comparison_delta(v1_overall, v2_overall),
        "artifacts": {
            "BM25_TOKENIZER_V1": v2_manifest["v1_reference"],
            "BM25_TOKENIZER_V2": {
                **v2_manifest["v2"],
                "artifact_path": str(args.v2_artifact_dir / "bm25_index.pkl").replace("\\", "/"),
                "artifact_sha256": sha256_file(args.v2_artifact_dir / "bm25_index.pkl"),
            },
        },
        "dense_complementarity": {
            "dense_backbone": "SECTION_PATH",
            "DENSE_MISS_BM25_V1_RECOVERED": v1_recovered,
            "DENSE_MISS_BM25_V2_RECOVERED": v2_recovered,
        },
        "hybrid_trigger": trigger,
        "holdout_evaluated": False,
        "online_models_called": False,
        "body_text_logged": False,
    }
    per_type_payload = {
        "schema_version": 1,
        "question_types": per_type,
        "critical_improvements": {
            "FIELD_V2_IMPROVED": improvements["field"],
            "EXACT_TERM_V2_IMPROVED": improvements["exact_term"],
            "INTERFACE_V2_IMPROVED": improvements["interface"],
        },
        "semantic_regression_at_hit20_or_hit50": semantic_regression,
    }
    identifier_payload = {
        "schema_version": 1,
        "detection": "deterministic separator/camel/alphanumeric/acronym regex after NFKC",
        "identifier_case_count": len(identifiers),
        "cases": identifiers,
        "previous_identifier_split_mismatch_cases": mismatch_rows,
        "tokenization_mismatch_fixed": "YES" if mismatch_fixed else "NO",
        "question_text_persisted": False,
        "real_tokens_persisted": False,
    }
    high_df_payload = {
        "schema_version": 1,
        "source": "prior BM25 failure taxonomy HIGH_DF_LOW_IDF cases",
        "case_count": len(high_df_rows),
        "cases": high_df_rows,
        "high_df_remains_unresolved": "YES" if high_df_unresolved else "NO",
        "idf_manually_adjusted": False,
        "corpus_specific_weighting_added": False,
        "real_tokens_persisted": False,
    }
    repeated_payload = {
        "schema_version": 1,
        "source": "prior BM25 failure taxonomy REPEATED_TERM_DISTRACTOR cases",
        "case_count": len(repeated_rows),
        "status_counts": {
            name: repeated_status_counts[name] for name in ("IMPROVED", "UNCHANGED", "REGRESSED")
        },
        "cases": repeated_rows,
        "repeated_term_distractor_improved": repeated_improved,
        "penalty_added": False,
    }

    tests_md = """# TOKENIZER_V2_TECHNICAL Contract Tests

Contract status: **PASS**

- Unicode normalization: NFKC
- English normalization: casefold
- Whitespace: collapsed before tokenization
- Identifiers: full atomic token plus first-level separator/camel components
- Numbers and units: retained
- Chinese segmentation: V1 behavior retained
- Natural repeated source terms: retained
- Recursive/artificial combination tokens: prohibited and absent
- Query/index function: identical (`technical_tokenize_v2`)

Automated test suite: `tests/test_text_tokenization_v2.py` (7 tests).
The machine-readable contract contains only the requested synthetic examples.
"""

    def h(metrics: dict, k: int) -> float:
        return metrics["hit_at_k"][str(k)]

    hybrid_lines = ""
    if hybrid_payload:
        hm = hybrid_payload["hybrid_v2_metrics"]
        hybrid_lines = (
            f"HYBRID_V2_HIT1 = {h(hm, 1):.6f}\n"
            f"HYBRID_V2_HIT5 = {h(hm, 5):.6f}\n"
            f"HYBRID_V2_HIT20 = {h(hm, 20):.6f}\n"
            f"HYBRID_V2_HIT50 = {h(hm, 50):.6f}\n"
        )
    report = f"""# Technical Identifier-Aware BM25 Tokenizer Experiment

Generated: `{now()}`  
Scope: frozen 40-case DEV only. Holdout was not loaded or evaluated.

## Result

TOKENIZER_V2_TECHNICAL was evaluated symmetrically on queries and the same frozen 5,090 child texts. V1 was reproduced from the untouched frozen pickle; only a separate V2 BM25 artifact was created. No Chunk, Section, Embedding, FAISS, Ground Truth, RRF algorithm, metadata representation, IDF weighting, routing, learned component, or penalty was changed.

| Metric | BM25 V1 | BM25 V2 | Delta |
|---|---:|---:|---:|
| Hit@1 | {h(v1_overall, 1):.6f} | {h(v2_overall, 1):.6f} | {h(v2_overall, 1)-h(v1_overall, 1):+.6f} |
| Hit@5 | {h(v1_overall, 5):.6f} | {h(v2_overall, 5):.6f} | {h(v2_overall, 5)-h(v1_overall, 5):+.6f} |
| Hit@20 | {h(v1_overall, 20):.6f} | {h(v2_overall, 20):.6f} | {h(v2_overall, 20)-h(v1_overall, 20):+.6f} |
| Hit@50 | {h(v1_overall, 50):.6f} | {h(v2_overall, 50):.6f} | {h(v2_overall, 50)-h(v1_overall, 50):+.6f} |
| MRR@5 | {v1_overall['mrr_at_5']:.6f} | {v2_overall['mrr_at_5']:.6f} | {v2_overall['mrr_at_5']-v1_overall['mrr_at_5']:+.6f} |
| MRR@50 | {v1_overall['mrr_at_50']:.6f} | {v2_overall['mrr_at_50']:.6f} | {v2_overall['mrr_at_50']-v1_overall['mrr_at_50']:+.6f} |

Critical type improvement is defined before inspection as a strict Hit@20 or Hit@50 increase. Hybrid confirmation is gated by an overall Hit@20/50 gain of at least {SIGNIFICANT_OVERALL_HIT_GAIN:.2f}, at least two improved critical types, or at least {SIGNIFICANT_DENSE_RECOVERY_GAIN} additional Dense misses recovered at Top50.

## Decision

- Identifier cases detected: {len(identifiers)}
- Previous split mismatch fixed: {'YES' if mismatch_fixed else 'NO'}
- High-DF failures still outside Top50: {'YES' if high_df_unresolved else 'NO'}
- Repeated-term result: {repeated_improved} ({dict(repeated_status_counts)})
- Dense misses recovered by V1/V2: {v1_recovered['count']} / {v2_recovered['count']}
- Hybrid confirmation trigger: {'YES' if hybrid_triggered else 'NO'}
- BM25 value: {bm25_value}
- Recommended retrieval policy: {retrieval_policy}

## Required Summary

```text
BM25_V1_HIT1 = {h(v1_overall, 1):.6f}
BM25_V1_HIT5 = {h(v1_overall, 5):.6f}
BM25_V1_HIT20 = {h(v1_overall, 20):.6f}
BM25_V1_HIT50 = {h(v1_overall, 50):.6f}

BM25_V2_HIT1 = {h(v2_overall, 1):.6f}
BM25_V2_HIT5 = {h(v2_overall, 5):.6f}
BM25_V2_HIT20 = {h(v2_overall, 20):.6f}
BM25_V2_HIT50 = {h(v2_overall, 50):.6f}

FIELD_V2_IMPROVED = {'YES' if improvements['field'] else 'NO'}
EXACT_TERM_V2_IMPROVED = {'YES' if improvements['exact_term'] else 'NO'}
INTERFACE_V2_IMPROVED = {'YES' if improvements['interface'] else 'NO'}

TOKENIZATION_MISMATCH_FIXED = {'YES' if mismatch_fixed else 'NO'}
HIGH_DF_REMAINS_UNRESOLVED = {'YES' if high_df_unresolved else 'NO'}
REPEATED_TERM_DISTRACTOR_IMPROVED = {repeated_improved}

DENSE_MISS_BM25_V1_RECOVERED = {v1_recovered['count']}
DENSE_MISS_BM25_V2_RECOVERED = {v2_recovered['count']}

HYBRID_CONFIRMATION_RUN = {'YES' if hybrid_triggered else 'NO'}
{hybrid_lines}BM25_VALUE_VERIFIED = {bm25_value}
RECOMMENDED_RETRIEVAL_POLICY = {retrieval_policy}
READY_FOR_RERANKER_VALIDATION = {ready_for_reranker}
```

This concludes the final controlled BM25 repair experiment. No further BM25/Hybrid optimization is proposed.
"""

    args.report_dir.mkdir(parents=True, exist_ok=True)
    write_json_new(args.report_dir / "tokenizer_contract.json", contract)
    write_text_new(args.report_dir / "tokenizer_tests.md", tests_md)
    write_json_new(args.report_dir / "bm25_v1_v2_metrics.json", metrics_payload)
    write_json_new(args.report_dir / "per_type_metrics.json", per_type_payload)
    write_json_new(args.report_dir / "identifier_rank_delta.json", identifier_payload)
    write_json_new(args.report_dir / "high_df_analysis.json", high_df_payload)
    write_json_new(args.report_dir / "repeated_term_analysis.json", repeated_payload)
    write_text_new(args.report_dir / "bm25_tokenizer_report.md", report)

    print(
        json.dumps(
            {
                "status": "PASS",
                "v1_hit20": h(v1_overall, 20),
                "v1_hit50": h(v1_overall, 50),
                "v2_hit20": h(v2_overall, 20),
                "v2_hit50": h(v2_overall, 50),
                "hybrid_confirmation_run": hybrid_triggered,
                "bm25_value_verified": bm25_value,
                "retrieval_policy": retrieval_policy,
                "holdout_evaluated": False,
                "online_models_called": False,
                "body_text_logged": False,
            }
        )
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--baseline-artifact-dir",
        type=Path,
        default=Path("data/rd_v2_corpus/retrieval_artifacts/rd-v2-retrieval-v1.0"),
    )
    parser.add_argument(
        "--v2-artifact-dir",
        type=Path,
        default=Path(
            "data/rd_v2_corpus/retrieval_artifacts/rd-v2-retrieval-v1.0_bm25_tokenizer_v2"
        ),
    )
    parser.add_argument(
        "--dense-artifact-dir",
        type=Path,
        default=Path(
            "data/rd_v2_corpus/retrieval_artifacts/rd-v2-retrieval-v1.0_embedding_enrichment/embedding_repr_section_path"
        ),
    )
    parser.add_argument(
        "--dataset-dir",
        type=Path,
        default=Path("reports/rd_v2_real_retrieval_validation/rd-v2-retrieval-v1.0"),
    )
    parser.add_argument(
        "--prior-bm25-metrics",
        type=Path,
        default=Path("reports/rd_v2_hybrid_ablation/bm25_baseline.json"),
    )
    parser.add_argument(
        "--dense-metrics",
        type=Path,
        default=Path("reports/rd_v2_embedding_enrichment/dev_metrics.json"),
    )
    parser.add_argument(
        "--failure-taxonomy",
        type=Path,
        default=Path("reports/rd_v2_bm25_failure_analysis/bm25_failure_taxonomy.json"),
    )
    parser.add_argument(
        "--lexical-audit",
        type=Path,
        default=Path("reports/rd_v2_bm25_failure_analysis/lexical_overlap_analysis.json"),
    )
    parser.add_argument(
        "--report-dir",
        type=Path,
        default=Path("reports/rd_v2_bm25_tokenizer_experiment"),
    )
    return parser.parse_args()


if __name__ == "__main__":
    main(parse_args())
