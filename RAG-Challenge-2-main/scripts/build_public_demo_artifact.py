"""Build the tiny tracked synthetic artifact used by the public demo profile."""

from __future__ import annotations

import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import faiss
import numpy as np

RAG_ROOT = Path(__file__).resolve().parents[1]
if str(RAG_ROOT) not in sys.path:
    sys.path.insert(0, str(RAG_ROOT))

from src.artifact_lifecycle import sha256_file
from src.document_lifecycle import (
    Document,
    DocumentCatalog,
    DocumentVersion,
    SectionSnapshot,
    VersionStatus,
)
from src.rd_v2_runtime import DeterministicHashEmbedder, FINAL_POLICY_VERSION


ARTIFACT_ROOT = RAG_ROOT / "public_demo_artifacts/rd-v2-public-demo-v1"
DIMENSION = 128
CREATED_AT = datetime(2026, 9, 22, tzinfo=timezone.utc)

ROWS = [
    ("public-a-requirements", "PAYMENT", "REQUIREMENT", "Case A 需求规格说明书",
     "public-a-req-v1", "V1.0", VersionStatus.SUPERSEDED, None,
     "容量与接口", "REQ-023 支付批处理最大并发为 500，客户端通过同步接口等待结果。"),
    ("public-a-requirements", "PAYMENT", "REQUIREMENT", "Case A 需求规格说明书",
     "public-a-req-v2", "V2.0", VersionStatus.ACTIVE, "public-a-req-v1",
     "容量与接口", "REQ-023 支付批处理最大并发调整为 1000，吞吐量目标为 200 MB/s，并改为异步任务接口。"),
    ("public-a-design", "PAYMENT", "DESIGN", "Case A 系统设计说明书",
     "public-a-design-v1", "V1.0", VersionStatus.ACTIVE, None,
     "连接池设计", "DES-014 面向 REQ-023，连接池按最大并发 500 配置，并在同步请求内返回结果。"),
    ("public-a-api", "PAYMENT", "API", "Case A 接口规范",
     "public-a-api-v1", "V1.0", VersionStatus.ACTIVE, None,
     "批处理接口", "API-008 面向 REQ-023，POST /batches 同步返回处理结果。"),
    ("public-a-test", "PAYMENT", "TEST_CASE", "Case A 测试用例",
     "public-a-test-v1", "V1.0", VersionStatus.ACTIVE, None,
     "容量验收", "TC-102 验证 REQ-023，以 500 并发持续运行并检查错误率。"),
    ("public-a-runbook", "PAYMENT", "RUNBOOK", "Case A 运维手册",
     "public-a-runbook-v1", "V1.0", VersionStatus.ACTIVE, None,
     "容量监控", "OPS-006 监控批处理并发与同步接口超时率。"),
    ("public-b-requirements", "AUDIT", "REQUIREMENT", "Case B 需求规格说明书",
     "public-b-req-v1", "V1.0", VersionStatus.SUPERSEDED, None,
     "数据留存要求", "REQ-071 审计日志在线可检索保存 7 天，超过周期后进入归档。"),
    ("public-b-requirements", "AUDIT", "REQUIREMENT", "Case B 需求规格说明书",
     "public-b-req-v2", "V2.0", VersionStatus.ACTIVE, "public-b-req-v1",
     "数据留存要求", "REQ-071 审计日志在线可检索保存周期调整为 30 天，第 31 天起进入归档。"),
    ("public-b-design", "AUDIT", "DESIGN", "Case B 系统设计说明书",
     "public-b-design-v1", "V1.0", VersionStatus.ACTIVE, None,
     "存储与归档设计", "DES-031 面向 REQ-071，审计日志按日期分区，在线存储保留 7 天。"),
    ("public-b-test", "AUDIT", "TEST_CASE", "Case B 测试用例",
     "public-b-test-v1", "V1.0", VersionStatus.ACTIVE, None,
     "合规验收", "TC-207 验证 REQ-071，第 7 天日志可在线查询，第 8 天从归档读取。"),
    ("public-b-runbook", "AUDIT", "RUNBOOK", "Case B 运维手册",
     "public-b-runbook-v1", "V1.0", VersionStatus.ACTIVE, None,
     "存储容量巡检", "OPS-031 每日检查在线日志分区容量与保存周期告警。"),
]


def _sha(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _write_json(path: Path, payload: dict) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def main() -> None:
    ARTIFACT_ROOT.mkdir(parents=True, exist_ok=True)
    document_map: dict[str, Document] = {}
    versions: list[DocumentVersion] = []
    sections: dict[str, list[SectionSnapshot]] = {}
    chunks: list[dict] = []

    for index, row in enumerate(ROWS):
        (
            document_id, project_id, document_type, title,
            version_id, version_label, status, previous_version_id,
            section_title, text,
        ) = row
        document_map.setdefault(
            document_id,
            Document(
                document_id=document_id,
                project_id=project_id,
                document_type=document_type,
                title=title,
                created_at=CREATED_AT,
            ),
        )
        versions.append(
            DocumentVersion(
                version_id=version_id,
                document_id=document_id,
                version_label=version_label,
                status=status,
                source_hash=_sha(text),
                previous_version_id=previous_version_id,
                source_document_id=version_id,
                source_name=f"{version_id}.docx",
                created_at=CREATED_AT,
                activated_at=CREATED_AT if status == VersionStatus.ACTIVE else None,
                superseded_at=CREATED_AT if status == VersionStatus.SUPERSEDED else None,
            )
        )
        section_id = f"{version_id}:section:001"
        section = SectionSnapshot(
            section_id=section_id,
            section_path=[title, section_title],
            content=text,
            page_start=1,
            page_end=1,
        )
        sections[version_id] = [section]
        chunks.append({
            "id": index,
            "chunk_id": f"{version_id}:chunk:001",
            "document_id": version_id,
            "version_id": version_id,
            "page": 1,
            "page_number": 1,
            "type": "content",
            "section_id": section_id,
            "parent_id": section_id,
            "section_title": section_title,
            "section_path": [title, section_title],
            "section_level": 2,
            "section_child_index": 0,
            "section_source": "SYNTHETIC_PUBLIC_DEMO",
            "length_tokens": len(text),
            "text": text,
        })

    catalog = DocumentCatalog(
        list(document_map.values()),
        versions,
        sections_by_version=sections,
    )
    _write_json(ARTIFACT_ROOT / "version_catalog.json", catalog.payload())

    chunk_path = ARTIFACT_ROOT / "child_chunks.jsonl"
    chunk_path.write_text(
        "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in chunks),
        encoding="utf-8",
    )
    embedder = DeterministicHashEmbedder(dimension=DIMENSION)
    vectors = embedder.encode(
        [" / ".join(row["section_path"]) + "\n" + row["text"] for row in chunks]
    )
    np.save(ARTIFACT_ROOT / "embeddings.npy", vectors)
    index = faiss.IndexFlatIP(DIMENSION)
    index.add(np.asarray(vectors, dtype=np.float32))
    (ARTIFACT_ROOT / "child_vectors.faiss").write_bytes(
        faiss.serialize_index(index).tobytes()
    )

    _write_json(
        ARTIFACT_ROOT / "corpus_manifest.json",
        {
            "schema_version": 1,
            "corpus_version": "public-synthetic-two-case/1.0",
            "document_count": 0,
            "documents": [],
            "body_text_included": False,
        },
    )
    _write_json(
        ARTIFACT_ROOT / "structure_sidecar_manifest.json",
        {
            "schema_version": 1,
            "structure_version": "public-synthetic/1.0",
            "sidecar_count": 0,
            "sidecars": [],
        },
    )
    _write_json(
        ARTIFACT_ROOT / "retrieval_policy.json",
        {
            "schema_version": 1,
            "retrieval_policy_version": FINAL_POLICY_VERSION,
            "retrieval_policy": "DENSE_ONLY",
            "dense_representation": "SECTION_PATH",
            "dense_top_k": 20,
            "final_top_k": 5,
            "bm25_enabled": False,
            "hybrid_enabled": False,
            "reranker_enabled": False,
        },
    )
    roles = {
        "corpus_manifest": ARTIFACT_ROOT / "corpus_manifest.json",
        "structure_sidecar_manifest": ARTIFACT_ROOT / "structure_sidecar_manifest.json",
        "chunk_artifact": chunk_path,
        "embedding_artifact": ARTIFACT_ROOT / "embeddings.npy",
        "faiss_index": ARTIFACT_ROOT / "child_vectors.faiss",
        "retrieval_policy": ARTIFACT_ROOT / "retrieval_policy.json",
    }
    artifacts = {}
    for role, path in roles.items():
        artifacts[role] = {
            "path": path.relative_to(RAG_ROOT).as_posix(),
            "sha256": sha256_file(path),
            "bytes": path.stat().st_size,
        }
    _write_json(
        ARTIFACT_ROOT / "artifact_manifest.json",
        {
            "schema_version": 1,
            "artifact_id": "rd-v2-public-demo-v1",
            "status": "COMPLETE",
            "created_at": CREATED_AT.isoformat(),
            "corpus_version": "public-synthetic-two-case/1.0",
            "source_hashes": [],
            "canonical_pdf_hashes": [],
            "embedding_representation": "SECTION_PATH",
            "embedding_model": "deterministic-hash-ngrams",
            "embedding_model_revision": "public-demo-v1",
            "embedding_dimension": DIMENSION,
            "query_prefix": "",
            "chunk_count": len(chunks),
            "embedding_count": len(chunks),
            "faiss_vector_count": len(chunks),
            "faiss_index_type": "IndexFlatIP",
            "retrieval_policy_version": FINAL_POLICY_VERSION,
            "artifacts": artifacts,
            "body_text_included": True,
            "online_models_called": False,
            "classification": "FULLY_SYNTHETIC",
            "demo_cases": ["case-a", "case-b"],
        },
    )
    _write_json(
        ARTIFACT_ROOT / "artifact_build_state.json",
        {
            "schema_version": 1,
            "status": "COMPLETE",
            "input_fingerprint": _sha("public-synthetic-two-case/1.0"),
            "completed_batches": 1,
            "total_batches": 1,
            "body_text_logged": False,
            "completed_at": CREATED_AT.isoformat(),
        },
    )


if __name__ == "__main__":
    main()
