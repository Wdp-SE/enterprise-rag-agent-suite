import json
import logging
from typing import List, Tuple, Dict, Union
import pickle
from pathlib import Path
import faiss
from openai import OpenAI
from dotenv import load_dotenv
import os
import numpy as np
from src.reranking import LLMReranker
from src.versioning.models import VersionResolutionPlan
from src.versioning.policy import apply_version_policy
from src.provider_config import resolve_provider_model
from src.vector_utils import faiss_index_has_unit_norm_vectors, l2_normalize_rows
from src.document_metadata import normalize_document_metadata
from src.text_tokenization import technical_tokenize

try:
    from rank_bm25 import BM25Okapi
except ImportError:  # BM25 is outside the reliable vector baseline.
    BM25Okapi = None

try:
    import dashscope
except ImportError:
    dashscope = None

_log = logging.getLogger(__name__)

class BM25Retriever:
    def __init__(self, bm25_db_dir: Path, documents_dir: Path):
        # 初始化BM25检索器，指定BM25索引和文档目录
        self.bm25_db_dir = bm25_db_dir
        self.documents_dir = documents_dir
        
    def retrieve_by_company_name(self, company_name: str, query: str, top_n: int = 3, return_parent_pages: bool = False) -> List[Dict]:
        # 按公司名检索相关文本块，返回BM25分数最高的top_n个块
        document_path = None
        for path in self.documents_dir.glob("*.json"):
            with open(path, 'r', encoding='utf-8') as f:
                doc = json.load(f)
                if doc["metainfo"]["company_name"] == company_name:
                    document_path = path
                    document = doc
                    break
                    
        if document_path is None:
            raise ValueError(f"No report found with '{company_name}' company name.")
            
        # 加载对应的BM25索引
        bm25_path = self.bm25_db_dir / f"{document['metainfo']['sha1_name']}.pkl"
        with open(bm25_path, 'rb') as f:
            bm25_index = pickle.load(f)
            
        # 获取文档内容和BM25索引
        document = document
        chunks = document["content"]["chunks"]
        pages = document["content"]["pages"]
        
        # 计算BM25分数
        tokenized_query = technical_tokenize(query)
        scores = bm25_index.get_scores(tokenized_query)
        
        actual_top_n = min(top_n, len(scores))
        top_indices = sorted(range(len(scores)), key=lambda i: scores[i], reverse=True)[:actual_top_n]
        
        retrieval_results = []
        seen_pages = set()
        
        for index in top_indices:
            score = round(float(scores[index]), 4)
            chunk = chunks[index]
            parent_page = next(page for page in pages if page["page"] == chunk["page"])
            
            if return_parent_pages:
                if parent_page["page"] not in seen_pages:
                    seen_pages.add(parent_page["page"])
                    result = {
                        "distance": score,
                        "page": parent_page["page"],
                        "text": parent_page["text"]
                    }
                    retrieval_results.append(result)
            else:
                result = {
                    "distance": score,
                    "page": chunk["page"],
                    "text": chunk["text"]
                }
                retrieval_results.append(result)
        
        return retrieval_results



class VectorRetriever:
    def __init__(
        self,
        vector_db_dir: Path,
        documents_dir: Path,
        embedding_provider: str = "dashscope",
        embedding_model: str = None,
        additional_corpora: List[Tuple[Path, Path]] = None,
    ):
        # 初始化向量检索器，加载所有向量库和文档
        self.vector_db_dir = vector_db_dir
        self.documents_dir = documents_dir
        self.additional_corpora = additional_corpora or []
        self.embedding_provider, self.embedding_model = resolve_provider_model(
            embedding_provider,
            embedding_model,
            "embedding",
        )
        self.llm = self._set_up_llm()
        self.all_dbs = self._load_dbs()

    def _set_up_llm(self):
        # 根据 embedding_provider 初始化对应的 LLM 客户端
        load_dotenv()
        if self.embedding_provider == "openai":
            llm = OpenAI(
                api_key=os.getenv("OPENAI_API_KEY"),
                timeout=None,
                max_retries=2
            )
            return llm
        elif self.embedding_provider == "dashscope":
            if dashscope is not None:
                dashscope.api_key = os.getenv("DASHSCOPE_API_KEY")
            return None  # dashscope 不需要 client 对象
        else:
            raise ValueError(f"不支持的 embedding provider: {self.embedding_provider}")

    def _get_embedding(self, text: str):
        # 根据 embedding_provider 获取文本的向量表示
        if self.embedding_provider == "openai":
            embedding = self.llm.embeddings.create(
                input=text,
                model=self.embedding_model
            )
            return embedding.data[0].embedding
        elif self.embedding_provider == "dashscope":
            if dashscope is None:
                raise ImportError("DashScope embeddings require the 'dashscope' package.")
            rsp = dashscope.TextEmbedding.call(
                model=self.embedding_model,
                input=[text]
            )
            # 兼容 dashscope 返回格式，不能用 resp.output，需用 resp['output']
            if 'output' in rsp and 'embeddings' in rsp['output']:
                # 多条输入（本处只有一条）
                emb = rsp['output']['embeddings'][0]
                if emb['embedding'] is None or len(emb['embedding']) == 0:
                    raise RuntimeError(f"DashScope返回的embedding为空，text_index={emb.get('text_index', None)}")
                return emb['embedding']
            elif 'output' in rsp and 'embedding' in rsp['output']:
                # 兼容单条输入格式
                if rsp['output']['embedding'] is None or len(rsp['output']['embedding']) == 0:
                    raise RuntimeError("DashScope返回的embedding为空")
                return rsp['output']['embedding']
            else:
                raise RuntimeError(f"DashScope embedding API返回格式异常: {rsp}")
        else:
            raise ValueError(f"不支持的 embedding provider: {self.embedding_provider}")

    @staticmethod
    def set_up_llm():
        # 静态方法，初始化OpenAI LLM
        load_dotenv()
        llm = OpenAI(
            api_key=os.getenv("OPENAI_API_KEY"),
            timeout=None,
            max_retries=2
        )
        return llm

    def _load_dbs(self):
        # 加载所有向量库和对应文档，建立映射
        all_dbs = []
        loaded_document_ids = set()
        corpus_locations = [
            (self.vector_db_dir, self.documents_dir),
            *self.additional_corpora,
        ]
        for vector_db_dir, documents_dir in corpus_locations:
            all_documents_paths = list(Path(documents_dir).glob('*.json'))
            vector_db_files = {
                db_path.stem: db_path for db_path in Path(vector_db_dir).glob('*.faiss')
            }
            for document_path in all_documents_paths:
                self._load_document_db(
                    document_path,
                    vector_db_files,
                    all_dbs,
                    loaded_document_ids,
                )
        return all_dbs

    def _load_document_db(
        self,
        document_path: Path,
        vector_db_files: Dict[str, Path],
        all_dbs: List[Dict],
        loaded_document_ids: set,
    ) -> None:
        """Load one matched JSON/FAISS pair without changing corpus layout."""
        stem = document_path.stem
        try:
            with open(document_path, 'r', encoding='utf-8') as f:
                document = json.load(f)
        except Exception as e:
            _log.error(f"Error loading JSON from {document_path.name}: {e}")
            return

        if not (isinstance(document, dict) and "metainfo" in document and "content" in document):
            _log.warning(f"Skipping {document_path.name}: does not match the expected schema.")
            return

        metainfo = normalize_document_metadata(
            document.get("metainfo"), source_identifier=document_path.name
        )
        document["metainfo"] = metainfo
        document_id = metainfo["document_id"]
        if document_id in loaded_document_ids:
            raise ValueError(f"Duplicate document_id '{document_id}' in document corpus")

        index_key = next(
            (
                candidate
                for candidate in (
                    document_id,
                    metainfo.get("sha1_name"),
                    stem,
                )
                if candidate and candidate in vector_db_files
            ),
            None,
        )
        if index_key is None:
            _log.warning(f"No matching vector DB found for document {document_path.name}")
            return

        try:
            vector_db = faiss.read_index(str(vector_db_files[index_key]))
        except Exception as e:
            _log.error(f"Error reading vector DB for {document_path.name}: {e}")
            return

        if not faiss_index_has_unit_norm_vectors(vector_db):
            raise ValueError(
                f"FAISS index '{vector_db_files[index_key].name}' contains legacy non-normalized "
                "embeddings. Rebuild the index before cosine-similarity retrieval."
            )

        chunks = document["content"].get("chunks", [])
        pages = document["content"].get("pages", [])
        if vector_db.ntotal != len(chunks):
            raise ValueError(
                f"FAISS index '{vector_db_files[index_key].name}' has {vector_db.ntotal} vectors "
                f"but document '{document_path.name}' has {len(chunks)} chunks"
            )
        for chunk_index, chunk in enumerate(chunks):
            chunk.setdefault("document_id", document_id)
            chunk.setdefault("id", chunk_index)
            chunk.setdefault("chunk_id", f"{document_id}:{chunk['id']}")
        for page in pages:
            page.setdefault("document_id", document_id)

        all_dbs.append(
            {
                "name": document_id,
                "legacy_name": stem,
                "vector_db": vector_db,
                "document": document,
            }
        )
        loaded_document_ids.add(document_id)

    @property
    def document_ids(self) -> List[str]:
        return [report["name"] for report in self.all_dbs]

    @staticmethod
    def get_strings_cosine_similarity(str1, str2):
        # 计算两个字符串的余弦相似度（通过嵌入）
        llm = VectorRetriever.set_up_llm()
        embeddings = llm.embeddings.create(input=[str1, str2], model="text-embedding-3-large")
        embedding1 = embeddings.data[0].embedding
        embedding2 = embeddings.data[1].embedding
        similarity_score = np.dot(embedding1, embedding2) / (np.linalg.norm(embedding1) * np.linalg.norm(embedding2))
        similarity_score = round(similarity_score, 4)
        return similarity_score

    @staticmethod
    def _result_metadata(report: Dict) -> Dict:
        metainfo = report["document"]["metainfo"]
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

    def _retrieve_from_reports(
        self,
        reports: List[Dict],
        query: str,
        *,
        top_n: int,
        per_document_top_k: int,
        return_parent_pages: bool,
        version_plan: VersionResolutionPlan = None,
    ) -> List[Dict]:
        if top_n <= 0 or per_document_top_k <= 0 or not reports:
            return []

        embedding_array = l2_normalize_rows(self._get_embedding(query))
        chunk_candidates = []

        # Keep each FAISS independent: local Top-K per document, then global merge.
        for report in reports:
            document = report["document"]
            chunks = document["content"]["chunks"]
            actual_top_k = min(per_document_top_k, len(chunks))
            if actual_top_k == 0:
                continue
            distances, indices = report["vector_db"].search(
                x=embedding_array, k=actual_top_k
            )
            result_metadata = self._result_metadata(report)
            for distance, index in zip(distances[0], indices[0]):
                if index < 0:
                    continue
                chunk = chunks[int(index)]
                candidate = {
                    **result_metadata,
                    "distance": round(float(distance), 4),
                    "page": chunk["page"],
                    "page_number": chunk.get("page_number", chunk["page"]),
                    "text": chunk["text"],
                    "chunk_id": chunk["chunk_id"],
                }
                for field in (
                    "section_id",
                    "parent_id",
                    "section_title",
                    "section_path",
                    "section_level",
                    "section_child_index",
                ):
                    if field in chunk:
                        candidate[field] = chunk[field]
                if version_plan is not None:
                    candidate = apply_version_policy(candidate, version_plan)
                chunk_candidates.append(candidate)

        chunk_candidates.sort(
            key=lambda result: result.get("final_pre_rerank_score", result["distance"]),
            reverse=True,
        )
        if not return_parent_pages:
            return chunk_candidates[:top_n]

        parent_results = []
        seen_pages = set()
        reports_by_id = {
            report["document"]["metainfo"]["document_id"]: report for report in reports
        }
        for candidate in chunk_candidates:
            page_key = (candidate["document_id"], candidate["page"])
            if page_key in seen_pages:
                continue
            seen_pages.add(page_key)
            document = reports_by_id[candidate["document_id"]]["document"]
            parent_page = next(
                page for page in document["content"]["pages"]
                if page["page"] == candidate["page"]
            )
            parent_results.append({**candidate, "text": parent_page["text"]})
            if len(parent_results) == top_n:
                break
        return parent_results

    def retrieve(
        self,
        query: str,
        top_n: int = 3,
        per_document_top_k: int = None,
        return_parent_pages: bool = False,
        document_ids: List[str] = None,
        version_plan: VersionResolutionPlan = None,
    ) -> List[Dict]:
        """Retrieve across the corpus without company-name routing."""
        selected_reports = self.all_dbs
        if version_plan is not None:
            plan_ids = set(version_plan.eligible_document_ids)
            document_ids = (
                sorted(plan_ids)
                if document_ids is None
                else sorted(plan_ids & set(document_ids))
            )
        if document_ids is not None:
            selected_ids = set(document_ids)
            selected_reports = [
                report for report in self.all_dbs if report["name"] in selected_ids
            ]
        return self._retrieve_from_reports(
            selected_reports,
            query,
            top_n=top_n,
            per_document_top_k=per_document_top_k or top_n,
            return_parent_pages=return_parent_pages,
            version_plan=version_plan,
        )

    def retrieve_by_company_name(self, company_name: str, query: str, llm_reranking_sample_size: int = None, top_n: int = 3, return_parent_pages: bool = False) -> List[Tuple[str, float]]:
        # Legacy competition routing remains a single-company wrapper.
        target_report = next(
            (
                report for report in self.all_dbs
                if (
                    report["document"]["metainfo"].get("legacy_company_name")
                    or report["document"]["metainfo"].get("company_name")
                ) == company_name
            ),
            None,
        )
        if target_report is None:
            _log.error(f"No report found with '{company_name}' company name.")
            raise ValueError(f"No report found with '{company_name}' company name.")

        return self._retrieve_from_reports(
            [target_report],
            query,
            top_n=top_n,
            per_document_top_k=top_n,
            return_parent_pages=return_parent_pages,
        )

    def retrieve_all(self, company_name: str) -> List[Dict]:
        # 检索公司所有文本块，返回全部内容
        target_report = None
        for report in self.all_dbs:
            document = report.get("document", {})
            metainfo = document.get("metainfo")
            if not metainfo:
                continue
            if (metainfo.get("legacy_company_name") or metainfo.get("company_name")) == company_name:
                target_report = report
                break
        
        if target_report is None:
            _log.error(f"No report found with '{company_name}' company name.")
            raise ValueError(f"No report found with '{company_name}' company name.")
        
        document = target_report["document"]
        pages = document["content"]["pages"]
        
        all_pages = []
        for page in sorted(pages, key=lambda p: p["page"]):
            result = {
                **self._result_metadata(target_report),
                "distance": 0.5,
                "page": page["page"],
                "text": page["text"]
            }
            all_pages.append(result)
            
        return all_pages


class HybridRetriever:
    def __init__(
        self,
        vector_db_dir: Path,
        documents_dir: Path,
        embedding_provider: str = "dashscope",
        embedding_model: str = None,
        rerank_provider: str = "dashscope",
        rerank_model: str = None,
        additional_corpora: List[Tuple[Path, Path]] = None,
    ):
        self.vector_retriever = VectorRetriever(
            vector_db_dir,
            documents_dir,
            embedding_provider=embedding_provider,
            embedding_model=embedding_model,
            additional_corpora=additional_corpora,
        )
        self.reranker = LLMReranker(provider=rerank_provider, model=rerank_model)

    def retrieve(
        self,
        query: str,
        llm_reranking_sample_size: int = 28,
        documents_batch_size: int = 2,
        top_n: int = 6,
        llm_weight: float = 0.7,
        return_parent_pages: bool = False,
        per_document_top_k: int = None,
        document_ids: List[str] = None,
        version_plan: VersionResolutionPlan = None,
    ) -> List[Dict]:
        vector_results = self.vector_retriever.retrieve(
            query=query,
            top_n=llm_reranking_sample_size,
            per_document_top_k=per_document_top_k or llm_reranking_sample_size,
            return_parent_pages=return_parent_pages,
            document_ids=document_ids,
            version_plan=version_plan,
        )
        reranked_results = self.reranker.rerank_documents(
            query=query,
            documents=vector_results,
            documents_batch_size=documents_batch_size,
            llm_weight=llm_weight,
        )
        return reranked_results[:top_n]

    @property
    def document_ids(self) -> List[str]:
        return self.vector_retriever.document_ids
        
    def retrieve_by_company_name(
        self, 
        company_name: str, 
        query: str, 
        llm_reranking_sample_size: int = 28,
        documents_batch_size: int = 2,
        top_n: int = 6,
        llm_weight: float = 0.7,
        return_parent_pages: bool = False
    ) -> List[Dict]:
        """
        Retrieve and rerank documents using hybrid approach.
        
        Args:
            company_name: Name of the company to search documents for
            query: Search query
            llm_reranking_sample_size: Number of initial results to retrieve from vector DB
            documents_batch_size: Number of documents to analyze in one LLM prompt
            top_n: Number of final results to return after reranking
            llm_weight: Weight given to LLM scores (0-1)
            return_parent_pages: Whether to return full pages instead of chunks
            
        Returns:
            List of reranked document dictionaries with scores
        """
        # Get initial results from vector retriever
        vector_results = self.vector_retriever.retrieve_by_company_name(
            company_name=company_name,
            query=query,
            top_n=llm_reranking_sample_size,
            return_parent_pages=return_parent_pages
        )
        
        # Rerank results using LLM
        reranked_results = self.reranker.rerank_documents(
            query=query,
            documents=vector_results,
            documents_batch_size=documents_batch_size,
            llm_weight=llm_weight
        )
        
        return reranked_results[:top_n]
