"""Bind existing frozen R&D V2 files into one formal, load-only namespace.

This command never parses, chunks, embeds, builds FAISS, or overwrites a
completed namespace.  It only validates and references the already-frozen
artifacts using content hashes.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from pathlib import Path

import numpy as np

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.artifact_lifecycle import (  # noqa: E402
    ArtifactBuildLifecycle,
    ArtifactLifecycleError,
    sha256_file,
)
from src.rd_v2_runtime import (  # noqa: E402
    FINAL_DENSE_REPRESENTATION,
    FINAL_POLICY_VERSION,
    FINAL_RETRIEVAL_POLICY,
    FrozenArtifactValidator,
    RDV2Settings,
    load_faiss_index,
)


def load_json(path: Path) -> dict:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise RuntimeError("JSON_OBJECT_REQUIRED")
    return value


def relative(root: Path, path: Path) -> str:
    return path.resolve().relative_to(root.resolve()).as_posix()


def file_entry(root: Path, path: Path) -> dict:
    return {
        "path": relative(root, path),
        "sha256": sha256_file(path),
        "bytes": path.stat().st_size,
    }


def json_digest(value: object) -> str:
    encoded = json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def write_or_validate(path: Path, value: dict) -> None:
    if path.exists():
        if load_json(path) != value:
            raise RuntimeError("RESUME_METADATA_MISMATCH")
        return
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temporary.write_text(
        json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    os.replace(temporary, path)


def build(args: argparse.Namespace) -> dict:
    root = args.project_root.resolve()
    final_root = args.output.resolve()
    corpus_snapshot_path = (
        root / "reports" / "rd_v2_real_retrieval_validation" / "corpus_snapshot.json"
    )
    baseline_root = (
        root
        / "data"
        / "rd_v2_corpus"
        / "retrieval_artifacts"
        / "rd-v2-retrieval-v1.0"
    )
    dense_root = (
        root
        / "data"
        / "rd_v2_corpus"
        / "retrieval_artifacts"
        / "rd-v2-retrieval-v1.0_embedding_enrichment"
        / "embedding_repr_section_path"
    )
    policy_source = (
        root
        / "reports"
        / "rd_v2_final_retrieval_validation"
        / "final_retrieval_policy.json"
    )
    sidecar_root = (
        root / "data" / "rd_v2_corpus" / "manifest" / "resolved_structure_sidecars"
    )
    normalized_pdf_root = root / "data" / "rd_v2_corpus" / "normalized" / "pdfs"
    raw_root = root / "data" / "rd_v2_corpus" / "raw"

    required = [
        corpus_snapshot_path,
        baseline_root / "artifact_manifest.json",
        baseline_root / "child_chunks.jsonl",
        dense_root / "artifact_manifest.json",
        dense_root / "embeddings.npy",
        dense_root / "child_vectors.faiss",
        policy_source,
    ]
    if any(not path.is_file() for path in required):
        raise RuntimeError("FROZEN_INPUT_MISSING")

    corpus = load_json(corpus_snapshot_path)
    baseline = load_json(baseline_root / "artifact_manifest.json")
    dense = load_json(dense_root / "artifact_manifest.json")
    policy = load_json(policy_source)
    if (
        policy.get("status") != "FROZEN"
        or policy.get("retrieval_policy_version") != FINAL_POLICY_VERSION
        or policy.get("retrieval_policy") != FINAL_RETRIEVAL_POLICY
        or policy.get("dense_representation") != FINAL_DENSE_REPRESENTATION
        or bool(policy.get("bm25_enabled"))
        or bool(policy.get("hybrid_enabled"))
        or bool(policy.get("reranker_enabled"))
    ):
        raise RuntimeError("FROZEN_POLICY_INVALID")
    if sha256_file(corpus_snapshot_path) != policy["corpus_snapshot_sha256"]:
        raise RuntimeError("CORPUS_SNAPSHOT_HASH_MISMATCH")
    if sha256_file(dense_root / "artifact_manifest.json") != policy[
        "dense_artifact_manifest_sha256"
    ]:
        raise RuntimeError("DENSE_MANIFEST_HASH_MISMATCH")
    if sha256_file(dense_root / "child_vectors.faiss") != policy["dense_faiss_sha256"]:
        raise RuntimeError("DENSE_FAISS_HASH_MISMATCH")
    if dense.get("mode") != FINAL_DENSE_REPRESENTATION:
        raise RuntimeError("DENSE_REPRESENTATION_MISMATCH")
    if dense.get("baseline_child_chunks_sha256") != baseline["artifact_files"][
        "child_chunks.jsonl"
    ]["sha256"]:
        raise RuntimeError("CHUNK_ALIGNMENT_MISMATCH")

    documents = []
    sidecars = []
    for document in corpus.get("documents", []):
        document_id = document["document_id"]
        sidecar = sidecar_root / f"{document_id}.json"
        canonical_pdf = normalized_pdf_root / f"{document_id}.pdf"
        raw_matches = list(raw_root.glob(f"{document_id}.*"))
        if len(raw_matches) != 1 or not sidecar.is_file() or not canonical_pdf.is_file():
            raise RuntimeError("CORPUS_COMPONENT_MISSING")
        if sha256_file(raw_matches[0]) != document["source_hash"]:
            raise RuntimeError("SOURCE_HASH_MISMATCH")
        if sha256_file(canonical_pdf) != document["canonical_pdf_hash"]:
            raise RuntimeError("CANONICAL_PDF_HASH_MISMATCH")
        if sha256_file(sidecar) != document["structure_sidecar_hash"]:
            raise RuntimeError("STRUCTURE_SIDECAR_HASH_MISMATCH")
        documents.append(
            {
                "document_id": document_id,
                "source_sha256": document["source_hash"],
                "canonical_pdf_sha256": document["canonical_pdf_hash"],
            }
        )
        sidecars.append(
            {
                "document_id": document_id,
                **file_entry(root, sidecar),
            }
        )

    fingerprint_payload = {
        "policy_version": FINAL_POLICY_VERSION,
        "policy_sha256": sha256_file(policy_source),
        "corpus_snapshot_sha256": sha256_file(corpus_snapshot_path),
        "baseline_manifest_sha256": sha256_file(
            baseline_root / "artifact_manifest.json"
        ),
        "dense_manifest_sha256": sha256_file(dense_root / "artifact_manifest.json"),
    }
    fingerprint = json_digest(fingerprint_payload)
    final_root.mkdir(parents=True, exist_ok=True)
    lifecycle = ArtifactBuildLifecycle(
        final_root / "artifact_build_state.json", final_root
    )
    if not lifecycle.state_path.exists():
        initial = lifecycle.initialize(input_fingerprint=fingerprint, total_batches=1)
    else:
        initial = lifecycle.read()
    lifecycle.start(input_fingerprint=fingerprint, resume=args.resume)
    existing_manifest_path = final_root / "artifact_manifest.json"
    if existing_manifest_path.is_file():
        created_at = str(load_json(existing_manifest_path)["created_at"])
    else:
        created_at = str(initial.get("created_at", initial["updated_at"]))

    corpus_manifest = {
        "schema_version": 1,
        "corpus_version": corpus["corpus_version"],
        "corpus_snapshot": file_entry(root, corpus_snapshot_path),
        "document_count": len(documents),
        "documents": documents,
        "body_text_included": False,
    }
    structure_manifest = {
        "schema_version": 1,
        "structure_version": baseline["structure_version"],
        "chunker_version": baseline["chunker_version"],
        "sidecar_count": len(sidecars),
        "sidecars": sidecars,
        "body_text_included": False,
    }
    corpus_manifest_path = final_root / "corpus_manifest.json"
    structure_manifest_path = final_root / "structure_sidecar_manifest.json"
    policy_path = final_root / "retrieval_policy.json"
    write_or_validate(corpus_manifest_path, corpus_manifest)
    write_or_validate(structure_manifest_path, structure_manifest)
    write_or_validate(policy_path, policy)

    support_files = {
        "corpus_manifest": corpus_manifest_path,
        "structure_sidecar_manifest": structure_manifest_path,
        "retrieval_policy": policy_path,
    }
    lifecycle.checkpoint(completed_batches=1, files=support_files)

    count = int(dense["child_chunk_count"])
    dimension = int(dense["dimension"])
    manifest = {
        "schema_version": 1,
        "artifact_id": f"{FINAL_POLICY_VERSION}+{fingerprint[:16]}",
        "status": "COMPLETE",
        "created_at": created_at,
        "corpus_version": corpus["corpus_version"],
        "source_hashes": [
            {"document_id": row["document_id"], "sha256": row["source_sha256"]}
            for row in documents
        ],
        "canonical_pdf_hashes": [
            {
                "document_id": row["document_id"],
                "sha256": row["canonical_pdf_sha256"],
            }
            for row in documents
        ],
        "structure_version": baseline["structure_version"],
        "chunker_version": baseline["chunker_version"],
        "embedding_representation": dense["mode"],
        "embedding_model": dense["embedding"]["model"],
        "embedding_model_revision": dense["embedding"]["model_revision"],
        "embedding_dimension": dimension,
        "embedding_normalization": dense["normalization"],
        "query_prefix": dense["embedding"]["query_prefix"],
        "chunk_count": count,
        "embedding_count": int(dense["embedding_count"]),
        "faiss_vector_count": int(dense["faiss_count"]),
        "faiss_index_type": dense["faiss_index_type"],
        "retrieval_policy_version": FINAL_POLICY_VERSION,
        "artifacts": {
            "corpus_manifest": file_entry(root, corpus_manifest_path),
            "structure_sidecar_manifest": file_entry(root, structure_manifest_path),
            "chunk_artifact": file_entry(root, baseline_root / "child_chunks.jsonl"),
            "embedding_artifact": file_entry(root, dense_root / "embeddings.npy"),
            "faiss_index": file_entry(root, dense_root / "child_vectors.faiss"),
            "retrieval_policy": file_entry(root, policy_path),
        },
        "runtime_contract": {
            "load_only": True,
            "automatic_rebuild": False,
            "bm25_enabled": False,
            "hybrid_enabled": False,
            "reranker_enabled": False,
            "embedding_faiss_process_isolation": True,
            "torch_threads": 1,
            "mkldnn_enabled": False,
            "kmp_duplicate_lib_ok_allowed": False,
        },
        "body_text_included": False,
        "online_models_called": False,
    }
    artifact_manifest_path = existing_manifest_path
    write_or_validate(artifact_manifest_path, manifest)

    def validate_materialized_files() -> None:
        chunks = sum(
            1
            for line in (baseline_root / "child_chunks.jsonl").open(encoding="utf-8")
            if line.strip()
        )
        matrix = np.load(dense_root / "embeddings.npy", mmap_mode="r")
        if chunks != count or matrix.shape != (count, dimension):
            raise RuntimeError("ARTIFACT_COUNT_OR_DIMENSION_MISMATCH")
        index = load_faiss_index(dense_root / "child_vectors.faiss")
        if int(index.ntotal) != count or int(index.d) != dimension:
            raise RuntimeError("FAISS_COUNT_OR_DIMENSION_MISMATCH")

    lifecycle.complete(validator=validate_materialized_files)
    settings = RDV2Settings(
        project_root=root,
        artifact_root=final_root,
        artifact_manifest=artifact_manifest_path,
    )
    FrozenArtifactValidator(settings).validate_and_load()
    return {
        "status": "PASS",
        "artifact_id": manifest["artifact_id"],
        "chunk_count": count,
        "embedding_count": manifest["embedding_count"],
        "faiss_vector_count": manifest["faiss_vector_count"],
        "policy_version": FINAL_POLICY_VERSION,
        "online_models_called": False,
        "body_text_logged": False,
    }


def verify(args: argparse.Namespace) -> dict:
    settings = RDV2Settings(
        project_root=args.project_root.resolve(),
        artifact_root=args.output.resolve(),
        artifact_manifest=args.output.resolve() / "artifact_manifest.json",
    )
    bundle = FrozenArtifactValidator(settings).validate_and_load()
    return {
        "status": "PASS",
        "artifact_id": bundle.manifest["artifact_id"],
        "chunk_count": len(bundle.chunks),
        "faiss_vector_count": int(bundle.index.ntotal),
        "policy_version": bundle.policy["retrieval_policy_version"],
        "online_models_called": False,
        "body_text_logged": False,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=("build", "verify"))
    parser.add_argument("--project-root", type=Path, default=PROJECT_ROOT)
    parser.add_argument(
        "--output",
        type=Path,
        default=PROJECT_ROOT
        / "data"
        / "rd_v2_corpus"
        / "retrieval_artifacts"
        / FINAL_POLICY_VERSION,
    )
    parser.add_argument("--resume", action="store_true")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    try:
        result = build(args) if args.action == "build" else verify(args)
    except Exception as exc:
        if args.action == "build":
            state_path = args.output / "artifact_build_state.json"
            if state_path.is_file():
                try:
                    ArtifactBuildLifecycle(state_path, args.output).fail(
                        getattr(exc, "code", type(exc).__name__)
                    )
                except ArtifactLifecycleError:
                    pass
        raise
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
