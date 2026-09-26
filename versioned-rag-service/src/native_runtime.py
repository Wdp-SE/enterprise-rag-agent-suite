"""Windows-safe native runtime rules for the frozen R&D V2 embedding path."""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Mapping, MutableMapping

import numpy as np


class NativeRuntimePolicyError(RuntimeError):
    pass


@dataclass(frozen=True)
class NativeRuntimePolicy:
    torch_threads: int = 1
    mkldnn_enabled: bool = False

    def validate_environment(self, environ: Mapping[str, str] | None = None) -> None:
        values = environ if environ is not None else os.environ
        duplicate_ok = str(values.get("KMP_DUPLICATE_LIB_OK", "")).strip().casefold()
        if duplicate_ok in {"1", "true", "yes", "on"}:
            raise NativeRuntimePolicyError("KMP_DUPLICATE_LIB_OK_FORBIDDEN")
        if self.torch_threads != 1 or self.mkldnn_enabled:
            raise NativeRuntimePolicyError("NATIVE_RUNTIME_POLICY_INVALID")

    def prepare_process_environment(
        self, environ: MutableMapping[str, str] | None = None
    ) -> None:
        target = environ if environ is not None else os.environ
        self.validate_environment(target)
        target["OMP_NUM_THREADS"] = "1"
        target["MKL_NUM_THREADS"] = "1"
        target["HF_HUB_OFFLINE"] = "1"
        target["TRANSFORMERS_OFFLINE"] = "1"

    def apply_torch(self, torch_module) -> None:
        self.validate_environment()
        torch_module.set_num_threads(1)
        try:
            torch_module.set_num_interop_threads(1)
        except RuntimeError:
            # PyTorch only permits setting this once in a process.  The value is
            # verified immediately below when the API is available.
            pass
        torch_module.backends.mkldnn.enabled = False
        if int(torch_module.get_num_threads()) != 1:
            raise NativeRuntimePolicyError("TORCH_THREAD_POLICY_NOT_APPLIED")
        if bool(torch_module.backends.mkldnn.enabled):
            raise NativeRuntimePolicyError("MKLDNN_POLICY_NOT_APPLIED")


def validate_embedding_batch(values: np.ndarray, *, dimension: int | None = None) -> None:
    matrix = np.asarray(values)
    if matrix.ndim != 2 or matrix.shape[0] == 0:
        raise NativeRuntimePolicyError("EMBEDDING_BATCH_SHAPE_INVALID")
    if dimension is not None and matrix.shape[1] != dimension:
        raise NativeRuntimePolicyError("EMBEDDING_DIMENSION_MISMATCH")
    if not np.isfinite(matrix).all():
        raise NativeRuntimePolicyError("EMBEDDING_BATCH_NON_FINITE")
    norms = np.linalg.norm(matrix, axis=1)
    if not np.allclose(norms, 1.0, atol=1e-4):
        raise NativeRuntimePolicyError("EMBEDDING_BATCH_NOT_UNIT_NORMALIZED")

