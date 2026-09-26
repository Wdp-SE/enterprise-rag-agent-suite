import json
from pathlib import Path

import faiss
import numpy as np
import pytest
from fastapi.testclient import TestClient

from src.artifact_lifecycle import (
    ArtifactBuildLifecycle,
    ArtifactLifecycleError,
    sha256_file,
)
from src.native_runtime import (
    NativeRuntimePolicy,
    NativeRuntimePolicyError,
    validate_embedding_batch,
)
from src.rd_v2_api import create_app
from src.rd_v2_runtime import (
    ArtifactValidationError,
    FrozenArtifactValidator,
    RDV2QueryRuntime,
    RDV2Settings,
    validate_citation_membership,
)


def _write_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value), encoding="utf-8")


def _entry(root: Path, path: Path) -> dict:
    return {
        "path": path.relative_to(root).as_posix(),
        "sha256": sha256_file(path),
        "bytes": path.stat().st_size,
    }


def _artifact_fixture(tmp_path: Path) -> tuple[RDV2Settings, Path]:
    artifact_root = tmp_path / "artifacts" / "rd-v2-retrieval-final-v1.0"
    artifact_root.mkdir(parents=True)
    chunks_path = tmp_path / "frozen" / "child_chunks.jsonl"
    chunks_path.parent.mkdir(parents=True)
    chunks = [
        {
            "chunk_id": "doc-a:0",
            "document_id": "doc-a",
            "page": 1,
            "page_number": 1,
            "id": 0,
            "section_id": "doc-a:sec:1",
            "section_source": "WORD_OUTLINE",
            "section_path": ["A"],
            "length_tokens": 2,
            "text": "fixture evidence alpha",
        },
        {
            "chunk_id": "doc-a:1",
            "document_id": "doc-a",
            "page": 2,
            "page_number": 2,
            "id": 1,
            "section_id": "doc-a:sec:1",
            "section_source": "WORD_OUTLINE",
            "section_path": ["A"],
            "length_tokens": 2,
            "text": "fixture evidence beta",
        },
    ]
    chunks_path.write_text(
        "".join(json.dumps(row) + "\n" for row in chunks), encoding="utf-8"
    )
    embedding_path = tmp_path / "frozen" / "embeddings.npy"
    vectors = np.asarray([[1.0, 0.0, 0.0], [0.0, 1.0, 0.0]], dtype=np.float32)
    np.save(embedding_path, vectors)
    index_path = tmp_path / "frozen" / "child_vectors.faiss"
    index = faiss.IndexFlatIP(3)
    index.add(vectors)
    faiss.write_index(index, str(index_path))

    corpus_path = artifact_root / "corpus_manifest.json"
    structure_path = artifact_root / "structure_sidecar_manifest.json"
    policy_path = artifact_root / "retrieval_policy.json"
    _write_json(corpus_path, {"corpus_version": "fixture", "documents": []})
    _write_json(structure_path, {"structure_version": "fixture", "sidecars": []})
    _write_json(
        policy_path,
        {
            "retrieval_policy_version": "rd-v2-retrieval-final-v1.0",
            "retrieval_policy": "DENSE_ONLY",
            "dense_representation": "SECTION_PATH",
            "dense_top_k": 20,
            "final_top_k": 5,
            "bm25_enabled": False,
            "hybrid_enabled": False,
            "reranker_enabled": False,
        },
    )
    artifacts = {
        "corpus_manifest": _entry(tmp_path, corpus_path),
        "structure_sidecar_manifest": _entry(tmp_path, structure_path),
        "chunk_artifact": _entry(tmp_path, chunks_path),
        "embedding_artifact": _entry(tmp_path, embedding_path),
        "faiss_index": _entry(tmp_path, index_path),
        "retrieval_policy": _entry(tmp_path, policy_path),
    }
    _write_json(
        artifact_root / "artifact_manifest.json",
        {
            "status": "COMPLETE",
            "retrieval_policy_version": "rd-v2-retrieval-final-v1.0",
            "embedding_dimension": 3,
            "embedding_model_revision": "fixture",
            "query_prefix": "query: ",
            "chunk_count": 2,
            "embedding_count": 2,
            "faiss_vector_count": 2,
            "artifacts": artifacts,
        },
    )
    _write_json(artifact_root / "artifact_build_state.json", {"status": "COMPLETE"})
    settings = RDV2Settings(
        project_root=tmp_path,
        artifact_root=artifact_root,
        artifact_manifest=artifact_root / "artifact_manifest.json",
    )
    return settings, artifact_root


class FakeEmbedder:
    def __init__(self):
        self.calls = 0
        self.closed = False

    def encode(self, texts):
        self.calls += 1
        return np.asarray([[1.0, 0.0, 0.0] for _ in texts], dtype=np.float32)

    def close(self):
        self.closed = True


class InvalidCitationGenerator:
    def generate(self, *, question, context):
        return {
            "final_answer": "unsupported",
            "relevant_sources": [{"document_id": "missing", "page_number": 99}],
        }


def test_frozen_manifest_loads_counts_dimension_policy_and_faiss(tmp_path):
    settings, _ = _artifact_fixture(tmp_path)
    bundle = FrozenArtifactValidator(settings).validate_and_load()
    assert len(bundle.chunks) == 2
    assert bundle.index.ntotal == 2
    assert bundle.index.d == 3
    assert bundle.policy["retrieval_policy"] == "DENSE_ONLY"


@pytest.mark.parametrize(
    ("field", "value", "code"),
    [
        ("chunk_count", 3, "ARTIFACT_COUNT_MISMATCH"),
        ("embedding_dimension", 4, "EMBEDDING_DIMENSION_MISMATCH"),
        ("retrieval_policy_version", "wrong", "POLICY_VERSION_MISMATCH"),
    ],
)
def test_startup_validation_fails_closed(tmp_path, field, value, code):
    settings, artifact_root = _artifact_fixture(tmp_path)
    path = artifact_root / "artifact_manifest.json"
    manifest = json.loads(path.read_text(encoding="utf-8"))
    manifest[field] = value
    _write_json(path, manifest)
    with pytest.raises(ArtifactValidationError) as error:
        FrozenArtifactValidator(settings).validate_and_load()
    assert error.value.code == code


def test_startup_rejects_hash_mismatch(tmp_path):
    settings, artifact_root = _artifact_fixture(tmp_path)
    (artifact_root / "corpus_manifest.json").write_text("{}", encoding="utf-8")
    with pytest.raises(ArtifactValidationError) as error:
        FrozenArtifactValidator(settings).validate_and_load()
    assert error.value.code == "ARTIFACT_HASH_MISMATCH"


def test_startup_rejects_partial_artifact(tmp_path):
    settings, artifact_root = _artifact_fixture(tmp_path)
    _write_json(artifact_root / "artifact_build_state.json", {"status": "FAILED"})
    with pytest.raises(ArtifactValidationError) as error:
        FrozenArtifactValidator(settings).validate_and_load()
    assert error.value.code == "ARTIFACT_NOT_COMPLETE"


def test_query_loads_frozen_index_without_rebuild_and_keeps_trace_text_free(tmp_path):
    settings, _ = _artifact_fixture(tmp_path)
    bundle = FrozenArtifactValidator(settings).validate_and_load()
    embedder = FakeEmbedder()
    runtime = RDV2QueryRuntime(
        settings=settings, bundle=bundle, embedder=embedder, generator=None
    )
    result = runtime.query("fixture question")
    assert result["status"] == "GENERATION_DISABLED_BY_DATA_POLICY"
    assert result["answer"] == "N/A"
    assert embedder.calls == 1
    assert result["trace"]
    assert all("text" not in row for row in result["trace"])
    assert all({"version_label", "section_path"}.issubset(row) for row in result["trace"])
    assert not hasattr(runtime, "build")


def test_invalid_citation_is_fail_closed(tmp_path):
    settings, _ = _artifact_fixture(tmp_path)
    bundle = FrozenArtifactValidator(settings).validate_and_load()
    runtime = RDV2QueryRuntime(
        settings=settings,
        bundle=bundle,
        embedder=FakeEmbedder(),
        generator=InvalidCitationGenerator(),
    )
    result = runtime.query("fixture question")
    assert result["status"] == "FAIL_CLOSED"
    assert result["answer"] == "N/A"
    assert result["sources"] == []
    assert result["trusted_qa"]["enforced"] is True
    assert result["trusted_qa"]["post_validation_status"] == "EMPTY_VALID_CITATIONS"


def test_citation_membership_keeps_composite_document_page_identity():
    retrieved = [{"document_id": "doc-a", "page": 2}]
    claimed = [
        {"document_id": "doc-a", "page_number": 2},
        {"document_id": "doc-b", "page_number": 2},
    ]
    assert validate_citation_membership(claimed, retrieved) == [
        {"document_id": "doc-a", "page_number": 2}
    ]


def test_checkpoint_failure_and_validated_resume(tmp_path):
    root = tmp_path / "artifact"
    root.mkdir()
    checkpoint = root / "batch.npy"
    checkpoint.write_bytes(b"partial")
    lifecycle = ArtifactBuildLifecycle(root / "state.json", root)
    lifecycle.initialize(input_fingerprint="abc", total_batches=1)
    lifecycle.start(input_fingerprint="abc")
    lifecycle.checkpoint(completed_batches=1, files={"embedding": checkpoint})
    lifecycle.fail("BATCH_FAILED")
    assert lifecycle.read()["status"] == "FAILED"
    lifecycle.start(input_fingerprint="abc", resume=True)
    lifecycle.complete(validator=lambda: None)
    assert lifecycle.read()["status"] == "COMPLETE"


def test_partial_checkpoint_cannot_be_marked_complete(tmp_path):
    root = tmp_path / "artifact"
    root.mkdir()
    lifecycle = ArtifactBuildLifecycle(root / "state.json", root)
    lifecycle.initialize(input_fingerprint="abc", total_batches=1)
    lifecycle.start(input_fingerprint="abc")
    with pytest.raises(ArtifactLifecycleError, match="PARTIAL_ARTIFACT"):
        lifecycle.complete(validator=lambda: None)


def test_runtime_policy_rejects_kmp_duplicate_and_bad_vectors():
    policy = NativeRuntimePolicy()
    with pytest.raises(NativeRuntimePolicyError, match="KMP_DUPLICATE"):
        policy.validate_environment({"KMP_DUPLICATE_LIB_OK": "TRUE"})
    with pytest.raises(NativeRuntimePolicyError, match="NON_FINITE"):
        validate_embedding_batch(np.asarray([[np.nan, 0.0]], dtype=np.float32))
    with pytest.raises(NativeRuntimePolicyError, match="UNIT_NORMALIZED"):
        validate_embedding_batch(np.asarray([[2.0, 0.0]], dtype=np.float32))


def test_minimal_api_health_artifact_status_and_query(tmp_path):
    settings, _ = _artifact_fixture(tmp_path)
    bundle = FrozenArtifactValidator(settings).validate_and_load()
    embedder = FakeEmbedder()
    runtime = RDV2QueryRuntime(
        settings=settings, bundle=bundle, embedder=embedder, generator=None
    )
    with TestClient(create_app(runtime)) as client:
        health = client.get("/health")
        assert health.status_code == 200
        assert health.json()["artifact_status"] == "COMPLETE"
        artifacts = client.get("/artifacts/status")
        assert artifacts.status_code == 200
        assert artifacts.json()["retrieval_policy"] == "DENSE_ONLY"
        response = client.post("/query", json={"question": "fixture question"})
        assert response.status_code == 200
        assert response.json()["status"] == "GENERATION_DISABLED_BY_DATA_POLICY"
    assert embedder.closed is True


def test_retrieve_returns_frozen_chunks_without_generation(tmp_path):
    settings, _ = _artifact_fixture(tmp_path)
    bundle = FrozenArtifactValidator(settings).validate_and_load()
    embedder = FakeEmbedder()

    class ForbiddenGenerator:
        def generate(self, **kwargs):
            raise AssertionError("/retrieve must not invoke generation")

    runtime = RDV2QueryRuntime(
        settings=settings, bundle=bundle, embedder=embedder,
        generator=ForbiddenGenerator(),
    )
    with TestClient(create_app(runtime)) as client:
        for question in ("alpha", "beta", "gamma"):
            response = client.post("/retrieve", json={"query": question, "top_k": 1})
            assert response.status_code == 200
            body = response.json()
            assert body["query"] == question
            assert len(body["results"]) == 1
            hit = body["results"][0]
            chunk = bundle.chunks[0]
            assert hit["chunk_id"] == chunk["chunk_id"]
            assert hit["document_id"] == chunk["document_id"]
            assert hit["section_id"] == chunk["section_id"]
            assert hit["section_path"] == chunk["section_path"]
            assert hit["page_number"] == chunk["page_number"]
            assert hit["content"] == chunk["text"]
            assert hit["rank"] == 1
            assert hit["similarity"] == 1.0
        response = client.post("/retrieve", json={"query": "top two", "top_k": 2})
        assert [item["rank"] for item in response.json()["results"]] == [1, 2]
        assert client.post("/retrieve", json={"query": "x", "top_k": 0}).status_code == 422
        assert client.post("/retrieve", json={"query": "x", "unexpected": 1}).status_code == 422
    assert embedder.calls == 4


def test_retrieve_startup_fail_closed_when_lifecycle_invalid(tmp_path):
    settings, artifact_root = _artifact_fixture(tmp_path)
    _write_json(artifact_root / "artifact_build_state.json", {"status": "FAILED"})
    with pytest.raises(ArtifactValidationError, match="ARTIFACT_NOT_COMPLETE"):
        with TestClient(create_app(runtime_factory=lambda: RDV2QueryRuntime(
            settings=settings,
            bundle=FrozenArtifactValidator(settings).validate_and_load(),
            embedder=FakeEmbedder(),
        ))):
            pass
