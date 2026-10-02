from __future__ import annotations

import numpy as np
import pytest

from src.rd_v2_api import CandidateServiceRegistry
from src.rd_v2_runtime import DeterministicHashEmbedder


def test_public_hash_embedder_is_deterministic_normalized_and_semantic_by_shared_terms() -> None:
    embedder = DeterministicHashEmbedder(dimension=64, query_prefix="")
    vectors = embedder.encode(["日志保留周期调整为30天", "日志保存30天", "最大并发1000"])
    assert vectors.shape == (3, 64)
    assert np.allclose(np.linalg.norm(vectors, axis=1), 1.0)
    assert np.allclose(vectors[0], embedder.encode(["日志保留周期调整为30天"])[0])
    assert float(vectors[0] @ vectors[1]) > float(vectors[0] @ vectors[2])


def test_candidate_service_registry_isolates_sessions_and_rejects_path_escape(tmp_path) -> None:
    created = []

    def factory(root, embedder):
        value = {"root": root, "embedder": embedder}
        created.append(value)
        return value

    marker = object()
    registry = CandidateServiceRegistry(tmp_path, marker, service_factory=factory)
    first = registry.get("session_aaaaaaaa")
    again = registry.get("session_aaaaaaaa")
    second = registry.get("session_bbbbbbbb")

    assert first is again
    assert first is not second
    assert first["root"] == tmp_path / "sessions" / "session_aaaaaaaa"
    assert second["root"] == tmp_path / "sessions" / "session_bbbbbbbb"
    assert len(created) == 2
    with pytest.raises(ValueError, match="session"):
        registry.get("../escape")
