"""In-process retrieval comparisons over frozen public-corpus chunks.

This module does not change the deployed retrieval policy or write an index.
"""

from __future__ import annotations

import math
import sys
import time
from collections import Counter
from pathlib import Path

import numpy as np


REPOSITORY = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPOSITORY / "versioned-rag-service"))
from src.public_knowledge import tokens  # noqa: E402


class OfflineIndex:
    """Use the production BM25 formula and fixed version scope for each query."""

    def __init__(self, chunks: list[dict]):
        self.chunks = chunks
        self.search_texts = [
            chunk.get("search_text") or
            f"{chunk['heading']} {chunk['document_key']} {chunk['content']}"
            for chunk in chunks
        ]
        self.term_freqs = [Counter(tokens(value)) for value in self.search_texts]
        self.lengths = np.array([sum(row.values()) for row in self.term_freqs])
        self.avg_length = float(np.mean(self.lengths))
        self.doc_freq: Counter[str] = Counter()
        for row in self.term_freqs:
            self.doc_freq.update(row.keys())
        self.neural_vectors: np.ndarray | None = None
        self.encoder = None

    def attach_neural(self, encoder) -> None:
        vectors = encoder.encode_passages(self.search_texts)
        if vectors.shape[0] != len(self.chunks):
            raise ValueError("neural index size mismatch")
        self.encoder = encoder
        self.neural_vectors = np.asarray(vectors, dtype=np.float32)

    def _bm25(self, query: str) -> np.ndarray:
        scores = np.zeros(len(self.chunks), dtype=np.float32)
        n = len(self.chunks)
        for term in set(tokens(query)):
            df = self.doc_freq.get(term, 0)
            if not df:
                continue
            idf = math.log(1 + (n - df + 0.5) / (df + 0.5))
            for i, row in enumerate(self.term_freqs):
                tf = row.get(term, 0)
                if tf:
                    scores[i] += idf * tf * 2.2 / (
                        tf + 1.2 * (0.25 + 0.75 * self.lengths[i] / self.avg_length)
                    )
        return scores

    def search(
        self,
        query: str,
        *,
        version: str,
        strategy: str,
        top_k: int = 5,
        bm25_weight: float = 0.5,
        max_chunks_per_document: int | None = None,
    ) -> tuple[list[dict], float]:
        if strategy not in ("bm25", "neural_dense", "hybrid"):
            raise ValueError("unsupported experimental strategy")
        if not 1 <= top_k <= len(self.chunks):
            raise ValueError("invalid top_k")
        if max_chunks_per_document is not None and max_chunks_per_document < 1:
            raise ValueError("invalid document cap")
        start = time.perf_counter()
        eligible = [
            i for i, chunk in enumerate(self.chunks)
            if version == "all" or chunk["version"] == version
        ]

        bm25_scores = self._bm25(query) if strategy in ("bm25", "hybrid") else None
        neural_scores = None
        if strategy in ("neural_dense", "hybrid"):
            if self.encoder is None or self.neural_vectors is None:
                raise ValueError("neural encoder not attached")
            query_vector = self.encoder.encode_queries([query])[0]
            neural_scores = self.neural_vectors @ query_vector

        if strategy == "bm25":
            assert bm25_scores is not None
            order = sorted(eligible, key=lambda i: bm25_scores[i], reverse=True)
            scores = bm25_scores
        elif strategy == "neural_dense":
            assert neural_scores is not None
            order = sorted(eligible, key=lambda i: neural_scores[i], reverse=True)
            scores = neural_scores
        else:
            assert bm25_scores is not None and neural_scores is not None
            bm25_order = sorted(eligible, key=lambda i: bm25_scores[i], reverse=True)
            neural_order = sorted(eligible, key=lambda i: neural_scores[i], reverse=True)
            fused = np.zeros(len(self.chunks), dtype=np.float32)
            for rank, i in enumerate(bm25_order[:50], start=1):
                fused[i] += bm25_weight / (60 + rank)
            for rank, i in enumerate(neural_order[:50], start=1):
                fused[i] += (1 - bm25_weight) / (60 + rank)
            order = sorted(eligible, key=lambda i: fused[i], reverse=True)
            scores = fused

        selected: list[int] = []
        per_document: Counter[str] = Counter()
        for i in order:
            document_id = self.chunks[i]["document_id"]
            if max_chunks_per_document is not None and per_document[document_id] >= max_chunks_per_document:
                continue
            selected.append(i)
            per_document[document_id] += 1
            if len(selected) == top_k:
                break
        hits = [
            {
                **self.chunks[i],
                "rank": rank,
                "retrieval_score": float(scores[i]),
                "retrieval_policy": strategy,
            }
            for rank, i in enumerate(selected, start=1)
        ]
        return hits, round((time.perf_counter() - start) * 1000, 3)
