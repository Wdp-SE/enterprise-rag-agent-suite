"""Sparse retrieval, RRF fusion, and bounded section context for RAG V2."""

from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
from typing import Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

from rank_bm25 import BM25Plus

from src.document_metadata import normalize_document_metadata
from src.context_expansion import SectionContextExpander
from src.reranking import LLMReranker
from src.retrieval import VectorRetriever
from src.text_tokenization import technical_tokenize
from src.versioning.models import VersionResolutionPlan
from src.versioning.policy import apply_version_policy


def _metadata_from_document(document: Dict) -> Dict:
    metainfo = normalize_document_metadata(document.get("metainfo"))
    result = {
        "document_id": metainfo["document_id"],
        "document_title": metainfo["title"],
        "document_type": metainfo["document_type"],
        "source": metainfo["source"],
        "source_url": metainfo.get("source_url"),
        "category": metainfo.get("category"),
        "tags": metainfo.get("tags", []),
    }
    for field in (
        "document_number",
        "publish_date",
        "effective_date",
        "version_family",
        "version",
        "status",
    ):
        if metainfo.get(field) is not None:
            result[field] = metainfo[field]
    return result


def _normalise_chunk(chunk: Mapping, metadata: Optional[Mapping] = None) -> Dict:
    result = dict(metadata or {})
    result.update(dict(chunk))
    page_number = result.get("page_number", result.get("page"))
    result["page"] = page_number
    result["page_number"] = page_number
    result.setdefault("parent_id", result.get("section_id"))
    return result


class BM25Retriever:
    """Lightweight corpus-wide BM25 with an explicit ``build/search`` API."""

    def __init__(
        self,
        documents_dir: Optional[Path] = None,
        additional_documents_dirs: Optional[Sequence[Path]] = None,
    ):
        self.chunks: List[Dict] = []
        self.index: Optional[BM25Plus] = None
        self._token_sets: List[set[str]] = []
        if documents_dir is not None:
            self.load_documents(
                [Path(documents_dir), *(additional_documents_dirs or [])]
            )

    def load_documents(self, directories: Iterable[Path]) -> None:
        chunks: List[Dict] = []
        seen_document_ids = set()
        for directory in directories:
            for path in sorted(Path(directory).glob("*.json")):
                document = json.loads(path.read_text(encoding="utf-8"))
                if not (
                    isinstance(document, dict)
                    and "metainfo" in document
                    and "content" in document
                ):
                    continue
                metadata = _metadata_from_document(document)
                document_id = metadata["document_id"]
                if document_id in seen_document_ids:
                    raise ValueError(
                        f"Duplicate document_id '{document_id}' in BM25 corpus"
                    )
                seen_document_ids.add(document_id)
                for index, chunk in enumerate(document["content"].get("chunks", [])):
                    normalised = _normalise_chunk(chunk, metadata)
                    normalised.setdefault("id", index)
                    normalised.setdefault("chunk_id", f"{document_id}:{index}")
                    chunks.append(normalised)
        self.build(chunks)

    def build(self, chunks: Iterable[Mapping]) -> "BM25Retriever":
        self.chunks = [_normalise_chunk(chunk) for chunk in chunks]
        tokenized = [technical_tokenize(chunk.get("text", "")) for chunk in self.chunks]
        self._token_sets = [set(tokens) for tokens in tokenized]
        # BM25Plus avoids the zero-IDF edge case of tiny prototype corpora while
        # retaining the same local sparse-retrieval semantics.
        self.index = BM25Plus(tokenized) if tokenized else None
        return self

    def search(
        self,
        query: str,
        top_k: int = 10,
        *,
        document_ids: Optional[Sequence[str]] = None,
        version_plan: Optional[VersionResolutionPlan] = None,
    ) -> List[Dict]:
        if self.index is None or top_k <= 0:
            return []
        tokens = technical_tokenize(query)
        if not tokens:
            return []
        selected_ids = set(document_ids) if document_ids is not None else None
        if version_plan is not None:
            eligible = set(version_plan.eligible_document_ids)
            selected_ids = eligible if selected_ids is None else selected_ids & eligible

        scores = self.index.get_scores(tokens)
        query_tokens = set(tokens)
        candidates = []
        for index, score in enumerate(scores):
            chunk = self.chunks[index]
            if selected_ids is not None and chunk.get("document_id") not in selected_ids:
                continue
            if not query_tokens.intersection(self._token_sets[index]):
                continue
            # Zero-score rows add arbitrary noise to RRF and hide whether sparse
            # retrieval genuinely contributed.
            if float(score) <= 0.0:
                continue
            candidate = dict(chunk)
            candidate["bm25_score"] = round(float(score), 6)
            candidate["distance"] = candidate["bm25_score"]
            candidate["retrieval_source"] = "bm25"
            if version_plan is not None:
                candidate = apply_version_policy(candidate, version_plan)
            candidates.append(candidate)
        candidates.sort(
            key=lambda item: item.get("final_pre_rerank_score", item["bm25_score"]),
            reverse=True,
        )
        return candidates[:top_k]


def _dedupe_key(result: Mapping) -> Tuple:
    chunk_id = result.get("chunk_id")
    if chunk_id:
        return ("chunk", chunk_id)
    return (
        "fallback",
        result.get("document_id"),
        result.get("page", result.get("page_number")),
        result.get("text"),
    )


def reciprocal_rank_fusion(
    dense_results: Sequence[Mapping],
    bm25_results: Sequence[Mapping],
    *,
    rrf_k: int = 60,
    dense_weight: float = 1.0,
    bm25_weight: float = 1.0,
    top_k: Optional[int] = None,
) -> List[Dict]:
    """Fuse ranks without pretending dense and BM25 scores share a scale."""
    if rrf_k < 0:
        raise ValueError("rrf_k must be non-negative")
    fused: Dict[Tuple, Dict] = {}
    sources = (
        ("dense", dense_results, dense_weight),
        ("bm25", bm25_results, bm25_weight),
    )
    for source_name, results, weight in sources:
        seen_in_source = set()
        for rank, raw_result in enumerate(results, start=1):
            key = _dedupe_key(raw_result)
            if key in seen_in_source:
                continue
            seen_in_source.add(key)
            result = fused.setdefault(
                key,
                {
                    **dict(raw_result),
                    "rrf_score": 0.0,
                    "retrieval_sources": [],
                },
            )
            result["rrf_score"] += float(weight) / (rrf_k + rank)
            result["retrieval_sources"].append(source_name)
            result[f"{source_name}_rank"] = rank
            if source_name == "dense":
                result["dense_score"] = raw_result.get("distance")
            else:
                result["bm25_score"] = raw_result.get(
                    "bm25_score", raw_result.get("distance")
                )

    fused_results = list(fused.values())
    for result in fused_results:
        result["rrf_score"] = round(result["rrf_score"], 8)
        result["distance"] = result["rrf_score"]
        result["final_pre_rerank_score"] = result["rrf_score"]
    fused_results.sort(
        key=lambda result: (
            -result["rrf_score"],
            result.get("dense_rank", 10**9),
            result.get("bm25_rank", 10**9),
            str(_dedupe_key(result)),
        )
    )
    return fused_results[:top_k] if top_k is not None else fused_results


@dataclass(frozen=True)
class RDRetrievalConfig:
    dense_top_k: int = 12
    bm25_top_k: int = 12
    fusion_top_k: int = 10
    rerank_top_k: int = 5
    rrf_k: int = 60
    dense_weight: float = 1.0
    bm25_weight: float = 1.0
    neighbor_children: int = 1
    context_max_tokens: int = 1800

    def __post_init__(self):
        positive = (
            self.dense_top_k,
            self.bm25_top_k,
            self.fusion_top_k,
            self.rerank_top_k,
            self.context_max_tokens,
        )
        if any(value <= 0 for value in positive):
            raise ValueError("retrieval limits and context budget must be positive")
        if self.rrf_k < 0 or self.neighbor_children < 0:
            raise ValueError("rrf_k and neighbor_children must be non-negative")


class RDHybridRetriever:
    """Existing dense retrieval + BM25 + RRF + optional existing reranker."""

    def __init__(
        self,
        vector_db_dir: Path,
        documents_dir: Path,
        *,
        embedding_provider: str = "dashscope",
        embedding_model: Optional[str] = None,
        rerank_provider: str = "dashscope",
        rerank_model: Optional[str] = None,
        additional_corpora: Optional[List[Tuple[Path, Path]]] = None,
        config: Optional[RDRetrievalConfig] = None,
        use_reranker: bool = False,
        vector_retriever=None,
        bm25_retriever=None,
        reranker=None,
    ):
        self.config = config or RDRetrievalConfig()
        additional_corpora = additional_corpora or []
        self.vector_retriever = vector_retriever or VectorRetriever(
            vector_db_dir,
            documents_dir,
            embedding_provider=embedding_provider,
            embedding_model=embedding_model,
            additional_corpora=additional_corpora,
        )
        self.bm25_retriever = bm25_retriever or BM25Retriever(
            documents_dir,
            additional_documents_dirs=[documents for _, documents in additional_corpora],
        )
        self.reranker = reranker
        if use_reranker and self.reranker is None:
            self.reranker = LLMReranker(
                provider=rerank_provider, model=rerank_model
            )
        self.context_expander = SectionContextExpander(
            [documents_dir, *[documents for _, documents in additional_corpora]],
            neighbor_children=self.config.neighbor_children,
            max_tokens=self.config.context_max_tokens,
        )

    @property
    def document_ids(self) -> List[str]:
        return self.vector_retriever.document_ids

    def retrieve(
        self,
        query: str,
        *,
        top_n: Optional[int] = None,
        per_document_top_k: Optional[int] = None,
        return_parent_pages: bool = False,
        document_ids: Optional[List[str]] = None,
        version_plan: Optional[VersionResolutionPlan] = None,
        expand_context: bool = True,
        llm_reranking_sample_size: Optional[int] = None,
        documents_batch_size: int = 2,
        llm_weight: float = 0.7,
    ) -> List[Dict]:
        del return_parent_pages  # Section expansion supersedes legacy page expansion.
        dense_top_k = llm_reranking_sample_size or self.config.dense_top_k
        dense_results = self.vector_retriever.retrieve(
            query=query,
            top_n=dense_top_k,
            per_document_top_k=per_document_top_k or dense_top_k,
            return_parent_pages=False,
            document_ids=document_ids,
            version_plan=version_plan,
        )
        sparse_results = self.bm25_retriever.search(
            query,
            top_k=self.config.bm25_top_k,
            document_ids=document_ids,
            version_plan=version_plan,
        )
        fused = reciprocal_rank_fusion(
            dense_results,
            sparse_results,
            rrf_k=self.config.rrf_k,
            dense_weight=self.config.dense_weight,
            bm25_weight=self.config.bm25_weight,
            top_k=self.config.fusion_top_k,
        )
        requested_top_k = top_n or self.config.rerank_top_k
        if self.reranker is not None:
            fused = self.reranker.rerank_documents(
                query=query,
                documents=fused,
                documents_batch_size=documents_batch_size,
                llm_weight=llm_weight,
            )
        primary = fused[:requested_top_k]
        return self.context_expander.expand(primary) if expand_context else primary
