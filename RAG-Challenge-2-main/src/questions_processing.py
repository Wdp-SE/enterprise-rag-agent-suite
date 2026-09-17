import json
from typing import Union, Dict, List, Optional
import re
from pathlib import Path
from src.retrieval import VectorRetriever, HybridRetriever
from src.rd_retrieval import RDHybridRetriever, RDRetrievalConfig
from src.api_requests import APIProcessor
from tqdm import tqdm
import pandas as pd
import threading
import concurrent.futures
from datetime import date
import hashlib

from src.versioning import VersionResolver
from src.trusted_qa import (
    EnforcementScope,
    ShadowPolicyProfile,
    TrustedQAMode,
    TrustedQATrace,
    apply_post_answer_enforcement,
    build_answer_evidence_audit,
    collect_retrieval_signals,
    decide_evidence_sufficiency,
    decide_post_answer_enforcement,
    not_available_answer_audit,
)


class QuestionsProcessor:
    def __init__(
        self,
        vector_db_dir: Union[str, Path] = './vector_dbs',
        documents_dir: Union[str, Path] = './documents',
        questions_file_path: Optional[Union[str, Path]] = None,
        new_challenge_pipeline: bool = False,
        subset_path: Optional[Union[str, Path]] = None,
        parent_document_retrieval: bool = False,  # 是否启用父文档检索
        llm_reranking: bool = False,              # 是否启用LLM重排
        llm_reranking_sample_size: int = 20,
        top_n_retrieval: int = 10,
        parallel_requests: int = 10,
        api_provider: str = "dashscope", # openai
        answering_model: str = "qwen-turbo", # gpt-4o-2024-08-06
        full_context: bool = False,
        embedding_provider: str = "dashscope",
        embedding_model: str = "text-embedding-v1",
        rerank_provider: str = "dashscope",
        rerank_model: str = "qwen-turbo",
        routing_mode: str = "legacy_company",
        version_governance_enabled: bool = False,
        version_manifest_path: Optional[Union[str, Path]] = None,
        historical_vector_db_dir: Optional[Union[str, Path]] = None,
        historical_documents_dir: Optional[Union[str, Path]] = None,
        version_as_of_date: Optional[Union[str, date]] = None,
        trusted_qa_mode: str = "OFF",
        trusted_qa_policy_profile: str = "HARD_PLUS_SOFT",
        trusted_qa_enforcement_scope: str = "POST_ANSWER_ONLY",
        retrieval_mode: str = "generic_dense",
        bm25_db_dir: Optional[Union[str, Path]] = None,
        dense_top_k: int = 12,
        bm25_top_k: int = 12,
        fusion_top_k: int = 10,
        rerank_top_k: int = 5,
        rrf_k: int = 60,
        dense_weight: float = 1.0,
        bm25_weight: float = 1.0,
        neighbor_children: int = 1,
        context_max_tokens: int = 1800,
    ):
        # 初始化问题处理器，配置检索、模型、并发等参数
        self.questions = self._load_questions(questions_file_path)
        self.documents_dir = Path(documents_dir)
        self.vector_db_dir = Path(vector_db_dir)
        self.subset_path = Path(subset_path) if subset_path else None
        
        self.new_challenge_pipeline = new_challenge_pipeline
        self.return_parent_pages = parent_document_retrieval
        self.llm_reranking = llm_reranking
        self.llm_reranking_sample_size = llm_reranking_sample_size
        self.top_n_retrieval = top_n_retrieval
        self.answering_model = answering_model
        self.parallel_requests = parallel_requests
        self.api_provider = api_provider
        self.openai_processor = APIProcessor(provider=api_provider)
        self.full_context = full_context
        self.embedding_provider = embedding_provider
        self.embedding_model = embedding_model
        self.rerank_provider = rerank_provider
        self.rerank_model = rerank_model
        if retrieval_mode not in {"generic_dense", "rd_hybrid"}:
            raise ValueError("retrieval_mode must be 'generic_dense' or 'rd_hybrid'")
        if retrieval_mode == "rd_hybrid" and routing_mode != "generic":
            raise ValueError("rd_hybrid retrieval requires routing_mode='generic'")
        self.retrieval_mode = retrieval_mode
        self.bm25_db_dir = Path(bm25_db_dir) if bm25_db_dir else None
        self.rd_retrieval_config = RDRetrievalConfig(
            dense_top_k=dense_top_k,
            bm25_top_k=bm25_top_k,
            fusion_top_k=fusion_top_k,
            rerank_top_k=rerank_top_k,
            rrf_k=rrf_k,
            dense_weight=dense_weight,
            bm25_weight=bm25_weight,
            neighbor_children=neighbor_children,
            context_max_tokens=context_max_tokens,
        )
        if routing_mode not in {"legacy_company", "generic"}:
            raise ValueError("routing_mode must be 'legacy_company' or 'generic'")
        if routing_mode == "generic" and full_context:
            raise ValueError("full_context is disabled in generic routing mode")
        self.routing_mode = routing_mode
        self.version_governance_enabled = version_governance_enabled
        self.version_manifest_path = (
            Path(version_manifest_path) if version_manifest_path else None
        )
        self.historical_vector_db_dir = (
            Path(historical_vector_db_dir) if historical_vector_db_dir else None
        )
        self.historical_documents_dir = (
            Path(historical_documents_dir) if historical_documents_dir else None
        )
        if isinstance(version_as_of_date, str):
            version_as_of_date = date.fromisoformat(version_as_of_date)
        self.version_as_of_date = version_as_of_date
        self.trusted_qa_mode = TrustedQAMode(trusted_qa_mode)
        self.trusted_qa_policy_profile = ShadowPolicyProfile(
            trusted_qa_policy_profile
        )
        if trusted_qa_enforcement_scope != EnforcementScope.POST_ANSWER_ONLY.value:
            raise NotImplementedError(
                "only trusted_qa_enforcement_scope=POST_ANSWER_ONLY is implemented"
            )
        self.trusted_qa_enforcement_scope = EnforcementScope(
            trusted_qa_enforcement_scope
        )
        if self.version_governance_enabled and self.routing_mode != "generic":
            raise ValueError("version governance is only supported in generic routing mode")
        if self.version_governance_enabled and self.version_manifest_path is None:
            raise ValueError("version_manifest_path is required when version governance is enabled")
        if bool(self.historical_vector_db_dir) != bool(self.historical_documents_dir):
            raise ValueError("historical vector and document directories must be configured together")
        self.retriever = self._build_retriever()
        self.version_resolver = (
            VersionResolver.from_manifest_path(
                self.version_manifest_path,
                as_of_date=self.version_as_of_date,
            )
            if self.version_governance_enabled
            else None
        )

        self.answer_details = []
        self.detail_counter = 0
        self.response_data = None
        self._lock = threading.Lock()
        self._trusted_qa_traces: Dict[str, TrustedQATrace] = {}

    def _build_retriever(self):
        additional_corpora = []
        if self.version_governance_enabled and self.historical_vector_db_dir:
            additional_corpora.append(
                (self.historical_vector_db_dir, self.historical_documents_dir)
            )
        if self.retrieval_mode == "rd_hybrid":
            return RDHybridRetriever(
                vector_db_dir=self.vector_db_dir,
                documents_dir=self.documents_dir,
                embedding_provider=self.embedding_provider,
                embedding_model=self.embedding_model,
                rerank_provider=self.rerank_provider,
                rerank_model=self.rerank_model,
                additional_corpora=additional_corpora,
                config=self.rd_retrieval_config,
                use_reranker=self.llm_reranking,
            )
        if self.llm_reranking:
            return HybridRetriever(
                vector_db_dir=self.vector_db_dir,
                documents_dir=self.documents_dir,
                embedding_provider=self.embedding_provider,
                embedding_model=self.embedding_model,
                rerank_provider=self.rerank_provider,
                rerank_model=self.rerank_model,
                additional_corpora=additional_corpora,
            )
        return VectorRetriever(
            vector_db_dir=self.vector_db_dir,
            documents_dir=self.documents_dir,
            embedding_provider=self.embedding_provider,
            embedding_model=self.embedding_model,
            additional_corpora=additional_corpora,
        )

    def _load_questions(self, questions_file_path: Optional[Union[str, Path]]) -> List[Dict[str, str]]:
        # 加载问题文件，返回问题列表
        if questions_file_path is None:
            return []
        with open(questions_file_path, 'r', encoding='utf-8') as file:
            return json.load(file)

    def _format_retrieval_results(self, retrieval_results) -> str:
        """将检索结果格式化为RAG上下文字符串"""
        if not retrieval_results:
            return ""
        
        context_parts = []
        for result in retrieval_results:
            page_number = result['page']
            text = result['text']
            if self.routing_mode == "generic":
                section_lines = []
                if result.get("section_id"):
                    section_lines.append(f"section_id: {result['section_id']}")
                if result.get("section_path"):
                    path = result["section_path"]
                    if isinstance(path, list):
                        path = " > ".join(str(part) for part in path)
                    section_lines.append(f"section_path: {path}")
                if result.get("chunk_id"):
                    section_lines.append(f"chunk_id: {result['chunk_id']}")
                section_metadata = (
                    "\n" + "\n".join(section_lines) if section_lines else ""
                )
                context_parts.append(
                    "Retrieved evidence:\n"
                    f"document_id: {result['document_id']}\n"
                    f"document_title: {result['document_title']}\n"
                    f"page_number: {page_number}"
                    f"{section_metadata}\n"
                    f'"""\n{text}\n"""'
                )
            else:
                context_parts.append(f'Text retrieved from page {page_number}: \n"""\n{text}\n"""')
            
        return "\n\n---\n\n".join(context_parts)

    def _extract_references(self, pages_list: list, company_name: str) -> list:
        # 根据公司名和页码列表，提取引用信息
        if self.subset_path is None:
            raise ValueError("subset_path is required for new challenge pipeline when processing references.")
        self.companies_df = pd.read_csv(self.subset_path)

        # Find the company's SHA1 from the subset CSV
        matching_rows = self.companies_df[self.companies_df['company_name'] == company_name]
        if matching_rows.empty:
            company_sha1 = ""
        else:
            company_sha1 = matching_rows.iloc[0]['sha1']

        refs = []
        for page in pages_list:
            refs.append({"pdf_sha1": company_sha1, "page_index": page})
        return refs

    def _validate_page_references(self, claimed_pages: list, retrieval_results: list, min_pages: int = 0, max_pages: int = 8) -> list:
        """
        校验LLM答案中声明的页码是否真实存在于检索结果中。
        min_pages 参数仅为调用兼容保留；本方法不会自动生成模型未声明的引用。
        """
        if claimed_pages is None:
            claimed_pages = []
        
        retrieved_pages = {result['page'] for result in retrieval_results}
        validated_pages = []
        seen_pages = set()
        for page in claimed_pages:
            if page in retrieved_pages and page not in seen_pages:
                validated_pages.append(page)
                seen_pages.add(page)
        
        if len(validated_pages) < len(claimed_pages):
            removed_pages = set(claimed_pages) - set(validated_pages)
            print(f"Warning: Removed {len(removed_pages)} hallucinated page references: {removed_pages}")
        
        if len(validated_pages) > max_pages:
            print(f"Trimming references from {len(validated_pages)} to {max_pages} pages")
            validated_pages = validated_pages[:max_pages]
        
        return validated_pages

    def _validate_source_references(
        self, claimed_sources: list, retrieval_results: list, max_sources: int = 8
    ) -> list:
        """Validate generic citations by the composite document/page identity."""
        retrieved_by_key = {
            (result["document_id"], result["page"]): result
            for result in retrieval_results
        }
        validated_sources = []
        seen = set()
        for source in claimed_sources or []:
            if hasattr(source, "model_dump"):
                source = source.model_dump()
            if not isinstance(source, dict):
                continue
            key = (source.get("document_id"), source.get("page_number"))
            if key in seen or key not in retrieved_by_key:
                continue
            seen.add(key)
            result = retrieved_by_key[key]
            validated_source = {
                    "document_id": result["document_id"],
                    "document_title": result["document_title"],
                    "page_number": result["page"],
                    "source": result["source"],
                    "source_url": result.get("source_url"),
                }
            for field in (
                "document_number",
                "version",
                "status",
                "effective_date",
            ):
                if result.get(field) is not None:
                    validated_source[field] = result[field]
            validated_sources.append(validated_source)
            if len(validated_sources) == max_sources:
                break
        return validated_sources

    @staticmethod
    def _trusted_qa_question_id(question: str, question_id: Optional[str]) -> str:
        if question_id:
            return str(question_id)
        digest = hashlib.sha1(question.encode("utf-8")).hexdigest()[:16]
        return f"adhoc-{digest}"

    def _build_trusted_qa_shadow(
        self,
        *,
        question: str,
        question_id: Optional[str],
        retrieval_results: list,
        version_plan=None,
    ):
        if self.trusted_qa_mode == TrustedQAMode.OFF:
            return None, None
        stable_question_id = self._trusted_qa_question_id(question, question_id)
        snapshot = collect_retrieval_signals(
            question_id=stable_question_id,
            retrieval_results=retrieval_results,
            version_governance_enabled=self.version_governance_enabled,
            version_plan=version_plan,
        )
        decision = decide_evidence_sufficiency(
            snapshot,
            mode=self.trusted_qa_mode,
            profile=self.trusted_qa_policy_profile,
        )
        return snapshot, decision

    def _record_trusted_qa_trace(
        self,
        *,
        snapshot,
        decision,
        post_answer_audit,
        actual_pipeline_result: Optional[dict] = None,
        post_answer_enforcement=None,
        original_pipeline_result: Optional[dict] = None,
        final_pipeline_result: Optional[dict] = None,
    ) -> None:
        if snapshot is None or decision is None:
            return
        trace = TrustedQATrace(
            question_id=snapshot.question_id,
            signal_snapshot=snapshot,
            shadow_decision=decision,
            post_answer_audit=post_answer_audit,
            actual_pipeline_result=actual_pipeline_result,
            post_answer_enforcement=post_answer_enforcement,
            original_pipeline_result=original_pipeline_result,
            final_pipeline_result=final_pipeline_result,
        )
        with self._lock:
            self._trusted_qa_traces[snapshot.question_id] = trace

    def get_trusted_qa_traces(self) -> list[dict]:
        """Return JSON-safe Shadow traces without changing answer response schemas."""
        with self._lock:
            return [
                trace.model_dump(mode="json")
                for trace in self._trusted_qa_traces.values()
            ]

    @staticmethod
    def _trusted_qa_result_snapshot(result: dict) -> dict:
        """Retain only answer/citation state needed to audit enforcement."""
        fields = (
            "final_answer",
            "relevant_pages",
            "relevant_sources",
            "references",
            "sources",
            "error_type",
        )
        return {field: result[field] for field in fields if field in result}

    def _finalize_trusted_qa_answer(
        self,
        *,
        answer_dict: dict,
        original_answer_dict: dict,
        audit,
        snapshot,
        decision,
        citation_fields: tuple[str, ...],
    ) -> dict:
        """Apply the post-answer-only policy after existing validation."""
        enforcement = decide_post_answer_enforcement(
            audit,
            mode=self.trusted_qa_mode,
        )
        final_answer_dict = apply_post_answer_enforcement(
            answer_dict,
            enforcement,
            citation_fields=citation_fields,
        )
        original_result = self._trusted_qa_result_snapshot(original_answer_dict)
        final_result = self._trusted_qa_result_snapshot(final_answer_dict)
        self._record_trusted_qa_trace(
            snapshot=snapshot,
            decision=decision,
            post_answer_audit=audit,
            actual_pipeline_result=final_result,
            post_answer_enforcement=enforcement,
            original_pipeline_result=original_result,
            final_pipeline_result=final_result,
        )
        return final_answer_dict

    def get_answer_for_company(
        self,
        company_name: str,
        question: str,
        schema: str,
        question_id: Optional[str] = None,
    ) -> dict:
        # 针对单个公司，检索上下文并调用LLM生成答案
        if self.full_context:
            retrieval_results = self.retriever.retrieve_all(company_name)
        else:           
            retrieval_results = self.retriever.retrieve_by_company_name(
                company_name=company_name,
                query=question,
                llm_reranking_sample_size=self.llm_reranking_sample_size,
                top_n=self.top_n_retrieval,
                return_parent_pages=self.return_parent_pages
            )
        
        snapshot, decision = self._build_trusted_qa_shadow(
            question=question,
            question_id=question_id,
            retrieval_results=retrieval_results,
        )
        if not retrieval_results:
            self._record_trusted_qa_trace(
                snapshot=snapshot,
                decision=decision,
                post_answer_audit=not_available_answer_audit(),
                actual_pipeline_result={"error_type": "NoRelevantContext"},
            )
            raise ValueError("No relevant context found")
        
        rag_context = self._format_retrieval_results(retrieval_results)
        try:
            answer_dict = self.openai_processor.get_answer_from_rag_context(
                question=question,
                rag_context=rag_context,
                schema=schema,
                model=self.answering_model
            )
        except Exception as err:
            audit = build_answer_evidence_audit(
                generation_performed=True,
                structured_output_valid=False,
                citation_membership_checked=False,
                generation_error_type=type(err).__name__,
            )
            if self.trusted_qa_mode == TrustedQAMode.ENFORCE:
                return self._finalize_trusted_qa_answer(
                    answer_dict={
                        "final_answer": None,
                        "relevant_pages": [],
                        "references": [],
                    },
                    original_answer_dict={"error_type": type(err).__name__},
                    audit=audit,
                    snapshot=snapshot,
                    decision=decision,
                    citation_fields=("relevant_pages", "references"),
                )
            self._record_trusted_qa_trace(
                snapshot=snapshot,
                decision=decision,
                post_answer_audit=audit,
                actual_pipeline_result={"error_type": type(err).__name__},
                post_answer_enforcement=decide_post_answer_enforcement(
                    audit, mode=self.trusted_qa_mode
                ),
                original_pipeline_result={"error_type": type(err).__name__},
                final_pipeline_result={"error_type": type(err).__name__},
            )
            raise
        self.response_data = self.openai_processor.response_data
        original_answer_dict = dict(answer_dict)
        claimed_pages = list(answer_dict.get("relevant_pages", []))
        validated_pages = claimed_pages
        citation_membership_checked = False
        if self.new_challenge_pipeline:
            validated_pages = self._validate_page_references(
                claimed_pages, retrieval_results
            )
            citation_membership_checked = True
            answer_dict["relevant_pages"] = validated_pages
            answer_dict["references"] = self._extract_references(validated_pages, company_name)
        audit = build_answer_evidence_audit(
            generation_performed=True,
            structured_output_valid=True,
            final_answer=answer_dict.get("final_answer"),
            claimed_citations=claimed_pages,
            validated_citations=validated_pages,
            citation_membership_checked=citation_membership_checked,
        )
        return self._finalize_trusted_qa_answer(
            answer_dict=answer_dict,
            original_answer_dict=original_answer_dict,
            audit=audit,
            snapshot=snapshot,
            decision=decision,
            citation_fields=("relevant_pages", "references"),
        )

    def get_answer_generic(
        self, question: str, schema: str, question_id: Optional[str] = None
    ) -> dict:
        version_plan = None
        if self.version_resolver is not None:
            version_plan = self.version_resolver.resolve(
                question,
                available_document_ids=self.retriever.document_ids,
            )
        if self.retrieval_mode == "rd_hybrid":
            retrieval_results = self.retriever.retrieve(
                query=question,
                top_n=self.top_n_retrieval,
                return_parent_pages=False,
                version_plan=version_plan,
                expand_context=True,
                documents_batch_size=self.llm_reranking_sample_size,
            )
        elif self.llm_reranking:
            retrieval_results = self.retriever.retrieve(
                query=question,
                llm_reranking_sample_size=self.llm_reranking_sample_size,
                top_n=self.top_n_retrieval,
                return_parent_pages=self.return_parent_pages,
                version_plan=version_plan,
            )
        else:
            retrieval_results = self.retriever.retrieve(
                query=question,
                top_n=self.top_n_retrieval,
                per_document_top_k=self.llm_reranking_sample_size,
                return_parent_pages=self.return_parent_pages,
                version_plan=version_plan,
            )
        snapshot, decision = self._build_trusted_qa_shadow(
            question=question,
            question_id=question_id,
            retrieval_results=retrieval_results,
            version_plan=version_plan,
        )
        if not retrieval_results:
            self._record_trusted_qa_trace(
                snapshot=snapshot,
                decision=decision,
                post_answer_audit=not_available_answer_audit(),
                actual_pipeline_result={"error_type": "NoRelevantContext"},
            )
            raise ValueError("No relevant context found")

        try:
            answer_dict = self.openai_processor.get_answer_from_rag_context(
                question=question,
                rag_context=self._format_retrieval_results(retrieval_results),
                schema=schema,
                model=self.answering_model,
                prompt_mode="generic",
            )
        except Exception as err:
            audit = build_answer_evidence_audit(
                generation_performed=True,
                structured_output_valid=False,
                citation_membership_checked=False,
                generation_error_type=type(err).__name__,
            )
            if self.trusted_qa_mode == TrustedQAMode.ENFORCE:
                return self._finalize_trusted_qa_answer(
                    answer_dict={
                        "final_answer": None,
                        "relevant_sources": [],
                        "sources": [],
                    },
                    original_answer_dict={"error_type": type(err).__name__},
                    audit=audit,
                    snapshot=snapshot,
                    decision=decision,
                    citation_fields=("relevant_sources", "sources"),
                )
            self._record_trusted_qa_trace(
                snapshot=snapshot,
                decision=decision,
                post_answer_audit=audit,
                actual_pipeline_result={"error_type": type(err).__name__},
                post_answer_enforcement=decide_post_answer_enforcement(
                    audit, mode=self.trusted_qa_mode
                ),
                original_pipeline_result={"error_type": type(err).__name__},
                final_pipeline_result={"error_type": type(err).__name__},
            )
            raise
        self.response_data = self.openai_processor.response_data
        original_answer_dict = dict(answer_dict)
        claimed_sources = list(answer_dict.get("relevant_sources", []))
        validated_sources = self._validate_source_references(
            claimed_sources, retrieval_results
        )
        answer_dict["sources"] = validated_sources
        if answer_dict.get("final_answer") == "N/A":
            answer_dict["sources"] = []
        if version_plan is not None:
            answer_dict["version_trace"] = version_plan.trace()
        audit = build_answer_evidence_audit(
            generation_performed=True,
            structured_output_valid=True,
            final_answer=answer_dict.get("final_answer"),
            claimed_citations=claimed_sources,
            validated_citations=answer_dict["sources"],
            citation_membership_checked=True,
        )
        return self._finalize_trusted_qa_answer(
            answer_dict=answer_dict,
            original_answer_dict=original_answer_dict,
            audit=audit,
            snapshot=snapshot,
            decision=decision,
            citation_fields=("relevant_sources", "sources"),
        )

    def _extract_companies_from_subset(self, question_text: str) -> list[str]:
        """从问题文本中提取公司名，匹配subset文件中的公司"""
        if not hasattr(self, 'companies_df'):
            if self.subset_path is None:
                raise ValueError("subset_path must be provided to use subset extraction")
            self.companies_df = pd.read_csv(self.subset_path)
        
        found_companies = []
        company_names = sorted(self.companies_df['company_name'].unique(), key=len, reverse=True)
        
        for company in company_names:
            escaped_company = re.escape(company)
            
            pattern = rf'{escaped_company}(?:\W|$)'
            
            if re.search(pattern, question_text, re.IGNORECASE):
                found_companies.append(company)
                question_text = re.sub(pattern, '', question_text, flags=re.IGNORECASE)
        
        return found_companies

    def process_question(
        self, question: str, schema: str, question_id: Optional[str] = None
    ):
        # 处理单个问题，支持多公司比较
        if self.routing_mode == "generic":
            return self.get_answer_generic(
                question=question, schema=schema, question_id=question_id
            )

        if self.new_challenge_pipeline:
            extracted_companies = self._extract_companies_from_subset(question)
        else:
            extracted_companies = re.findall(r'"([^"]*)"', question)
        
        if len(extracted_companies) == 0:
            raise ValueError("No company name found in the question.")
        
        if len(extracted_companies) == 1:
            company_name = extracted_companies[0]
            answer_dict = self.get_answer_for_company(
                company_name=company_name,
                question=question,
                schema=schema,
                question_id=question_id,
            )
            return answer_dict
        else:
            return self.process_comparative_question(question, extracted_companies, schema)
    
    def _create_answer_detail_ref(self, answer_dict: dict, question_index: int) -> str:
        """创建答案详情的引用ID，并存储详细内容"""
        ref_id = f"#/answer_details/{question_index}"
        with self._lock:
            self.answer_details[question_index] = {
                "step_by_step_analysis": answer_dict.get('step_by_step_analysis'),
                "reasoning_summary": answer_dict.get('reasoning_summary'),
                "relevant_pages": answer_dict.get('relevant_pages', []),
                "sources": answer_dict.get('sources', []),
                "response_data": self.response_data,
                "self": ref_id
            }
        return ref_id

    def _calculate_statistics(self, processed_questions: List[dict], print_stats: bool = False) -> dict:
        """统计处理结果，包括总数、错误数、N/A数、成功数"""
        total_questions = len(processed_questions)
        error_count = sum(1 for q in processed_questions if "error" in q)
        na_count = sum(1 for q in processed_questions if (q.get("value") if "value" in q else q.get("answer")) == "N/A")
        success_count = total_questions - error_count - na_count
        if print_stats:
            print(f"\nFinal Processing Statistics:")
            print(f"Total questions: {total_questions}")
            print(f"Errors: {error_count} ({(error_count/total_questions)*100:.1f}%)")
            print(f"N/A answers: {na_count} ({(na_count/total_questions)*100:.1f}%)")
            print(f"Successfully answered: {success_count} ({(success_count/total_questions)*100:.1f}%)\n")
        
        return {
            "total_questions": total_questions,
            "error_count": error_count,
            "na_count": na_count,
            "success_count": success_count
        }

    def process_questions_list(self, questions_list: List[dict], output_path: str = None, submission_file: bool = False, team_email: str = "", submission_name: str = "", pipeline_details: str = "") -> dict:
        # 批量处理问题列表，支持并行与断点保存，返回处理结果和统计信息
        total_questions = len(questions_list)
        # 给每个问题加索引，便于后续答案详情定位
        questions_with_index = [{**q, "_question_index": i} for i, q in enumerate(questions_list)]
        self.answer_details = [None] * total_questions  # 预分配答案详情列表
        processed_questions = []
        parallel_threads = self.parallel_requests

        if parallel_threads <= 1:
            # 单线程顺序处理
            for question_data in tqdm(questions_with_index, desc="Processing questions"):
                processed_question = self._process_single_question(question_data)
                processed_questions.append(processed_question)
                if output_path:
                    self._save_progress(processed_questions, output_path, submission_file=submission_file, team_email=team_email, submission_name=submission_name, pipeline_details=pipeline_details)
        else:
            # 多线程并行处理
            with tqdm(total=total_questions, desc="Processing questions") as pbar:
                for i in range(0, total_questions, parallel_threads):
                    batch = questions_with_index[i : i + parallel_threads]
                    with concurrent.futures.ThreadPoolExecutor(max_workers=parallel_threads) as executor:
                        # executor.map 保证结果顺序与输入一致
                        batch_results = list(executor.map(self._process_single_question, batch))
                    processed_questions.extend(batch_results)
                    
                    if output_path:
                        self._save_progress(processed_questions, output_path, submission_file=submission_file, team_email=team_email, submission_name=submission_name, pipeline_details=pipeline_details)
                    pbar.update(len(batch_results))
        
        statistics = self._calculate_statistics(processed_questions, print_stats = True)
        
        return {
            "questions": processed_questions,
            "answer_details": self.answer_details,
            "statistics": statistics
        }

    def _process_single_question(self, question_data: dict) -> dict:
        question_index = question_data.get("_question_index", 0)
        
        if self.routing_mode == "generic":
            question_text = question_data.get("question", question_data.get("text"))
            schema = question_data.get("schema", question_data.get("kind", "text"))
        elif self.new_challenge_pipeline:
            question_text = question_data.get("text")
            schema = question_data.get("kind")
        else:
            question_text = question_data.get("question")
            schema = question_data.get("schema")
        try:
            answer_dict = self.process_question(
                question_text,
                schema,
                question_id=question_data.get("question_id"),
            )
            
            if "error" in answer_dict:
                detail_ref = self._create_answer_detail_ref({
                    "step_by_step_analysis": None,
                    "reasoning_summary": None,
                    "relevant_pages": None
                }, question_index)
                if self.routing_mode == "generic":
                    return {
                        "question": question_text,
                        "schema": schema,
                        "answer": None,
                        "sources": [],
                        "error": answer_dict["error"],
                        "answer_details": {"$ref": detail_ref},
                    }
                if self.new_challenge_pipeline:
                    return {
                        "question_text": question_text,
                        "kind": schema,
                        "value": None,
                        "references": [],
                        "error": answer_dict["error"],
                        "answer_details": {"$ref": detail_ref}
                    }
                else:
                    return {
                        "question": question_text,
                        "schema": schema,
                        "answer": None,
                        "error": answer_dict["error"],
                        "answer_details": {"$ref": detail_ref},
                    }
            detail_ref = self._create_answer_detail_ref(answer_dict, question_index)
            if self.routing_mode == "generic":
                return {
                    "question": question_text,
                    "schema": schema,
                    "answer": answer_dict.get("final_answer"),
                    "sources": answer_dict.get("sources", []),
                    "answer_details": {"$ref": detail_ref},
                }
            if self.new_challenge_pipeline:
                return {
                    "question_text": question_text,
                    "kind": schema,
                    "value": answer_dict.get("final_answer"),
                    "references": answer_dict.get("references", []),
                    "answer_details": {"$ref": detail_ref}
                }
            else:
                return {
                    "question": question_text,
                    "schema": schema,
                    "answer": answer_dict.get("final_answer"),
                    "answer_details": {"$ref": detail_ref},
                }
        except Exception as err:
            return self._handle_processing_error(question_text, schema, err, question_index)

    def _handle_processing_error(self, question_text: str, schema: str, err: Exception, question_index: int) -> dict:
        """
        处理问题处理过程中的异常。
        记录错误详情并返回包含错误信息的字典。
        """
        import traceback
        error_message = str(err)
        tb = traceback.format_exc()
        error_ref = f"#/answer_details/{question_index}"
        error_detail = {
            "error_traceback": tb,
            "self": error_ref
        }
        
        with self._lock:
            self.answer_details[question_index] = error_detail
        
        print(f"Error encountered processing question: {question_text}")
        print(f"Error type: {type(err).__name__}")
        print(f"Error message: {error_message}")
        print(f"Full traceback:\n{tb}\n")
        
        if self.routing_mode == "generic":
            return {
                "question": question_text,
                "schema": schema,
                "answer": None,
                "sources": [],
                "error": f"{type(err).__name__}: {error_message}",
                "answer_details": {"$ref": error_ref},
            }
        if self.new_challenge_pipeline:
            return {
                "question_text": question_text,
                "kind": schema,
                "value": None,
                "references": [],
                "error": f"{type(err).__name__}: {error_message}",
                "answer_details": {"$ref": error_ref}
            }
        else:
            return {
                "question": question_text,
                "schema": schema,
                "answer": None,
                "error": f"{type(err).__name__}: {error_message}",
                "answer_details": {"$ref": error_ref},
            }

    def _post_process_submission_answers(self, processed_questions: List[dict]) -> List[dict]:
        """
        提交格式后处理：
        1. 页码从1-based转为0-based
        2. N/A答案清空引用
        3. 格式化为比赛提交schema
        4. 包含step_by_step_analysis
        """
        submission_answers = []
        
        for q in processed_questions:
            question_text = q.get("question_text") or q.get("question")
            kind = q.get("kind") or q.get("schema")
            value = "N/A" if "error" in q else (q.get("value") if "value" in q else q.get("answer"))
            references = q.get("references", [])
            
            answer_details_ref = q.get("answer_details", {}).get("$ref", "")
            step_by_step_analysis = None
            if answer_details_ref and answer_details_ref.startswith("#/answer_details/"):
                try:
                    index = int(answer_details_ref.split("/")[-1])
                    if 0 <= index < len(self.answer_details) and self.answer_details[index]:
                        step_by_step_analysis = self.answer_details[index].get("step_by_step_analysis")
                except (ValueError, IndexError):
                    pass
            
            # Clear references if value is N/A
            if value == "N/A":
                references = []
            else:
                # Convert page indices from one-based to zero-based (competition requires 0-based page indices, but for debugging it is easier to use 1-based)
                references = [
                    {
                        "pdf_sha1": ref["pdf_sha1"],
                        "page_index": ref["page_index"] - 1
                    }
                    for ref in references
                ]
            
            submission_answer = {
                "question_text": question_text,
                "kind": kind,
                "value": value,
                "references": references,
            }
            
            if step_by_step_analysis:
                submission_answer["reasoning_process"] = step_by_step_analysis
            
            submission_answers.append(submission_answer)
        
        return submission_answers

    def _save_progress(self, processed_questions: List[dict], output_path: Optional[str], submission_file: bool = False, team_email: str = "", submission_name: str = "", pipeline_details: str = ""):
        if output_path:
            statistics = self._calculate_statistics(processed_questions)
            
            # Prepare debug content
            result = {
                "questions": processed_questions,
                "answer_details": self.answer_details,
                "statistics": statistics
            }
            output_file = Path(output_path)
            debug_file = output_file.with_name(output_file.stem + "_debug" + output_file.suffix)
            with open(debug_file, 'w', encoding='utf-8') as file:
                json.dump(result, file, ensure_ascii=False, indent=2)
            
            if submission_file:
                # Post-process answers for submission
                submission_answers = self._post_process_submission_answers(processed_questions)
                submission = {
                    "answers": submission_answers,
                    "team_email": team_email,
                    "submission_name": submission_name,
                    "details": pipeline_details
                }
                with open(output_file, 'w', encoding='utf-8') as file:
                    json.dump(submission, file, ensure_ascii=False, indent=2)

    def process_all_questions(self, output_path: str = 'questions_with_answers.json', team_email: str = "79250515615@yandex.com", submission_name: str = "Ilia_Ris SO CoT + Parent Document Retrieval", submission_file: bool = False, pipeline_details: str = ""):
        result = self.process_questions_list(
            self.questions,
            output_path,
            submission_file=submission_file,
            team_email=team_email,
            submission_name=submission_name,
            pipeline_details=pipeline_details
        )
        return result

    def process_comparative_question(self, question: str, companies: List[str], schema: str) -> dict:
        """
        处理多公司比较类问题：
        1. 先将比较问题重写为单公司问题
        2. 并行处理每个公司
        3. 汇总结果并生成最终比较答案
        """
        # Step 1: Rephrase the comparative question
        rephrased_questions = self.openai_processor.get_rephrased_questions(
            original_question=question,
            companies=companies
        )
        
        individual_answers = {}
        aggregated_references = []
        
        # Step 2: Process each individual question in parallel
        def process_company_question(company: str) -> tuple[str, dict]:
            """Helper function to process one company's question and return (company, answer)"""
            sub_question = rephrased_questions.get(company)
            if not sub_question:
                raise ValueError(f"Could not generate sub-question for company: {company}")
            
            answer_dict = self.get_answer_for_company(
                company_name=company, 
                question=sub_question, 
                schema="number"
            )
            return company, answer_dict

        with concurrent.futures.ThreadPoolExecutor() as executor:
            future_to_company = {
                executor.submit(process_company_question, company): company 
                for company in companies
            }
            
            for future in concurrent.futures.as_completed(future_to_company):
                try:
                    company, answer_dict = future.result()
                    individual_answers[company] = answer_dict
                    
                    company_references = answer_dict.get("references", [])
                    aggregated_references.extend(company_references)
                except Exception as e:
                    company = future_to_company[future]
                    print(f"Error processing company {company}: {str(e)}")
                    raise
        
        # Remove duplicate references
        unique_refs = {}
        for ref in aggregated_references:
            key = (ref.get("pdf_sha1"), ref.get("page_index"))
            unique_refs[key] = ref
        aggregated_references = list(unique_refs.values())
        
        # Step 3: Get the comparative answer using all individual answers
        comparative_answer = self.openai_processor.get_answer_from_rag_context(
            question=question,
            rag_context=individual_answers,
            schema="comparative",
            model=self.answering_model
        )
        self.response_data = self.openai_processor.response_data
        
        comparative_answer["references"] = aggregated_references
        return comparative_answer
    
