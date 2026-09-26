"""Torch-only worker used by the frozen R&D V2 query runtime.

This module must remain free of FAISS imports.  The service process owns FAISS;
the spawned worker owns PyTorch/Transformers.
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np

from src.native_runtime import NativeRuntimePolicy, validate_embedding_batch


def embedding_worker_main(request_queue, response_queue, config: dict) -> None:
    """Serve embedding requests without ever logging request text."""

    if "faiss" in sys.modules:
        response_queue.put({"type": "FATAL", "code": "PROCESS_ISOLATION_VIOLATION"})
        return
    try:
        policy = NativeRuntimePolicy(
            torch_threads=int(config["torch_threads"]),
            mkldnn_enabled=bool(config["mkldnn_enabled"]),
        )
        policy.prepare_process_environment()
        import torch
        from transformers import AutoModel, AutoTokenizer

        policy.apply_torch(torch)
        snapshot = Path(config["snapshot"])
        if not snapshot.is_dir() or not (snapshot / "config.json").is_file():
            raise RuntimeError("EMBEDDING_MODEL_SNAPSHOT_INCOMPLETE")
        tokenizer = AutoTokenizer.from_pretrained(snapshot, local_files_only=True)
        model = AutoModel.from_pretrained(snapshot, local_files_only=True)
        model.eval()
        dimension = int(model.config.hidden_size)
        if dimension != int(config["dimension"]):
            raise RuntimeError("EMBEDDING_DIMENSION_MISMATCH")
        response_queue.put({"type": "READY", "dimension": dimension})
    except Exception as exc:
        response_queue.put({"type": "FATAL", "code": type(exc).__name__})
        return

    while True:
        try:
            request = request_queue.get()
        except (EOFError, KeyboardInterrupt, OSError):
            return
        if request is None:
            return
        request_id = request.get("id")
        try:
            texts = list(request["texts"])
            with torch.inference_mode():
                encoded = tokenizer(
                    [str(config["query_prefix"]) + value for value in texts],
                    padding=True,
                    truncation=True,
                    max_length=int(config["max_length"]),
                    return_tensors="pt",
                )
                vectors = model(**encoded).last_hidden_state[:, 0]
                vectors = torch.nn.functional.normalize(vectors, p=2, dim=1)
                values = vectors.cpu().numpy().astype(np.float32)
            validate_embedding_batch(values, dimension=dimension)
            response_queue.put(
                {"type": "RESULT", "id": request_id, "vectors": values}
            )
        except Exception as exc:
            # Only the exception class is returned.  Exception messages can
            # unexpectedly contain request data or local filesystem details.
            response_queue.put(
                {"type": "ERROR", "id": request_id, "code": type(exc).__name__}
            )
