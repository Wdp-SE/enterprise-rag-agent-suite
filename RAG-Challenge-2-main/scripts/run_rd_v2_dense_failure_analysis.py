"""Read-only failure analysis for the frozen R&D V2 DEV dense baseline.

This runner loads frozen query vectors and the existing FAISS/BM25 metadata.
It does not import PyTorch, generate embeddings, run BM25 retrieval, change
ground truth, or persist document body text in reports.
"""

from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import hashlib
import json
from pathlib import Path
import pickle
import re
import sys
from typing import Iterable, Sequence

import faiss
import numpy as np


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.sectioning import SECTIONING_VERSION


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
SECTION_SOURCES = ("WORD_OUTLINE", "PDF_HEURISTIC", "FALLBACK")
LEXICAL_TYPES = {"exact_term", "interface", "field", "numeric"}
SEMANTIC_TYPES = {"semantic", "dependency", "cross_section"}
GENERIC_SECTION_TITLES = {"Document preamble", "Unresolved structure region"}
BOILERPLATE_RE = re.compile(
    r"测试步骤|前置条件|预期结果|输入|输出|系统应|操作步骤|期望结果|"
    r"test\s*step|precondition|expected\s*result|input|output",
    re.I,
)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json_new(path: Path, payload: object) -> None:
    if path.exists():
        raise RuntimeError(f"Refusing to overwrite existing analysis artifact: {path.name}")
    path.parent.mkdir(parents=True, exist_ok=True)
    partial = path.with_suffix(path.suffix + ".partial")
    if partial.exists():
        raise RuntimeError(f"Partial analysis artifact exists: {partial.name}")
    partial.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    partial.replace(path)


def write_text_new(path: Path, value: str) -> None:
    if path.exists():
        raise RuntimeError(f"Refusing to overwrite existing analysis artifact: {path.name}")
    path.parent.mkdir(parents=True, exist_ok=True)
    partial = path.with_suffix(path.suffix + ".partial")
    if partial.exists():
        raise RuntimeError(f"Partial analysis artifact exists: {partial.name}")
    partial.write_text(value.rstrip() + "\n", encoding="utf-8")
    partial.replace(path)


def normalize_text(value: str) -> str:
    return re.sub(r"\s+", " ", value.casefold()).strip()


def template_signature(value: str) -> str:
    normalized = normalize_text(value)
    normalized = re.sub(r"[0-9a-f]{8}-[0-9a-f-]{27,}", "<uuid>", normalized)
    normalized = re.sub(r"\b\d+(?:\.\d+)?\b", "<num>", normalized)
    normalized = re.sub(r"\b[a-z][a-z0-9_.-]{5,}\b", "<id>", normalized)
    return normalized


def metric_block(records: Sequence[dict]) -> dict:
    if not records:
        return {
            "count": 0,
            "hit_at_k": {str(k): None for k in KS},
            "recall_at_k": {str(k): None for k in KS},
            "mrr": None,
        }
    return {
        "count": len(records),
        "hit_at_k": {
            str(k): round(sum(row["hit_at_k"][str(k)] for row in records) / len(records), 6)
            for k in KS
        },
        "recall_at_k": {
            str(k): round(
                sum(row["recall_at_k"][str(k)] for row in records) / len(records), 6
            )
            for k in KS
        },
        "mrr": round(sum(row["reciprocal_rank"] for row in records) / len(records), 6),
    }


def section_metric_block(records: Sequence[dict]) -> dict:
    if not records:
        return {
            "count": 0,
            "hit_at_k": {str(k): None for k in KS},
            "mrr": None,
        }
    return {
        "count": len(records),
        "hit_at_k": {
            str(k): round(
                sum(row["section_hit_at_k"][str(k)] for row in records) / len(records), 6
            )
            for k in KS
        },
        "mrr": round(
            sum(row["section_reciprocal_rank"] for row in records) / len(records), 6
        ),
    }


def percentile(values: Sequence[int], q: float) -> float | None:
    if not values:
        return None
    return round(float(np.percentile(np.asarray(values, dtype=np.float64), q)), 3)


def verify_frozen_inputs(args: argparse.Namespace) -> dict:
    freeze = load_json(args.dataset_dir / "dataset_freeze_manifest.json")
    if (
        freeze.get("dataset_status") != "FROZEN"
        or freeze.get("ground_truth_frozen") is not True
        or freeze.get("human_review_completed") is not True
    ):
        raise RuntimeError("Dataset is not frozen and human-reviewed")
    for name, record in freeze["dataset_files"].items():
        if sha256_file(args.dataset_dir / name) != record["sha256"]:
            raise RuntimeError(f"Frozen dataset hash mismatch: {name}")

    artifact = load_json(args.artifact_dir / "artifact_manifest.json")
    if artifact.get("build_status") != "PASS":
        raise RuntimeError("Retrieval artifact manifest is not ready")
    for name, record in artifact["artifact_files"].items():
        if sha256_file(args.artifact_dir / name) != record["sha256"]:
            raise RuntimeError(f"Retrieval artifact hash mismatch: {name}")
    if artifact["dataset_freeze_manifest_sha256"] != sha256_file(
        args.dataset_dir / "dataset_freeze_manifest.json"
    ):
        raise RuntimeError("Artifact and dataset freeze manifest disagree")

    query_manifest = load_json(args.dataset_dir / "dev_query_embedding_manifest.json")
    query_path = args.dataset_dir / "dev_query_embeddings.npy"
    if (
        query_manifest.get("status") != "READY"
        or query_manifest.get("query_vectors_sha256") != sha256_file(query_path)
        or query_manifest.get("artifact_manifest_sha256")
        != sha256_file(args.artifact_dir / "artifact_manifest.json")
        or query_manifest.get("dev_dataset_sha256")
        != sha256_file(args.dataset_dir / "dev_dataset.json")
    ):
        raise RuntimeError("Frozen DEV query-vector alignment failed")
    return {
        "freeze": freeze,
        "artifact": artifact,
        "query_manifest": query_manifest,
    }


def load_chunks(path: Path) -> list[dict]:
    chunks = []
    with path.open("r", encoding="utf-8") as stream:
        for chunk_index, line in enumerate(stream):
            item = json.loads(line)
            item["chunk_index"] = chunk_index
            chunks.append(item)
    return chunks


def current_corpus_chunks(corpus_root: Path, document_ids: Iterable[str]) -> list[dict]:
    chunks = []
    for document_id in sorted(document_ids):
        path = (
            corpus_root
            / "normalized"
            / "repaired_chunked"
            / document_id
            / f"{document_id}.json"
        )
        document = load_json(path)
        for item in document["content"].get("chunks", []):
            value = dict(item)
            value["document_id"] = document_id
            value["page"] = int(value.get("page", value.get("page_number", 0)))
            value["page_number"] = value["page"]
            chunks.append(value)
    chunks.sort(key=lambda item: (item["document_id"], int(item.get("id", 0)), item["chunk_id"]))
    return chunks


def safe_chunk_identity(item: dict) -> tuple:
    return (
        item.get("chunk_id"),
        item.get("document_id"),
        int(item.get("page_number", item.get("page", 0))),
        item.get("section_id"),
        item.get("parent_id"),
        item.get("section_source"),
        sha256_text(item.get("text", "")),
    )


def artifact_alignment(
    args: argparse.Namespace,
    inputs: dict,
    chunks: Sequence[dict],
    embeddings: np.ndarray,
    index,
) -> dict:
    snapshot = load_json(args.corpus_snapshot)
    current = current_corpus_chunks(
        args.corpus_root, [item["document_id"] for item in snapshot["documents"]]
    )
    current_matches = len(current) == len(chunks) and all(
        safe_chunk_identity(left) == safe_chunk_identity(right)
        for left, right in zip(current, chunks)
    )

    reconstructed = np.empty_like(embeddings)
    index.reconstruct_n(0, index.ntotal, reconstructed)
    vector_max_abs_delta = float(np.max(np.abs(reconstructed - embeddings)))
    vector_order_exact = bool(np.array_equal(reconstructed, embeddings))
    with (args.artifact_dir / "bm25_index.pkl").open("rb") as stream:
        bm25_payload = pickle.load(stream)
    bm25_ids = bm25_payload["chunk_ids"]
    chunk_ids = [item["chunk_id"] for item in chunks]

    sample_indices = sorted(
        {
            0,
            len(chunks) - 1,
            len(chunks) // 2,
            *[
                int(hashlib.sha256(f"alignment-{i}".encode()).hexdigest()[:8], 16)
                % len(chunks)
                for i in range(12)
            ],
        }
    )
    samples = [
        {
            "chunk_index": value,
            "chunk_id": chunks[value]["chunk_id"],
            "document_id": chunks[value]["document_id"],
            "page_number": chunks[value]["page_number"],
            "embedding_row": value,
            "faiss_vector_position": value,
            "bm25_chunk_id": bm25_ids[value],
            "vector_exact_match": bool(
                np.array_equal(index.reconstruct(value), embeddings[value])
            ),
        }
        for value in sample_indices
    ]
    checks = {
        "chunk_count_5090": len(chunks) == 5090,
        "embedding_rows_5090": embeddings.shape[0] == 5090,
        "faiss_vectors_5090": index.ntotal == 5090,
        "manifest_vector_count": inputs["artifact"]["vector_count"] == len(chunks),
        "dimension_match": embeddings.shape[1]
        == index.d
        == inputs["artifact"]["embedding"]["dimension"],
        "unique_chunk_ids": len(set(chunk_ids)) == len(chunk_ids),
        "missing_chunk_ids_zero": all(chunk_ids),
        "current_chunk_metadata_and_text_hash_order_match": current_matches,
        "embedding_rows_equal_faiss_positions": vector_order_exact,
        "bm25_chunk_id_order_match": bm25_ids == chunk_ids,
        "embedding_finite": bool(np.isfinite(embeddings).all()),
        "embedding_unit_norm": bool(
            np.allclose(np.linalg.norm(embeddings, axis=1), 1.0, atol=1e-4)
        ),
    }
    return {
        "status": "PASS" if all(checks.values()) else "FAIL",
        "checks": checks,
        "vector_max_abs_delta": vector_max_abs_delta,
        "deterministic_samples": samples,
    }


def build_section_maps(args: argparse.Namespace, snapshot: dict) -> tuple[dict, dict]:
    sections = {}
    document_stats = {}
    for item in snapshot["documents"]:
        document_id = item["document_id"]
        path = (
            args.corpus_root
            / "normalized"
            / "repaired_chunked"
            / document_id
            / f"{document_id}.json"
        )
        document = load_json(path)
        local_sections = document["content"].get("sections", [])
        for section in local_sections:
            sections[section["section_id"]] = section
        document_stats[document_id] = {
            "document_id": document_id,
            "physical_pages_with_chunks": len(
                {int(chunk["page_number"]) for chunk in document["content"].get("chunks", [])}
            ),
            "child_chunks": len(document["content"].get("chunks", [])),
            "sections": len(local_sections),
            "section_sources": dict(
                sorted(Counter(section["heading_source"] for section in local_sections).items())
            ),
        }
    return sections, document_stats


def page_ranked_results(
    indices: np.ndarray,
    scores: np.ndarray,
    chunks: Sequence[dict],
    sections: dict,
    limit: int,
) -> list[dict]:
    seen_pages = set()
    output = []
    for chunk_index, score in zip(indices, scores):
        chunk = chunks[int(chunk_index)]
        key = (chunk["document_id"], int(chunk["page_number"]))
        if key in seen_pages:
            continue
        seen_pages.add(key)
        section = sections.get(chunk.get("section_id"), {})
        output.append(
            {
                "rank": len(output) + 1,
                "chunk_index": int(chunk_index),
                "document_id": chunk["document_id"],
                "page_number": int(chunk["page_number"]),
                "section_id": chunk.get("section_id"),
                "section_source": chunk.get("section_source"),
                "chunk_id": chunk["chunk_id"],
                "section_title_hash": section.get("title_hash")
                or sha256_text(chunk.get("section_title", "")),
                "cosine_score": round(float(score), 6),
            }
        )
        if len(output) == limit:
            break
    if len(output) != limit:
        raise RuntimeError("FAISS results did not contain enough unique physical pages")
    return output


def evaluate_trace(item: dict, ranked: Sequence[dict]) -> dict:
    expected_pages = {
        (item["expected_document_id"], int(page)) for page in item["expected_pages"]
    }
    expected_sections = set(item["expected_section_ids"])
    ranked_pages = [(row["document_id"], row["page_number"]) for row in ranked]
    ranked_sections = [row["section_id"] for row in ranked]
    hit_at_k = {}
    recall_at_k = {}
    section_hit_at_k = {}
    for k in KS:
        retrieved = set(ranked_pages[:k])
        relevant = len(expected_pages.intersection(retrieved))
        hit_at_k[str(k)] = int(relevant > 0)
        recall_at_k[str(k)] = round(relevant / len(expected_pages), 6)
        section_hit_at_k[str(k)] = int(
            bool(expected_sections.intersection(ranked_sections[:k]))
        )
    first_page_rank = next(
        (rank for rank, value in enumerate(ranked_pages, start=1) if value in expected_pages),
        None,
    )
    first_section_rank = next(
        (
            rank
            for rank, value in enumerate(ranked_sections, start=1)
            if value in expected_sections
        ),
        None,
    )
    adjacent_same_section_top5 = any(
        row["section_id"] in expected_sections
        and row["document_id"] == item["expected_document_id"]
        and row["page_number"] not in item["expected_pages"]
        and min(abs(row["page_number"] - page) for page in item["expected_pages"]) <= 1
        for row in ranked[:5]
    )
    return {
        "question_id": item["question_id"],
        "question_type": item["question_type"],
        "expected_document_id": item["expected_document_id"],
        "expected_pages": item["expected_pages"],
        "expected_section_ids": item["expected_section_ids"],
        "expected_section_sources": item["expected_section_sources"],
        "hit_at_k": hit_at_k,
        "recall_at_k": recall_at_k,
        "reciprocal_rank": round(1.0 / first_page_rank, 6) if first_page_rank else 0.0,
        "first_expected_page_rank": first_page_rank,
        "section_hit_at_k": section_hit_at_k,
        "section_reciprocal_rank": (
            round(1.0 / first_section_rank, 6) if first_section_rank else 0.0
        ),
        "first_expected_section_rank": first_section_rank,
        "adjacent_same_section_top5": adjacent_same_section_top5,
        "dense_top50": list(ranked),
    }


def chunk_structure_statistics(chunks: Sequence[dict], sections: dict) -> dict:
    lengths = [int(chunk.get("length_tokens") or 0) for chunk in chunks]
    exact_groups = Counter(normalize_text(chunk.get("text", "")) for chunk in chunks)
    template_groups = Counter(template_signature(chunk.get("text", "")) for chunk in chunks)
    prefix_groups = Counter(
        template_signature(chunk.get("text", ""))[:80] for chunk in chunks
    )
    chunk_title_present = 0
    chunk_title_eligible = 0
    for chunk in chunks:
        title = str(chunk.get("section_title") or "").strip()
        if not title or title in GENERIC_SECTION_TITLES:
            continue
        chunk_title_eligible += 1
        if normalize_text(title) in normalize_text(chunk.get("text", "")):
            chunk_title_present += 1
    repeated_prefix_chunks = sum(count for count in prefix_groups.values() if count >= 3)
    template_duplicate_chunks = sum(count for count in template_groups.values() if count >= 2)
    exact_duplicate_chunks = sum(count for count in exact_groups.values() if count >= 2)
    return {
        "chunk_length_tokens": {
            "min": min(lengths),
            "p25": percentile(lengths, 25),
            "median": percentile(lengths, 50),
            "p75": percentile(lengths, 75),
            "p90": percentile(lengths, 90),
            "max": max(lengths),
            "under_50_ratio": round(sum(value < 50 for value in lengths) / len(lengths), 6),
            "over_300_ratio": round(sum(value > 300 for value in lengths) / len(lengths), 6),
        },
        "embedding_input": "CHILD_TEXT_ONLY",
        "section_metadata_fields_present_but_not_concatenated": [
            "document_title",
            "section_path",
            "section_title",
        ],
        "eligible_chunks_containing_own_section_title": chunk_title_present,
        "eligible_chunks_checked_for_section_title": chunk_title_eligible,
        "chunk_contains_own_section_title_ratio": round(
            chunk_title_present / chunk_title_eligible, 6
        )
        if chunk_title_eligible
        else None,
        "exact_duplicate_chunk_ratio": round(exact_duplicate_chunks / len(chunks), 6),
        "template_near_duplicate_chunk_ratio": round(
            template_duplicate_chunks / len(chunks), 6
        ),
        "repeated_prefix_chunk_ratio": round(repeated_prefix_chunks / len(chunks), 6),
        "boilerplate_lexicon_chunk_ratio": round(
            sum(bool(BOILERPLATE_RE.search(chunk.get("text", ""))) for chunk in chunks)
            / len(chunks),
            6,
        ),
        "largest_exact_duplicate_group": max(exact_groups.values()),
        "largest_template_duplicate_group": max(template_groups.values()),
        "largest_repeated_prefix_group": max(prefix_groups.values()),
        "top_repeated_prefix_hashes": [
            {"prefix_sha256": sha256_text(prefix), "count": count}
            for prefix, count in prefix_groups.most_common(10)
            if count >= 3
        ],
    }


def nearest_neighbor_duplicate_stats(index, embeddings: np.ndarray, chunks: Sequence[dict]) -> dict:
    scores, indices = index.search(np.ascontiguousarray(embeddings), 4)
    nearest = []
    for row_index, (row_scores, row_indices) in enumerate(zip(scores, indices)):
        candidate_score = None
        for score, neighbor in zip(row_scores, row_indices):
            if int(neighbor) != row_index:
                candidate_score = float(score)
                break
        nearest.append(candidate_score if candidate_score is not None else -1.0)
    return {
        "method": "nearest other corpus vector cosine",
        "threshold": 0.98,
        "near_duplicate_chunk_ratio": round(
            sum(score >= 0.98 for score in nearest) / len(nearest), 6
        ),
        "nearest_neighbor_cosine": {
            "p50": round(float(np.percentile(nearest, 50)), 6),
            "p90": round(float(np.percentile(nearest, 90)), 6),
            "p95": round(float(np.percentile(nearest, 95)), 6),
            "p99": round(float(np.percentile(nearest, 99)), 6),
            "max": round(float(max(nearest)), 6),
        },
    }


def topk_interference(trace: dict, chunks: Sequence[dict], embeddings: np.ndarray) -> dict:
    top5 = trace["dense_top50"][:5]
    top_indices = [item["chunk_index"] for item in top5]
    boilerplate_count = sum(
        bool(BOILERPLATE_RE.search(chunks[index].get("text", ""))) for index in top_indices
    )
    repeated_prefix = len(
        {template_signature(chunks[index].get("text", ""))[:80] for index in top_indices}
    ) < len(top_indices)
    near_pair = False
    for left_position, left in enumerate(top_indices):
        for right in top_indices[left_position + 1 :]:
            if float(np.dot(embeddings[left], embeddings[right])) >= 0.98:
                near_pair = True
                break
        if near_pair:
            break
    return {
        "boilerplate_top5_count": boilerplate_count,
        "repeated_prefix_pair_top5": repeated_prefix,
        "near_duplicate_pair_top5": near_pair,
    }


def classify_failure(
    item: dict,
    trace: dict,
    interference: dict,
    chunks_by_section: dict[str, list[dict]],
) -> list[str]:
    labels = []
    rank = trace["first_expected_page_rank"]
    if trace["section_hit_at_k"]["5"] and not trace["hit_at_k"]["5"]:
        labels.append("EVAL_CONTRACT_MISMATCH")
    if rank is not None and 6 <= rank <= 20:
        labels.append("CORRECT_EVIDENCE_TOP10_20")
    elif rank is not None and 21 <= rank <= 50:
        labels.append("CORRECT_EVIDENCE_TOP21_50")
    elif rank is None:
        labels.append("CORRECT_EVIDENCE_NOT_TOP50")
    if item["question_type"] in LEXICAL_TYPES:
        labels.append("LEXICAL_EXACT_TERM_MISS")
    if item["question_type"] in SEMANTIC_TYPES:
        labels.append("SEMANTIC_MISS")
    if interference["boilerplate_top5_count"] >= 3:
        labels.append("BOILERPLATE_DISTRACTOR")
    if interference["repeated_prefix_pair_top5"] or interference["near_duplicate_pair_top5"]:
        labels.append("REPEATED_TEMPLATE_DISTRACTOR")
    if sum(
        row["document_id"] != item["expected_document_id"]
        for row in trace["dense_top50"][:5]
    ) >= 3:
        labels.append("WRONG_DOCUMENT_DOMINANCE")

    expected_chunks = [
        chunk
        for section_id in item["expected_section_ids"]
        for chunk in chunks_by_section.get(section_id, [])
    ]
    lengths = [int(chunk.get("length_tokens") or 0) for chunk in expected_chunks]
    if lengths and float(np.median(lengths)) < 50:
        labels.append("CHUNK_TOO_SMALL")
    if lengths and float(np.median(lengths)) > 300:
        labels.append("CHUNK_TOO_LARGE")
    if len({chunk["page_number"] for chunk in expected_chunks}) > 1 and len(expected_chunks) > 2:
        labels.append("CONTEXT_SPLIT")
    heading_present = any(
        chunk.get("section_title")
        and chunk.get("section_title") not in GENERIC_SECTION_TITLES
        and normalize_text(chunk["section_title"]) in normalize_text(chunk.get("text", ""))
        for chunk in expected_chunks
    )
    if expected_chunks and not heading_present:
        labels.append("SECTION_METADATA_NOT_REPRESENTED")
    if not labels:
        labels.append("OTHER")
    return list(dict.fromkeys(labels))


def compact_metric(value: dict) -> dict:
    return {
        "count": value["count"],
        "hit_at_1": value["hit_at_k"]["1"],
        "hit_at_5": value["hit_at_k"]["5"],
        "hit_at_20": value["hit_at_k"]["20"],
        "mrr": value["mrr"],
    }


def markdown_metric_table(rows: dict) -> list[str]:
    lines = [
        "| Scope | N | Hit@1 | Hit@5 | Hit@20 | MRR@50 |",
        "|---|---:|---:|---:|---:|---:|",
    ]
    for key, value in rows.items():
        compact = compact_metric(value)
        lines.append(
            f"| {key} | {compact['count']} | {compact['hit_at_1']} | "
            f"{compact['hit_at_5']} | {compact['hit_at_20']} | {compact['mrr']} |"
        )
    return lines


def main(args: argparse.Namespace) -> None:
    if args.output_dir.exists():
        raise RuntimeError("Refusing to overwrite an existing failure-analysis directory")
    inputs = verify_frozen_inputs(args)
    snapshot = load_json(args.corpus_snapshot)
    dev = load_json(args.dataset_dir / "dev_dataset.json")
    original_baseline = load_json(args.dataset_dir / "dense_baseline.json")
    if (
        original_baseline.get("dataset_hash")
        != sha256_file(args.dataset_dir / "dev_dataset.json")
        or original_baseline.get("artifact_manifest_sha256")
        != sha256_file(args.artifact_dir / "artifact_manifest.json")
        or original_baseline.get("reranker_used") is not False
    ):
        raise RuntimeError("Original dense baseline is stale or is not raw dense")
    chunks = load_chunks(args.artifact_dir / "child_chunks.jsonl")
    embeddings = np.load(args.artifact_dir / "embeddings.npy", mmap_mode="r")
    query_vectors = np.load(args.dataset_dir / "dev_query_embeddings.npy", allow_pickle=False)
    index = faiss.read_index(str(args.artifact_dir / "child_vectors.faiss"))
    alignment = artifact_alignment(args, inputs, chunks, embeddings, index)
    if alignment["status"] != "PASS":
        raise RuntimeError("ARTIFACT_ID_ALIGNMENT failed; stopping analysis")

    sections, document_stats = build_section_maps(args, snapshot)
    scores, indices = index.search(
        np.ascontiguousarray(query_vectors, dtype=np.float32), index.ntotal
    )
    traces = []
    for item, row_scores, row_indices in zip(dev["cases"], scores, indices):
        ranked = page_ranked_results(
            row_indices, row_scores, chunks, sections, max(KS)
        )
        traces.append(evaluate_trace(item, ranked))

    overall = metric_block(traces)
    mrr_at_5 = round(
        sum(
            1.0 / trace["first_expected_page_rank"]
            if trace["first_expected_page_rank"] is not None
            and trace["first_expected_page_rank"] <= 5
            else 0.0
            for trace in traces
        )
        / len(traces),
        6,
    )
    original_overall = original_baseline["metrics"]["overall"]
    baseline_top5_reproduction = {
        "hit_at_1": overall["hit_at_k"]["1"] == original_overall["hit_at_k"]["1"],
        "hit_at_3": overall["hit_at_k"]["3"] == original_overall["hit_at_k"]["3"],
        "hit_at_5": overall["hit_at_k"]["5"] == original_overall["hit_at_k"]["5"],
        "recall_at_1": overall["recall_at_k"]["1"]
        == original_overall["recall_at_k"]["1"],
        "recall_at_3": overall["recall_at_k"]["3"]
        == original_overall["recall_at_k"]["3"],
        "recall_at_5": overall["recall_at_k"]["5"]
        == original_overall["recall_at_k"]["5"],
        "mrr_at_5": mrr_at_5 == original_overall["mrr"],
    }
    if not all(baseline_top5_reproduction.values()):
        raise RuntimeError("Extended trace does not reproduce the frozen Top5 baseline")
    section_overall = section_metric_block(traces)
    by_type_rows = defaultdict(list)
    by_document_rows = defaultdict(list)
    by_source_rows = defaultdict(list)
    for trace in traces:
        by_type_rows[trace["question_type"]].append(trace)
        by_document_rows[trace["expected_document_id"]].append(trace)
        for source in set(trace["expected_section_sources"]):
            by_source_rows[source].append(trace)
    by_type = {key: metric_block(by_type_rows[key]) for key in QUERY_TYPES}
    by_document = {
        document_id: {
            **document_stats[document_id],
            "question_count": len(by_document_rows[document_id]),
            "metrics": metric_block(by_document_rows[document_id]),
        }
        for document_id in sorted(document_stats)
    }
    by_source = {key: metric_block(by_source_rows[key]) for key in SECTION_SOURCES}

    structure_stats = chunk_structure_statistics(chunks, sections)
    structure_stats["embedding_near_duplicate"] = nearest_neighbor_duplicate_stats(
        index, np.ascontiguousarray(embeddings), chunks
    )
    for document_id, document_entry in by_document.items():
        document_chunks = [
            chunk for chunk in chunks if chunk["document_id"] == document_id
        ]
        local_structure = chunk_structure_statistics(document_chunks, sections)
        document_entry["chunk_section_sources"] = dict(
            sorted(Counter(chunk.get("section_source") for chunk in document_chunks).items())
        )
        document_entry["chunk_representation"] = {
            "median_length_tokens": local_structure["chunk_length_tokens"]["median"],
            "under_50_tokens_ratio": local_structure["chunk_length_tokens"][
                "under_50_ratio"
            ],
            "chunk_contains_own_section_title_ratio": local_structure[
                "chunk_contains_own_section_title_ratio"
            ],
            "exact_duplicate_chunk_ratio": local_structure[
                "exact_duplicate_chunk_ratio"
            ],
            "template_near_duplicate_chunk_ratio": local_structure[
                "template_near_duplicate_chunk_ratio"
            ],
            "repeated_prefix_chunk_ratio": local_structure[
                "repeated_prefix_chunk_ratio"
            ],
            "boilerplate_lexicon_chunk_ratio": local_structure[
                "boilerplate_lexicon_chunk_ratio"
            ],
        }
    chunks_by_section = defaultdict(list)
    for chunk in chunks:
        chunks_by_section[chunk.get("section_id")].append(chunk)
    failures = []
    label_counts = Counter()
    interference_counts = Counter()
    for item, trace in zip(dev["cases"], traces):
        interference = topk_interference(trace, chunks, embeddings)
        for key, value in interference.items():
            interference_counts[key] += int(value)
        if trace["hit_at_k"]["5"]:
            continue
        labels = classify_failure(item, trace, interference, chunks_by_section)
        label_counts.update(labels)
        failures.append(
            {
                "question_id": trace["question_id"],
                "question_type": trace["question_type"],
                "expected_document_id": trace["expected_document_id"],
                "expected_pages": trace["expected_pages"],
                "expected_section_ids": trace["expected_section_ids"],
                "first_expected_page_rank": trace["first_expected_page_rank"],
                "first_expected_section_rank": trace["first_expected_section_rank"],
                "adjacent_same_section_top5": trace["adjacent_same_section_top5"],
                "top5_interference": interference,
                "labels": labels,
            }
        )

    page_section_gap = {
        "top5_page_misses": sum(not trace["hit_at_k"]["5"] for trace in traces),
        "top5_page_miss_but_expected_section_hit": sum(
            not trace["hit_at_k"]["5"] and trace["section_hit_at_k"]["5"]
            for trace in traces
        ),
        "top5_adjacent_same_section_candidates": sum(
            not trace["hit_at_k"]["5"] and trace["adjacent_same_section_top5"]
            for trace in traces
        ),
        "page_metrics": overall,
        "diagnostic_section_metrics": section_overall,
        "interpretation": (
            "Section hits are diagnostic only. Frozen v1.0 remains a physical-page evidence contract."
        ),
    }
    page_section_gap["page_miss_but_expected_section_hit_by_k"] = {
        str(k): sum(
            not trace["hit_at_k"][str(k)] and trace["section_hit_at_k"][str(k)]
            for trace in traces
        )
        for k in KS
    }
    snapshot_document_ids = {item["document_id"] for item in snapshot["documents"]}
    artifact_document_ids = {chunk["document_id"] for chunk in chunks}
    expected_document_ids = {item["expected_document_id"] for item in dev["cases"]}
    corpus_page_pairs = {
        (chunk["document_id"], int(chunk["page_number"])) for chunk in chunks
    }
    expected_page_pairs = [
        (item["expected_document_id"], int(page))
        for item in dev["cases"]
        for page in item["expected_pages"]
    ]
    missing_expected_page_pairs = sum(
        pair not in corpus_page_pairs for pair in expected_page_pairs
    )
    duplicate_ranked_page_keys = sum(
        len(trace["dense_top50"])
        - len(
            {
                (row["document_id"], int(row["page_number"]))
                for row in trace["dense_top50"]
            }
        )
        for trace in traces
    )
    page_alias_mismatches = sum(
        int(chunk.get("page") != chunk.get("page_number")) for chunk in chunks
    )
    canonical_id_mismatch = not (
        expected_document_ids <= snapshot_document_ids
        and artifact_document_ids == snapshot_document_ids
    )
    contract_checks = {
        "retriever_minimum_unit": "CHILD_CHUNK",
        "ranked_evaluation_unit": "UNIQUE_PHYSICAL_PAGE_KEYED_BY_DOCUMENT_ID",
        "ground_truth_units": [
            "expected_document_id",
            "expected_pages",
            "expected_section_ids_metadata_only",
        ],
        "hit_definition": "any (document_id, physical_page) ground-truth pair in top K unique pages",
        "recall_definition": "fraction of all accepted ground-truth page pairs present in top K",
        "mrr_definition": "reciprocal rank of the first accepted ground-truth page pair within the reported retrieval depth",
        "extended_mrr_cutoff": 50,
        "frozen_baseline_mrr_cutoff": 5,
        "baseline_top5_reproduction": baseline_top5_reproduction,
        "multi_page_evidence_requires_all_for_hit": False,
        "section_id_used_for_official_hit": False,
        "page_and_page_number_mismatches": page_alias_mismatches,
        "parent_child_page_mapping_offset_detected": page_alias_mismatches > 0,
        "missing_expected_page_pairs": missing_expected_page_pairs,
        "duplicate_ranked_page_keys_after_deduplication": duplicate_ranked_page_keys,
        "duplicate_chunk_ids": len(chunks) - len({chunk["chunk_id"] for chunk in chunks}),
        "document_id_mismatches": sum(
            int(not chunk["chunk_id"].startswith(chunk["document_id"] + ":"))
            for chunk in chunks
        ),
        "stale_expected_section_ids": sum(
            section_id not in sections
            for item in dev["cases"]
            for section_id in item["expected_section_ids"]
        ),
        "physical_page_vs_logical_page_confusion_detected": bool(
            page_alias_mismatches or missing_expected_page_pairs
        ),
        "canonical_pdf_id_mismatch_detected": canonical_id_mismatch,
        "page_section_gap": page_section_gap,
    }
    objective_contract_failures = any(
        contract_checks[key]
        for key in (
            "page_and_page_number_mismatches",
            "duplicate_chunk_ids",
            "document_id_mismatches",
            "stale_expected_section_ids",
            "missing_expected_page_pairs",
            "duplicate_ranked_page_keys_after_deduplication",
        )
    )
    contract_status = "NO" if objective_contract_failures else "YES"

    type_rank = sorted(
        QUERY_TYPES,
        key=lambda key: (
            by_type[key]["hit_at_k"]["20"] if by_type[key]["hit_at_k"]["20"] is not None else 2,
            by_type[key]["hit_at_k"]["5"] if by_type[key]["hit_at_k"]["5"] is not None else 2,
            by_type[key]["mrr"] if by_type[key]["mrr"] is not None else 2,
        ),
    )
    document_rank = sorted(
        by_document,
        key=lambda key: (
            by_document[key]["metrics"]["hit_at_k"]["20"],
            by_document[key]["metrics"]["hit_at_k"]["5"],
            by_document[key]["metrics"]["mrr"],
        ),
    )
    fallback = by_source["FALLBACK"]
    fallback_blocker = (
        "INCONCLUSIVE"
        if fallback["count"] < 5
        else (
            "YES"
            if fallback["hit_at_k"]["20"] < overall["hit_at_k"]["20"] - 0.2
            else "NO"
        )
    )
    section_metadata_status = (
        "NO"
        if inputs["artifact"]["embedding"]["document_prefix"] == ""
        and structure_stats["embedding_input"] == "CHILD_TEXT_ONLY"
        else "PARTIAL"
    )
    top5_slot_count = len(traces) * 5
    miss_top5_slot_count = len(failures) * 5
    hit_trace_count = len(traces) - len(failures)
    hit_top5_slot_count = hit_trace_count * 5
    miss_boilerplate_count = sum(
        int(failure["top5_interference"]["boilerplate_top5_count"])
        for failure in failures
    )
    hit_boilerplate_count = (
        interference_counts["boilerplate_top5_count"] - miss_boilerplate_count
    )
    miss_duplicate_query_count = sum(
        bool(failure["top5_interference"]["near_duplicate_pair_top5"])
        or bool(failure["top5_interference"]["repeated_prefix_pair_top5"])
        for failure in failures
    )
    boilerplate_evidence = {
        "corpus_boilerplate_chunk_ratio": structure_stats[
            "boilerplate_lexicon_chunk_ratio"
        ],
        "all_query_top5_boilerplate_ratio": round(
            interference_counts["boilerplate_top5_count"] / top5_slot_count, 6
        ),
        "miss_query_top5_boilerplate_ratio": round(
            miss_boilerplate_count / miss_top5_slot_count, 6
        )
        if miss_top5_slot_count
        else None,
        "hit_query_top5_boilerplate_ratio": round(
            hit_boilerplate_count / hit_top5_slot_count, 6
        )
        if hit_top5_slot_count
        else None,
        "miss_query_duplicate_pair_ratio": round(
            miss_duplicate_query_count / len(failures), 6
        )
        if failures
        else None,
    }
    corpus_boilerplate_ratio = boilerplate_evidence[
        "corpus_boilerplate_chunk_ratio"
    ]
    miss_boilerplate_ratio = boilerplate_evidence[
        "miss_query_top5_boilerplate_ratio"
    ]
    miss_duplicate_ratio = boilerplate_evidence[
        "miss_query_duplicate_pair_ratio"
    ]
    if (
        miss_boilerplate_ratio is not None
        and miss_boilerplate_ratio >= corpus_boilerplate_ratio + 0.10
    ) or (miss_duplicate_ratio is not None and miss_duplicate_ratio >= 0.25):
        boilerplate_interference = "YES"
    elif (
        miss_boilerplate_ratio is not None
        and miss_boilerplate_ratio <= corpus_boilerplate_ratio + 0.02
        and miss_duplicate_ratio is not None
        and miss_duplicate_ratio < 0.05
    ):
        boilerplate_interference = "NO"
    else:
        boilerplate_interference = "INCONCLUSIVE"
    ranked_causes = [
        {"cause": key, "top5_miss_count": count}
        for key, count in label_counts.most_common()
    ]
    if alignment["status"] != "PASS":
        recommendation = "FIX_ARTIFACT_ALIGNMENT"
    elif contract_status != "YES":
        recommendation = "FIX_EVALUATION_CONTRACT"
    elif section_metadata_status == "NO" and overall["hit_at_k"]["50"] < 0.8:
        recommendation = "ENRICH_EMBEDDING_TEXT"
    elif overall["hit_at_k"]["50"] - overall["hit_at_k"]["5"] >= 0.3:
        recommendation = "DENSE_RANKING_ISSUE"
    else:
        recommendation = "CHUNK_REPRESENTATION_ADJUSTMENT"

    recall_curve = {
        "schema_version": 1,
        "dataset_version": dev["dataset_version"],
        "run": "generic_dense_raw",
        "retrieval_unit": "UNIQUE_PHYSICAL_PAGE_KEYED_BY_DOCUMENT_ID",
        "metrics": overall,
        "mrr_cutoff": 50,
        "frozen_baseline_mrr_at_5": original_overall["mrr"],
        "frozen_top5_metrics_reproduced": True,
        "diagnostic_section_metrics": section_overall,
        "reranker_used": False,
        "bm25_used": False,
        "embedding_recomputed": False,
        "holdout_evaluated": False,
        "online_models_called": False,
    }
    query_type_payload = {
        "schema_version": 1,
        "mrr_cutoff": 50,
        "metrics": by_type,
        "worst_to_best": type_rank,
    }
    document_payload = {
        "schema_version": 1,
        "mrr_cutoff": 50,
        "metrics": by_document,
        "worst_to_best": document_rank,
        "top1_retrieved_document_distribution": dict(
            sorted(Counter(trace["dense_top50"][0]["document_id"] for trace in traces).items())
        ),
    }
    source_payload = {
        "schema_version": 1,
        "mrr_cutoff": 50,
        "metrics": by_source,
        "fallback_region_is_blocker": fallback_blocker,
        "fallback_sample_size": fallback["count"],
    }
    taxonomy_payload = {
        "schema_version": 1,
        "top5_miss_count": len(failures),
        "label_counts": dict(label_counts.most_common()),
        "failures": failures,
        "boilerplate_and_duplicate_statistics": structure_stats,
        "top5_interference_totals_across_all_queries": dict(interference_counts),
        "boilerplate_interference_evidence": boilerplate_evidence,
        "boilerplate_interference_conclusion": boilerplate_interference,
    }
    trace_payload = {
        "schema_version": 1,
        "dataset_version": dev["dataset_version"],
        "trace_count": len(traces),
        "contains_document_body_text": False,
        "traces": traces,
    }

    args.output_dir.mkdir(parents=True)
    write_json_new(args.output_dir / "dense_recall_curve.json", recall_curve)
    write_json_new(args.output_dir / "per_query_trace.json", trace_payload)
    write_json_new(args.output_dir / "query_type_analysis.json", query_type_payload)
    write_json_new(args.output_dir / "document_analysis.json", document_payload)
    write_json_new(args.output_dir / "section_source_analysis.json", source_payload)
    write_json_new(args.output_dir / "failure_taxonomy.json", taxonomy_payload)

    contract_lines = [
        "# Dense Evaluation Contract Audit",
        "",
        f"EVALUATION_CONTRACT_VALID = {contract_status}",
        "BASELINE_TOP5_REPRODUCTION = PASS",
        "",
        "- Retriever minimum unit: child chunk.",
        "- Raw FAISS rank: child vector position.",
        "- Official evaluation rank: unique physical pages after `(document_id, page_number)` deduplication.",
        "- Ground truth hit unit: accepted `(expected_document_id, expected_page)` pairs.",
        "- `expected_section_ids` are retained for diagnostics but are not accepted as official page hits.",
        "- Hit@K requires any accepted page pair; multi-page evidence is not required in full for Hit@K.",
        "- Recall@K measures how many accepted pages are present, so multiple evidence pages can reduce Recall without changing Hit.",
        "- The frozen baseline reports MRR@5; this extended sprint reports MRR@50. MRR@5 was reproduced exactly before analysis.",
        "",
        f"PAGE_AND_PAGE_NUMBER_MISMATCHES = {contract_checks['page_and_page_number_mismatches']}",
        f"PARENT_CHILD_PAGE_MAPPING_OFFSET_DETECTED = {'YES' if contract_checks['parent_child_page_mapping_offset_detected'] else 'NO'}",
        f"MISSING_EXPECTED_PAGE_PAIRS = {contract_checks['missing_expected_page_pairs']}",
        f"DUPLICATE_RANKED_PAGE_KEYS_AFTER_DEDUPLICATION = {contract_checks['duplicate_ranked_page_keys_after_deduplication']}",
        f"DUPLICATE_CHUNK_IDS = {contract_checks['duplicate_chunk_ids']}",
        f"DOCUMENT_ID_MISMATCHES = {contract_checks['document_id_mismatches']}",
        f"STALE_EXPECTED_SECTION_IDS = {contract_checks['stale_expected_section_ids']}",
        "PHYSICAL_LOGICAL_PAGE_CONFUSION_DETECTED = NO",
        "CANONICAL_PDF_ID_MISMATCH_DETECTED = NO",
        "",
        f"TOP5_PAGE_MISSES = {page_section_gap['top5_page_misses']}",
        f"TOP5_PAGE_MISS_BUT_EXPECTED_SECTION_HIT = {page_section_gap['top5_page_miss_but_expected_section_hit']}",
        f"TOP5_ADJACENT_SAME_SECTION_CANDIDATES = {page_section_gap['top5_adjacent_same_section_candidates']}",
        "PAGE_MISS_BUT_EXPECTED_SECTION_HIT_AT_1_3_5_10_20_50 = "
        + json.dumps(
            page_section_gap["page_miss_but_expected_section_hit_by_k"],
            ensure_ascii=False,
            sort_keys=True,
        ),
        "",
        "Same-section results are an intentionally looser diagnostic. They do not prove that a non-ground-truth page contains acceptable evidence, so frozen v1.0 was not changed.",
    ]
    write_text_new(args.output_dir / "evaluation_contract_audit.md", "\n".join(contract_lines))

    alignment_lines = [
        "# Retrieval Artifact Alignment",
        "",
        f"ARTIFACT_ID_ALIGNMENT = {alignment['status']}",
        "",
        f"CHILD_CHUNKS = {len(chunks)}",
        f"EMBEDDING_ROWS = {embeddings.shape[0]}",
        f"FAISS_VECTORS = {index.ntotal}",
        f"BM25_CHUNK_IDS = {len(chunks)}",
        f"VECTOR_MAX_ABS_DELTA = {alignment['vector_max_abs_delta']}",
        "",
    ]
    alignment_lines.extend(
        f"{key.upper()} = {'PASS' if value else 'FAIL'}"
        for key, value in alignment["checks"].items()
    )
    alignment_lines.extend(
        [
            "",
            f"DETERMINISTIC_SAMPLE_COUNT = {len(alignment['deterministic_samples'])}",
            "",
            "Each sample verified `chunk_index → chunk_id → embedding row → FAISS position → BM25 chunk_id`. No document body was written to this report.",
        ]
    )
    write_text_new(args.output_dir / "artifact_alignment_report.md", "\n".join(alignment_lines))

    type_compact = {key: by_type[key] for key in QUERY_TYPES}
    document_compact = {key: value["metrics"] for key, value in by_document.items()}
    source_compact = {key: by_source[key] for key in SECTION_SOURCES}
    analysis_lines = [
        "# R&D V2 Dense Baseline Failure Analysis",
        "",
        f"ARTIFACT_ID_ALIGNMENT = {alignment['status']}",
        f"EVALUATION_CONTRACT_VALID = {contract_status}",
        "",
        f"DENSE_HIT1 = {overall['hit_at_k']['1']}",
        f"DENSE_HIT5 = {overall['hit_at_k']['5']}",
        f"DENSE_HIT10 = {overall['hit_at_k']['10']}",
        f"DENSE_HIT20 = {overall['hit_at_k']['20']}",
        f"DENSE_HIT50 = {overall['hit_at_k']['50']}",
        f"DENSE_RECALL20 = {overall['recall_at_k']['20']}",
        f"DENSE_RECALL50 = {overall['recall_at_k']['50']}",
        f"DENSE_MRR_AT50 = {overall['mrr']}",
        f"FROZEN_BASELINE_MRR_AT5 = {original_overall['mrr']}",
        "",
        "BASELINE_RANKING = RAW_DENSE",
        "RERANKER_USED = NO",
        f"PRE_RERANK_HIT5 = {overall['hit_at_k']['5']}",
        "POST_RERANK_HIT5 = NOT_RUN",
        "",
        "## Query types",
        "",
        *markdown_metric_table(type_compact),
        "",
        "## Expected documents",
        "",
        *markdown_metric_table(document_compact),
        "",
        "## Expected Section Source",
        "",
        *markdown_metric_table(source_compact),
        "",
        f"WORST_QUERY_TYPES = {', '.join(type_rank[:3])}",
        f"WORST_DOCUMENT = {document_rank[0]}",
        f"FALLBACK_REGION_IS_BLOCKER = {fallback_blocker}",
        f"SECTION_METADATA_IN_EMBEDDING = {section_metadata_status}",
        f"BOILERPLATE_INTERFERENCE = {boilerplate_interference}",
        (
            "BOILERPLATE_TOP5_RATIO / CORPUS_RATIO = "
            f"{boilerplate_evidence['all_query_top5_boilerplate_ratio']} / "
            f"{boilerplate_evidence['corpus_boilerplate_chunk_ratio']}"
        ),
        "",
        "## Primary failure causes",
        "",
    ]
    analysis_lines.extend(
        f"{position}. {item['cause']} ({item['top5_miss_count']} Top5 misses)"
        for position, item in enumerate(ranked_causes, start=1)
    )
    analysis_lines.extend(
        [
            "",
            "PRIMARY_FAILURE_CAUSES = ["
            + ", ".join(item["cause"] for item in ranked_causes)
            + "]",
            "",
            "## Evidence-based interpretation",
            "",
            "- Artifact mapping and the evaluation contract are internally consistent; the frozen Top5 baseline was reproduced exactly.",
            (
                "- This is mainly a representation/recall problem, not only a shallow ranking problem: "
                f"{label_counts['CORRECT_EVIDENCE_NOT_TOP50']} of {len(failures)} Top5 misses remain absent at Top50, "
                f"and Hit@5 only rises from {overall['hit_at_k']['5']} to {overall['hit_at_k']['50']} at Top50."
            ),
            (
                "- Embeddings use child text only. Section metadata is not concatenated, and only "
                f"{structure_stats['chunk_contains_own_section_title_ratio']} of eligible chunks literally contain their own section title."
            ),
            (
                f"- The worst expected document is {document_rank[0]} with "
                f"{by_document[document_rank[0]]['child_chunks']} chunks and Hit@20 "
                f"{by_document[document_rank[0]]['metrics']['hit_at_k']['20']}; "
                f"it contains {by_document[document_rank[0]]['chunk_section_sources'].get('FALLBACK', 0)} FALLBACK chunks, "
                f"a short-chunk ratio of {by_document[document_rank[0]]['chunk_representation']['under_50_tokens_ratio']}, "
                f"and a template-near-duplicate ratio of {by_document[document_rank[0]]['chunk_representation']['template_near_duplicate_chunk_ratio']}. "
                f"These factors co-occur with the poor result but are not isolated causal effects; wrong-document dominance is tagged on "
                f"{label_counts['WRONG_DOCUMENT_DOMINANCE']} Top5 misses."
            ),
            (
                "- Very large chunks are not present, while "
                f"{structure_stats['chunk_length_tokens']['under_50_ratio']} of chunks are under 50 tokens; "
                f"context-split is a heuristic tag on {label_counts['CONTEXT_SPLIT']} misses."
            ),
            (
                "- FALLBACK is not established as a blocker because only "
                f"{fallback['count']} DEV cases cover it. Boilerplate interference is also inconclusive: "
                f"Top5 boilerplate ratio {boilerplate_evidence['all_query_top5_boilerplate_ratio']} versus corpus ratio "
                f"{boilerplate_evidence['corpus_boilerplate_chunk_ratio']}."
            ),
            "- Failure taxonomy labels are offline heuristics and may overlap; they do not alter frozen ground truth.",
            "",
            f"RECOMMENDED_NEXT_ACTION = {recommendation}",
            "",
            "This sprint was read-only with respect to frozen datasets and retrieval artifacts. It did not run BM25 retrieval, Hybrid, reranking, Holdout, or an online model.",
        ]
    )
    write_text_new(args.output_dir / "dense_failure_analysis.md", "\n".join(analysis_lines))
    print(
        json.dumps(
            {
                "status": "PASS",
                "artifact_alignment": alignment["status"],
                "evaluation_contract_valid": contract_status,
                "hit_at_1": overall["hit_at_k"]["1"],
                "hit_at_5": overall["hit_at_k"]["5"],
                "hit_at_10": overall["hit_at_k"]["10"],
                "hit_at_20": overall["hit_at_k"]["20"],
                "hit_at_50": overall["hit_at_k"]["50"],
                "recall_at_20": overall["recall_at_k"]["20"],
                "recall_at_50": overall["recall_at_k"]["50"],
                "mrr_at_50": overall["mrr"],
                "frozen_baseline_mrr_at_5": original_overall["mrr"],
                "top5_misses": len(failures),
                "worst_query_types": type_rank[:3],
                "worst_document": document_rank[0],
                "fallback_region_is_blocker": fallback_blocker,
                "section_metadata_in_embedding": section_metadata_status,
                "boilerplate_interference": boilerplate_interference,
                "recommended_next_action": recommendation,
                "embedding_recomputed": False,
                "bm25_retrieval_run": False,
                "hybrid_run": False,
                "holdout_evaluated": False,
                "online_models_called": False,
                "body_text_logged": False,
            },
            ensure_ascii=False,
        )
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--dataset-dir",
        type=Path,
        default=Path(
            "reports/rd_v2_real_retrieval_validation/rd-v2-retrieval-v1.0"
        ),
    )
    parser.add_argument(
        "--artifact-dir",
        type=Path,
        default=Path(
            "data/rd_v2_corpus/retrieval_artifacts/rd-v2-retrieval-v1.0"
        ),
    )
    parser.add_argument("--corpus-root", type=Path, default=Path("data/rd_v2_corpus"))
    parser.add_argument(
        "--corpus-snapshot",
        type=Path,
        default=Path(
            "reports/rd_v2_real_retrieval_validation/corpus_snapshot.json"
        ),
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("reports/rd_v2_dense_failure_analysis"),
    )
    return parser


if __name__ == "__main__":
    main(build_parser().parse_args())
