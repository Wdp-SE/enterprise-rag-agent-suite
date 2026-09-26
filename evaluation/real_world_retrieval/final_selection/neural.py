"""Pinned multilingual E5 encoder for the local retrieval-selection experiment."""

from __future__ import annotations

import hashlib
import tempfile
from pathlib import Path

import numpy as np


MODEL_ID = "intfloat/multilingual-e5-small"
MODEL_REVISION = "ada7b62be30f82b0bc5da131b0477721c8fc14e9"
_MODEL_FILES = {
    "config.json": 655,
    "model.safetensors": 470641600,
    "tokenizer.json": 17082730,
    "tokenizer_config.json": 443,
    "special_tokens_map.json": 167,
    "sentencepiece.bpe.model": 5069051,
}
_WEIGHTS_SHA256 = "1a55775f53449dac10a2bcbc312469fac40b96d53198c407081a831f81c98477"


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


class NeuralEncoder:
    """Encode queries and passages with one CPU model and a temp-only cache."""

    def __init__(self, cache_dir: str | Path | None = None, batch_size: int = 8):
        if batch_size < 1:
            raise ValueError("batch_size must be positive")
        temp_root = Path(tempfile.gettempdir()).resolve()
        cache_root = Path(cache_dir).resolve() if cache_dir is not None else temp_root / "rag-retrieval-e5"
        if cache_root != temp_root and temp_root not in cache_root.parents:
            raise ValueError("model cache must be inside the OS temporary directory")
        self.model_dir = cache_root / MODEL_REVISION
        self.batch_size = batch_size
        self._ensure_model_files()

        import torch
        from transformers import AutoModel, AutoTokenizer

        self._torch = torch
        self.tokenizer = AutoTokenizer.from_pretrained(
            self.model_dir, local_files_only=True, use_fast=True
        )
        self.model = AutoModel.from_pretrained(
            self.model_dir, local_files_only=True, use_safetensors=True
        ).to("cpu")
        self.model.eval()

    def _ensure_model_files(self) -> None:
        """Fetch only safetensors and tokenizer assets into the OS temp directory."""
        import requests

        self.model_dir.mkdir(parents=True, exist_ok=True)
        base_url = f"https://huggingface.co/{MODEL_ID}/resolve/{MODEL_REVISION}"
        for name, expected_size in _MODEL_FILES.items():
            target = self.model_dir / name
            if target.exists() and target.stat().st_size == expected_size:
                if name != "model.safetensors" or _sha256(target) == _WEIGHTS_SHA256:
                    continue
            partial = target.with_name(target.name + ".part")
            digest = hashlib.sha256()
            size = 0
            try:
                with requests.get(f"{base_url}/{name}", stream=True, timeout=(15, 60)) as response:
                    response.raise_for_status()
                    with partial.open("wb") as output:
                        for block in response.iter_content(chunk_size=1024 * 1024):
                            if block:
                                output.write(block)
                                digest.update(block)
                                size += len(block)
                if size != expected_size:
                    raise ValueError(f"incomplete download for {name}: {size} != {expected_size}")
                if name == "model.safetensors" and digest.hexdigest() != _WEIGHTS_SHA256:
                    raise ValueError("model.safetensors SHA-256 does not match the pinned revision")
                partial.replace(target)
            finally:
                partial.unlink(missing_ok=True)

    def _encode(self, texts: list[str], prefix: str) -> np.ndarray:
        if not all(isinstance(text, str) for text in texts):
            raise TypeError("texts must contain strings")
        if not texts:
            return np.empty((0, self.model.config.hidden_size), dtype=np.float32)

        vectors = []
        for offset in range(0, len(texts), self.batch_size):
            inputs = self.tokenizer(
                [f"{prefix}: {text}" for text in texts[offset:offset + self.batch_size]],
                max_length=512,
                padding=True,
                truncation=True,
                return_tensors="pt",
            )
            with self._torch.inference_mode():
                hidden = self.model(**inputs).last_hidden_state
                mask = inputs["attention_mask"].unsqueeze(-1)
                pooled = (hidden * mask).sum(dim=1) / mask.sum(dim=1).clamp(min=1)
                normalized = self._torch.nn.functional.normalize(pooled, p=2, dim=1)
            vectors.append(normalized.cpu().numpy().astype(np.float32, copy=False))
        return np.concatenate(vectors, axis=0)

    def encode_queries(self, texts: list[str]) -> np.ndarray:
        return self._encode(texts, "query")

    def encode_passages(self, texts: list[str]) -> np.ndarray:
        return self._encode(texts, "passage")
