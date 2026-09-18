"""Compare target-document full rebuild with formal incremental version update."""

from __future__ import annotations

import json
import os
import shutil
import sys
import tempfile
import time
from dataclasses import asdict
from pathlib import Path

import numpy as np

from benchmark_utils import read_json, reduction_percent, stats, utc_now, write_json


SCRIPT_DIR = Path(__file__).resolve().parent
BENCHMARK_ROOT = SCRIPT_DIR.parent
WORKSPACE = BENCHMARK_ROOT.parents[1]
RAG_ROOT = WORKSPACE / "RAG-Challenge-2-main"
RUNTIME_ROOT = BENCHMARK_ROOT / "runtime" / "rag_incremental"
OUTPUT = BENCHMARK_ROOT / "rag_incremental_benchmark.json"
MEASURED_RUNS = 5

sys.path.insert(0, str(RAG_ROOT))
from src.document_lifecycle import (  # noqa: E402
    RetrievalScope,
    SectionSnapshot,
    VersionLifecycleService,
)
from src.native_runtime import NativeRuntimePolicy  # noqa: E402
from src.rd_v2_runtime import (  # noqa: E402
    FINAL_DENSE_REPRESENTATION,
    FINAL_RETRIEVAL_POLICY,
    _discover_snapshot,
)


class LocalSectionEmbedder:
    """Timed local BGE CLS embeddings with no external model access."""

    def __init__(self, snapshot: Path, dimension: int, max_length: int = 512):
        os.environ["HF_HUB_OFFLINE"] = "1"
        os.environ["TRANSFORMERS_OFFLINE"] = "1"
        policy = NativeRuntimePolicy(torch_threads=1, mkldnn_enabled=False)
        policy.prepare_process_environment()
        import torch
        from transformers import AutoModel, AutoTokenizer

        policy.apply_torch(torch)
        self.torch = torch
        self.tokenizer = AutoTokenizer.from_pretrained(snapshot, local_files_only=True)
        self.model = AutoModel.from_pretrained(snapshot, local_files_only=True)
        self.model.eval()
        self.dimension = dimension
        self.max_length = max_length
        if int(self.model.config.hidden_size) != dimension:
            raise ValueError("local embedding dimension differs from frozen manifest")
        self.elapsed_seconds = 0.0
        self.encoded_text_count = 0

    def reset(self) -> None:
        self.elapsed_seconds = 0.0
        self.encoded_text_count = 0

    def encode(self, texts):
        values = list(texts)
        started = time.perf_counter()
        with self.torch.inference_mode():
            encoded = self.tokenizer(
                values,
                padding=True,
                truncation=True,
                max_length=self.max_length,
                return_tensors="pt",
            )
            vectors = self.model(**encoded).last_hidden_state[:, 0]
            vectors = self.torch.nn.functional.normalize(vectors, p=2, dim=1)
            result = vectors.cpu().numpy().astype(np.float32)
        self.elapsed_seconds += time.perf_counter() - started
        self.encoded_text_count += len(values)
        return result


class TimedLifecycleService(VersionLifecycleService):
    """Measurement-only subclass; delegates index creation unchanged."""

    def __init__(self, root: Path):
        self.index_refresh_seconds = 0.0
        super().__init__(root)

    def reset_measurements(self) -> None:
        self.index_refresh_seconds = 0.0

    def _build_active_index(self, versions, artifacts, refresh_version):
        started = time.perf_counter()
        result = super()._build_active_index(versions, artifacts, refresh_version)
        self.index_refresh_seconds += time.perf_counter() - started
        return result


def ingest(service, embedder, document, sections, *, version: int):
    return service.ingest_version(
        document_id=document["document_id"],
        project_id=document["project_id"],
        document_type=document["document_type"],
        title=document["title"],
        version_id=f"{document['document_id']}@{version}.0",
        version_label=f"V{version}.0",
        source_bytes=f"synthetic-version-{version}".encode(),
        source_name=f"synthetic_v{version}.json",
        sections=sections,
        embedder=embedder,
        activate=True,
    )


def correctness(service: TimedLifecycleService, document_id: str) -> dict:
    v1 = f"{document_id}@1.0"
    v2 = f"{document_id}@2.0"
    artifact = service._read_artifact(v2)
    query_vector = artifact["embeddings"][0]
    active = service.search(
        query_vector,
        RetrievalScope(document_ids=[document_id], active_only=True),
        top_k=5,
    )
    historical = service.search(
        query_vector,
        RetrievalScope(version_ids=[v1], active_only=False),
        top_k=5,
    )
    diff = service.diff(document_id, v1, v2)
    if not active or {row["version_id"] for row in active} != {v2}:
        raise AssertionError("active search returned the wrong version")
    if not historical or {row["version_id"] for row in historical} != {v1}:
        raise AssertionError("historical search returned the wrong version")
    expected = {"ADDED": 1, "REMOVED": 1, "MODIFIED": 2, "UNCHANGED": 9}
    if diff.summary != expected:
        raise AssertionError(f"unexpected version diff: {diff.summary}")
    return {
        "active_scope": "PASS",
        "historical_scope": "PASS",
        "version_diff": "PASS",
        "diff_summary": diff.summary,
    }


def timed_full(root: Path, embedder, document, v2) -> dict:
    service = TimedLifecycleService(root)
    embedder.reset()
    service.reset_measurements()
    started = time.perf_counter()
    report = ingest(service, embedder, document, v2, version=2)
    total = time.perf_counter() - started
    index_time = service.index_refresh_seconds
    embedding_time = embedder.elapsed_seconds
    return {
        "total_seconds": total,
        "embedding_seconds": embedding_time,
        "index_refresh_seconds": index_time,
        "document_processing_seconds": max(0.0, total - embedding_time - index_time),
        "encoded_text_count": embedder.encoded_text_count,
        "report": asdict(report),
    }


def timed_incremental(root: Path, embedder, document, v1, v2) -> tuple[dict, TimedLifecycleService]:
    service = TimedLifecycleService(root)
    ingest(service, embedder, document, v1, version=1)
    embedder.reset()
    service.reset_measurements()
    started = time.perf_counter()
    report = ingest(service, embedder, document, v2, version=2)
    total = time.perf_counter() - started
    index_time = service.index_refresh_seconds
    embedding_time = embedder.elapsed_seconds
    return (
        {
            "total_seconds": total,
            "embedding_seconds": embedding_time,
            "index_refresh_seconds": index_time,
            "document_processing_seconds": max(0.0, total - embedding_time - index_time),
            "encoded_text_count": embedder.encoded_text_count,
            "report": asdict(report),
        },
        service,
    )


def summarize_runs(runs: list[dict]) -> dict:
    return {
        "total_seconds": stats(row["total_seconds"] for row in runs),
        "embedding_seconds": stats(row["embedding_seconds"] for row in runs),
        "index_refresh_seconds": stats(row["index_refresh_seconds"] for row in runs),
        "document_processing_seconds": stats(
            row["document_processing_seconds"] for row in runs
        ),
        "encoded_text_count": sorted({row["encoded_text_count"] for row in runs}),
    }


def main() -> int:
    fixture = read_json(BENCHMARK_ROOT / "fixtures" / "incremental_versions.json")
    document = fixture["document"]
    v1 = [SectionSnapshot.model_validate(row) for row in fixture["v1"]]
    v2 = [SectionSnapshot.model_validate(row) for row in fixture["v2"]]
    manifest = read_json(
        RAG_ROOT
        / "data"
        / "rd_v2_corpus"
        / "retrieval_artifacts"
        / "rd-v2-retrieval-final-v1.0"
        / "artifact_manifest.json"
    )
    snapshot = _discover_snapshot(manifest)
    if snapshot is None:
        raise RuntimeError("local frozen embedding snapshot is unavailable")
    embedder = LocalSectionEmbedder(snapshot, int(manifest["embedding_dimension"]))
    embedder.encode(["合成本地模型预热文本"])
    embedder.reset()

    RUNTIME_ROOT.mkdir(parents=True, exist_ok=True)
    warmup_root = RUNTIME_ROOT / "warmup"
    shutil.rmtree(warmup_root, ignore_errors=True)
    timed_full(warmup_root / "full", embedder, document, v2)
    timed_incremental(warmup_root / "incremental", embedder, document, v1, v2)
    shutil.rmtree(warmup_root, ignore_errors=True)

    full_runs: list[dict] = []
    incremental_runs: list[dict] = []
    correctness_result = None
    for index in range(MEASURED_RUNS):
        with tempfile.TemporaryDirectory(prefix=f"run-{index+1:02d}-", dir=RUNTIME_ROOT) as temp:
            pair_root = Path(temp)
            if index % 2 == 0:
                full = timed_full(pair_root / "full", embedder, document, v2)
                incremental, service = timed_incremental(
                    pair_root / "incremental", embedder, document, v1, v2
                )
            else:
                incremental, service = timed_incremental(
                    pair_root / "incremental", embedder, document, v1, v2
                )
                full = timed_full(pair_root / "full", embedder, document, v2)
            correctness_result = correctness(service, document["document_id"])
            full_runs.append(full)
            incremental_runs.append(incremental)

    full_summary = summarize_runs(full_runs)
    incremental_summary = summarize_runs(incremental_runs)
    incremental_report = incremental_runs[0]["report"]
    full_required = len(v2)
    reused = int(incremental_report["reused_embeddings"])
    new_embeddings = int(incremental_report["new_embeddings"])
    if (
        full_runs[0]["encoded_text_count"] != full_required
        or new_embeddings != incremental_runs[0]["encoded_text_count"]
        or reused + new_embeddings != full_required
    ):
        raise AssertionError("embedding counts do not reconcile")
    payload = {
        "schema_version": 1,
        "benchmark": "RAG full rebuild versus incremental version update",
        "captured_at": utc_now(),
        "status": "PASS",
        "data_policy": "SYNTHETIC_OFFLINE",
        "online_models_called": False,
        "retrieval_policy": FINAL_RETRIEVAL_POLICY,
        "dense_representation": FINAL_DENSE_REPRESENTATION,
        "embedding_model": manifest["embedding_model"],
        "embedding_model_revision": manifest["embedding_model_revision"],
        "embedding_dimension": manifest["embedding_dimension"],
        "model_state": "warm local model; lifecycle cache recreated for every run",
        "full_rebuild_scope": "target document from normalized SectionSnapshot input",
        "upstream_parse_scope": "excluded equally; formal lifecycle API receives normalized sections",
        "index_refresh_strategy": incremental_report["index_refresh_strategy"],
        "warmup_pairs": 1,
        "measured_independent_runs": MEASURED_RUNS,
        "run_order": "alternating full/incremental within independent pairs",
        "fixture": {
            "v1_sections": len(v1),
            "v2_sections": len(v2),
            "unchanged_sections": incremental_report["unchanged_sections"],
            "modified_sections": incremental_report["modified_sections"],
            "added_sections": incremental_report["added_sections"],
            "removed_sections": incremental_report["removed_sections"],
            "unchanged_share_of_v2_percent": round(
                incremental_report["unchanged_sections"] / len(v2) * 100.0, 3
            ),
        },
        "counts": {
            "total_sections": len(v2),
            "total_chunks": len(v2),
            "reused_chunks": reused,
            "new_chunks": new_embeddings,
            "total_embeddings_required_full": full_required,
            "new_embeddings_incremental": new_embeddings,
            "reused_embeddings": reused,
            "embedding_reuse_rate_percent": round(reused / full_required * 100.0, 3),
            "embedding_compute_reduction_percent": round(
                (full_required - new_embeddings) / full_required * 100.0, 3
            ),
        },
        "full_rebuild": full_summary,
        "incremental_update": incremental_summary,
        "comparison": {
            "full_rebuild_p50_seconds": full_summary["total_seconds"]["p50"],
            "incremental_update_p50_seconds": incremental_summary["total_seconds"]["p50"],
            "elapsed_reduction_percent": reduction_percent(
                full_summary["total_seconds"]["p50"],
                incremental_summary["total_seconds"]["p50"],
            ),
            "embedding_elapsed_reduction_percent": reduction_percent(
                full_summary["embedding_seconds"]["p50"],
                incremental_summary["embedding_seconds"]["p50"],
            ),
        },
        "raw_runs": {
            "full_rebuild": full_runs,
            "incremental_update": incremental_runs,
        },
        "correctness": correctness_result,
        "truthfulness_note": (
            "The lifecycle performs incremental embedding reuse, then rewrites the exact active "
            "vector matrix from cached vectors; it does not perform an in-place FAISS mutation."
        ),
    }
    write_json(OUTPUT, payload)
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
