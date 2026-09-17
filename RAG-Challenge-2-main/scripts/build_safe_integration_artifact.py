"""One-time, separate synthetic artifact for the document workflow integration demo.

The completed private artifact is untouched. Preparation reuses the existing
12-page synthetic specification chunks and the frozen SECTION_PATH text builder.
Embedding and FAISS materialization run as separate commands on Windows.
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.artifact_lifecycle import ArtifactBuildLifecycle, sha256_file
from src.embedding_text import EmbeddingTextBuilder, RetrievalTextMode
from src.rd_v2_runtime import FrozenArtifactValidator, RDV2Settings


SAFE_ROOT = ROOT / "data/rd_v2_corpus/retrieval_artifacts/rd-v2-retrieval-final-v1.0-safe-integration"
SNAPSHOT = Path.home() / ".cache/huggingface/hub/models--BAAI--bge-small-zh-v1.5/snapshots/7999e1d3359715c523056ef9478215996d62a620"
ROWS = (
    ("项目背景", "项目背景：示例研发项目需要统一管理需求、开发、测试和验收材料。"),
    ("项目目标", "项目目标：完成结构化研发文档整理，并形成可人工审核的项目计划草稿。"),
    ("阶段划分", "阶段划分：项目分为需求梳理、方案设计、开发测试、验收准备四个阶段。"),
    ("验收依据", "验收依据：以需求规格说明书、测试报告和验收检查表为依据。"),
)


def write_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def entry(path: Path) -> dict:
    return {"path": path.relative_to(ROOT).as_posix(), "sha256": sha256_file(path), "bytes": path.stat().st_size}


def prepare() -> None:
    if (SAFE_ROOT / "artifact_manifest.json").exists() or (SAFE_ROOT / "embeddings.npy").exists():
        raise RuntimeError("safe artifact already prepared; refusing overwrite")
    SAFE_ROOT.mkdir(parents=True, exist_ok=True)
    raw = ROOT / "data/rd_v2_corpus/raw"
    canonical = ROOT / "data/rd_v2_corpus/normalized/pdfs"
    for folder in (raw, canonical):
        folder.mkdir(parents=True, exist_ok=True)
    demo_pdf = ROOT / "data/rd_v2_prototype/pdf_reports/rd_v2_demo_specification.pdf"
    if not demo_pdf.is_file():
        raise FileNotFoundError("existing 12-page synthetic specification missing")
    for folder in (raw, canonical):
        destination = folder / "safe-demo-12p.pdf"
        if destination.exists():
            if sha256_file(destination) != sha256_file(demo_pdf):
                raise RuntimeError("safe synthetic source hash mismatch")
        else:
            shutil.copyfile(demo_pdf, destination)

    source = raw / "safe-project-plan.pdf"
    if not source.is_file():
        raise FileNotFoundError("generate safe-project-plan.pdf with create_safe_project_pdf.py")
    canonical_source = canonical / source.name
    if canonical_source.exists():
        if sha256_file(canonical_source) != sha256_file(source):
            raise RuntimeError("safe canonical PDF hash mismatch")
    else:
        shutil.copyfile(source, canonical_source)

    import pypdfium2 as pdfium

    document = pdfium.PdfDocument(str(source))
    assert len(document) == len(ROWS)
    for index, (_, content) in enumerate(ROWS):
        actual = document[index].get_textpage().get_text_range()
        if content not in actual:
            raise RuntimeError("synthetic physical page text mismatch")

    old = json.loads((ROOT / "data/rd_v2_prototype/databases/chunked_reports/rd_v2_demo_specification.json").read_text(encoding="utf-8"))
    chunks = []
    for item in old["content"]["chunks"]:
        chunk = dict(item)
        chunk["document_id"] = "safe-demo-12p"
        chunk["chunk_id"] = chunk["chunk_id"].replace("rd_v2_demo_specification", "safe-demo-12p")
        chunk["section_id"] = chunk["section_id"].replace("rd_v2_demo_specification", "safe-demo-12p")
        chunk["page_number"] = chunk["page"]
        chunk["id"] = len(chunks)
        chunks.append(chunk)
    for number, (title, content) in enumerate(ROWS, start=1):
        chunks.append({
            "id": len(chunks), "chunk_id": f"safe-project-plan:{number}",
            "document_id": "safe-project-plan", "page": number,
            "page_number": number, "text": content,
            "section_id": f"safe-project-plan:section:{number}",
            "section_title": title, "section_path": [title],
            "section_source": "PDF_HEURISTIC", "type": "content",
        })
    chunks_path = SAFE_ROOT / "child_chunks.jsonl"
    chunks_path.write_text("".join(json.dumps(chunk, ensure_ascii=False) + "\n" for chunk in chunks), encoding="utf-8")

    from scripts.run_rd_v2_real_retrieval_validation import LocalBGEEmbedder

    builder = EmbeddingTextBuilder()
    texts = [builder.build(
        RetrievalTextMode.SECTION_PATH, child_text=item["text"],
        section_title=item.get("section_title", ""),
        section_path=item.get("section_path", []),
    ).retrieval_text for item in chunks]
    embedder = LocalBGEEmbedder(SNAPSHOT, threads=1, batch_size=8, max_length=512)
    vectors = embedder.encode(texts)
    if vectors.shape != (len(chunks), 512):
        raise RuntimeError("safe embedding shape mismatch")
    np.save(SAFE_ROOT / "embeddings.npy", vectors)
    print(f"SAFE_PREPARE=PASS chunks={len(chunks)} pages=12+4 dimension=512")


def index() -> None:
    if (SAFE_ROOT / "child_vectors.faiss").exists():
        raise RuntimeError("safe FAISS already exists; refusing overwrite")
    vectors = np.load(SAFE_ROOT / "embeddings.npy")
    import faiss

    index = faiss.IndexFlatIP(512)
    index.add(np.ascontiguousarray(vectors, dtype=np.float32))
    (SAFE_ROOT / "child_vectors.faiss").write_bytes(faiss.serialize_index(index).tobytes())
    print(f"SAFE_INDEX=PASS vectors={index.ntotal} strategy=IndexFlatIP")


def finalize() -> None:
    if (SAFE_ROOT / "artifact_manifest.json").exists():
        raise RuntimeError("safe manifest already exists; refusing overwrite")
    source_ids = ("safe-demo-12p", "safe-project-plan")
    raw = ROOT / "data/rd_v2_corpus/raw"
    canonical = ROOT / "data/rd_v2_corpus/normalized/pdfs"
    docs = [{
        "document_id": doc,
        "source_sha256": sha256_file(raw / f"{doc}.pdf"),
        "canonical_pdf_sha256": sha256_file(canonical / f"{doc}.pdf"),
    } for doc in source_ids]
    corpus_path = SAFE_ROOT / "corpus_manifest.json"
    sidecar_path = SAFE_ROOT / "structure_sidecar_manifest.json"
    policy_path = SAFE_ROOT / "retrieval_policy.json"
    write_json(corpus_path, {
        "schema_version": 1, "corpus_version": "safe-integration-synthetic/1.0",
        "document_count": len(docs), "documents": docs,
        "body_text_included": False,
    })
    write_json(sidecar_path, {
        "schema_version": 1, "structure_version": "synthetic-pdf-physical-pages/1.0",
        "sidecar_count": 0, "sidecars": [],
    })
    write_json(policy_path, {
        "schema_version": 1, "retrieval_policy_version": "rd-v2-retrieval-final-v1.0",
        "retrieval_policy": "DENSE_ONLY", "dense_representation": "SECTION_PATH",
        "dense_top_k": 20, "final_top_k": 5,
        "bm25_enabled": False, "hybrid_enabled": False, "reranker_enabled": False,
    })
    chunks_path = SAFE_ROOT / "child_chunks.jsonl"
    chunk_count = sum(1 for _ in chunks_path.open(encoding="utf-8"))
    manifest_path = SAFE_ROOT / "artifact_manifest.json"
    write_json(manifest_path, {
        "schema_version": 1, "artifact_id": "rd-v2-retrieval-final-v1.0-safe-integration",
        "status": "COMPLETE", "created_at": datetime.now(timezone.utc).isoformat(),
        "corpus_version": "safe-integration-synthetic/1.0",
        "source_hashes": [{"document_id": doc["document_id"], "sha256": doc["source_sha256"]} for doc in docs],
        "canonical_pdf_hashes": [{"document_id": doc["document_id"], "sha256": doc["canonical_pdf_sha256"]} for doc in docs],
        "embedding_representation": "SECTION_PATH",
        "embedding_model": "BAAI/bge-small-zh-v1.5",
        "embedding_model_revision": SNAPSHOT.name,
        "embedding_dimension": 512, "query_prefix": "为这个句子生成表示以用于检索相关文章：",
        "chunk_count": chunk_count, "embedding_count": chunk_count,
        "faiss_vector_count": chunk_count, "faiss_index_type": "IndexFlatIP",
        "retrieval_policy_version": "rd-v2-retrieval-final-v1.0",
        "artifacts": {
            "corpus_manifest": entry(corpus_path),
            "structure_sidecar_manifest": entry(sidecar_path),
            "chunk_artifact": entry(chunks_path),
            "embedding_artifact": entry(SAFE_ROOT / "embeddings.npy"),
            "faiss_index": entry(SAFE_ROOT / "child_vectors.faiss"),
            "retrieval_policy": entry(policy_path),
        },
        "body_text_included": False, "online_models_called": False,
    })
    lifecycle = ArtifactBuildLifecycle(SAFE_ROOT / "artifact_build_state.json", SAFE_ROOT)
    fingerprint = sha256_file(manifest_path)
    lifecycle.initialize(input_fingerprint=fingerprint, total_batches=1)
    lifecycle.start(input_fingerprint=fingerprint)
    lifecycle.checkpoint(completed_batches=1, files={
        "manifest": manifest_path, "chunks": chunks_path,
        "embeddings": SAFE_ROOT / "embeddings.npy",
        "faiss": SAFE_ROOT / "child_vectors.faiss",
    })
    lifecycle.complete(validator=lambda: None)
    settings = RDV2Settings.from_env(ROOT)
    settings = replace(settings, artifact_root=SAFE_ROOT, artifact_manifest=manifest_path)
    bundle = FrozenArtifactValidator(settings).validate_and_load()
    print(f"SAFE_FINALIZE=PASS lifecycle=COMPLETE chunks={len(bundle.chunks)}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("phase", choices=("prepare", "index", "finalize"))
    phase = parser.parse_args().phase
    {"prepare": prepare, "index": index, "finalize": finalize}[phase]()
