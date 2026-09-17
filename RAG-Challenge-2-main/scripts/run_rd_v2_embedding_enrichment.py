"""Controlled, offline embedding-representation experiment for frozen R&D V2.

Actions are deliberately process-separated:

* ``embed`` may load Transformers/PyTorch but never imports FAISS.
* ``index`` and ``evaluate`` may load FAISS but never import PyTorch.

Retrieval text exists only in the embedding process.  It is hashed, not saved;
the immutable child text remains the citation/display/context evidence.
"""

from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import ctypes
from datetime import datetime
import gc
import hashlib
import json
import os
from pathlib import Path
import shutil
import sys
from typing import Iterable, Sequence
from zoneinfo import ZoneInfo

import numpy as np


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from scripts.run_rd_v2_real_retrieval_validation import LocalBGEEmbedder
from src.embedding_text import EmbeddingTextBuilder, RetrievalTextMode


DATASET_VERSION = "rd-v2-retrieval-v1.0"
EXPERIMENT_VERSION = "rd-v2-embedding-enrichment-v0.1"
MODEL_ID = "BAAI/bge-small-zh-v1.5"
KS = (1, 3, 5, 10, 20, 50)
MODES = tuple(RetrievalTextMode)
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
MODE_NAMESPACES = {
    RetrievalTextMode.CHILD_ONLY: "embedding_repr_child_only",
    RetrievalTextMode.SECTION_TITLE: "embedding_repr_section_title",
    RetrievalTextMode.SECTION_PATH: "embedding_repr_section_path",
    RetrievalTextMode.DOCUMENT_SECTION_PATH: "embedding_repr_document_section_path",
}
BUILDER_CONFIG = {
    "max_path_components": 8,
    "max_path_characters": 320,
    "max_title_characters": 160,
}
SELECTION_WEIGHTS = {
    "overall_hit1": 1.0,
    "overall_hit5": 3.0,
    "overall_hit20": 3.0,
    "overall_hit50": 2.0,
    "overall_recall20": 2.0,
    "overall_recall50": 1.0,
    "overall_mrr5": 1.0,
    "overall_mrr50": 1.0,
    "critical_type_balance": 0.5,
    "semantic_balance": 0.25,
    "top5_recovered_each": 0.03,
    "top50_recovered_each": 0.02,
    "regressed_each": -0.02,
    "baseline_hit1_broken_each": -0.04,
}


if os.name == "nt":
    ctypes.windll.kernel32.SetErrorMode(0x0001 | 0x0002 | 0x8000)


def now() -> str:
    return datetime.now(ZoneInfo("Asia/Shanghai")).isoformat(timespec="seconds")


def json_bytes(value: object) -> bytes:
    return (json.dumps(value, ensure_ascii=False, indent=2) + "\n").encode("utf-8")


def load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json_new(path: Path, value: object) -> None:
    if path.exists():
        raise RuntimeError(f"Refusing to overwrite existing artifact: {path.name}")
    path.parent.mkdir(parents=True, exist_ok=True)
    partial = path.with_suffix(path.suffix + ".partial")
    if partial.exists():
        raise RuntimeError(f"Partial output exists: {partial.name}")
    partial.write_bytes(json_bytes(value))
    partial.replace(path)


def write_text_new(path: Path, value: str) -> None:
    if path.exists():
        raise RuntimeError(f"Refusing to overwrite existing report: {path.name}")
    path.parent.mkdir(parents=True, exist_ok=True)
    partial = path.with_suffix(path.suffix + ".partial")
    if partial.exists():
        raise RuntimeError(f"Partial output exists: {partial.name}")
    partial.write_text(value.rstrip() + "\n", encoding="utf-8")
    partial.replace(path)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def sha256_json(value: object) -> str:
    return hashlib.sha256(
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode(
            "utf-8"
        )
    ).hexdigest()


def sequence_digest(values: Iterable[str]) -> str:
    digest = hashlib.sha256()
    for value in values:
        encoded = value.encode("utf-8")
        digest.update(len(encoded).to_bytes(8, "big"))
        digest.update(encoded)
    return digest.hexdigest()


def mode_from_arg(value: str) -> RetrievalTextMode:
    try:
        return RetrievalTextMode(value.upper())
    except ValueError as exc:
        raise argparse.ArgumentTypeError(f"Unknown representation mode: {value}") from exc


def namespace_paths(args: argparse.Namespace, mode: RetrievalTextMode) -> tuple[Path, Path]:
    name = MODE_NAMESPACES[mode]
    return args.artifact_root / name, args.artifact_root / f".{name}.build.partial"


def verify_frozen_inputs(args: argparse.Namespace, *, include_queries: bool = False) -> dict:
    freeze_path = args.dataset_dir / "dataset_freeze_manifest.json"
    freeze = load_json(freeze_path)
    if (
        freeze.get("dataset_version") != DATASET_VERSION
        or freeze.get("dataset_status") != "FROZEN"
        or freeze.get("ground_truth_frozen") is not True
        or freeze.get("human_review_completed") is not True
    ):
        raise RuntimeError("Frozen dataset contract is not satisfied")
    for name, record in freeze["dataset_files"].items():
        if sha256_file(args.dataset_dir / name) != record["sha256"]:
            raise RuntimeError(f"Frozen dataset hash mismatch: {name}")

    baseline_manifest_path = args.baseline_artifact_dir / "artifact_manifest.json"
    baseline = load_json(baseline_manifest_path)
    if baseline.get("build_status") != "PASS":
        raise RuntimeError("Frozen baseline artifacts are not ready")
    for name, record in baseline["artifact_files"].items():
        if sha256_file(args.baseline_artifact_dir / name) != record["sha256"]:
            raise RuntimeError(f"Frozen baseline artifact hash mismatch: {name}")
    if (
        baseline["dataset_freeze_manifest_sha256"] != sha256_file(freeze_path)
        or baseline["corpus_snapshot_sha256"] != sha256_file(args.corpus_snapshot)
        or baseline["embedding"]["model"] != MODEL_ID
    ):
        raise RuntimeError("Frozen corpus/dataset/model alignment failed")

    dev_path = args.dataset_dir / "dev_dataset.json"
    dev = load_json(dev_path)
    result = {"freeze": freeze, "baseline": baseline, "dev": dev}
    if include_queries:
        query_path = args.dataset_dir / "dev_query_embeddings.npy"
        query_manifest = load_json(args.dataset_dir / "dev_query_embedding_manifest.json")
        if (
            query_manifest.get("status") != "READY"
            or query_manifest.get("dev_dataset_sha256") != sha256_file(dev_path)
            or query_manifest.get("artifact_manifest_sha256")
            != sha256_file(baseline_manifest_path)
            or query_manifest.get("query_vectors_sha256") != sha256_file(query_path)
            or query_manifest.get("model_revision")
            != baseline["embedding"]["model_revision"]
        ):
            raise RuntimeError("Frozen DEV query-vector alignment failed")
        result["query_manifest"] = query_manifest
    return result


def load_chunks(args: argparse.Namespace) -> list[dict]:
    chunks = []
    path = args.baseline_artifact_dir / "child_chunks.jsonl"
    with path.open("r", encoding="utf-8") as stream:
        for index, line in enumerate(stream):
            item = json.loads(line)
            item["chunk_index"] = index
            chunks.append(item)
    if len(chunks) != 5090:
        raise RuntimeError("Frozen child chunk count is not 5090")
    chunk_ids = [item.get("chunk_id") for item in chunks]
    if any(not value for value in chunk_ids) or len(set(chunk_ids)) != len(chunk_ids):
        raise RuntimeError("Frozen child chunk IDs are incomplete or duplicated")
    return chunks


def load_document_titles(args: argparse.Namespace, document_ids: Iterable[str]) -> dict[str, str]:
    titles = {}
    for document_id in sorted(document_ids):
        path = (
            args.corpus_root
            / "normalized"
            / "repaired_chunked"
            / document_id
            / f"{document_id}.json"
        )
        document = load_json(path)
        titles[document_id] = str(document.get("metainfo", {}).get("title") or "").strip()
    return titles


def tokenizer_length(tokenizer, value: str) -> int:
    return len(
        tokenizer(
            value,
            add_special_tokens=True,
            truncation=False,
            verbose=False,
        )["input_ids"]
    )


def prepare_retrieval_texts(
    *,
    chunks: Sequence[dict],
    document_titles: dict[str, str],
    builder: EmbeddingTextBuilder,
    mode: RetrievalTextMode,
    tokenizer,
    max_length: int,
) -> tuple[list[str], dict, dict]:
    texts: list[str] = []
    child_characters: list[int] = []
    retrieval_characters: list[int] = []
    child_tokens: list[int] = []
    retrieval_tokens: list[int] = []
    metadata_characters: list[int] = []
    metadata_included = 0
    document_included = 0
    path_limited = 0
    budget_fallback = 0
    child_over_limit = 0
    for chunk in chunks:
        child = chunk["text"]
        result = builder.build(
            mode,
            child_text=child,
            section_title=chunk.get("section_title"),
            section_path=chunk.get("section_path"),
            document_title=document_titles.get(chunk["document_id"], ""),
        )
        child_length = tokenizer_length(tokenizer, child)
        retrieval_length = tokenizer_length(tokenizer, result.retrieval_text)
        if child_length > max_length:
            child_over_limit += 1
        if result.metadata_characters and retrieval_length > max_length:
            # Metadata is omitted for this chunk rather than consuming tokens
            # that the frozen CHILD_ONLY representation allocated to evidence.
            result = builder.build(RetrievalTextMode.CHILD_ONLY, child_text=child)
            retrieval_length = child_length
            budget_fallback += 1
        if not result.retrieval_text.endswith(child):
            raise RuntimeError("Retrieval representation altered child evidence")
        texts.append(result.retrieval_text)
        child_characters.append(len(child))
        retrieval_characters.append(len(result.retrieval_text))
        child_tokens.append(child_length)
        retrieval_tokens.append(retrieval_length)
        metadata_characters.append(result.metadata_characters)
        metadata_included += int(result.section_metadata_included)
        document_included += int(result.document_title_included)
        path_limited += int(result.path_was_limited)
    if len(texts) != len(chunks):
        raise RuntimeError("Representation/chunk cardinality mismatch")
    stats = {
        "count": len(texts),
        "child_text_character_length": {
            "average": round(float(np.mean(child_characters)), 6),
            "maximum": max(child_characters),
        },
        "retrieval_text_character_length": {
            "average": round(float(np.mean(retrieval_characters)), 6),
            "maximum": max(retrieval_characters),
        },
        "child_token_length_including_special_tokens": {
            "average": round(float(np.mean(child_tokens)), 6),
            "maximum": max(child_tokens),
        },
        "retrieval_token_length_before_model_truncation": {
            "average": round(float(np.mean(retrieval_tokens)), 6),
            "maximum": max(retrieval_tokens),
        },
        "model_input_token_length": {
            "average": round(float(np.mean([min(value, max_length) for value in retrieval_tokens])), 6),
            "maximum": min(max(retrieval_tokens), max_length),
        },
        "metadata_character_length": {
            "average": round(float(np.mean(metadata_characters)), 6),
            "maximum": max(metadata_characters),
        },
        "section_metadata_included_count": metadata_included,
        "document_title_included_count": document_included,
        "metadata_limited_count": path_limited,
        "metadata_omitted_for_token_budget_count": budget_fallback,
        "child_text_over_model_limit_count": child_over_limit,
        "child_truncated_to_make_room_for_metadata_count": 0,
        "evidence_text_mutated": False,
    }
    plan = {
        "schema_version": 1,
        "experiment_version": EXPERIMENT_VERSION,
        "dataset_version": DATASET_VERSION,
        "mode": mode.value,
        "namespace": MODE_NAMESPACES[mode],
        "builder": "src.embedding_text.EmbeddingTextBuilder",
        "builder_config": BUILDER_CONFIG,
        "builder_config_sha256": sha256_json(BUILDER_CONFIG),
        "ordered_chunk_id_sha256": sequence_digest(item["chunk_id"] for item in chunks),
        "retrieval_input_sha256": sequence_digest(texts),
        "retrieval_text_persisted": False,
        "evidence_text_mutated": False,
    }
    return texts, stats, plan


def embed_mode(args: argparse.Namespace) -> None:
    if args.mode is None or args.model_snapshot is None:
        raise RuntimeError("embed requires --mode and --model-snapshot")
    if "faiss" in sys.modules:
        raise RuntimeError("Embedding process must not load FAISS")
    inputs = verify_frozen_inputs(args)
    mode = args.mode
    final_dir, staging = namespace_paths(args, mode)
    if final_dir.exists():
        raise RuntimeError("Refusing to overwrite a completed representation namespace")
    if staging.exists() and not args.resume_partial:
        raise RuntimeError("Partial namespace exists; audit it and pass --resume-partial")
    staging.mkdir(parents=True, exist_ok=True)
    chunks = load_chunks(args)
    document_titles = load_document_titles(
        args, {item["document_id"] for item in chunks}
    )

    os.environ["HF_HUB_OFFLINE"] = "1"
    os.environ["TRANSFORMERS_OFFLINE"] = "1"
    os.environ["OMP_NUM_THREADS"] = str(args.threads)
    os.environ["MKL_NUM_THREADS"] = str(args.threads)
    embedder = None
    if mode is RetrievalTextMode.CHILD_ONLY:
        from transformers import AutoTokenizer

        tokenizer = AutoTokenizer.from_pretrained(
            args.model_snapshot, local_files_only=True
        )
    else:
        embedder = LocalBGEEmbedder(
            args.model_snapshot,
            threads=args.threads,
            batch_size=args.batch_size,
            max_length=args.max_length,
        )
        tokenizer = embedder.tokenizer
    builder = EmbeddingTextBuilder(**BUILDER_CONFIG)
    texts, stats, plan = prepare_retrieval_texts(
        chunks=chunks,
        document_titles=document_titles,
        builder=builder,
        mode=mode,
        tokenizer=tokenizer,
        max_length=args.max_length,
    )
    plan.update(
        {
            "dataset_freeze_manifest_sha256": sha256_file(
                args.dataset_dir / "dataset_freeze_manifest.json"
            ),
            "corpus_snapshot_sha256": sha256_file(args.corpus_snapshot),
            "baseline_child_chunks_sha256": inputs["baseline"]["artifact_files"][
                "child_chunks.jsonl"
            ]["sha256"],
            "model": MODEL_ID,
            "model_revision": inputs["baseline"]["embedding"]["model_revision"],
            "max_length": args.max_length,
        }
    )
    plan_path = staging / "representation_plan.json"
    if plan_path.exists():
        if load_json(plan_path) != plan:
            raise RuntimeError("Partial representation plan does not match deterministic input")
    else:
        write_json_new(plan_path, plan)

    embedding_path = staging / "embeddings.npy"
    state_path = staging / "embedding_build_state.json"
    if mode is RetrievalTextMode.CHILD_ONLY:
        if embedding_path.exists() or state_path.exists():
            if not args.resume_partial:
                raise RuntimeError("Partial CHILD_ONLY materialization already exists")
        else:
            shutil.copyfile(
                args.baseline_artifact_dir / "embeddings.npy", embedding_path
            )
            write_json_new(
                state_path,
                {
                    "schema_version": 1,
                    "status": "COMPLETE",
                    "completed": len(chunks),
                    "total": len(chunks),
                    "source": "FROZEN_CHILD_ONLY_BASELINE_COPY",
                    "source_sha256": inputs["baseline"]["artifact_files"][
                        "embeddings.npy"
                    ]["sha256"],
                    "online_models_called": False,
                    "body_text_logged": False,
                },
            )
        resumed = False
    else:
        if (staging / "representation_stats.json").exists():
            raise RuntimeError("Embedding is complete; run the index action")
        embeddings, resumed = embedder.encode_to_checkpoint(
            texts, embedding_path, state_path
        )
        del embeddings
    matrix = np.load(embedding_path, mmap_mode="r")
    if matrix.shape != (len(chunks), inputs["baseline"]["embedding"]["dimension"]):
        raise RuntimeError("Embedding matrix shape validation failed")
    if not np.isfinite(matrix).all() or not np.allclose(
        np.linalg.norm(matrix, axis=1), 1.0, atol=1e-4
    ):
        raise RuntimeError("Embedding finite/unit-norm validation failed")
    del matrix, texts, tokenizer, embedder
    gc.collect()
    stats.update(
        {
            "schema_version": 1,
            "mode": mode.value,
            "embedding_count": len(chunks),
            "dimension": inputs["baseline"]["embedding"]["dimension"],
            "embedding_resumed_from_checkpoint": resumed,
            "embedding_process_loaded_faiss": False,
            "torch_threads": args.threads,
            "torch_mkldnn_enabled": False,
            "batch_finite_validation": True,
            "batch_unit_norm_validation": True,
            "online_models_called": False,
            "body_text_logged": False,
        }
    )
    write_json_new(staging / "representation_stats.json", stats)
    print(
        json.dumps(
            {
                "action": "embed",
                "status": "PASS",
                "mode": mode.value,
                "chunks": len(chunks),
                "metadata_omitted_for_token_budget": stats[
                    "metadata_omitted_for_token_budget_count"
                ],
                "embedding_process_loaded_faiss": False,
                "online_models_called": False,
                "body_text_logged": False,
            }
        )
    )


def index_mode(args: argparse.Namespace) -> None:
    if args.mode is None:
        raise RuntimeError("index requires --mode")
    if "torch" in sys.modules:
        raise RuntimeError("FAISS process must not load PyTorch")
    inputs = verify_frozen_inputs(args)
    chunks = load_chunks(args)
    mode = args.mode
    final_dir, staging = namespace_paths(args, mode)
    if final_dir.exists():
        raise RuntimeError("Refusing to overwrite a completed representation namespace")
    if not staging.is_dir():
        raise RuntimeError("Embedding staging namespace does not exist")
    plan = load_json(staging / "representation_plan.json")
    stats = load_json(staging / "representation_stats.json")
    if (
        plan["mode"] != mode.value
        or plan["ordered_chunk_id_sha256"]
        != sequence_digest(item["chunk_id"] for item in chunks)
        or plan["baseline_child_chunks_sha256"]
        != inputs["baseline"]["artifact_files"]["child_chunks.jsonl"]["sha256"]
    ):
        raise RuntimeError("Representation plan/chunk order alignment failed")
    embedding_path = staging / "embeddings.npy"
    embeddings = np.load(embedding_path, mmap_mode="r")
    if embeddings.shape != (len(chunks), inputs["baseline"]["embedding"]["dimension"]):
        raise RuntimeError("Embedding matrix shape mismatch")

    import faiss

    faiss_path = staging / "child_vectors.faiss"
    if mode is RetrievalTextMode.CHILD_ONLY:
        if not faiss_path.exists():
            shutil.copyfile(
                args.baseline_artifact_dir / "child_vectors.faiss", faiss_path
            )
        index = faiss.read_index(str(faiss_path))
    else:
        if faiss_path.exists():
            index = faiss.read_index(str(faiss_path))
        else:
            index = faiss.IndexFlatIP(int(embeddings.shape[1]))
            index.add(np.ascontiguousarray(embeddings, dtype=np.float32))
            faiss.write_index(index, str(faiss_path))
    if index.ntotal != len(chunks) or index.d != embeddings.shape[1]:
        raise RuntimeError("FAISS shape/count validation failed")
    reconstructed = np.empty_like(embeddings)
    index.reconstruct_n(0, index.ntotal, reconstructed)
    vector_delta = float(np.max(np.abs(reconstructed - embeddings)))
    if vector_delta != 0.0:
        raise RuntimeError("FAISS vector positions do not match embedding rows")
    files = {}
    for name in (
        "embeddings.npy",
        "embedding_build_state.json",
        "representation_plan.json",
        "representation_stats.json",
        "child_vectors.faiss",
    ):
        path = staging / name
        files[name] = {"sha256": sha256_file(path), "bytes": path.stat().st_size}
    manifest = {
        "schema_version": 1,
        "build_status": "PASS",
        "built_at": now(),
        "experiment_version": EXPERIMENT_VERSION,
        "dataset_version": DATASET_VERSION,
        "mode": mode.value,
        "namespace": MODE_NAMESPACES[mode],
        "dataset_freeze_manifest_sha256": sha256_file(
            args.dataset_dir / "dataset_freeze_manifest.json"
        ),
        "corpus_snapshot_sha256": sha256_file(args.corpus_snapshot),
        "baseline_artifact_manifest_sha256": sha256_file(
            args.baseline_artifact_dir / "artifact_manifest.json"
        ),
        "baseline_child_chunks_sha256": inputs["baseline"]["artifact_files"][
            "child_chunks.jsonl"
        ]["sha256"],
        "ordered_chunk_id_sha256": plan["ordered_chunk_id_sha256"],
        "retrieval_input_sha256": plan["retrieval_input_sha256"],
        "child_chunk_count": len(chunks),
        "embedding_count": int(embeddings.shape[0]),
        "dimension": int(embeddings.shape[1]),
        "faiss_count": int(index.ntotal),
        "faiss_index_type": type(index).__name__,
        "normalization": "L2_UNIT",
        "embedding": inputs["baseline"]["embedding"],
        "representation_stats": stats,
        "artifact_files": files,
        "id_alignment": "PASS",
        "vector_max_abs_delta": vector_delta,
        "evidence_text_mutated": False,
        "retrieval_text_persisted": False,
        "online_models_called": False,
        "body_text_logged": False,
        "native_runtime_safety": {
            "embedding_and_faiss_process_isolation": True,
            "index_process_loaded_pytorch": False,
            "windows_error_dialog_suppressed": os.name == "nt",
        },
    }
    write_json_new(staging / "artifact_manifest.json", manifest)
    del reconstructed, embeddings, index
    gc.collect()
    staging.replace(final_dir)
    print(
        json.dumps(
            {
                "action": "index",
                "status": "PASS",
                "mode": mode.value,
                "chunks": len(chunks),
                "embeddings": manifest["embedding_count"],
                "faiss": manifest["faiss_count"],
                "id_alignment": "PASS",
                "index_process_loaded_pytorch": False,
                "online_models_called": False,
                "body_text_logged": False,
            }
        )
    )


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
            str(k): round(
                sum(row["recall_at_k"][str(k)] for row in records) / len(records), 6
            )
            for k in KS
        },
        "mrr_at_5": round(sum(row["reciprocal_rank_at_5"] for row in records) / len(records), 6),
        "mrr_at_50": round(
            sum(row["reciprocal_rank_at_50"] for row in records) / len(records), 6
        ),
    }


def evaluate_case(item: dict, ranked_pages: Sequence[dict]) -> dict:
    expected = {
        (item["expected_document_id"], int(page)) for page in item["expected_pages"]
    }
    ranked_keys = [
        (row["document_id"], int(row["page_number"])) for row in ranked_pages
    ]
    first_rank = next(
        (rank for rank, key in enumerate(ranked_keys, start=1) if key in expected), None
    )
    first_evidence = ranked_pages[first_rank - 1] if first_rank else None
    hit_at_k = {}
    recall_at_k = {}
    for k in KS:
        relevant = len(expected.intersection(set(ranked_keys[:k])))
        hit_at_k[str(k)] = int(relevant > 0)
        recall_at_k[str(k)] = round(relevant / len(expected), 6)
    return {
        "question_id": item["question_id"],
        "question_type": item["question_type"],
        "expected_document_id": item["expected_document_id"],
        "expected_pages": item["expected_pages"],
        "expected_section_ids": item["expected_section_ids"],
        "expected_section_sources": item["expected_section_sources"],
        "hit_at_k": hit_at_k,
        "recall_at_k": recall_at_k,
        "first_evidence_rank": first_rank,
        "first_evidence": first_evidence,
        "reciprocal_rank_at_5": round(1.0 / first_rank, 6)
        if first_rank and first_rank <= 5
        else 0.0,
        "reciprocal_rank_at_50": round(1.0 / first_rank, 6) if first_rank else 0.0,
    }


def classify_delta(baseline_rank: int | None, new_rank: int | None) -> str:
    if baseline_rank is None and new_rank is not None:
        return "RECOVERED"
    if baseline_rank is None and new_rank is None:
        return "UNCHANGED"
    if baseline_rank is not None and new_rank is None:
        return "REGRESSED"
    assert baseline_rank is not None and new_rank is not None
    if new_rank < baseline_rank:
        return "IMPROVED"
    crossed_boundary = any(
        baseline_rank <= boundary < new_rank for boundary in (1, 5, 20, 50)
    )
    if new_rank - baseline_rank >= 5 or crossed_boundary:
        return "REGRESSED"
    return "UNCHANGED"


def safe_evidence(value: dict | None) -> dict | None:
    if value is None:
        return None
    return {
        "rank": value["rank"],
        "document_id": value["document_id"],
        "page_number": value["page_number"],
        "section_id": value.get("section_id"),
        "section_source": value.get("section_source"),
        "chunk_id": value["chunk_id"],
        "cosine_similarity": value["cosine_similarity"],
    }


def delta_analysis(
    baseline_records: Sequence[dict], new_records: Sequence[dict], mode: RetrievalTextMode
) -> dict:
    rows = []
    counts = Counter()
    top50_recovered = []
    top5_recovered = []
    hit1_broken = []
    for baseline, new in zip(baseline_records, new_records):
        if baseline["question_id"] != new["question_id"]:
            raise RuntimeError("Per-query mode alignment failed")
        baseline_rank = baseline["first_evidence_rank"]
        new_rank = new["first_evidence_rank"]
        classification = classify_delta(baseline_rank, new_rank)
        counts[classification] += 1
        row = {
            "question_id": baseline["question_id"],
            "question_type": baseline["question_type"],
            "expected_document_id": baseline["expected_document_id"],
            "expected_pages": baseline["expected_pages"],
            "expected_section_ids": baseline["expected_section_ids"],
            "baseline_rank": baseline_rank,
            "new_rank": new_rank,
            "rank_improvement": baseline_rank - new_rank
            if baseline_rank is not None and new_rank is not None
            else None,
            "classification": classification,
            "top50_recovered": baseline_rank is None and new_rank is not None,
            "top5_recovered": (baseline_rank is None or baseline_rank > 5)
            and new_rank is not None
            and new_rank <= 5,
            "baseline_hit1_broken": baseline_rank == 1 and new_rank != 1,
            "baseline_first_evidence": safe_evidence(baseline["first_evidence"]),
            "new_first_evidence": safe_evidence(new["first_evidence"]),
        }
        rows.append(row)
        if row["top50_recovered"]:
            top50_recovered.append(row)
        if row["top5_recovered"]:
            top5_recovered.append(row)
        if row["baseline_hit1_broken"]:
            hit1_broken.append(row)
    return {
        "mode": mode.value,
        "counts": {
            "IMPROVED": counts["IMPROVED"],
            "RECOVERED": counts["RECOVERED"],
            "TOP5_RECOVERED": len(top5_recovered),
            "REGRESSED": counts["REGRESSED"],
            "UNCHANGED": counts["UNCHANGED"],
            "BASELINE_HIT1_BROKEN": len(hit1_broken),
        },
        "top50_recovered_cases": top50_recovered,
        "top5_recovered_cases": top5_recovered,
        "baseline_hit1_broken_cases": hit1_broken,
        "per_query": rows,
    }


def mode_selection_score(
    mode: RetrievalTextMode,
    overall: dict,
    by_type: dict,
    delta: dict,
) -> tuple[float, dict]:
    hit = overall["hit_at_k"]
    recall = overall["recall_at_k"]
    critical_values = []
    for query_type in ("field", "exact_term", "dependency"):
        value = by_type[query_type]
        critical_values.extend(
            [value["hit_at_k"]["20"], value["hit_at_k"]["50"], value["mrr_at_50"]]
        )
    critical_balance = float(np.mean(critical_values))
    semantic = by_type["semantic"]
    semantic_balance = float(
        np.mean(
            [
                semantic["hit_at_k"]["20"],
                semantic["hit_at_k"]["50"],
                semantic["mrr_at_50"],
            ]
        )
    )
    movement = delta["counts"]
    parts = {
        "overall_hit1": hit["1"],
        "overall_hit5": hit["5"],
        "overall_hit20": hit["20"],
        "overall_hit50": hit["50"],
        "overall_recall20": recall["20"],
        "overall_recall50": recall["50"],
        "overall_mrr5": overall["mrr_at_5"],
        "overall_mrr50": overall["mrr_at_50"],
        "critical_type_balance": critical_balance,
        "semantic_balance": semantic_balance,
        "top5_recovered_each": movement["TOP5_RECOVERED"],
        "top50_recovered_each": movement["RECOVERED"],
        "regressed_each": movement["REGRESSED"],
        "baseline_hit1_broken_each": movement["BASELINE_HIT1_BROKEN"],
    }
    score = sum(parts[key] * SELECTION_WEIGHTS[key] for key in parts)
    return round(score, 6), {key: round(float(value), 6) for key, value in parts.items()}


def type_improved(candidate: dict, baseline: dict, query_type: str) -> bool:
    new = candidate[query_type]
    old = baseline[query_type]
    return any(
        new["hit_at_k"][str(k)] > old["hit_at_k"][str(k)] for k in (5, 20, 50)
    ) or new["mrr_at_50"] > old["mrr_at_50"]


def semantic_regression(candidate: dict, baseline: dict) -> str:
    new = candidate["semantic"]
    old = baseline["semantic"]
    drops = [
        old["hit_at_k"][str(k)] - new["hit_at_k"][str(k)] for k in (5, 20, 50)
    ]
    mrr_drop = old["mrr_at_50"] - new["mrr_at_50"]
    # A one-case Top5 movement in this nine-question slice is treated as MINOR
    # when deeper recall is stable/improved.  A material deep-recall or MRR
    # loss remains a full regression guardrail failure.
    if max(drops[1:]) >= 0.1 or mrr_drop >= 0.05 or sum(max(0.0, value) for value in drops) >= 0.2:
        return "YES"
    if max([*drops, mrr_drop]) > 0:
        return "MINOR"
    return "NO"


def dense_deficiency_conclusion(
    candidate_overall: dict,
    baseline_overall: dict,
    improvement_flags: dict,
    semantic_status: str,
) -> str:
    hit20_gain = (
        candidate_overall["hit_at_k"]["20"] - baseline_overall["hit_at_k"]["20"]
    )
    hit50_gain = (
        candidate_overall["hit_at_k"]["50"] - baseline_overall["hit_at_k"]["50"]
    )
    critical_count = sum(improvement_flags.values())
    if max(hit20_gain, hit50_gain) >= 0.1 and critical_count >= 2 and semantic_status != "YES":
        return "YES"
    if max(hit20_gain, hit50_gain) >= 0.05 or critical_count >= 1:
        return "PARTIAL"
    return "NO"


def markdown_metrics_table(metrics: dict) -> list[str]:
    lines = [
        "| Representation | Hit@1 | Hit@5 | Hit@20 | Hit@50 | Recall@20 | Recall@50 | MRR@5 | MRR@50 |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for mode in MODES:
        value = metrics[mode.value]["overall"]
        lines.append(
            f"| {mode.value} | {value['hit_at_k']['1']} | {value['hit_at_k']['5']} | "
            f"{value['hit_at_k']['20']} | {value['hit_at_k']['50']} | "
            f"{value['recall_at_k']['20']} | {value['recall_at_k']['50']} | "
            f"{value['mrr_at_5']} | {value['mrr_at_50']} |"
        )
    return lines


def evaluate(args: argparse.Namespace) -> None:
    if args.report_dir.exists():
        raise RuntimeError("Refusing to overwrite an existing enrichment report directory")
    if "torch" in sys.modules:
        raise RuntimeError("Evaluation/FAISS process must not load PyTorch")
    inputs = verify_frozen_inputs(args, include_queries=True)
    chunks = load_chunks(args)
    chunk_id_digest = sequence_digest(item["chunk_id"] for item in chunks)
    query_vectors = np.load(
        args.dataset_dir / "dev_query_embeddings.npy", allow_pickle=False
    )
    if query_vectors.shape != (
        len(inputs["dev"]["cases"]),
        inputs["baseline"]["embedding"]["dimension"],
    ) or not np.isfinite(query_vectors).all():
        raise RuntimeError("DEV query vectors failed shape/finite validation")

    import faiss

    metrics = {}
    records_by_mode = {}
    validation_modes = {}
    configs = {}
    for mode in MODES:
        namespace, _ = namespace_paths(args, mode)
        manifest_path = namespace / "artifact_manifest.json"
        manifest = load_json(manifest_path)
        for name, record in manifest["artifact_files"].items():
            if sha256_file(namespace / name) != record["sha256"]:
                raise RuntimeError(f"Experiment artifact hash mismatch: {mode.value}/{name}")
        if (
            manifest.get("build_status") != "PASS"
            or manifest.get("mode") != mode.value
            or manifest.get("child_chunk_count") != len(chunks)
            or manifest.get("embedding_count") != len(chunks)
            or manifest.get("faiss_count") != len(chunks)
            or manifest.get("ordered_chunk_id_sha256") != chunk_id_digest
            or manifest.get("id_alignment") != "PASS"
            or manifest.get("evidence_text_mutated") is not False
            or manifest.get("retrieval_text_persisted") is not False
        ):
            raise RuntimeError(f"Experiment artifact contract failed: {mode.value}")
        index = faiss.read_index(str(namespace / "child_vectors.faiss"))
        if index.ntotal != len(chunks):
            raise RuntimeError(f"FAISS count mismatch: {mode.value}")
        scores, indices = index.search(
            np.ascontiguousarray(query_vectors, dtype=np.float32), index.ntotal
        )
        records = []
        for item, row_scores, row_indices in zip(
            inputs["dev"]["cases"], scores, indices
        ):
            pages = []
            seen_pages = set()
            for score, chunk_index in zip(row_scores, row_indices):
                if int(chunk_index) < 0:
                    continue
                chunk = chunks[int(chunk_index)]
                key = (chunk["document_id"], int(chunk["page_number"]))
                if key in seen_pages:
                    continue
                seen_pages.add(key)
                pages.append(
                    {
                        "rank": len(pages) + 1,
                        "document_id": chunk["document_id"],
                        "page_number": int(chunk["page_number"]),
                        "section_id": chunk.get("section_id"),
                        "section_source": chunk.get("section_source"),
                        "chunk_id": chunk["chunk_id"],
                        "cosine_similarity": round(float(score), 6),
                    }
                )
                if len(pages) == max(KS):
                    break
            if len(pages) != max(KS):
                raise RuntimeError("Dense search returned fewer than 50 unique pages")
            records.append(evaluate_case(item, pages))
        overall = metric_block(records)
        by_type_rows = defaultdict(list)
        by_source_rows = defaultdict(list)
        for record in records:
            by_type_rows[record["question_type"]].append(record)
            for source in set(record["expected_section_sources"]):
                by_source_rows[source].append(record)
        metrics[mode.value] = {
            "overall": overall,
            "by_section_source": {
                source: metric_block(by_source_rows[source])
                for source in SECTION_SOURCES
            },
        }
        records_by_mode[mode] = records
        validation_modes[mode.value] = {
            "status": "PASS",
            "namespace": MODE_NAMESPACES[mode],
            "chunk_count": manifest["child_chunk_count"],
            "embedding_count": manifest["embedding_count"],
            "faiss_count": manifest["faiss_count"],
            "ordered_chunk_id_sha256": manifest["ordered_chunk_id_sha256"],
            "id_alignment": manifest["id_alignment"],
            "vector_max_abs_delta": manifest["vector_max_abs_delta"],
            "embedding_sha256": manifest["artifact_files"]["embeddings.npy"]["sha256"],
            "faiss_sha256": manifest["artifact_files"]["child_vectors.faiss"]["sha256"],
            "evidence_text_mutated": False,
            "retrieval_text_persisted": False,
            "embedding_process_loaded_faiss": False,
            "index_process_loaded_pytorch": False,
        }
        configs[mode.value] = {
            "namespace": MODE_NAMESPACES[mode],
            "retrieval_input_sha256": manifest["retrieval_input_sha256"],
            "representation_stats": manifest["representation_stats"],
        }
        del index

    baseline_original = load_json(args.dataset_dir / "dense_baseline.json")
    baseline_metrics = metrics[RetrievalTextMode.CHILD_ONLY.value]["overall"]
    original_overall = baseline_original["metrics"]["overall"]
    if not (
        baseline_metrics["hit_at_k"]["1"] == original_overall["hit_at_k"]["1"]
        and baseline_metrics["hit_at_k"]["3"] == original_overall["hit_at_k"]["3"]
        and baseline_metrics["hit_at_k"]["5"] == original_overall["hit_at_k"]["5"]
        and baseline_metrics["recall_at_k"]["5"] == original_overall["recall_at_k"]["5"]
        and baseline_metrics["mrr_at_5"] == original_overall["mrr"]
    ):
        raise RuntimeError("CHILD_ONLY failed to reproduce the frozen dense baseline")

    per_type = {}
    for mode in MODES:
        rows = defaultdict(list)
        for record in records_by_mode[mode]:
            rows[record["question_type"]].append(record)
        per_type[mode.value] = {
            query_type: metric_block(rows[query_type]) for query_type in QUERY_TYPES
        }

    baseline_records = records_by_mode[RetrievalTextMode.CHILD_ONLY]
    delta = {}
    baseline_delta = {
        "mode": RetrievalTextMode.CHILD_ONLY.value,
        "counts": {
            "IMPROVED": 0,
            "RECOVERED": 0,
            "TOP5_RECOVERED": 0,
            "REGRESSED": 0,
            "UNCHANGED": len(baseline_records),
            "BASELINE_HIT1_BROKEN": 0,
        },
        "top50_recovered_cases": [],
        "top5_recovered_cases": [],
        "baseline_hit1_broken_cases": [],
        "per_query": [],
    }
    delta[RetrievalTextMode.CHILD_ONLY.value] = baseline_delta
    for mode in MODES[1:]:
        delta[mode.value] = delta_analysis(
            baseline_records, records_by_mode[mode], mode
        )

    selection = {}
    for mode in MODES:
        score, parts = mode_selection_score(
            mode,
            metrics[mode.value]["overall"],
            per_type[mode.value],
            delta[mode.value],
        )
        selection[mode.value] = {"score": score, "components": parts}
    semantic_status_by_mode = {
        mode.value: semantic_regression(
            per_type[mode.value], per_type[RetrievalTextMode.CHILD_ONLY.value]
        )
        for mode in MODES
    }
    maximum_score = max(value["score"] for value in selection.values())
    near_best_modes = [
        mode
        for mode in MODES
        if selection[mode.value]["score"] >= maximum_score - 0.05
    ]
    semantic_order = {"YES": 0, "MINOR": 1, "NO": 2}
    best_mode = max(
        near_best_modes,
        key=lambda value: (
            semantic_order[semantic_status_by_mode[value.value]],
            -delta[value.value]["counts"]["BASELINE_HIT1_BROKEN"],
            -delta[value.value]["counts"]["REGRESSED"],
            selection[value.value]["score"],
            -MODES.index(value),
        ),
    )
    best_delta = delta[best_mode.value]
    improvements = {
        query_type: type_improved(
            per_type[best_mode.value],
            per_type[RetrievalTextMode.CHILD_ONLY.value],
            query_type,
        )
        for query_type in ("field", "exact_term", "dependency")
    }
    semantic_status = semantic_status_by_mode[best_mode.value]
    deficiency = dense_deficiency_conclusion(
        metrics[best_mode.value]["overall"],
        baseline_metrics,
        improvements,
        semantic_status,
    )
    if deficiency == "YES":
        recommendation = "VALIDATE_SELECTED_REPRESENTATION_ON_HOLDOUT"
    elif deficiency == "PARTIAL":
        recommendation = "REVIEW_PARTIAL_GAINS_BEFORE_NEXT_RETRIEVAL_EXPERIMENT"
    else:
        recommendation = "EVALUATE_MODEL_SUITABILITY_OR_HYBRID_IN_NEXT_PHASE"

    staging = args.report_dir.with_name("." + args.report_dir.name + ".build.partial")
    if staging.exists():
        raise RuntimeError("Partial report directory already exists")
    staging.mkdir(parents=True)
    representation_payload = {
        "schema_version": 1,
        "experiment_version": EXPERIMENT_VERSION,
        "dataset_version": DATASET_VERSION,
        "builder": "src.embedding_text.EmbeddingTextBuilder",
        "builder_config": BUILDER_CONFIG,
        "modes": {
            "CHILD_ONLY": "child_text",
            "SECTION_TITLE": "[Section] section_title + [Content] child_text",
            "SECTION_PATH": "[Section] deduplicated section_path + [Content] child_text",
            "DOCUMENT_SECTION_PATH": "[Document] document_title + [Section] deduplicated section_path + [Content] child_text",
        },
        "normalization": {
            "metadata_whitespace_collapsed": True,
            "casefolded_deduplication": True,
            "empty_metadata_skipped": True,
            "path_preserves_deepest_components_when_limited": True,
            "child_text_normalized_or_mutated": False,
            "page_number_included": False,
            "chunk_or_section_id_included": False,
            "ground_truth_included": False,
        },
        "length_statistics": configs,
        "selection_rule": {
            "method": "weighted balanced DEV score across overall recall/ranking, critical query types, semantic balance, recoveries, and regressions",
            "weights": SELECTION_WEIGHTS,
            "scores": selection,
            "near_best_score_tolerance": 0.05,
            "near_best_guardrail_order": [
                "prefer no semantic regression",
                "prefer fewer baseline Hit@1 breaks",
                "prefer fewer material rank regressions",
                "prefer higher weighted score",
            ],
            "semantic_status_by_mode": semantic_status_by_mode,
            "near_best_modes": [mode.value for mode in near_best_modes],
        },
        "retrieval_text_persisted": False,
        "evidence_text_mutated": False,
    }
    validation_payload = {
        "schema_version": 1,
        "status": "PASS",
        "expected_count": 5090,
        "modes": validation_modes,
        "cross_mode_ordered_chunk_id_alignment": "PASS"
        if len({value["ordered_chunk_id_sha256"] for value in validation_modes.values()}) == 1
        else "FAIL",
        "frozen_child_only_baseline_reproduced": True,
        "embedding_and_faiss_process_isolation": True,
        "online_models_called": False,
        "body_text_logged": False,
    }
    dev_payload = {
        "schema_version": 1,
        "dataset_version": DATASET_VERSION,
        "split": "DEV",
        "retrieval": "GENERIC_DENSE_RAW",
        "reranker_used": False,
        "metrics": metrics,
        "best_representation": best_mode.value,
        "selection": selection,
        "holdout_evaluated": False,
        "online_models_called": False,
    }
    type_payload = {
        "schema_version": 1,
        "query_types": list(QUERY_TYPES),
        "metrics": per_type,
        "best_representation": best_mode.value,
        "field_improved": improvements["field"],
        "exact_term_improved": improvements["exact_term"],
        "dependency_improved": improvements["dependency"],
        "semantic_regression": semantic_status,
    }
    delta_payload = {
        "schema_version": 1,
        "baseline": RetrievalTextMode.CHILD_ONLY.value,
        "regression_definition": "new rank is absent, breaks baseline Hit@1, crosses Top5/Top20/Top50 downward, or falls by at least five page ranks",
        "modes": delta,
        "best_representation": best_mode.value,
    }
    write_json_new(staging / "representation_configs.json", representation_payload)
    write_json_new(staging / "artifact_validation.json", validation_payload)
    write_json_new(staging / "dev_metrics.json", dev_payload)
    write_json_new(staging / "per_type_metrics.json", type_payload)
    write_json_new(staging / "rank_delta_analysis.json", delta_payload)

    exact_metric_lines = []
    for mode in MODES:
        value = metrics[mode.value]["overall"]
        field_prefix = (
            "BASELINE_CHILD_ONLY"
            if mode is RetrievalTextMode.CHILD_ONLY
            else mode.value
        )
        for k in (1, 5, 20, 50):
            exact_metric_lines.append(
                f"{field_prefix}_HIT{k} = {value['hit_at_k'][str(k)]}"
            )
    length_lines = [
        "| Representation | Avg chars | Max chars | Avg tokens | Max tokens | Metadata budget fallback |",
        "|---|---:|---:|---:|---:|---:|",
    ]
    for mode in MODES:
        value = configs[mode.value]["representation_stats"]
        length_lines.append(
            f"| {mode.value} | {value['retrieval_text_character_length']['average']} | "
            f"{value['retrieval_text_character_length']['maximum']} | "
            f"{value['retrieval_token_length_before_model_truncation']['average']} | "
            f"{value['retrieval_token_length_before_model_truncation']['maximum']} | "
            f"{value['metadata_omitted_for_token_budget_count']} |"
        )
    type_lines = [
        "| Representation | Type | N | Hit@5 | Hit@20 | Hit@50 | MRR@50 |",
        "|---|---|---:|---:|---:|---:|---:|",
    ]
    for mode in MODES:
        for query_type in ("field", "exact_term", "dependency", "semantic"):
            value = per_type[mode.value][query_type]
            type_lines.append(
                f"| {mode.value} | {query_type} | {value['count']} | "
                f"{value['hit_at_k']['5']} | {value['hit_at_k']['20']} | "
                f"{value['hit_at_k']['50']} | {value['mrr_at_50']} |"
            )
    source_lines = [
        "| Representation | Section source | N | Hit@5 | Hit@20 | Hit@50 |",
        "|---|---|---:|---:|---:|---:|",
    ]
    for mode in MODES:
        for source in SECTION_SOURCES:
            value = metrics[mode.value]["by_section_source"][source]
            source_lines.append(
                f"| {mode.value} | {source} | {value['count']} | "
                f"{value['hit_at_k']['5']} | {value['hit_at_k']['20']} | "
                f"{value['hit_at_k']['50']} |"
            )
    delta_lines = [
        "| Representation | Improved | Top50 recovered | Top5 recovered | Regressed | Unchanged | Baseline Hit@1 broken |",
        "|---|---:|---:|---:|---:|---:|---:|",
    ]
    for mode in MODES[1:]:
        value = delta[mode.value]["counts"]
        delta_lines.append(
            f"| {mode.value} | {value['IMPROVED']} | {value['RECOVERED']} | "
            f"{value['TOP5_RECOVERED']} | {value['REGRESSED']} | "
            f"{value['UNCHANGED']} | {value['BASELINE_HIT1_BROKEN']} |"
        )
    lines = [
        "# R&D V2 Controlled Embedding Text Enrichment Experiment",
        "",
        "ARTIFACT_VALIDATION = PASS",
        "FROZEN_CHILD_ONLY_BASELINE_REPRODUCED = YES",
        "RETRIEVAL = GENERIC_DENSE_RAW",
        "RERANKER_USED = NO",
        "EVIDENCE_TEXT_MUTATED = NO",
        "",
        "## DEV metrics",
        "",
        *markdown_metrics_table(metrics),
        "",
        *exact_metric_lines,
        "",
        "## Retrieval input lengths",
        "",
        *length_lines,
        "",
        "## Critical query types and semantic guardrail",
        "",
        *type_lines,
        "",
        "## Section source",
        "",
        *source_lines,
        "",
        "## Rank deltas versus CHILD_ONLY",
        "",
        *delta_lines,
        "",
        f"BEST_REPRESENTATION = {best_mode.value}",
        f"TOP50_RECOVERED_COUNT = {best_delta['counts']['RECOVERED']}",
        f"TOP5_RECOVERED_COUNT = {best_delta['counts']['TOP5_RECOVERED']}",
        f"REGRESSION_COUNT = {best_delta['counts']['REGRESSED']}",
        "",
        f"FIELD_IMPROVED = {'YES' if improvements['field'] else 'NO'}",
        f"EXACT_TERM_IMPROVED = {'YES' if improvements['exact_term'] else 'NO'}",
        f"DEPENDENCY_IMPROVED = {'YES' if improvements['dependency'] else 'NO'}",
        f"SEMANTIC_REGRESSION = {semantic_status}",
        f"DENSE_REPRESENTATION_DEFICIENCY_CONFIRMED = {deficiency}",
        "",
        "## Interpretation",
        "",
        "- CHILD_ONLY is a byte-preserving copy of the frozen embedding/index baseline and reproduced its published Top5 metrics.",
        "- B/C/D changed only the in-memory text sent to the same local embedding model; chunk order, IDs, boundaries, evidence text, query vectors, and evaluation contract stayed fixed.",
        "- Each mode used 5090 chunks, 5090 embeddings, and 5090 FAISS vectors with exact row/position alignment.",
        "- Candidate selection used a balanced weighted score, then a 0.05 near-tie guardrail favoring semantic stability, preservation of baseline Hit@1 cases, and fewer material rank regressions.",
        "- Section-source and all seven query-type metrics are retained in the JSON reports; PDF_HEURISTIC remains unreported where DEV has no eligible cases.",
        "",
        f"RECOMMENDED_NEXT_ACTION = {recommendation}",
        "",
        "No Hybrid, BM25 retrieval experiment, reranker, Holdout, Qwen/DashScope, or Trusted QA evaluation was run.",
    ]
    write_text_new(staging / "embedding_enrichment_report.md", "\n".join(lines))
    staging.replace(args.report_dir)
    summary = {
        "status": "PASS",
        "best_representation": best_mode.value,
        "top50_recovered_count": best_delta["counts"]["RECOVERED"],
        "top5_recovered_count": best_delta["counts"]["TOP5_RECOVERED"],
        "regression_count": best_delta["counts"]["REGRESSED"],
        "field_improved": improvements["field"],
        "exact_term_improved": improvements["exact_term"],
        "dependency_improved": improvements["dependency"],
        "semantic_regression": semantic_status,
        "dense_representation_deficiency_confirmed": deficiency,
        "recommended_next_action": recommendation,
        "holdout_evaluated": False,
        "hybrid_run": False,
        "reranker_run": False,
        "online_models_called": False,
        "body_text_logged": False,
    }
    for mode in MODES:
        value = metrics[mode.value]["overall"]
        summary[mode.value] = {
            "hit1": value["hit_at_k"]["1"],
            "hit5": value["hit_at_k"]["5"],
            "hit20": value["hit_at_k"]["20"],
            "hit50": value["hit_at_k"]["50"],
        }
    print(json.dumps(summary, ensure_ascii=False))


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser()
    result.add_argument("action", choices=("embed", "index", "evaluate"))
    result.add_argument("--mode", type=mode_from_arg)
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
        default=Path("reports/rd_v2_embedding_enrichment"),
    )
    result.add_argument("--model-snapshot", type=Path)
    result.add_argument("--threads", type=int, default=1)
    result.add_argument("--batch-size", type=int, default=8)
    result.add_argument("--max-length", type=int, default=512)
    result.add_argument("--resume-partial", action="store_true")
    return result


def main() -> None:
    args = parser().parse_args()
    if args.threads != 1:
        raise SystemExit("Windows runtime policy requires --threads 1")
    if args.action == "embed":
        embed_mode(args)
    elif args.action == "index":
        index_mode(args)
    else:
        evaluate(args)


if __name__ == "__main__":
    main()
