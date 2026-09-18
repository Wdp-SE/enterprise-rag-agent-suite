from __future__ import annotations

import hashlib

import faiss
import numpy as np
from fastapi.testclient import TestClient

from src.document_lifecycle import (
    Document,
    DocumentCatalog,
    DocumentVersion,
    SectionSnapshot,
    VersionStatus,
)
from src.rd_v2_api import create_app
from src.rd_v2_runtime import FrozenArtifactBundle, RDV2QueryRuntime, RDV2Settings


class FixedEmbedder:
    def __init__(self):
        self.closed = False

    def encode(self, texts):
        return np.asarray([[1.0, 0.0] for _ in texts], dtype=np.float32)

    def close(self):
        self.closed = True


def _runtime(tmp_path):
    documents = [
        Document(document_id="REQ", project_id="P", document_type="requirements", title="需求"),
        Document(document_id="DESIGN", project_id="P", document_type="design", title="设计"),
    ]
    versions = [
        DocumentVersion(version_id="REQ@1", document_id="REQ", version_label="V1",
                        status=VersionStatus.SUPERSEDED, source_hash="1" * 64,
                        source_document_id="req-v1"),
        DocumentVersion(version_id="REQ@2", document_id="REQ", version_label="V2",
                        status=VersionStatus.ACTIVE, source_hash="2" * 64,
                        previous_version_id="REQ@1", source_document_id="req-v2"),
        DocumentVersion(version_id="DESIGN@1", document_id="DESIGN", version_label="V1",
                        status=VersionStatus.ACTIVE, source_hash="3" * 64,
                        source_document_id="design-v1"),
    ]
    sections = {
        "REQ@1": [SectionSnapshot(section_id="r1", section_path=["容量"], content="并发 500",
                                  page_start=1, page_end=1)],
        "REQ@2": [SectionSnapshot(section_id="r2", section_path=["容量"], content="并发 1000",
                                  page_start=2, page_end=2)],
    }
    catalog = DocumentCatalog(documents, versions, sections_by_version=sections)
    raw_chunks = [
        ("req-v1", "REQ@1", "old-1", "r1", "并发 500", 1),
        ("design-v1", "DESIGN@1", "design-1", "d1", "设计内容", 4),
        ("req-v2", "REQ@2", "new-1", "r2", "并发 1000", 2),
        ("req-v2", "REQ@2", "new-2", "r3", "吞吐 200", 3),
    ]
    chunks = []
    for source_doc, version_id, chunk_id, section_id, text, page in raw_chunks:
        chunks.append(catalog.enrich_chunk({
            "document_id": source_doc, "version_id": version_id, "chunk_id": chunk_id,
            "section_id": section_id, "section_path": [section_id], "section_source": "TEST",
            "page": page, "page_number": page, "text": text,
        }))
    vectors = np.asarray([[1.0, 0.0], [0.99, 0.141067], [0.8, 0.6], [0.7, 0.714142]], dtype=np.float32)
    vectors /= np.linalg.norm(vectors, axis=1, keepdims=True)
    index = faiss.IndexFlatIP(2)
    index.add(vectors)
    bundle = FrozenArtifactBundle(
        manifest={"status": "COMPLETE", "embedding_dimension": 2},
        policy={"retrieval_policy": "DENSE_ONLY"},
        chunks=chunks,
        embeddings=vectors,
        index=index,
        catalog=catalog,
    )
    settings = RDV2Settings(
        project_root=tmp_path,
        artifact_root=tmp_path,
        artifact_manifest=tmp_path / "artifact_manifest.json",
        dense_top_k=4,
        final_top_k=2,
    )
    return RDV2QueryRuntime(settings=settings, bundle=bundle, embedder=FixedEmbedder())


def test_runtime_filters_candidates_before_topk_and_defaults_active_only(tmp_path):
    runtime = _runtime(tmp_path)
    default = runtime.retriever.retrieve("并发", top_k=3)
    assert [item["version_id"] for item in default] == ["DESIGN@1", "REQ@2", "REQ@2"]
    scoped = runtime.retriever.retrieve(
        "并发", top_k=2, scope={"document_ids": ["REQ"], "active_only": True}
    )
    assert [item["chunk_id"] for item in scoped] == ["new-1", "new-2"]
    historical = runtime.retriever.retrieve(
        "并发", top_k=2, scope={"version_ids": ["REQ@1"], "active_only": False}
    )
    assert [item["chunk_id"] for item in historical] == ["old-1"]


def test_v3_api_catalog_versions_diff_and_backward_compatible_retrieve(tmp_path):
    runtime = _runtime(tmp_path)
    with TestClient(create_app(runtime)) as client:
        legacy = client.post("/retrieve", json={"query": "并发", "top_k": 2})
        assert legacy.status_code == 200
        assert all(row["version_status"] == "ACTIVE" for row in legacy.json()["results"])
        scoped = client.post("/retrieve", json={
            "query": "并发", "top_k": 2,
            "scope": {"document_ids": ["REQ"], "active_only": True},
        })
        assert [row["chunk_id"] for row in scoped.json()["results"]] == ["new-1", "new-2"]
        assert client.post("/retrieve", json={
            "query": "并发", "scope": {"version_ids": ["REQ@1"], "active_only": True},
        }).status_code == 422
        documents = client.get("/documents").json()["documents"]
        assert {row["document_id"] for row in documents} == {"REQ", "DESIGN"}
        assert next(row for row in documents if row["document_id"] == "REQ")["active_version"]["version_id"] == "REQ@2"
        versions = client.get("/documents/REQ/versions").json()["versions"]
        assert {row["status"] for row in versions} == {"ACTIVE", "SUPERSEDED"}
        diff = client.get("/documents/REQ/diff", params={
            "from_version_id": "REQ@1", "to_version_id": "REQ@2",
        })
        assert diff.status_code == 200
        assert diff.json()["summary"]["MODIFIED"] == 1

