"""Offline latency sample for the frozen 5k-chunk V3 scope path."""

from __future__ import annotations

import argparse
import json
import statistics
import sys
import time
from pathlib import Path

import numpy as np

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.document_lifecycle import RetrievalScope
from src.rd_v2_runtime import FrozenArtifactValidator, FrozenDenseRetriever, RDV2Settings


class FixedEmbedder:
    def __init__(self, vector):
        self.vector = np.asarray([vector], dtype=np.float32)

    def encode(self, texts):
        return np.repeat(self.vector, len(texts), axis=0)


def median_latency(callable_, repeats: int) -> float:
    samples = []
    for _ in range(repeats):
        started = time.perf_counter()
        callable_()
        samples.append((time.perf_counter() - started) * 1000)
    return round(statistics.median(samples), 3)


def main() -> int:
    arguments = argparse.ArgumentParser()
    arguments.add_argument("--output", type=Path, required=True)
    arguments.add_argument("--repeats", type=int, default=10)
    args = arguments.parse_args()
    output = args.output.resolve()
    if output.exists():
        raise FileExistsError(f"output already exists: {output}")
    settings = RDV2Settings.from_env(PROJECT_ROOT)
    started = time.perf_counter()
    bundle = FrozenArtifactValidator(settings).validate_and_load()
    startup_ms = (time.perf_counter() - started) * 1000
    query = np.asarray(bundle.embeddings[0], dtype=np.float32)
    retriever = FrozenDenseRetriever(bundle, FixedEmbedder(query))
    first_document = bundle.catalog.documents[0].document_id
    all_active_ms = median_latency(
        lambda: retriever.retrieve("离线基准", top_k=5), args.repeats
    )
    single_document_ms = median_latency(
        lambda: retriever.retrieve(
            "离线基准",
            top_k=5,
            scope=RetrievalScope(document_ids=[first_document]),
        ),
        args.repeats,
    )
    result = {
        "corpus_chunks": len(bundle.chunks),
        "documents": len(bundle.catalog.documents),
        "versions": len(bundle.catalog.versions),
        "artifact_and_catalog_startup_ms": round(startup_ms, 3),
        "all_active_retrieval_median_ms": all_active_ms,
        "single_document_retrieval_median_ms": single_document_ms,
        "repeats": args.repeats,
        "embedding_call_included": False,
        "full_rebuild_baseline_ms": None,
        "production_qps_claimed": False,
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

