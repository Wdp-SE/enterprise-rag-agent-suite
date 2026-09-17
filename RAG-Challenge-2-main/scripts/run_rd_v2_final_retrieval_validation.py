"""Finalize Dense-only R&D V2 retrieval and run one frozen HOLDOUT evaluation.

Actions are deliberately process-separated:

* ``dev-freeze`` uses existing DEV query vectors and existing FAISS namespaces.
* ``embed-eval-queries`` loads only the frozen local embedding model.
* ``evaluate-once`` loads FAISS, evaluates HOLDOUT exactly once, and evaluates
  the independent structure stress set without mixing it into HOLDOUT metrics.

No action invokes BM25, Hybrid, an online reranker, answer generation, or an
online model. Reports contain IDs/ranks/metrics, never question or body text.
"""

from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import ctypes
from datetime import datetime
import hashlib
import json
import os
from pathlib import Path
import sys
from typing import Iterable, Sequence
from zoneinfo import ZoneInfo

import numpy as np


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


POLICY_VERSION = "rd-v2-retrieval-final-v1.0"
DATASET_VERSION = "rd-v2-retrieval-v1.0"
REPRESENTATIONS = ("SECTION_PATH", "DOCUMENT_SECTION_PATH")
NAMESPACES = {
    "SECTION_PATH": "embedding_repr_section_path",
    "DOCUMENT_SECTION_PATH": "embedding_repr_document_section_path",
}
QUERY_TYPES = (
    "semantic",
    "exact_term",
    "interface",
    "field",
    "numeric",
    "dependency",
    "cross_section",
)
KS = (1, 3, 5, 10, 12, 20)
RERANK_INPUT_K = 12
DENSE_TOP_K = 20
FINAL_TOP_K = 5
QUERY_PREFIX = "为这个句子生成表示以用于检索相关文章："
STRESS_PASS_HIT20_THRESHOLD = 0.50


if os.name == "nt":
    ctypes.windll.kernel32.SetErrorMode(0x0001 | 0x0002 | 0x8000)


def now() -> str:
    return datetime.now(ZoneInfo("Asia/Shanghai")).isoformat(timespec="seconds")


def load_json(path: Path) -> dict:
    with path.open("r", encoding="utf-8") as stream:
        return json.load(stream)


def json_bytes(payload: object) -> bytes:
    return (json.dumps(payload, ensure_ascii=False, indent=2) + "\n").encode("utf-8")


def write_json_new(path: Path, payload: object) -> None:
    if path.exists():
        raise RuntimeError(f"Refusing to overwrite existing output: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    partial = path.with_suffix(path.suffix + ".partial")
    if partial.exists():
        raise RuntimeError(f"Partial output already exists: {partial}")
    partial.write_bytes(json_bytes(payload))
    partial.replace(path)


def write_text_new(path: Path, value: str) -> None:
    if path.exists():
        raise RuntimeError(f"Refusing to overwrite existing output: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    partial = path.with_suffix(path.suffix + ".partial")
    if partial.exists():
        raise RuntimeError(f"Partial output already exists: {partial}")
    partial.write_text(value, encoding="utf-8", newline="\n")
    partial.replace(path)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


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


def verify_dataset(dataset: dict, split: str, count: int) -> None:
    if dataset.get("dataset_version") != DATASET_VERSION:
        raise RuntimeError(f"Unexpected {split} dataset version")
    if dataset.get("dataset_status") != "FROZEN" or not dataset.get("ground_truth_frozen"):
        raise RuntimeError(f"{split} dataset is not frozen")
    if dataset.get("split") != split or len(dataset.get("cases", [])) != count:
        raise RuntimeError(f"Unexpected {split} split/count")


def verify_structure_stress(stress: dict) -> None:
    cases = stress.get("cases", [])
    source_counts = Counter(case.get("expected_section_source") for case in cases)
    if (
        len(cases) != 6
        or len({case.get("question_id") for case in cases}) != 6
        or source_counts != Counter({"FALLBACK": 4, "PDF_HEURISTIC": 2})
        or stress.get("excluded_from_main_holdout_metric") is not True
        or stress.get("excluded_from_hybrid_parameter_selection") is not True
    ):
        raise RuntimeError("Structure stress set contract failed")


def verify_base_inputs(args: argparse.Namespace) -> tuple[list[dict], dict]:
    artifact = load_json(args.baseline_artifact_dir / "artifact_manifest.json")
    chunks = load_chunks(args.baseline_artifact_dir / "child_chunks.jsonl")
    if artifact.get("build_status") != "PASS" or len(chunks) != 5090:
        raise RuntimeError("Frozen base artifacts are not valid")
    if artifact.get("dataset_version") != DATASET_VERSION:
        raise RuntimeError("Artifact/dataset version mismatch")
    child_record = artifact["artifact_files"]["child_chunks.jsonl"]
    if sha256_file(args.baseline_artifact_dir / "child_chunks.jsonl") != child_record["sha256"]:
        raise RuntimeError("Frozen child chunk hash mismatch")
    chunk_ids = [chunk["chunk_id"] for chunk in chunks]
    if len(set(chunk_ids)) != len(chunks) or any(not value for value in chunk_ids):
        raise RuntimeError("Frozen chunk IDs are missing or duplicated")
    return chunks, artifact


def namespace_path(args: argparse.Namespace, representation: str) -> Path:
    return args.enrichment_artifact_root / NAMESPACES[representation]


def verify_namespace(args: argparse.Namespace, representation: str, chunks: Sequence[dict]) -> dict:
    path = namespace_path(args, representation)
    manifest = load_json(path / "artifact_manifest.json")
    if (
        manifest.get("build_status") != "PASS"
        or manifest.get("mode") != representation
        or manifest.get("child_chunk_count") != len(chunks)
        or manifest.get("faiss_count") != len(chunks)
        or manifest.get("ordered_chunk_id_sha256")
        != sequence_digest(chunk["chunk_id"] for chunk in chunks)
    ):
        raise RuntimeError(f"Dense namespace validation failed: {representation}")
    faiss_record = manifest["artifact_files"]["child_vectors.faiss"]
    if sha256_file(path / "child_vectors.faiss") != faiss_record["sha256"]:
        raise RuntimeError(f"Dense FAISS hash mismatch: {representation}")
    return manifest


def safe_chunk_result(chunk: dict, score: float) -> dict:
    return {
        "chunk_index": int(chunk["chunk_index"]),
        "chunk_id": chunk["chunk_id"],
        "document_id": chunk["document_id"],
        "page_number": int(chunk["page_number"]),
        "section_id": chunk.get("section_id"),
        "section_source": chunk.get("section_source"),
        "dense_score": round(float(score), 8),
    }


def dense_chunk_rankings(index, vectors: np.ndarray, chunks: Sequence[dict]) -> list[list[dict]]:
    scores, indices = index.search(
        np.ascontiguousarray(vectors, dtype=np.float32), index.ntotal
    )
    return [
        [
            safe_chunk_result(chunks[int(chunk_index)], float(score))
            for score, chunk_index in zip(row_scores, row_indices)
            if int(chunk_index) >= 0
        ]
        for row_scores, row_indices in zip(scores, indices)
    ]


def page_dedupe(rows: Sequence[dict], limit: int | None = None) -> list[dict]:
    pages = []
    seen = set()
    for row in rows:
        key = (row["document_id"], int(row["page_number"]))
        if key in seen:
            continue
        seen.add(key)
        pages.append(
            {
                "rank": len(pages) + 1,
                "chunk_id": row["chunk_id"],
                "document_id": row["document_id"],
                "page_number": int(row["page_number"]),
                "section_id": row.get("section_id"),
                "section_source": row.get("section_source"),
                "dense_score": row["dense_score"],
            }
        )
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
        "expected_section_sources": case.get("expected_section_sources", []),
        "first_evidence_rank": first_rank,
        "hit_at_k": hit_at_k,
        "recall_at_k": recall_at_k,
        "reciprocal_rank_at_12": round(1 / first_rank, 6)
        if first_rank and first_rank <= 12
        else 0.0,
        "reciprocal_rank_at_20": round(1 / first_rank, 6)
        if first_rank and first_rank <= 20
        else 0.0,
    }


def metric_block(records: Sequence[dict]) -> dict:
    if not records:
        return {
            "count": 0,
            "hit_at_k": {str(k): None for k in KS},
            "recall_at_k": {str(k): None for k in KS},
            "mrr_at_12": None,
            "mrr_at_20": None,
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
        "mrr_at_12": round(
            sum(row["reciprocal_rank_at_12"] for row in records) / len(records), 6
        ),
        "mrr_at_20": round(
            sum(row["reciprocal_rank_at_20"] for row in records) / len(records), 6
        ),
    }


def metrics_with_types(records: Sequence[dict]) -> tuple[dict, dict]:
    grouped: dict[str, list[dict]] = defaultdict(list)
    for record in records:
        grouped[record["question_type"]].append(record)
    return metric_block(records), {
        question_type: metric_block(grouped[question_type]) for question_type in QUERY_TYPES
    }


def candidate_pool_records(
    cases: Sequence[dict], chunk_rankings: Sequence[Sequence[dict]]
) -> list[dict]:
    return [
        evaluate_case(case, page_dedupe(rows[:RERANK_INPUT_K]))
        for case, rows in zip(cases, chunk_rankings)
    ]


def selection_tuple(payload: dict) -> tuple:
    candidate = payload["rerank_candidate_pool"]["overall"]
    full = payload["page_deduped_retrieval"]["overall"]
    types = payload["rerank_candidate_pool"]["by_question_type"]
    critical = sum(
        types[name]["hit_at_k"]["12"] for name in ("field", "exact_term", "dependency")
    ) / 3
    return (
        candidate["hit_at_k"]["12"],
        candidate["recall_at_k"]["12"],
        critical,
        full["hit_at_k"]["5"],
        full["hit_at_k"]["1"],
        candidate["mrr_at_12"],
        types["semantic"]["hit_at_k"]["12"],
    )


def dev_freeze(args: argparse.Namespace) -> None:
    outputs = (
        args.report_dir / "dense_representation_comparison.json",
        args.report_dir / "reranker_validation.json",
        args.report_dir / "final_retrieval_policy.json",
    )
    if any(path.exists() for path in outputs):
        raise RuntimeError("Refusing to overwrite an existing DEV freeze output")
    chunks, base_artifact = verify_base_inputs(args)
    dev = load_json(args.dataset_dir / "dev_dataset.json")
    verify_dataset(dev, "DEV", 40)
    query_path = args.dataset_dir / "dev_query_embeddings.npy"
    query_manifest = load_json(args.dataset_dir / "dev_query_embedding_manifest.json")
    if (
        query_manifest.get("status") != "READY"
        or query_manifest.get("dataset_version") != DATASET_VERSION
        or query_manifest.get("query_vectors_sha256") != sha256_file(query_path)
        or query_manifest.get("count") != 40
    ):
        raise RuntimeError("Frozen DEV query vectors failed validation")
    vectors = np.load(query_path, allow_pickle=False)
    if vectors.shape != (40, base_artifact["embedding"]["dimension"]):
        raise RuntimeError("DEV query vector shape mismatch")
    if "torch" in sys.modules:
        raise RuntimeError("DEV selection process must not load PyTorch")
    import faiss

    results = {}
    namespace_manifests = {}
    for representation in REPRESENTATIONS:
        manifest = verify_namespace(args, representation, chunks)
        namespace_manifests[representation] = manifest
        index = faiss.read_index(
            str(namespace_path(args, representation) / "child_vectors.faiss")
        )
        if index.ntotal != len(chunks) or index.d != vectors.shape[1]:
            raise RuntimeError(f"Dense index shape mismatch: {representation}")
        chunk_rows = dense_chunk_rankings(index, vectors, chunks)
        full_records = [
            evaluate_case(case, page_dedupe(rows))
            for case, rows in zip(dev["cases"], chunk_rows)
        ]
        candidate_records = candidate_pool_records(dev["cases"], chunk_rows)
        full_overall, full_types = metrics_with_types(full_records)
        candidate_overall, candidate_types = metrics_with_types(candidate_records)
        results[representation] = {
            "namespace": NAMESPACES[representation],
            "artifact_manifest_sha256": sha256_file(
                namespace_path(args, representation) / "artifact_manifest.json"
            ),
            "faiss_sha256": manifest["artifact_files"]["child_vectors.faiss"]["sha256"],
            "page_deduped_retrieval": {
                "overall": full_overall,
                "by_question_type": full_types,
            },
            "rerank_candidate_pool": {
                "input_unit": "TOP_12_CHILD_CHUNKS_THEN_PHYSICAL_PAGE_DEDUPE",
                "input_k": RERANK_INPUT_K,
                "overall": candidate_overall,
                "by_question_type": candidate_types,
            },
        }
        results[representation]["selection_tuple"] = list(
            selection_tuple(results[representation])
        )

    selected = max(
        REPRESENTATIONS,
        key=lambda name: (selection_tuple(results[name]), -REPRESENTATIONS.index(name)),
    )
    comparison = {
        "schema_version": 1,
        "policy_version": POLICY_VERSION,
        "dataset_version": DATASET_VERSION,
        "split": "DEV",
        "representations_compared": list(REPRESENTATIONS),
        "new_representation_generated": False,
        "rerank_input_k": RERANK_INPUT_K,
        "selection_priority": [
            "candidate_pool_hit_at_12",
            "candidate_pool_recall_at_12",
            "mean_field_exact_term_dependency_candidate_hit_at_12",
            "page_deduped_hit_at_5",
            "page_deduped_hit_at_1",
            "candidate_pool_mrr_at_12",
            "semantic_candidate_hit_at_12",
        ],
        "results": results,
        "final_dense_representation": selected,
        "selection_frozen_before_holdout": True,
        "bm25_used": False,
        "hybrid_used": False,
        "holdout_evaluated": False,
        "body_text_logged": False,
    }

    selected_candidate = results[selected]["rerank_candidate_pool"]
    reranker_validation = {
        "schema_version": 1,
        "policy_version": POLICY_VERSION,
        "dataset_version": DATASET_VERSION,
        "split": "DEV",
        "dense_representation": selected,
        "candidate_pool": {
            "unit": selected_candidate["input_unit"],
            "input_k": RERANK_INPUT_K,
        },
        "existing_reranker": {
            "class": "src.reranking.LLMReranker",
            "configured_provider": "dashscope",
            "configured_model": "qwen-turbo",
            "execution_mode": "ONLINE_LLM_API",
            "local_reranker_artifact_available": False,
        },
        "status": "NOT_RUN_CONSTRAINT_BLOCKED",
        "blocker": (
            "The only configured R&D V2 reranker is DashScope qwen-turbo and the repository's "
            "other reranker is the online Jina API. This sprint prohibits Qwen/DashScope and "
            "model replacement; no local reranker artifact exists."
        ),
        "PRE_RERANK": {
            "overall": selected_candidate["overall"],
            "by_question_type": selected_candidate["by_question_type"],
        },
        "POST_RERANK": None,
        "candidate_recall_unchanged": "NOT_EVALUATED",
        "rank_movement": {
            "IMPROVED_RANK": None,
            "UNCHANGED": None,
            "REGRESSED_RANK": None,
            "TOP1_GAIN": None,
            "TOP1_LOSS": None,
        },
        "reranker_value_verified": "NO",
        "reranker_enabled": False,
        "online_models_called": False,
        "body_text_logged": False,
    }

    policy = {
        "schema_version": 1,
        "retrieval_policy_version": POLICY_VERSION,
        "status": "FROZEN",
        "frozen_at": now(),
        "frozen_before_holdout": True,
        "mutation_policy": (
            "This v1.0 policy must not be modified based on HOLDOUT results. Objective corrections "
            "require a new version and an explicit reason."
        ),
        "dataset_version": DATASET_VERSION,
        "corpus_version": base_artifact["corpus_version"],
        "corpus_snapshot_sha256": base_artifact["corpus_snapshot_sha256"],
        "dev_dataset_sha256": sha256_file(args.dataset_dir / "dev_dataset.json"),
        "dense_representation_comparison_sha256": None,
        "reranker_validation_sha256": None,
        "retrieval_policy": "DENSE_ONLY",
        "dense_representation": selected,
        "dense_namespace": NAMESPACES[selected],
        "dense_artifact_manifest_sha256": results[selected]["artifact_manifest_sha256"],
        "dense_faiss_sha256": results[selected]["faiss_sha256"],
        "embedding_model": base_artifact["embedding"]["model"],
        "embedding_model_revision": base_artifact["embedding"]["model_revision"],
        "query_prefix": base_artifact["embedding"]["query_prefix"],
        "reranker_enabled": False,
        "reranker_value_verified": "NO",
        "reranker_validation_status": reranker_validation["status"],
        "dense_top_k": DENSE_TOP_K,
        "rerank_input_k": RERANK_INPUT_K,
        "rerank_input_active": False,
        "final_top_k": FINAL_TOP_K,
        "evaluation_depth": 20,
        "bm25_enabled": False,
        "hybrid_enabled": False,
        "holdout_evaluated_at_freeze": False,
        "online_models_called": False,
    }

    args.report_dir.mkdir(parents=True, exist_ok=True)
    comparison_path = args.report_dir / "dense_representation_comparison.json"
    reranker_path = args.report_dir / "reranker_validation.json"
    write_json_new(comparison_path, comparison)
    write_json_new(reranker_path, reranker_validation)
    policy["dense_representation_comparison_sha256"] = sha256_file(comparison_path)
    policy["reranker_validation_sha256"] = sha256_file(reranker_path)
    write_json_new(args.report_dir / "final_retrieval_policy.json", policy)
    print(
        json.dumps(
            {
                "action": "dev-freeze",
                "status": "PASS",
                "final_dense_representation": selected,
                "reranker_status": reranker_validation["status"],
                "reranker_enabled": False,
                "policy_version": POLICY_VERSION,
                "holdout_evaluated": False,
                "online_models_called": False,
            }
        )
    )


def embed_eval_queries(args: argparse.Namespace) -> None:
    policy_path = args.report_dir / "final_retrieval_policy.json"
    if not policy_path.is_file():
        raise RuntimeError("Freeze the final retrieval policy before embedding evaluation queries")
    if (args.report_dir / "holdout_results.json").exists():
        raise RuntimeError("HOLDOUT has already been evaluated")
    if args.eval_query_artifact_dir.exists():
        raise RuntimeError("Refusing to overwrite evaluation query embeddings")
    policy = load_json(policy_path)
    if policy.get("status") != "FROZEN" or not policy.get("frozen_before_holdout"):
        raise RuntimeError("Final policy freeze validation failed")
    holdout = load_json(args.dataset_dir / "holdout_dataset.json")
    stress = load_json(args.dataset_dir / "structure_stress_set.json")
    verify_dataset(holdout, "HOLDOUT", 20)
    verify_structure_stress(stress)
    if "faiss" in sys.modules:
        raise RuntimeError("Embedding process must not load FAISS")
    if args.model_snapshot is None:
        raise RuntimeError("--model-snapshot is required for local offline query embedding")
    from scripts.run_rd_v2_real_retrieval_validation import LocalBGEEmbedder

    embedder = LocalBGEEmbedder(
        args.model_snapshot,
        threads=args.threads,
        batch_size=args.query_batch_size,
        max_length=512,
    )
    cases = [*holdout["cases"], *stress["cases"]]
    vectors = embedder.encode(
        [case["question"] for case in cases], prefix=policy["query_prefix"], log_progress=False
    )
    if vectors.shape != (26, 512) or not np.isfinite(vectors).all():
        raise RuntimeError("Evaluation query embedding validation failed")
    if not np.allclose(np.linalg.norm(vectors, axis=1), 1.0, atol=1e-4):
        raise RuntimeError("Evaluation query embeddings are not unit normalized")
    args.eval_query_artifact_dir.mkdir(parents=True)
    vector_path = args.eval_query_artifact_dir / "eval_query_embeddings.npy"
    with vector_path.open("xb") as stream:
        np.save(stream, vectors, allow_pickle=False)
    manifest = {
        "schema_version": 1,
        "status": "READY_NOT_EVALUATED",
        "created_at": now(),
        "retrieval_policy_version": POLICY_VERSION,
        "retrieval_policy_sha256": sha256_file(policy_path),
        "holdout_dataset_sha256": sha256_file(args.dataset_dir / "holdout_dataset.json"),
        "structure_stress_set_sha256": sha256_file(args.dataset_dir / "structure_stress_set.json"),
        "model": policy["embedding_model"],
        "model_revision": policy["embedding_model_revision"],
        "query_prefix": policy["query_prefix"],
        "count": 26,
        "dimension": 512,
        "partitions": {"HOLDOUT": [0, 20], "STRUCTURE_STRESS": [20, 26]},
        "ordered_question_id_sha256": sequence_digest(case["question_id"] for case in cases),
        "vector_sha256": sha256_file(vector_path),
        "holdout_retrieval_evaluated": False,
        "embedding_process_loaded_faiss": False,
        "online_models_called": False,
        "body_text_logged": False,
    }
    write_json_new(args.eval_query_artifact_dir / "artifact_manifest.json", manifest)
    print(
        json.dumps(
            {
                "action": "embed-eval-queries",
                "status": "PASS",
                "count": 26,
                "holdout_retrieval_evaluated": False,
                "embedding_process_loaded_faiss": False,
                "online_models_called": False,
            }
        )
    )


def holdout_metrics_payload(records: Sequence[dict]) -> tuple[dict, dict]:
    return metrics_with_types(records)


def evaluate_once(args: argparse.Namespace) -> None:
    policy_path = args.report_dir / "final_retrieval_policy.json"
    holdout_path = args.report_dir / "holdout_results.json"
    stress_path = args.report_dir / "structure_stress_results.json"
    final_report_path = args.report_dir / "final_retrieval_validation_report.md"
    start_marker = args.report_dir / "holdout_evaluation_started.json"
    complete_marker = args.report_dir / "holdout_evaluation_completed.json"
    if any(path.exists() for path in (holdout_path, stress_path, final_report_path, start_marker, complete_marker)):
        raise RuntimeError("HOLDOUT evaluation was already started or completed; refusing a second run")
    policy = load_json(policy_path)
    policy_hash = sha256_file(policy_path)
    if (
        policy.get("status") != "FROZEN"
        or policy.get("retrieval_policy_version") != POLICY_VERSION
        or policy.get("retrieval_policy") != "DENSE_ONLY"
        or policy.get("reranker_enabled") is not False
        or not policy.get("frozen_before_holdout")
    ):
        raise RuntimeError("Frozen policy validation failed")
    chunks, base_artifact = verify_base_inputs(args)
    representation = policy["dense_representation"]
    dense_manifest = verify_namespace(args, representation, chunks)
    if (
        sha256_file(namespace_path(args, representation) / "artifact_manifest.json")
        != policy["dense_artifact_manifest_sha256"]
        or dense_manifest["artifact_files"]["child_vectors.faiss"]["sha256"]
        != policy["dense_faiss_sha256"]
    ):
        raise RuntimeError("Frozen policy/dense artifact hash mismatch")
    holdout = load_json(args.dataset_dir / "holdout_dataset.json")
    stress = load_json(args.dataset_dir / "structure_stress_set.json")
    verify_dataset(holdout, "HOLDOUT", 20)
    verify_structure_stress(stress)
    query_manifest = load_json(args.eval_query_artifact_dir / "artifact_manifest.json")
    vector_path = args.eval_query_artifact_dir / "eval_query_embeddings.npy"
    all_cases = [*holdout["cases"], *stress["cases"]]
    if (
        query_manifest.get("status") != "READY_NOT_EVALUATED"
        or query_manifest.get("retrieval_policy_sha256") != policy_hash
        or query_manifest.get("vector_sha256") != sha256_file(vector_path)
        or query_manifest.get("ordered_question_id_sha256")
        != sequence_digest(case["question_id"] for case in all_cases)
    ):
        raise RuntimeError("Evaluation query artifact validation failed")
    vectors = np.load(vector_path, allow_pickle=False)
    if vectors.shape != (26, 512) or not np.isfinite(vectors).all():
        raise RuntimeError("Evaluation query vectors failed validation")
    write_json_new(
        start_marker,
        {
            "schema_version": 1,
            "started_at": now(),
            "retrieval_policy_version": POLICY_VERSION,
            "retrieval_policy_sha256": policy_hash,
            "holdout_dataset_sha256": sha256_file(args.dataset_dir / "holdout_dataset.json"),
            "attempt": 1,
        },
    )
    if "torch" in sys.modules:
        raise RuntimeError("FAISS evaluation process must not load PyTorch")
    import faiss

    index = faiss.read_index(str(namespace_path(args, representation) / "child_vectors.faiss"))
    if index.ntotal != len(chunks) or index.d != vectors.shape[1]:
        raise RuntimeError("Final dense index shape mismatch")
    rankings = dense_chunk_rankings(index, vectors, chunks)
    holdout_rows = rankings[:20]
    stress_rows = rankings[20:]
    holdout_records = [
        evaluate_case(case, page_dedupe(rows))
        for case, rows in zip(holdout["cases"], holdout_rows)
    ]
    holdout_overall, holdout_types = holdout_metrics_payload(holdout_records)
    failures = [
        {
            "question_id": row["question_id"],
            "question_type": row["question_type"],
            "expected_document_id": row["expected_document_id"],
            "expected_pages": row["expected_pages"],
            "first_evidence_rank": row["first_evidence_rank"],
            "failure": "MISS_AT_20",
        }
        for row in holdout_records
        if not row["hit_at_k"]["20"]
    ]
    holdout_payload = {
        "schema_version": 1,
        "run": "FROZEN_HOLDOUT_ONCE",
        "attempt": 1,
        "evaluated_at": now(),
        "retrieval_policy_version": POLICY_VERSION,
        "retrieval_policy_sha256": policy_hash,
        "dataset_version": DATASET_VERSION,
        "dataset_sha256": sha256_file(args.dataset_dir / "holdout_dataset.json"),
        "split": "HOLDOUT",
        "answerable_case_count": 20,
        "dense_representation": representation,
        "reranker_enabled": False,
        "metrics": {"overall": holdout_overall, "by_question_type": holdout_types},
        "improvement_cases": [],
        "improvement_cases_note": "No PRE/POST reranker comparison because the frozen policy disables reranking.",
        "failure_cases": failures,
        "policy_adjusted_from_holdout": False,
        "bm25_used": False,
        "hybrid_used": False,
        "answer_evaluation_run": False,
        "online_models_called": False,
        "body_text_logged": False,
    }

    stress_records = [
        evaluate_case(case, page_dedupe(rows))
        for case, rows in zip(stress["cases"], stress_rows)
    ]
    by_source: dict[str, list[dict]] = defaultdict(list)
    for case, record in zip(stress["cases"], stress_records):
        by_source[case["expected_section_source"]].append(record)
    source_metrics = {
        source: metric_block(by_source[source]) for source in ("FALLBACK", "PDF_HEURISTIC")
    }
    source_pass = {
        source: source_metrics[source]["hit_at_k"]["20"] >= STRESS_PASS_HIT20_THRESHOLD
        for source in source_metrics
    }
    stress_failures = [
        {
            "question_id": row["question_id"],
            "question_type": row["question_type"],
            "expected_section_source": case["expected_section_source"],
            "expected_document_id": row["expected_document_id"],
            "expected_pages": row["expected_pages"],
            "first_evidence_rank": row["first_evidence_rank"],
            "failure": "MISS_AT_20",
        }
        for case, row in zip(stress["cases"], stress_records)
        if not row["hit_at_k"]["20"]
    ]
    stress_payload = {
        "schema_version": 1,
        "run": "FROZEN_STRUCTURE_STRESS_ONCE",
        "evaluated_at": now(),
        "retrieval_policy_version": POLICY_VERSION,
        "retrieval_policy_sha256": policy_hash,
        "excluded_from_holdout_overall_metrics": True,
        "case_count": 6,
        "dataset_status": stress.get("dataset_status"),
        "human_review_status": "PENDING",
        "interpretation_scope": "DIAGNOSTIC_ONLY_UNREVIEWED_STRESS_GROUND_TRUTH",
        "source_counts": {"FALLBACK": 4, "PDF_HEURISTIC": 2},
        "pass_rule": f"PASS when source-specific Hit@20 >= {STRESS_PASS_HIT20_THRESHOLD:.2f}; lower indicates a clear path-level blocker.",
        "metrics_by_section_source": source_metrics,
        "source_pass": {
            source: "YES" if value else "NO" for source, value in source_pass.items()
        },
        "failure_cases": stress_failures,
        "bm25_used": False,
        "hybrid_used": False,
        "reranker_enabled": False,
        "online_models_called": False,
        "body_text_logged": False,
    }

    dense_comparison = load_json(args.report_dir / "dense_representation_comparison.json")
    reranker_validation = load_json(args.report_dir / "reranker_validation.json")
    selected_dev = dense_comparison["results"][representation]["rerank_candidate_pool"]["overall"]
    ready_hardening = all(source_pass.values())
    report = f"""# Final Dense + Reranker Validation

Generated: `{now()}`  
Policy: `{POLICY_VERSION}` (frozen before HOLDOUT)

## Final decision

`{representation}` won the DEV-only representation gate at the fixed Top-{RERANK_INPUT_K} child candidate depth. The existing R&D V2 reranker could not be legally executed: it is DashScope `qwen-turbo`, while this sprint explicitly prohibits Qwen/DashScope and provides no frozen local reranker artifact. It was not replaced or simulated, so it is disabled in the final policy.

The frozen policy is Dense-only with `dense_top_k={DENSE_TOP_K}`, inactive `rerank_input_k={RERANK_INPUT_K}`, and `final_top_k={FINAL_TOP_K}`. HOLDOUT was evaluated exactly once after the policy file was written. Structure stress results are kept separate from formal HOLDOUT metrics.

## HOLDOUT

| Metric | Value |
|---|---:|
| Hit@1 | {holdout_overall['hit_at_k']['1']:.6f} |
| Hit@3 | {holdout_overall['hit_at_k']['3']:.6f} |
| Hit@5 | {holdout_overall['hit_at_k']['5']:.6f} |
| Hit@10 | {holdout_overall['hit_at_k']['10']:.6f} |
| Hit@20 | {holdout_overall['hit_at_k']['20']:.6f} |
| MRR@20 | {holdout_overall['mrr_at_20']:.6f} |

## Required summary

```text
FINAL_DENSE_REPRESENTATION = {representation}

PRE_RERANK_HIT1 = {selected_dev['hit_at_k']['1']:.6f}
POST_RERANK_HIT1 = NOT_RUN_CONSTRAINT_BLOCKED

PRE_RERANK_MRR = {selected_dev['mrr_at_12']:.6f}
POST_RERANK_MRR = NOT_RUN_CONSTRAINT_BLOCKED

RERANKER_VALUE_VERIFIED = {reranker_validation['reranker_value_verified']}
RERANKER_ENABLED = NO

FINAL_RETRIEVAL_POLICY = DENSE_ONLY
FINAL_RETRIEVAL_POLICY_VERSION = {POLICY_VERSION}

HOLDOUT_HIT1 = {holdout_overall['hit_at_k']['1']:.6f}
HOLDOUT_HIT3 = {holdout_overall['hit_at_k']['3']:.6f}
HOLDOUT_HIT5 = {holdout_overall['hit_at_k']['5']:.6f}
HOLDOUT_HIT20 = {holdout_overall['hit_at_k']['20']:.6f}
HOLDOUT_MRR = {holdout_overall['mrr_at_20']:.6f}

FALLBACK_STRESS_PASS = {'YES' if source_pass['FALLBACK'] else 'NO'}
PDF_HEURISTIC_STRESS_PASS = {'YES' if source_pass['PDF_HEURISTIC'] else 'NO'}

RETRIEVAL_EXPLORATION_COMPLETE = YES
READY_FOR_ENGINEERING_HARDENING = {'YES' if ready_hardening else 'NO'}
```

No HOLDOUT-driven adjustment was made. No Answer Evaluation, Qwen/DashScope call, API call, BM25, Hybrid, or Agent work was started.
"""

    write_json_new(holdout_path, holdout_payload)
    write_json_new(stress_path, stress_payload)
    write_text_new(final_report_path, report)
    write_json_new(
        complete_marker,
        {
            "schema_version": 1,
            "completed_at": now(),
            "retrieval_policy_version": POLICY_VERSION,
            "retrieval_policy_sha256": policy_hash,
            "attempt": 1,
            "holdout_results_sha256": sha256_file(holdout_path),
            "structure_stress_results_sha256": sha256_file(stress_path),
            "final_report_sha256": sha256_file(final_report_path),
            "policy_adjusted_from_holdout": False,
        },
    )
    print(
        json.dumps(
            {
                "action": "evaluate-once",
                "status": "PASS",
                "holdout_attempt": 1,
                "holdout_hit1": holdout_overall["hit_at_k"]["1"],
                "holdout_hit5": holdout_overall["hit_at_k"]["5"],
                "holdout_hit20": holdout_overall["hit_at_k"]["20"],
                "fallback_stress_pass": source_pass["FALLBACK"],
                "pdf_heuristic_stress_pass": source_pass["PDF_HEURISTIC"],
                "policy_adjusted_from_holdout": False,
                "online_models_called": False,
            }
        )
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "action", choices=("dev-freeze", "embed-eval-queries", "evaluate-once")
    )
    parser.add_argument(
        "--baseline-artifact-dir",
        type=Path,
        default=Path("data/rd_v2_corpus/retrieval_artifacts/rd-v2-retrieval-v1.0"),
    )
    parser.add_argument(
        "--enrichment-artifact-root",
        type=Path,
        default=Path(
            "data/rd_v2_corpus/retrieval_artifacts/rd-v2-retrieval-v1.0_embedding_enrichment"
        ),
    )
    parser.add_argument(
        "--eval-query-artifact-dir",
        type=Path,
        default=Path(
            "data/rd_v2_corpus/retrieval_artifacts/rd-v2-retrieval-final-v1.0_eval_queries"
        ),
    )
    parser.add_argument(
        "--dataset-dir",
        type=Path,
        default=Path("reports/rd_v2_real_retrieval_validation/rd-v2-retrieval-v1.0"),
    )
    parser.add_argument(
        "--report-dir",
        type=Path,
        default=Path("reports/rd_v2_final_retrieval_validation"),
    )
    parser.add_argument("--model-snapshot", type=Path)
    parser.add_argument("--threads", type=int, default=1)
    parser.add_argument("--query-batch-size", type=int, default=16)
    return parser.parse_args()


if __name__ == "__main__":
    arguments = parse_args()
    if arguments.action == "dev-freeze":
        dev_freeze(arguments)
    elif arguments.action == "embed-eval-queries":
        embed_eval_queries(arguments)
    else:
        evaluate_once(arguments)
