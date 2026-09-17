"""Freeze the reviewed R&D V2 dataset, build local indexes, and run DEV dense.

The three actions are intentionally separate hard gates.  The artifact build
uses only an explicitly supplied local Hugging Face snapshot and refuses to
overwrite a completed build.  Logs contain counts and hashes, never corpus or
question text.
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
import pickle
import re
import sys
from typing import Iterable, Sequence
from zoneinfo import ZoneInfo

import numpy as np
import pypdfium2 as pdfium
from rank_bm25 import BM25Plus


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from scripts.build_rd_v2_candidate_dataset import candidates_for_document, stable_hash
from src.sectioning import SECTIONING_VERSION
from src.text_tokenization import technical_tokenize


DATASET_VERSION = "rd-v2-retrieval-v1.0"
STRESS_VERSION = "rd-v2-structure-stress-v0.1"
MODEL_ID = "BAAI/bge-small-zh-v1.5"
QUERY_PREFIX = "为这个句子生成表示以用于检索相关文章："
REQUIRED_TYPES = {
    "semantic",
    "exact_term",
    "interface",
    "field",
    "numeric",
    "dependency",
    "cross_section",
}
SECTION_SOURCES = {"WORD_OUTLINE", "PDF_HEURISTIC", "FALLBACK"}
DATASET_MUTATION_POLICY = (
    "question, expected_document_id, expected_pages, expected_section_ids, "
    "question_type, and split are immutable. Objective corrections require "
    "a new dataset version and an explicit reason."
)


if os.name == "nt":
    # A native extension access violation must terminate the worker instead of
    # opening a modal dialog that also blocks the Codex terminal session.
    ctypes.windll.kernel32.SetErrorMode(0x0001 | 0x0002 | 0x8000)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def json_load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def json_bytes(payload: object) -> bytes:
    return (json.dumps(payload, ensure_ascii=False, indent=2) + "\n").encode("utf-8")


def write_json_new(path: Path, payload: object) -> None:
    if path.exists():
        raise RuntimeError(f"Refusing to overwrite existing artifact: {path.name}")
    path.parent.mkdir(parents=True, exist_ok=True)
    partial = path.with_suffix(path.suffix + ".partial")
    if partial.exists():
        raise RuntimeError(f"Partial artifact already exists: {partial.name}")
    partial.write_bytes(json_bytes(payload))
    partial.replace(path)


def write_text_new(path: Path, value: str) -> None:
    if path.exists():
        raise RuntimeError(f"Refusing to overwrite existing artifact: {path.name}")
    path.parent.mkdir(parents=True, exist_ok=True)
    partial = path.with_suffix(path.suffix + ".partial")
    if partial.exists():
        raise RuntimeError(f"Partial artifact already exists: {partial.name}")
    partial.write_text(value.rstrip() + "\n", encoding="utf-8")
    partial.replace(path)


def normalized_question(value: str) -> str:
    return " ".join(value.casefold().split())


def safe_now() -> str:
    return datetime.now(ZoneInfo("Asia/Shanghai")).isoformat(timespec="seconds")


def load_corpus_state(corpus_root: Path, snapshot_path: Path) -> dict:
    snapshot = json_load(snapshot_path)
    normalization = json_load(corpus_root / "manifest" / "normalization_manifest.json")
    normalized_by_id = {item["document_id"]: item for item in normalization["documents"]}
    documents = {}
    for item in snapshot["documents"]:
        document_id = item["document_id"]
        metadata = normalized_by_id.get(document_id)
        if metadata is None:
            raise RuntimeError("Corpus snapshot document is absent from normalization manifest")
        repaired_path = (
            corpus_root
            / "normalized"
            / "repaired_chunked"
            / document_id
            / f"{document_id}.json"
        )
        sidecar_path = (
            corpus_root
            / "manifest"
            / "resolved_structure_sidecars"
            / f"{document_id}.json"
        )
        word_path = (
            corpus_root
            / "manifest"
            / "word_structure_sidecars"
            / f"{document_id}.json"
        )
        source_path = corpus_root / metadata["staged_relative_path"]
        pdf_path = corpus_root / metadata["normalized_relative_path"]
        checks = {
            "source_hash": sha256_file(source_path) == item["source_hash"],
            "canonical_pdf_hash": sha256_file(pdf_path) == item["canonical_pdf_hash"],
            "structure_sidecar_hash": sha256_file(sidecar_path)
            == item["structure_sidecar_hash"],
            "chunk_artifact_hash": sha256_file(repaired_path)
            == item["chunk_artifact_hash"],
            "chunker_version": item["chunker_version"] == SECTIONING_VERSION,
            "word_extractor_version": json_load(word_path)["extractor_version"]
            == item["word_structure_extractor_version"],
        }
        if not all(checks.values()):
            raise RuntimeError(
                "Current corpus no longer matches the frozen corpus snapshot: "
                + ",".join(key for key, passed in checks.items() if not passed)
            )
        repaired = json_load(repaired_path)
        sections = repaired["content"].get("sections", [])
        chunks = repaired["content"].get("chunks", [])
        if len(sections) != item["section_count"] or len(chunks) != item["chunk_count"]:
            raise RuntimeError("Current Section/Chunk counts differ from the corpus snapshot")
        pdf = pdfium.PdfDocument(str(pdf_path))
        page_count = len(pdf)
        pdf.close()
        documents[document_id] = {
            "snapshot": item,
            "metadata": metadata,
            "repaired_path": repaired_path,
            "repaired": repaired,
            "page_count": page_count,
            "section_by_id": {section["section_id"]: section for section in sections},
        }
    if set(documents) != set(normalized_by_id):
        raise RuntimeError("Corpus snapshot does not cover the complete normalized corpus")
    return {
        "snapshot": snapshot,
        "snapshot_sha256": sha256_file(snapshot_path),
        "documents": documents,
    }


def validate_answerable_cases(cases: Sequence[dict], corpus: dict) -> list[str]:
    failures = []
    known_documents = set(corpus["documents"])
    for item in cases:
        document_id = item.get("expected_document_id")
        document = corpus["documents"].get(document_id)
        if document_id not in known_documents or document is None:
            failures.append("expected_document_missing")
            continue
        pages = item.get("expected_pages") or []
        if not pages or any(
            not isinstance(page, int) or page < 1 or page > document["page_count"]
            for page in pages
        ):
            failures.append("expected_page_missing")
        section_ids = item.get("expected_section_ids") or []
        if not section_ids or any(
            section_id not in document["section_by_id"] for section_id in section_ids
        ):
            failures.append("expected_section_missing")
            continue
        actual_sources = {
            document["section_by_id"][section_id]["heading_source"]
            for section_id in section_ids
        }
        expected_sources = set(item.get("expected_section_sources") or [])
        if not actual_sources or not actual_sources <= SECTION_SOURCES:
            failures.append("section_source_invalid")
        if actual_sources != expected_sources:
            failures.append("section_source_mismatch")
    return failures


def validate_split_contract(dev: Sequence[dict], holdout: Sequence[dict], corpus: dict) -> dict:
    dev_ids = {item["question_id"] for item in dev}
    holdout_ids = {item["question_id"] for item in holdout}
    dev_clusters = {item["topic_cluster_id"] for item in dev}
    holdout_clusters = {item["topic_cluster_id"] for item in holdout}
    all_cases = list(dev) + list(holdout)
    checks = {
        "dev_count": len(dev) == 40,
        "holdout_count": len(holdout) == 20,
        "question_id_unique": len(dev_ids) == len(dev)
        and len(holdout_ids) == len(holdout)
        and not dev_ids.intersection(holdout_ids),
        "question_text_unique": len({normalized_question(item["question"]) for item in all_cases})
        == len(all_cases),
        "topic_cluster_overlap_zero": not dev_clusters.intersection(holdout_clusters),
        "dev_seven_types": REQUIRED_TYPES
        <= {item["question_type"] for item in dev},
        "holdout_seven_types": REQUIRED_TYPES
        <= {item["question_type"] for item in holdout},
        "ground_truth_references_valid": not validate_answerable_cases(all_cases, corpus),
        "corpus_snapshot_current": True,
    }
    if not all(checks.values()):
        raise RuntimeError(
            "Dataset freeze validation failed: "
            + ",".join(key for key, passed in checks.items() if not passed)
        )
    return checks


def approve_case(item: dict) -> dict:
    approved = json.loads(json.dumps(item, ensure_ascii=False))
    approved["needs_human_review"] = False
    approved["review_status"] = "APPROVED"
    approved["human_review"] = {
        "question_answerable": True,
        "expected_document_correct": True,
        "expected_pages_correct": True,
        "expected_sections_correct": True,
        "question_type_correct": True,
        "split_leakage_checked": True,
        "approve": True,
        "review_basis": "USER_CONFIRMED_BEFORE_RETRIEVAL",
    }
    return approved


def approve_negative(item: dict) -> dict:
    approved = json.loads(json.dumps(item, ensure_ascii=False))
    approved["needs_human_review"] = False
    approved["review_status"] = "APPROVED"
    approved["human_review"] = {
        "unanswerable_across_frozen_corpus": True,
        "approve": True,
        "review_basis": "USER_CONFIRMED_BEFORE_RETRIEVAL",
    }
    return approved


def select_stress_cases(
    corpus: dict,
    frozen_cases: Sequence[dict],
    source: str,
    count: int,
    preferred_types: Sequence[str],
) -> list[dict]:
    used_questions = {normalized_question(item["question"]) for item in frozen_cases}
    candidates = []
    for document_id, document in corpus["documents"].items():
        for item in candidates_for_document(document_id, document["repaired"]):
            if item["expected_section_source"] != source:
                continue
            if item["question_type"] not in preferred_types:
                continue
            question = item["question"]
            if (
                len(question) < 12
                or normalized_question(question) in used_questions
                or "该内容区段" in question
                or "Document preamble" in question
                or "Unresolved structure region" in question
            ):
                continue
            candidates.append(item)
    type_rank = {value: index for index, value in enumerate(preferred_types)}
    candidates.sort(
        key=lambda item: (
            type_rank[item["question_type"]],
            stable_hash(f"stress|{source}|{item['question_id']}", 64),
        )
    )
    selected = []
    used_sections = set()
    for item in candidates:
        section_id = item["expected_section_id"]
        if section_id in used_sections:
            continue
        stress = json.loads(json.dumps(item, ensure_ascii=False))
        stress["question_id"] = "rdss-" + stable_hash(
            f"{source}|{item['question_id']}", 20
        )
        stress["split"] = "STRUCTURE_STRESS"
        stress["needs_human_review"] = True
        stress["review_status"] = "PENDING"
        stress["excluded_from_hybrid_parameter_selection"] = True
        stress["excluded_from_main_holdout_metric"] = True
        selected.append(stress)
        used_sections.add(section_id)
        if len(selected) == count:
            break
    return selected


def freeze(args: argparse.Namespace) -> None:
    output_dir = args.output_dir / DATASET_VERSION
    staging = args.output_dir / f".{DATASET_VERSION}.freeze.partial"
    if output_dir.exists() or staging.exists():
        raise RuntimeError("Refusing to overwrite an existing frozen dataset or partial freeze")

    candidate = json_load(args.candidate)
    negative_candidate = json_load(args.unanswerable_candidate)
    if candidate.get("dataset_status") != "CANDIDATE":
        raise RuntimeError("Freeze input must be the reviewed CANDIDATE dataset")
    if candidate.get("formal_retrieval_evaluation_allowed") is not False:
        raise RuntimeError("Candidate gate was unexpectedly open before freeze")
    cases = candidate["cases"]
    dev = [approve_case(item) for item in cases if item["split"] == "DEV"]
    holdout = [approve_case(item) for item in cases if item["split"] == "HOLDOUT"]
    negatives = [approve_negative(item) for item in negative_candidate["cases"]]
    if len(negatives) != 10 or any(
        item.get("answerability") != "UNANSWERABLE"
        or item.get("excluded_from_answerable_metrics") is not True
        for item in negatives
    ):
        raise RuntimeError("Unanswerable freeze contract failed")

    corpus = load_corpus_state(args.corpus_root, args.corpus_snapshot)
    checks = validate_split_contract(dev, holdout, corpus)
    frozen_at = safe_now()
    shared = {
        "schema_version": 1,
        "dataset_version": DATASET_VERSION,
        "dataset_status": "FROZEN",
        "ground_truth_frozen": True,
        "frozen_at": frozen_at,
        "corpus_version": corpus["snapshot"]["corpus_version"],
        "corpus_snapshot_sha256": corpus["snapshot_sha256"],
        "human_review_completed": True,
        "human_review_modifications": "NONE",
        "ground_truth_adjusted_from_retrieval_results": False,
        "mutation_policy": DATASET_MUTATION_POLICY,
    }
    dev_payload = {
        **shared,
        "split": "DEV",
        "count": len(dev),
        "question_types": dict(sorted(Counter(item["question_type"] for item in dev).items())),
        "cases": dev,
    }
    holdout_payload = {
        **shared,
        "split": "HOLDOUT",
        "count": len(holdout),
        "question_types": dict(
            sorted(Counter(item["question_type"] for item in holdout).items())
        ),
        "cases": holdout,
    }
    negative_payload = {
        **shared,
        "split": "NEGATIVE",
        "count": len(negatives),
        "metric_policy": "EXCLUDED_FROM_HIT_RECALL_MRR",
        "cases": negatives,
    }

    fallback_stress = select_stress_cases(
        corpus,
        cases,
        "FALLBACK",
        4,
        ("numeric", "interface", "field", "dependency"),
    )
    pdf_stress = select_stress_cases(
        corpus,
        cases,
        "PDF_HEURISTIC",
        2,
        ("semantic", "exact_term", "dependency"),
    )
    stress_cases = fallback_stress + pdf_stress
    stress_payload = {
        "schema_version": 1,
        "dataset_version": STRESS_VERSION,
        "dataset_status": "CANDIDATE",
        "ground_truth_frozen": False,
        "created_at": frozen_at,
        "corpus_version": corpus["snapshot"]["corpus_version"],
        "purpose": "SECTION_SOURCE_ROBUSTNESS_ANALYSIS_ONLY",
        "excluded_from_hybrid_parameter_selection": True,
        "excluded_from_main_holdout_metric": True,
        "needs_human_review": True,
        "summary": {
            "total": len(stress_cases),
            "FALLBACK": len(fallback_stress),
            "PDF_HEURISTIC": len(pdf_stress),
        },
        "pdf_heuristic_note": (
            "Candidate questions were found; they require separate human review."
            if pdf_stress
            else "No natural candidate with explicit ground truth was found; no question was fabricated."
        ),
        "cases": stress_cases,
    }

    staging.mkdir(parents=True)
    datasets = {
        "dev_dataset.json": dev_payload,
        "holdout_dataset.json": holdout_payload,
        "unanswerable_set.json": negative_payload,
        "structure_stress_set.json": stress_payload,
    }
    for name, payload in datasets.items():
        write_json_new(staging / name, payload)
    file_records = {
        name: {
            "sha256": sha256_file(staging / name),
            "bytes": (staging / name).stat().st_size,
        }
        for name in datasets
    }
    manifest = {
        "schema_version": 1,
        "dataset_version": DATASET_VERSION,
        "dataset_status": "FROZEN",
        "ground_truth_frozen": True,
        "frozen_at": frozen_at,
        "human_review_completed": True,
        "human_review_scope": {"DEV": "40/40", "HOLDOUT": "20/20", "unanswerable": "10/10"},
        "human_review_modifications": "NONE",
        "ground_truth_adjusted_from_retrieval_results": False,
        "counts": {"DEV": len(dev), "HOLDOUT": len(holdout), "unanswerable": len(negatives)},
        "corpus_snapshot_id": corpus["snapshot"]["corpus_version"],
        "corpus_snapshot_sha256": corpus["snapshot_sha256"],
        "question_ids": {
            "DEV": [item["question_id"] for item in dev],
            "HOLDOUT": [item["question_id"] for item in holdout],
            "unanswerable": [item["question_id"] for item in negatives],
        },
        "candidate_inputs": {
            "candidate_dataset_sha256": sha256_file(args.candidate),
            "unanswerable_candidate_sha256": sha256_file(args.unanswerable_candidate),
        },
        "dataset_files": file_records,
        "static_validation": {"status": "PASS", "checks": checks},
        "mutation_policy": DATASET_MUTATION_POLICY,
        "formal_retrieval_evaluation_allowed": True,
    }
    write_json_new(staging / "dataset_freeze_manifest.json", manifest)
    staging.replace(output_dir)
    print(
        json.dumps(
            {
                "action": "freeze",
                "status": "PASS",
                "dataset_version": DATASET_VERSION,
                "dev": len(dev),
                "holdout": len(holdout),
                "unanswerable": len(negatives),
                "stress_fallback": len(fallback_stress),
                "stress_pdf_heuristic": len(pdf_stress),
                "body_text_logged": False,
            },
            ensure_ascii=False,
        )
    )


class LocalBGEEmbedder:
    def __init__(self, snapshot: Path, *, threads: int, batch_size: int, max_length: int):
        if not snapshot.is_dir() or not (snapshot / "config.json").is_file():
            raise RuntimeError("The explicit local embedding model snapshot is incomplete")
        os.environ["HF_HUB_OFFLINE"] = "1"
        os.environ["TRANSFORMERS_OFFLINE"] = "1"
        os.environ["OMP_NUM_THREADS"] = str(max(1, threads))
        os.environ["MKL_NUM_THREADS"] = str(max(1, threads))
        import torch
        from transformers import AutoModel, AutoTokenizer

        torch.set_num_threads(max(1, threads))
        torch.set_num_interop_threads(1)
        torch.backends.mkldnn.enabled = False
        self.torch = torch
        self.batch_size = batch_size
        self.max_length = max_length
        self.snapshot = snapshot
        self.tokenizer = AutoTokenizer.from_pretrained(snapshot, local_files_only=True)
        self.model = AutoModel.from_pretrained(snapshot, local_files_only=True)
        self.model.eval()
        self.dimension = int(self.model.config.hidden_size)

    def encode(
        self,
        texts: Sequence[str],
        *,
        prefix: str = "",
        log_progress: bool = False,
    ) -> np.ndarray:
        output = np.empty((len(texts), self.dimension), dtype=np.float32)
        total = len(texts)
        with self.torch.inference_mode():
            for start in range(0, total, self.batch_size):
                batch = [prefix + value for value in texts[start : start + self.batch_size]]
                encoded = self.tokenizer(
                    batch,
                    padding=True,
                    truncation=True,
                    max_length=self.max_length,
                    return_tensors="pt",
                )
                vectors = self.model(**encoded).last_hidden_state[:, 0]
                vectors = self.torch.nn.functional.normalize(vectors, p=2, dim=1)
                values = vectors.cpu().numpy().astype(np.float32)
                self._validate_batch(values)
                output[start : start + len(batch)] = values
                completed = start + len(batch)
                if log_progress and (completed == total or completed % (self.batch_size * 10) == 0):
                    print(
                        json.dumps(
                            {"phase": "local_embedding", "completed": completed, "total": total}
                        ),
                        flush=True,
                    )
        return output

    def encode_to_checkpoint(
        self,
        texts: Sequence[str],
        output_path: Path,
        progress_path: Path,
    ) -> tuple[np.ndarray, bool]:
        total = len(texts)
        resumed = False
        if output_path.exists() or progress_path.exists():
            if not output_path.is_file() or not progress_path.is_file():
                raise RuntimeError("Embedding checkpoint is incomplete")
            progress = json_load(progress_path)
            completed = int(progress.get("completed", -1))
            if (
                progress.get("total") != total
                or progress.get("dimension") != self.dimension
                or completed < 0
                or completed > total
            ):
                raise RuntimeError("Embedding checkpoint metadata mismatch")
            matrix = np.lib.format.open_memmap(output_path, mode="r+")
            if matrix.shape != (total, self.dimension) or matrix.dtype != np.float32:
                raise RuntimeError("Embedding checkpoint matrix mismatch")
            resumed = completed > 0
        else:
            completed = 0
            matrix = np.lib.format.open_memmap(
                output_path,
                mode="w+",
                dtype=np.float32,
                shape=(total, self.dimension),
            )
            self._write_progress(progress_path, completed, total)

        with self.torch.inference_mode():
            for start in range(completed, total, self.batch_size):
                batch = list(texts[start : start + self.batch_size])
                encoded = self.tokenizer(
                    batch,
                    padding=True,
                    truncation=True,
                    max_length=self.max_length,
                    return_tensors="pt",
                )
                vectors = self.model(**encoded).last_hidden_state[:, 0]
                vectors = self.torch.nn.functional.normalize(vectors, p=2, dim=1)
                values = vectors.cpu().numpy().astype(np.float32)
                self._validate_batch(values)
                matrix[start : start + len(batch)] = values
                matrix.flush()
                completed = start + len(batch)
                self._write_progress(progress_path, completed, total)
                if completed == total or completed % (self.batch_size * 10) == 0:
                    print(
                        json.dumps(
                            {"phase": "local_embedding", "completed": completed, "total": total}
                        ),
                        flush=True,
                    )
        return np.asarray(matrix), resumed

    @staticmethod
    def _validate_batch(values: np.ndarray) -> None:
        if not np.isfinite(values).all():
            raise RuntimeError("Local embedding batch contains non-finite values")
        norms = np.linalg.norm(values, axis=1)
        if not np.allclose(norms, 1.0, atol=1e-4):
            raise RuntimeError("Local embedding batch is not unit normalized")

    def _write_progress(self, path: Path, completed: int, total: int) -> None:
        payload = {
            "schema_version": 1,
            "model": MODEL_ID,
            "model_revision": self.snapshot.name,
            "dimension": self.dimension,
            "completed": completed,
            "total": total,
            "status": "COMPLETE" if completed == total else "IN_PROGRESS",
            "body_text_logged": False,
        }
        partial = path.with_suffix(path.suffix + ".partial")
        partial.write_bytes(json_bytes(payload))
        partial.replace(path)


def verify_dataset_manifest(dataset_dir: Path) -> tuple[dict, dict, dict, dict]:
    manifest_path = dataset_dir / "dataset_freeze_manifest.json"
    manifest = json_load(manifest_path)
    if (
        manifest.get("dataset_status") != "FROZEN"
        or manifest.get("ground_truth_frozen") is not True
        or manifest.get("human_review_completed") is not True
        or manifest.get("formal_retrieval_evaluation_allowed") is not True
    ):
        raise RuntimeError("Formal retrieval is blocked by the dataset freeze manifest")
    loaded = {}
    for name in ("dev_dataset.json", "holdout_dataset.json", "unanswerable_set.json"):
        path = dataset_dir / name
        record = manifest["dataset_files"][name]
        if sha256_file(path) != record["sha256"]:
            raise RuntimeError(f"Frozen dataset hash mismatch: {name}")
        loaded[name] = json_load(path)
    return (
        manifest,
        loaded["dev_dataset.json"],
        loaded["holdout_dataset.json"],
        loaded["unanswerable_set.json"],
    )


def collect_chunks(corpus_root: Path, snapshot: dict) -> list[dict]:
    chunks = []
    for item in sorted(snapshot["documents"], key=lambda value: value["document_id"]):
        document_id = item["document_id"]
        path = (
            corpus_root
            / "normalized"
            / "repaired_chunked"
            / document_id
            / f"{document_id}.json"
        )
        document = json_load(path)
        for chunk in document["content"].get("chunks", []):
            value = dict(chunk)
            value["document_id"] = document_id
            value["page"] = int(value.get("page", value.get("page_number", 0)))
            value["page_number"] = value["page"]
            chunks.append(value)
    chunks.sort(key=lambda item: (item["document_id"], int(item.get("id", 0)), item["chunk_id"]))
    if not chunks or any(not item.get("text", "").strip() for item in chunks):
        raise RuntimeError("Frozen child chunk artifact contains empty text")
    if len({item["chunk_id"] for item in chunks}) != len(chunks):
        raise RuntimeError("Frozen child chunk IDs are not globally unique")
    return chunks


def build_artifacts(args: argparse.Namespace) -> None:
    manifest, dev, holdout, _ = verify_dataset_manifest(args.dataset_dir)
    corpus = load_corpus_state(args.corpus_root, args.corpus_snapshot)
    if manifest["corpus_snapshot_sha256"] != corpus["snapshot_sha256"]:
        raise RuntimeError("Dataset freeze and current corpus snapshot disagree")
    validate_split_contract(dev["cases"], holdout["cases"], corpus)

    final_dir = args.artifact_root / DATASET_VERSION
    staging = args.artifact_root / f".{DATASET_VERSION}.build.partial"
    if final_dir.exists():
        raise RuntimeError("Refusing to recompute or overwrite retrieval artifacts")
    if staging.exists() and not args.resume_partial:
        raise RuntimeError("Partial build exists; use --resume-partial after auditing it")
    staging.mkdir(parents=True, exist_ok=True)
    chunks = collect_chunks(args.corpus_root, corpus["snapshot"])
    child_path = staging / "child_chunks.jsonl"
    if child_path.exists():
        existing_chunks = []
        with child_path.open("r", encoding="utf-8") as stream:
            for line in stream:
                existing_chunks.append(json.loads(line))
        if existing_chunks != chunks:
            raise RuntimeError("Partial child chunk artifact does not match the frozen corpus")
    else:
        with child_path.open("x", encoding="utf-8") as stream:
            for item in chunks:
                stream.write(json.dumps(item, ensure_ascii=False) + "\n")

    embedder = LocalBGEEmbedder(
        args.model_snapshot,
        threads=args.threads,
        batch_size=args.batch_size,
        max_length=args.max_length,
    )
    embedding_path = staging / "embeddings.npy"
    progress_path = staging / "embedding_build_state.json"
    embeddings, embedding_resumed = embedder.encode_to_checkpoint(
        [item["text"] for item in chunks], embedding_path, progress_path
    )
    if embeddings.shape != (len(chunks), embedder.dimension):
        raise RuntimeError("Embedding matrix shape contract failed")
    norms = np.linalg.norm(embeddings, axis=1)
    if not np.allclose(norms, 1.0, atol=1e-4):
        raise RuntimeError("Corpus embeddings are not unit normalized")
    embedding_dimension = embedder.dimension
    del embedder
    gc.collect()
    # Import FAISS only after all PyTorch work is complete.  Loading both native
    # runtimes before long CPU inference was unstable in this Windows runtime.
    import faiss

    faiss_path = staging / "child_vectors.faiss"
    if faiss_path.exists():
        index = faiss.read_index(str(faiss_path))
    else:
        index = faiss.IndexFlatIP(embedding_dimension)
        index.add(np.ascontiguousarray(embeddings, dtype=np.float32))
        faiss.write_index(index, str(faiss_path))
    if index.ntotal != len(chunks):
        raise RuntimeError("FAISS vector count does not match child chunks")

    bm25_path = staging / "bm25_index.pkl"
    if bm25_path.exists():
        with bm25_path.open("rb") as stream:
            bm25_payload = pickle.load(stream)
        if bm25_payload.get("chunk_ids") != [item["chunk_id"] for item in chunks]:
            raise RuntimeError("Partial BM25 artifact does not match frozen chunks")
        bm25 = bm25_payload["index"]
    else:
        tokenized = [technical_tokenize(item["text"]) for item in chunks]
        bm25 = BM25Plus(tokenized)
        with bm25_path.open("xb") as stream:
            pickle.dump(
                {"index": bm25, "chunk_ids": [item["chunk_id"] for item in chunks]},
                stream,
                protocol=pickle.HIGHEST_PROTOCOL,
            )

    sidecar_hashes = "|".join(
        item["structure_sidecar_hash"] for item in corpus["snapshot"]["documents"]
    )
    artifact_files = {
        path.name: {"sha256": sha256_file(path), "bytes": path.stat().st_size}
        for path in (child_path, embedding_path, progress_path, faiss_path, bm25_path)
    }
    artifact_manifest = {
        "schema_version": 1,
        "build_status": "PASS",
        "built_at": safe_now(),
        "dataset_version": DATASET_VERSION,
        "dataset_freeze_manifest_sha256": sha256_file(
            args.dataset_dir / "dataset_freeze_manifest.json"
        ),
        "corpus_version": corpus["snapshot"]["corpus_version"],
        "corpus_snapshot_sha256": corpus["snapshot_sha256"],
        "chunker_version": SECTIONING_VERSION,
        "structure_version": "sha256:" + hashlib.sha256(
            sidecar_hashes.encode("ascii")
        ).hexdigest(),
        "child_chunk_count": len(chunks),
        "embedding": {
            "provider": "local_huggingface_transformers",
            "model": MODEL_ID,
            "model_revision": args.model_snapshot.name,
            "model_config_sha256": sha256_file(args.model_snapshot / "config.json"),
            "dimension": embedding_dimension,
            "dtype": "float32",
            "pooling": "CLS",
            "normalization": "L2_UNIT",
            "document_prefix": "",
            "query_prefix": QUERY_PREFIX,
            "max_length": args.max_length,
            "corpus_embedding_passes": 1,
            "resumed_from_checkpoint": embedding_resumed,
            "interrupted_unmaterialized_attempts_before_checkpointing": args.interrupted_attempts,
            "discarded_corrupt_checkpoint_rows": args.discarded_corrupt_checkpoint_rows,
            "online_access": False,
        },
        "vector_count": int(index.ntotal),
        "faiss": {"index_type": type(index).__name__, "metric": "INNER_PRODUCT", "vector_count": int(index.ntotal)},
        "bm25": {
            "index_type": type(bm25).__name__,
            "tokenizer": "src.text_tokenization.technical_tokenize",
            "corpus_size": len(chunks),
        },
        "artifact_files": artifact_files,
        "sensitive_body_text_logged": False,
        "online_models_called": False,
        "native_runtime_safety": {
            "faiss_imported_after_pytorch_embedding": True,
            "torch_mkldnn_enabled": False,
            "torch_threads": args.threads,
            "windows_native_error_dialog_suppressed": os.name == "nt",
            "batch_finite_validation": True,
            "batch_unit_norm_validation": True,
        },
    }
    write_json_new(staging / "artifact_manifest.json", artifact_manifest)
    # ``encode_to_checkpoint`` returns a view backed by a NumPy memmap.  Windows
    # refuses to rename the containing directory until that handle is released.
    del embeddings
    gc.collect()
    staging.replace(final_dir)
    print(
        json.dumps(
            {
                "action": "build-artifacts",
                "status": "PASS",
                "vectors": int(index.ntotal),
                "dimension": embedding_dimension,
                "bm25_chunks": len(chunks),
                "corpus_embedding_passes": 1,
                "resumed_from_checkpoint": embedding_resumed,
                "online_models_called": False,
                "body_text_logged": False,
            }
        )
    )


def verify_artifacts(artifact_dir: Path, dataset_dir: Path, corpus_snapshot: Path) -> dict:
    manifest = json_load(artifact_dir / "artifact_manifest.json")
    if manifest.get("build_status") != "PASS" or manifest.get("online_models_called") is not False:
        raise RuntimeError("Retrieval artifact manifest is not ready")
    if manifest["dataset_freeze_manifest_sha256"] != sha256_file(
        dataset_dir / "dataset_freeze_manifest.json"
    ):
        raise RuntimeError("Retrieval artifacts were built from a different dataset freeze")
    if manifest["corpus_snapshot_sha256"] != sha256_file(corpus_snapshot):
        raise RuntimeError("Retrieval artifacts were built from a different corpus snapshot")
    for name, record in manifest["artifact_files"].items():
        if sha256_file(artifact_dir / name) != record["sha256"]:
            raise RuntimeError(f"Retrieval artifact hash mismatch: {name}")
    return manifest


def metric_block(records: Sequence[dict], ks: Sequence[int] = (1, 3, 5)) -> dict:
    if not records:
        return {
            "evaluated_questions": 0,
            "hit_at_k": {str(k): None for k in ks},
            "recall_at_k": {str(k): None for k in ks},
            "mrr": None,
        }
    return {
        "evaluated_questions": len(records),
        "hit_at_k": {
            str(k): round(sum(item["hit_at_k"][str(k)] for item in records) / len(records), 6)
            for k in ks
        },
        "recall_at_k": {
            str(k): round(sum(item["recall_at_k"][str(k)] for item in records) / len(records), 6)
            for k in ks
        },
        "mrr": round(sum(item["reciprocal_rank"] for item in records) / len(records), 6),
    }


def embed_dev_queries(args: argparse.Namespace) -> None:
    _, dev, holdout, _ = verify_dataset_manifest(args.dataset_dir)
    corpus = load_corpus_state(args.corpus_root, args.corpus_snapshot)
    validate_split_contract(dev["cases"], holdout["cases"], corpus)
    artifact = verify_artifacts(args.artifact_dir, args.dataset_dir, args.corpus_snapshot)
    if artifact["embedding"]["model_revision"] != args.model_snapshot.name:
        raise RuntimeError("Dense query model revision differs from corpus embedding revision")

    vector_path = args.dataset_dir / "dev_query_embeddings.npy"
    manifest_path = args.dataset_dir / "dev_query_embedding_manifest.json"
    if vector_path.exists() or manifest_path.exists():
        raise RuntimeError("Refusing to recompute DEV query embeddings")
    embedder = LocalBGEEmbedder(
        args.model_snapshot,
        threads=args.threads,
        batch_size=args.query_batch_size,
        max_length=artifact["embedding"]["max_length"],
    )
    questions = [item["question"] for item in dev["cases"]]
    query_vectors = embedder.encode(questions, prefix=QUERY_PREFIX, log_progress=False)
    if query_vectors.shape != (len(questions), artifact["embedding"]["dimension"]):
        raise RuntimeError("DEV query embedding shape mismatch")
    with vector_path.open("xb") as stream:
        np.save(stream, query_vectors, allow_pickle=False)
    query_manifest = {
        "schema_version": 1,
        "status": "READY",
        "dataset_version": DATASET_VERSION,
        "dev_dataset_sha256": sha256_file(args.dataset_dir / "dev_dataset.json"),
        "artifact_manifest_sha256": sha256_file(args.artifact_dir / "artifact_manifest.json"),
        "model": MODEL_ID,
        "model_revision": args.model_snapshot.name,
        "query_prefix": QUERY_PREFIX,
        "count": len(questions),
        "dimension": int(query_vectors.shape[1]),
        "normalization": "L2_UNIT",
        "query_vectors_sha256": sha256_file(vector_path),
        "pytorch_process_loaded_faiss": False,
        "online_models_called": False,
        "body_text_logged": False,
    }
    write_json_new(manifest_path, query_manifest)
    print(
        json.dumps(
            {
                "action": "embed-dev-queries",
                "status": "PASS",
                "queries": len(questions),
                "dimension": int(query_vectors.shape[1]),
                "faiss_loaded": False,
                "online_models_called": False,
                "body_text_logged": False,
            }
        )
    )


def evaluate_case(item: dict, ranked_pages: Sequence[dict], ks: Sequence[int] = (1, 3, 5)) -> dict:
    expected = {
        (item["expected_document_id"], int(page)) for page in item["expected_pages"]
    }
    ranked_keys = [(row["document_id"], int(row["page_number"])) for row in ranked_pages]
    hit_at_k = {}
    recall_at_k = {}
    for k in ks:
        retrieved = set(ranked_keys[:k])
        relevant = len(expected.intersection(retrieved))
        hit_at_k[str(k)] = int(relevant > 0)
        recall_at_k[str(k)] = round(relevant / len(expected), 6)
    first_rank = next(
        (rank for rank, key in enumerate(ranked_keys, start=1) if key in expected), None
    )
    return {
        "question_id": item["question_id"],
        "question_type": item["question_type"],
        "expected_document_id": item["expected_document_id"],
        "expected_pages": item["expected_pages"],
        "expected_section_sources": item["expected_section_sources"],
        "hit_at_k": hit_at_k,
        "recall_at_k": recall_at_k,
        "reciprocal_rank": round(1.0 / first_rank, 6) if first_rank else 0.0,
        "retrieved_pages": list(ranked_pages[: max(ks)]),
    }


def dense(args: argparse.Namespace) -> None:
    _, dev, holdout, _ = verify_dataset_manifest(args.dataset_dir)
    corpus = load_corpus_state(args.corpus_root, args.corpus_snapshot)
    validate_split_contract(dev["cases"], holdout["cases"], corpus)
    artifact = verify_artifacts(args.artifact_dir, args.dataset_dir, args.corpus_snapshot)
    output_json = args.dataset_dir / "dense_baseline.json"
    output_report = args.dataset_dir / "dense_baseline_report.md"
    final_report = args.dataset_dir / "retrieval_validation_report.md"
    if any(path.exists() for path in (output_json, output_report, final_report)):
        raise RuntimeError("Refusing to overwrite an existing dense baseline")

    chunks = []
    with (args.artifact_dir / "child_chunks.jsonl").open("r", encoding="utf-8") as stream:
        for line in stream:
            chunks.append(json.loads(line))
    query_path = args.dataset_dir / "dev_query_embeddings.npy"
    query_manifest_path = args.dataset_dir / "dev_query_embedding_manifest.json"
    query_manifest = json_load(query_manifest_path)
    if (
        query_manifest.get("status") != "READY"
        or query_manifest.get("pytorch_process_loaded_faiss") is not False
        or query_manifest.get("dev_dataset_sha256")
        != sha256_file(args.dataset_dir / "dev_dataset.json")
        or query_manifest.get("artifact_manifest_sha256")
        != sha256_file(args.artifact_dir / "artifact_manifest.json")
        or query_manifest.get("model_revision") != artifact["embedding"]["model_revision"]
        or query_manifest.get("query_vectors_sha256") != sha256_file(query_path)
    ):
        raise RuntimeError("DEV query embedding manifest validation failed")
    query_vectors = np.load(query_path, allow_pickle=False)
    if query_vectors.shape != (
        len(dev["cases"]),
        artifact["embedding"]["dimension"],
    ) or not np.isfinite(query_vectors).all():
        raise RuntimeError("DEV query embedding matrix validation failed")
    # This process has never imported PyTorch/Transformers.  Loading FAISS here
    # avoids the duplicate OpenMP runtime detected on Windows.
    import faiss

    index = faiss.read_index(str(args.artifact_dir / "child_vectors.faiss"))
    if index.ntotal != len(chunks) or index.ntotal != artifact["vector_count"]:
        raise RuntimeError("Dense index and chunk metadata count mismatch")
    search_k = min(index.ntotal, max(200, args.top_k * 20))
    scores, indices = index.search(np.ascontiguousarray(query_vectors), search_k)
    records = []
    for item, row_scores, row_indices in zip(dev["cases"], scores, indices):
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
                    "chunk_id": chunk["chunk_id"],
                    "section_id": chunk.get("section_id"),
                    "section_source": chunk.get("section_source"),
                    "cosine_similarity": round(float(score), 6),
                }
            )
            if len(pages) == args.top_k:
                break
        if len(pages) < args.top_k:
            raise RuntimeError("Dense search did not yield enough unique physical pages")
        records.append(evaluate_case(item, pages))

    by_type = defaultdict(list)
    by_source = defaultdict(list)
    for item in records:
        by_type[item["question_type"]].append(item)
        for source in set(item["expected_section_sources"]):
            by_source[source].append(item)
    overall = metric_block(records)
    type_metrics = {key: metric_block(by_type[key]) for key in sorted(REQUIRED_TYPES)}
    source_metrics = {key: metric_block(by_source[key]) for key in sorted(SECTION_SOURCES)}
    failures = [
        {
            "question_id": item["question_id"],
            "question_type": item["question_type"],
            "expected_document_id": item["expected_document_id"],
            "expected_pages": item["expected_pages"],
            "top5": item["retrieved_pages"],
        }
        for item in records
        if item["hit_at_k"]["5"] == 0
    ]
    payload = {
        "schema_version": 1,
        "run_name": "generic_dense",
        "run_status": "PASS",
        "run_at": safe_now(),
        "dataset_version": DATASET_VERSION,
        "dataset_split": "DEV",
        "dataset_hash": sha256_file(args.dataset_dir / "dev_dataset.json"),
        "corpus_version": artifact["corpus_version"],
        "artifact_manifest_sha256": sha256_file(args.artifact_dir / "artifact_manifest.json"),
        "embedding": artifact["embedding"],
        "retrieval_unit": "PHYSICAL_PAGE_DEDUPED_FROM_CHILD_DENSE_RANK",
        "ranking": "COSINE_SIMILARITY_VIA_NORMALIZED_INNER_PRODUCT",
        "top_k": args.top_k,
        "hybrid_used": False,
        "bm25_used": False,
        "reranker_used": False,
        "holdout_loaded_for_validation_only": True,
        "holdout_evaluated": False,
        "online_models_called": False,
        "native_runtime_isolation": {
            "query_embedding_process": "PYTORCH_ONLY",
            "retrieval_process": "FAISS_ONLY",
            "kmp_duplicate_lib_ok_used": False,
        },
        "metrics": {
            "overall": overall,
            "by_question_type": type_metrics,
            "by_section_source": source_metrics,
        },
        "failures_at_5": failures,
        "per_question": records,
        "sensitive_body_text_logged": False,
    }
    write_json_new(output_json, payload)

    def metric_row(label: str, value: dict) -> str:
        hit = value["hit_at_k"]
        recall = value["recall_at_k"]
        return (
            f"| {label} | {value['evaluated_questions']} | {hit['1']} | {hit['3']} | "
            f"{hit['5']} | {recall['1']} | {recall['3']} | {recall['5']} | {value['mrr']} |"
        )

    lines = [
        "# R&D V2 DEV Dense Baseline",
        "",
        "RUN = generic_dense",
        "",
        "DATASET_STATUS = FROZEN",
        "",
        "HYBRID_RUN = NO",
        "",
        "HOLDOUT_EVALUATED = NO",
        "",
        "ONLINE_MODELS_CALLED = NO",
        "",
        "Retrieval ranks unique physical pages using the highest-scoring child chunk for each `(document_id, page_number)`.",
        "",
        "| Scope | N | Hit@1 | Hit@3 | Hit@5 | Recall@1 | Recall@3 | Recall@5 | MRR |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|",
        metric_row("Overall DEV", overall),
        "",
        "## By question type",
        "",
        "| Type | N | Hit@1 | Hit@3 | Hit@5 | Recall@1 | Recall@3 | Recall@5 | MRR |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    lines.extend(metric_row(key, type_metrics[key]) for key in sorted(type_metrics))
    lines.extend(
        [
            "",
            "## By expected Section Source",
            "",
            "| Source | N | Hit@1 | Hit@3 | Hit@5 | Recall@1 | Recall@3 | Recall@5 | MRR |",
            "|---|---:|---:|---:|---:|---:|---:|---:|---:|",
        ]
    )
    lines.extend(metric_row(key, source_metrics[key]) for key in sorted(source_metrics))
    lines.extend(
        [
            "",
            f"FAILURES_AT_5 = {len(failures)}",
            "",
            "Structure Stress Set remains separate and was not evaluated in this baseline.",
        ]
    )
    write_text_new(output_report, "\n".join(lines))

    final_lines = [
        "# R&D V2 Real Retrieval Validation — Dense Stage",
        "",
        "DATASET_FROZEN = YES",
        f"DATASET_VERSION = {DATASET_VERSION}",
        "",
        f"DEV_COUNT = {len(dev['cases'])}",
        f"HOLDOUT_COUNT = {len(holdout['cases'])}",
        "UNANSWERABLE_COUNT = 10",
        "",
        "STRUCTURE_STRESS_SET_CREATED = YES",
        "",
        "ARTIFACT_BUILD = PASS",
        f"EMBEDDING_VECTOR_COUNT = {artifact['vector_count']}",
        f"FAISS_VECTOR_COUNT = {artifact['faiss']['vector_count']}",
        f"BM25_CHUNK_COUNT = {artifact['bm25']['corpus_size']}",
        "",
        f"DENSE_DEV_HIT1 = {overall['hit_at_k']['1']}",
        f"DENSE_DEV_HIT3 = {overall['hit_at_k']['3']}",
        f"DENSE_DEV_HIT5 = {overall['hit_at_k']['5']}",
        f"DENSE_DEV_RECALL5 = {overall['recall_at_k']['5']}",
        f"DENSE_DEV_MRR = {overall['mrr']}",
        "",
        "DENSE_BASELINE_READY = YES",
        "",
        "Hybrid Ablation, Holdout Evaluation, answer generation, Trusted QA, and online model calls were not run.",
    ]
    write_text_new(final_report, "\n".join(final_lines))
    print(
        json.dumps(
            {
                "action": "dense",
                "status": "PASS",
                "evaluated_dev": len(records),
                "hit_at_1": overall["hit_at_k"]["1"],
                "hit_at_3": overall["hit_at_k"]["3"],
                "hit_at_5": overall["hit_at_k"]["5"],
                "recall_at_5": overall["recall_at_k"]["5"],
                "mrr": overall["mrr"],
                "failures_at_5": len(failures),
                "hybrid_run": False,
                "holdout_evaluated": False,
                "online_models_called": False,
                "body_text_logged": False,
            }
        )
    )


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser()
    result.add_argument(
        "action", choices=("freeze", "build-artifacts", "embed-dev-queries", "dense")
    )
    result.add_argument("--corpus-root", type=Path, default=Path("data/rd_v2_corpus"))
    result.add_argument(
        "--corpus-snapshot",
        type=Path,
        default=Path("reports/rd_v2_real_retrieval_validation/corpus_snapshot.json"),
    )
    result.add_argument(
        "--candidate",
        type=Path,
        default=Path("reports/rd_v2_real_retrieval_validation/candidate_dataset.json"),
    )
    result.add_argument(
        "--unanswerable-candidate",
        type=Path,
        default=Path("reports/rd_v2_real_retrieval_validation/unanswerable_set.json"),
    )
    result.add_argument(
        "--output-dir",
        type=Path,
        default=Path("reports/rd_v2_real_retrieval_validation"),
    )
    result.add_argument(
        "--dataset-dir",
        type=Path,
        default=Path(f"reports/rd_v2_real_retrieval_validation/{DATASET_VERSION}"),
    )
    result.add_argument(
        "--artifact-root",
        type=Path,
        default=Path("data/rd_v2_corpus/retrieval_artifacts"),
    )
    result.add_argument(
        "--artifact-dir",
        type=Path,
        default=Path(f"data/rd_v2_corpus/retrieval_artifacts/{DATASET_VERSION}"),
    )
    result.add_argument("--model-snapshot", type=Path)
    result.add_argument("--threads", type=int, default=1)
    result.add_argument("--batch-size", type=int, default=8)
    result.add_argument("--query-batch-size", type=int, default=32)
    result.add_argument("--max-length", type=int, default=512)
    result.add_argument("--top-k", type=int, default=5)
    result.add_argument("--resume-partial", action="store_true")
    result.add_argument("--interrupted-attempts", type=int, default=0)
    result.add_argument("--discarded-corrupt-checkpoint-rows", type=int, default=0)
    return result


def main() -> None:
    args = parser().parse_args()
    if args.action in {"build-artifacts", "embed-dev-queries"} and args.model_snapshot is None:
        raise SystemExit("--model-snapshot is required for offline-only embedding")
    if args.action == "freeze":
        freeze(args)
    elif args.action == "build-artifacts":
        build_artifacts(args)
    elif args.action == "embed-dev-queries":
        embed_dev_queries(args)
    else:
        dense(args)


if __name__ == "__main__":
    main()
