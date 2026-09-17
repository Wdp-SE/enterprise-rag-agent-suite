"""Frozen, Dense-only runtime for R&D Document RAG V2.

The runtime has no parse/chunk/embed/index build path.  It can only load and
validate the explicitly frozen artifacts before serving a query.
"""

from __future__ import annotations

import hashlib
import json
import multiprocessing as mp
import os
import queue
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping, Optional, Protocol, Sequence

import numpy as np

from src.artifact_lifecycle import sha256_file
from src.native_runtime import NativeRuntimePolicy, validate_embedding_batch
from src.trusted_qa import (
    ShadowPolicyProfile,
    TrustedQAMode,
    apply_post_answer_enforcement,
    build_answer_evidence_audit,
    collect_retrieval_signals,
    decide_evidence_sufficiency,
    decide_post_answer_enforcement,
)


FINAL_POLICY_VERSION = "rd-v2-retrieval-final-v1.0"
FINAL_RETRIEVAL_POLICY = "DENSE_ONLY"
FINAL_DENSE_REPRESENTATION = "SECTION_PATH"


class ArtifactValidationError(RuntimeError):
    def __init__(self, code: str, detail: str = ""):
        self.code = code
        self.detail = detail
        super().__init__(f"{code}: {detail}" if detail else code)


class QueryRuntimeError(RuntimeError):
    def __init__(self, code: str):
        self.code = code
        super().__init__(code)


def _env_bool(name: str, default: bool) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    value = raw.strip().casefold()
    if value in {"1", "true", "yes", "on"}:
        return True
    if value in {"0", "false", "no", "off"}:
        return False
    raise ValueError(f"{name} must be a boolean")


@dataclass(frozen=True)
class RDV2Settings:
    project_root: Path
    artifact_root: Path
    artifact_manifest: Path
    policy_version: str = FINAL_POLICY_VERSION
    retrieval_policy: str = FINAL_RETRIEVAL_POLICY
    dense_representation: str = FINAL_DENSE_REPRESENTATION
    dense_top_k: int = 20
    final_top_k: int = 5
    context_budget: int = 1800
    neighbor_children: int = 1
    torch_threads: int = 1
    mkldnn_enabled: bool = False
    embedding_snapshot: Optional[Path] = None
    embedding_max_length: int = 512
    generation_provider: str = "dashscope"
    generation_model: str = "qwen-turbo"
    allow_external_generation: bool = False
    trusted_qa_mode: str = "ENFORCE"

    @classmethod
    def from_env(cls, project_root: Path | str | None = None) -> "RDV2Settings":
        root = Path(project_root or os.environ.get("RD_V2_PROJECT_ROOT", Path.cwd()))
        root = root.resolve()
        from dotenv import load_dotenv

        load_dotenv(root / ".env", override=False)
        artifact_value = Path(
            os.environ.get(
                "RD_V2_ARTIFACT_ROOT",
                Path("data")
                / "rd_v2_corpus"
                / "retrieval_artifacts"
                / FINAL_POLICY_VERSION,
            )
        )
        artifact_root = (
            artifact_value if artifact_value.is_absolute() else root / artifact_value
        ).resolve()
        raw_snapshot = os.environ.get("RD_V2_EMBEDDING_MODEL_SNAPSHOT")
        snapshot_value = Path(raw_snapshot) if raw_snapshot else None
        if snapshot_value is not None and not snapshot_value.is_absolute():
            snapshot_value = root / snapshot_value
        return cls(
            project_root=root,
            artifact_root=artifact_root,
            artifact_manifest=artifact_root / "artifact_manifest.json",
            dense_top_k=int(os.environ.get("RD_V2_DENSE_TOP_K", "20")),
            final_top_k=int(os.environ.get("RD_V2_FINAL_TOP_K", "5")),
            context_budget=int(os.environ.get("RD_V2_CONTEXT_BUDGET", "1800")),
            neighbor_children=int(os.environ.get("RD_V2_NEIGHBOR_CHILDREN", "1")),
            torch_threads=int(os.environ.get("RD_V2_TORCH_THREADS", "1")),
            mkldnn_enabled=_env_bool("RD_V2_MKLDNN_ENABLED", False),
            embedding_snapshot=(snapshot_value.resolve() if snapshot_value else None),
            generation_provider=os.environ.get("RD_V2_GENERATION_PROVIDER", "dashscope"),
            generation_model=os.environ.get("RD_V2_GENERATION_MODEL", "qwen-turbo"),
            allow_external_generation=_env_bool(
                "RD_V2_ALLOW_EXTERNAL_GENERATION", False
            ),
            trusted_qa_mode=os.environ.get("RD_V2_TRUSTED_QA_MODE", "ENFORCE"),
        )

    def validate(self) -> None:
        if self.policy_version != FINAL_POLICY_VERSION:
            raise ArtifactValidationError("POLICY_VERSION_MISMATCH")
        if (
            self.retrieval_policy != FINAL_RETRIEVAL_POLICY
            or self.dense_representation != FINAL_DENSE_REPRESENTATION
        ):
            raise ArtifactValidationError("POLICY_CONFIGURATION_MISMATCH")
        if self.dense_top_k < self.final_top_k or self.final_top_k < 1:
            raise ValueError("dense_top_k must be >= final_top_k >= 1")
        if self.context_budget < 1 or self.neighbor_children < 0:
            raise ValueError("invalid context expansion settings")
        if self.trusted_qa_mode not in {"OFF", "SHADOW", "ENFORCE"}:
            raise ValueError("RD_V2_TRUSTED_QA_MODE is invalid")
        NativeRuntimePolicy(
            torch_threads=self.torch_threads,
            mkldnn_enabled=self.mkldnn_enabled,
        ).validate_environment()


@dataclass
class FrozenArtifactBundle:
    manifest: dict
    policy: dict
    chunks: list[dict]
    index: object


def load_faiss_index(path: Path):
    """Load FAISS through Python's Unicode-safe file API on Windows.

    FAISS 1.9's native fopen path handling can fail for non-ASCII absolute
    paths.  Deserializing bytes preserves the index exactly and avoids changing
    the process working directory.
    """

    import faiss

    payload = np.frombuffer(path.read_bytes(), dtype=np.uint8)
    return faiss.deserialize_index(payload)


class FrozenArtifactValidator:
    """Fail-closed validator for the formal immutable artifact namespace."""

    def __init__(self, settings: RDV2Settings):
        self.settings = settings

    def _load_json(self, path: Path, missing_code: str) -> dict:
        if not path.is_file():
            raise ArtifactValidationError(missing_code)
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
        except Exception as exc:
            raise ArtifactValidationError("ARTIFACT_MANIFEST_INVALID") from exc
        if not isinstance(value, dict):
            raise ArtifactValidationError("ARTIFACT_MANIFEST_INVALID")
        return value

    def _resolve(self, relative: str) -> Path:
        path = (self.settings.project_root / relative).resolve()
        try:
            path.relative_to(self.settings.project_root)
        except ValueError as exc:
            raise ArtifactValidationError("ARTIFACT_PATH_OUTSIDE_PROJECT") from exc
        return path

    def _validate_file(self, metadata: Mapping[str, object], role: str) -> Path:
        path = self._resolve(str(metadata.get("path", "")))
        if not path.is_file():
            raise ArtifactValidationError("ARTIFACT_FILE_MISSING", role)
        if path.stat().st_size != int(metadata.get("bytes", -1)):
            raise ArtifactValidationError("ARTIFACT_HASH_MISMATCH", role)
        if sha256_file(path) != metadata.get("sha256"):
            raise ArtifactValidationError("ARTIFACT_HASH_MISMATCH", role)
        return path

    def validate_and_load(self) -> FrozenArtifactBundle:
        self.settings.validate()
        manifest = self._load_json(
            self.settings.artifact_manifest, "ARTIFACT_MANIFEST_MISSING"
        )
        if manifest.get("status") != "COMPLETE":
            raise ArtifactValidationError("ARTIFACT_NOT_COMPLETE")
        state_path = self.settings.artifact_root / "artifact_build_state.json"
        state = self._load_json(state_path, "ARTIFACT_BUILD_STATE_MISSING")
        if state.get("status") != "COMPLETE":
            raise ArtifactValidationError("ARTIFACT_NOT_COMPLETE")

        required = dict(manifest.get("artifacts", {}))
        expected_roles = {
            "corpus_manifest",
            "structure_sidecar_manifest",
            "chunk_artifact",
            "embedding_artifact",
            "faiss_index",
            "retrieval_policy",
        }
        if set(required) != expected_roles:
            raise ArtifactValidationError("ARTIFACT_MANIFEST_INVALID")
        paths = {
            role: self._validate_file(metadata, role)
            for role, metadata in required.items()
        }

        corpus_manifest = self._load_json(
            paths["corpus_manifest"], "CORPUS_MANIFEST_MISSING"
        )
        structure_manifest = self._load_json(
            paths["structure_sidecar_manifest"],
            "STRUCTURE_SIDECAR_MANIFEST_MISSING",
        )
        if "corpus_snapshot" in corpus_manifest:
            self._validate_file(corpus_manifest["corpus_snapshot"], "corpus_snapshot")
        for sidecar in structure_manifest.get("sidecars", []):
            self._validate_file(sidecar, "structure_sidecar")
        corpus_documents = list(corpus_manifest.get("documents", []))
        source_hashes = {
            row["document_id"]: row["sha256"]
            for row in manifest.get("source_hashes", [])
        }
        pdf_hashes = {
            row["document_id"]: row["sha256"]
            for row in manifest.get("canonical_pdf_hashes", [])
        }
        for document in corpus_documents:
            document_id = str(document["document_id"])
            if (
                source_hashes.get(document_id) != document.get("source_sha256")
                or pdf_hashes.get(document_id)
                != document.get("canonical_pdf_sha256")
            ):
                raise ArtifactValidationError("ARTIFACT_HASH_MISMATCH", "corpus")
            raw_matches = list(
                (
                    self.settings.project_root / "data" / "rd_v2_corpus" / "raw"
                ).glob(f"{document_id}.*")
            )
            canonical_pdf = (
                self.settings.project_root
                / "data"
                / "rd_v2_corpus"
                / "normalized"
                / "pdfs"
                / f"{document_id}.pdf"
            )
            if len(raw_matches) != 1 or not canonical_pdf.is_file():
                raise ArtifactValidationError("ARTIFACT_FILE_MISSING", "corpus")
            if (
                sha256_file(raw_matches[0]) != document["source_sha256"]
                or sha256_file(canonical_pdf) != document["canonical_pdf_sha256"]
            ):
                raise ArtifactValidationError("ARTIFACT_HASH_MISMATCH", "corpus")

        policy = self._load_json(paths["retrieval_policy"], "POLICY_FILE_MISSING")
        if (
            policy.get("retrieval_policy_version") != self.settings.policy_version
            or manifest.get("retrieval_policy_version") != self.settings.policy_version
        ):
            raise ArtifactValidationError("POLICY_VERSION_MISMATCH")
        if (
            policy.get("retrieval_policy") != FINAL_RETRIEVAL_POLICY
            or policy.get("dense_representation") != FINAL_DENSE_REPRESENTATION
            or bool(policy.get("bm25_enabled"))
            or bool(policy.get("hybrid_enabled"))
            or bool(policy.get("reranker_enabled"))
        ):
            raise ArtifactValidationError("POLICY_CONFIGURATION_MISMATCH")
        if (
            int(policy.get("dense_top_k", -1)) != self.settings.dense_top_k
            or int(policy.get("final_top_k", -1)) != self.settings.final_top_k
        ):
            raise ArtifactValidationError("POLICY_CONFIGURATION_MISMATCH")

        chunks = []
        chunk_ids = set()
        try:
            with paths["chunk_artifact"].open(encoding="utf-8") as stream:
                for line in stream:
                    if not line.strip():
                        continue
                    item = json.loads(line)
                    chunk_id = item.get("chunk_id")
                    if not chunk_id or chunk_id in chunk_ids:
                        raise ArtifactValidationError("ARTIFACT_CHUNK_ID_INVALID")
                    chunk_ids.add(chunk_id)
                    chunks.append(item)
        except ArtifactValidationError:
            raise
        except Exception as exc:
            raise ArtifactValidationError("ARTIFACT_CHUNK_FILE_INVALID") from exc

        expected_count = int(manifest.get("chunk_count", -1))
        embedding_count = int(manifest.get("embedding_count", -1))
        faiss_count = int(manifest.get("faiss_vector_count", -1))
        if len(chunks) != expected_count:
            raise ArtifactValidationError("ARTIFACT_COUNT_MISMATCH", "chunks")

        try:
            embeddings = np.load(paths["embedding_artifact"], mmap_mode="r")
        except Exception as exc:
            raise ArtifactValidationError("EMBEDDING_ARTIFACT_INVALID") from exc
        expected_dimension = int(manifest.get("embedding_dimension", -1))
        if embeddings.ndim != 2 or embeddings.shape[1] != expected_dimension:
            raise ArtifactValidationError("EMBEDDING_DIMENSION_MISMATCH")
        if embeddings.shape[0] != embedding_count:
            raise ArtifactValidationError("ARTIFACT_COUNT_MISMATCH", "embeddings")
        if not np.isfinite(embeddings).all():
            raise ArtifactValidationError("EMBEDDING_ARTIFACT_NON_FINITE")
        norms = np.linalg.norm(embeddings, axis=1)
        if not np.allclose(norms, 1.0, atol=1e-4):
            raise ArtifactValidationError("EMBEDDING_ARTIFACT_NOT_UNIT_NORMALIZED")

        try:
            index = load_faiss_index(paths["faiss_index"])
        except Exception as exc:
            raise ArtifactValidationError("FAISS_ARTIFACT_INVALID") from exc
        if int(index.d) != expected_dimension:
            raise ArtifactValidationError("EMBEDDING_DIMENSION_MISMATCH")
        if int(index.ntotal) != faiss_count:
            raise ArtifactValidationError("ARTIFACT_COUNT_MISMATCH", "faiss")
        if len(chunks) != embedding_count or embedding_count != faiss_count:
            raise ArtifactValidationError("ARTIFACT_COUNT_MISMATCH")
        return FrozenArtifactBundle(
            manifest=manifest, policy=policy, chunks=chunks, index=index
        )


class QueryEmbedder(Protocol):
    def encode(self, texts: Sequence[str]) -> np.ndarray: ...

    def close(self) -> None: ...


class LocalEmbeddingProcessClient:
    """Persistent spawned worker; PyTorch never shares a process with FAISS."""

    def __init__(
        self,
        *,
        snapshot: Path,
        dimension: int,
        query_prefix: str,
        max_length: int = 512,
        timeout_seconds: float = 120.0,
    ):
        self.snapshot = Path(snapshot)
        self.dimension = dimension
        self.query_prefix = query_prefix
        self.max_length = max_length
        self.timeout_seconds = timeout_seconds
        self._process = None
        self._request_queue = None
        self._response_queue = None

    def start(self) -> None:
        if self._process is not None and self._process.is_alive():
            return
        from src.local_embedding_worker import embedding_worker_main

        context = mp.get_context("spawn")
        self._request_queue = context.Queue(maxsize=4)
        self._response_queue = context.Queue(maxsize=4)
        config = {
            "snapshot": str(self.snapshot),
            "dimension": self.dimension,
            "query_prefix": self.query_prefix,
            "max_length": self.max_length,
            "torch_threads": 1,
            "mkldnn_enabled": False,
        }
        self._process = context.Process(
            target=embedding_worker_main,
            args=(self._request_queue, self._response_queue, config),
            name="rd-v2-embedding-worker",
            daemon=True,
        )
        self._process.start()
        try:
            response = self._response_queue.get(timeout=self.timeout_seconds)
        except queue.Empty as exc:
            self.close(force=True)
            raise QueryRuntimeError("EMBEDDING_WORKER_START_TIMEOUT") from exc
        if response.get("type") != "READY":
            self.close(force=True)
            raise QueryRuntimeError(str(response.get("code", "EMBEDDING_WORKER_FAILED")))

    def encode(self, texts: Sequence[str]) -> np.ndarray:
        self.start()
        request_id = uuid.uuid4().hex
        self._request_queue.put({"id": request_id, "texts": list(texts)})
        try:
            response = self._response_queue.get(timeout=self.timeout_seconds)
        except queue.Empty as exc:
            raise QueryRuntimeError("EMBEDDING_WORKER_QUERY_TIMEOUT") from exc
        if response.get("type") != "RESULT" or response.get("id") != request_id:
            raise QueryRuntimeError(str(response.get("code", "EMBEDDING_WORKER_FAILED")))
        vectors = np.asarray(response["vectors"], dtype=np.float32)
        validate_embedding_batch(vectors, dimension=self.dimension)
        return vectors

    def close(self, *, force: bool = False) -> None:
        if self._process is None:
            return
        if self._process.is_alive() and not force and self._request_queue is not None:
            self._request_queue.put(None)
            self._process.join(timeout=5)
        if self._process.is_alive():
            self._process.terminate()
            self._process.join(timeout=5)
        if self._request_queue is not None:
            self._request_queue.close()
        if self._response_queue is not None:
            self._response_queue.close()
        self._process = None


class FrozenDenseRetriever:
    def __init__(self, bundle: FrozenArtifactBundle, embedder: QueryEmbedder):
        self.bundle = bundle
        self.embedder = embedder

    def retrieve(self, question: str, *, top_k: int) -> list[dict]:
        query_vector = self.embedder.encode([question])
        dimension = int(self.bundle.manifest["embedding_dimension"])
        validate_embedding_batch(query_vector, dimension=dimension)
        limit = min(top_k, len(self.bundle.chunks))
        scores, indices = self.bundle.index.search(
            np.ascontiguousarray(query_vector, dtype=np.float32), limit
        )
        results = []
        for rank, (row, score) in enumerate(zip(indices[0], scores[0]), start=1):
            if int(row) < 0:
                continue
            item = dict(self.bundle.chunks[int(row)])
            similarity = float(score)
            item["distance"] = similarity
            item["dense_score"] = similarity
            item["retrieval_rank"] = rank
            item["retrieval_sources"] = ["dense"]
            results.append(item)
        return results


class ExistingGenerationAdapter:
    """Thin adapter around the existing generic structured-output generation."""

    def __init__(self, *, provider: str, model: str, schema: str = "text"):
        from src.api_requests import APIProcessor

        self.processor = APIProcessor(provider=provider)
        self.model = model
        self.schema = schema

    def generate(self, *, question: str, context: str) -> dict:
        return self.processor.get_answer_from_rag_context(
            question=question,
            rag_context=context,
            schema=self.schema,
            model=self.model,
            prompt_mode="generic",
        )


def _format_context(results: Sequence[Mapping[str, object]]) -> str:
    parts = []
    for result in results:
        section_path = result.get("section_path") or []
        if isinstance(section_path, (list, tuple)):
            section_path = " > ".join(str(part) for part in section_path)
        parts.append(
            "Retrieved evidence:\n"
            f"document_id: {result['document_id']}\n"
            f"page_number: {result.get('page', result.get('page_number'))}\n"
            f"section_id: {result.get('section_id', '')}\n"
            f"section_path: {section_path}\n"
            f"chunk_id: {result.get('chunk_id', '')}\n"
            f'\"\"\"\n{result.get("text", "")}\n\"\"\"'
        )
    return "\n\n---\n\n".join(parts)


def validate_citation_membership(
    claimed_sources: Sequence[object], retrieval_results: Sequence[Mapping[str, object]]
) -> list[dict]:
    allowed = {
        (result.get("document_id"), result.get("page", result.get("page_number")))
        for result in retrieval_results
    }
    validated = []
    seen = set()
    for source in claimed_sources or []:
        if hasattr(source, "model_dump"):
            source = source.model_dump()
        if not isinstance(source, Mapping):
            continue
        key = (source.get("document_id"), source.get("page_number"))
        if key in allowed and key not in seen:
            seen.add(key)
            validated.append({"document_id": key[0], "page_number": key[1]})
    return validated


def build_safe_trace(results: Sequence[Mapping[str, object]]) -> list[dict]:
    trace = []
    for result in results:
        trace.append(
            {
                "chunk_id": result.get("chunk_id"),
                "document_id": result.get("document_id"),
                "page_number": result.get("page", result.get("page_number")),
                "section_id": result.get("section_id"),
                "section_source": result.get("section_source"),
                "retrieval_rank": result.get("retrieval_rank"),
                "similarity_score": result.get("dense_score"),
                "context_role": result.get("context_role"),
            }
        )
    return trace


class RDV2QueryRuntime:
    def __init__(
        self,
        *,
        settings: RDV2Settings,
        bundle: FrozenArtifactBundle,
        embedder: QueryEmbedder,
        generator: Optional[ExistingGenerationAdapter] = None,
    ):
        from src.context_expansion import SectionContextExpander

        self.settings = settings
        self.bundle = bundle
        self.retriever = FrozenDenseRetriever(bundle, embedder)
        self.embedder = embedder
        self.generator = generator
        self.expander = SectionContextExpander.from_chunks(
            bundle.chunks,
            neighbor_children=settings.neighbor_children,
            max_tokens=settings.context_budget,
        )

    def health(self) -> dict:
        return {
            "service_status": "READY",
            "artifact_status": self.bundle.manifest["status"],
            "retrieval_policy_version": self.settings.policy_version,
            "retrieval_policy": FINAL_RETRIEVAL_POLICY,
            "dense_representation": FINAL_DENSE_REPRESENTATION,
        }

    def close(self) -> None:
        close = getattr(self.embedder, "close", None)
        if callable(close):
            close()

    def query(self, question: str) -> dict:
        if not isinstance(question, str) or not question.strip():
            raise QueryRuntimeError("QUESTION_EMPTY")
        dense_hits = self.retriever.retrieve(
            question.strip(), top_k=self.settings.dense_top_k
        )
        primary_hits = dense_hits[: self.settings.final_top_k]
        evidence = self.expander.expand(primary_hits)
        trace = build_safe_trace(evidence)
        if self.generator is None:
            status = (
                "GENERATION_DISABLED_BY_DATA_POLICY"
                if not self.settings.allow_external_generation
                else "GENERATION_NOT_CONFIGURED"
            )
            return {"answer": "N/A", "sources": [], "status": status, "trace": trace}

        question_id = "adhoc-" + hashlib.sha256(
            question.encode("utf-8")
        ).hexdigest()[:16]
        snapshot = collect_retrieval_signals(
            question_id=question_id,
            retrieval_results=evidence,
            version_governance_enabled=False,
        )
        shadow_decision = decide_evidence_sufficiency(
            snapshot,
            mode=TrustedQAMode(self.settings.trusted_qa_mode),
            profile=ShadowPolicyProfile.HARD_PLUS_SOFT,
        )
        try:
            generated = self.generator.generate(
                question=question, context=_format_context(evidence)
            )
            if not isinstance(generated, dict) or "final_answer" not in generated:
                raise ValueError("STRUCTURED_OUTPUT_INVALID")
            original = dict(generated)
            claimed = list(generated.get("relevant_sources") or [])
            validated = validate_citation_membership(claimed, evidence)
            generated["sources"] = validated
            if generated.get("final_answer") == "N/A":
                generated["sources"] = []
            audit = build_answer_evidence_audit(
                generation_performed=True,
                structured_output_valid=True,
                final_answer=generated.get("final_answer"),
                claimed_citations=claimed,
                validated_citations=generated["sources"],
                citation_membership_checked=True,
            )
        except Exception:
            original = {"final_answer": None, "relevant_sources": [], "sources": []}
            generated = dict(original)
            audit = build_answer_evidence_audit(
                generation_performed=True,
                structured_output_valid=False,
                citation_membership_checked=False,
                generation_error_type="GENERATION_OR_SCHEMA_ERROR",
            )
        enforcement = decide_post_answer_enforcement(
            audit, mode=TrustedQAMode(self.settings.trusted_qa_mode)
        )
        final = apply_post_answer_enforcement(
            generated, enforcement, citation_fields=("relevant_sources", "sources")
        )
        if enforcement.enforced:
            status = "FAIL_CLOSED"
        elif final.get("final_answer") == "N/A":
            status = "ABSTAINED"
        else:
            status = "OK"
        return {
            "answer": final.get("final_answer", "N/A"),
            "sources": final.get("sources", []),
            "status": status,
            "trace": trace,
            "trusted_qa": {
                "mode": self.settings.trusted_qa_mode,
                "shadow_decision": (
                    shadow_decision.decision.value
                    if shadow_decision is not None
                    else None
                ),
                "post_answer_action": enforcement.action.value,
                "enforced": enforcement.enforced,
                "policy_version": enforcement.policy_version,
            },
        }


def _discover_snapshot(project_manifest: Mapping[str, object]) -> Optional[Path]:
    explicit = os.environ.get("RD_V2_EMBEDDING_MODEL_SNAPSHOT")
    if explicit:
        return Path(explicit).resolve()
    revision = str(project_manifest.get("embedding_model_revision", ""))
    hf_home = Path(os.environ.get("HF_HOME", Path.home() / ".cache" / "huggingface"))
    candidate = (
        hf_home
        / "hub"
        / "models--BAAI--bge-small-zh-v1.5"
        / "snapshots"
        / revision
    )
    return candidate.resolve() if candidate.is_dir() else None


def create_runtime(
    settings: RDV2Settings | None = None,
    *,
    embedder: QueryEmbedder | None = None,
    generator: ExistingGenerationAdapter | None = None,
) -> RDV2QueryRuntime:
    settings = settings or RDV2Settings.from_env()
    bundle = FrozenArtifactValidator(settings).validate_and_load()
    if embedder is None:
        snapshot = settings.embedding_snapshot or _discover_snapshot(bundle.manifest)
        if snapshot is None:
            raise QueryRuntimeError("EMBEDDING_MODEL_SNAPSHOT_NOT_CONFIGURED")
        embedder = LocalEmbeddingProcessClient(
            snapshot=snapshot,
            dimension=int(bundle.manifest["embedding_dimension"]),
            query_prefix=str(bundle.manifest["query_prefix"]),
            max_length=settings.embedding_max_length,
        )
    if generator is None and settings.allow_external_generation:
        generator = ExistingGenerationAdapter(
            provider=settings.generation_provider,
            model=settings.generation_model,
        )
    return RDV2QueryRuntime(
        settings=settings, bundle=bundle, embedder=embedder, generator=generator
    )
