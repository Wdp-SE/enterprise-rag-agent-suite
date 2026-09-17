"""Vector normalization helpers used by ingestion and retrieval."""

import numpy as np


def l2_normalize_rows(values, *, zero_tolerance: float = 1e-12) -> np.ndarray:
    """Return float32 row vectors normalized to unit L2 norm."""
    array = np.asarray(values, dtype=np.float32)
    if array.ndim == 1:
        array = array.reshape(1, -1)
    if array.ndim != 2 or array.shape[1] == 0:
        raise ValueError("Embeddings must be a non-empty one- or two-dimensional array.")

    norms = np.linalg.norm(array, axis=1, keepdims=True)
    zero_rows = np.flatnonzero(norms[:, 0] <= zero_tolerance)
    if zero_rows.size:
        raise ValueError(f"Cannot normalize zero-length embedding rows: {zero_rows.tolist()}.")
    return array / norms


def faiss_index_has_unit_norm_vectors(
    index,
    *,
    sample_size: int = 32,
    atol: float = 1e-3,
) -> bool:
    """Check representative stored vectors without mutating the FAISS index."""
    if index.ntotal == 0:
        return True
    if not hasattr(index, "reconstruct"):
        raise ValueError("The FAISS index does not support vector reconstruction.")

    count = min(index.ntotal, sample_size)
    sample_indices = np.linspace(0, index.ntotal - 1, num=count, dtype=int)
    vectors = np.vstack([index.reconstruct(int(i)) for i in sample_indices])
    norms = np.linalg.norm(vectors, axis=1)
    return bool(np.allclose(norms, 1.0, atol=atol, rtol=0.0))
