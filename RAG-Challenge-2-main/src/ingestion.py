import os
import json
import pickle
import hashlib
from typing import List, Union
from pathlib import Path
from tqdm import tqdm

from dotenv import load_dotenv
from openai import OpenAI
import faiss
import numpy as np
from tenacity import retry, wait_fixed, stop_after_attempt
from src.provider_config import resolve_provider_model
from src.vector_utils import l2_normalize_rows
from src.document_metadata import normalize_document_metadata
from src.text_tokenization import technical_tokenize

try:
    import dashscope
    from dashscope import TextEmbedding
except ImportError:  # Required only for the DashScope embedding provider.
    dashscope = None
    TextEmbedding = None

try:
    from rank_bm25 import BM25Okapi
except ImportError:  # BM25 is not required by the vector baseline.
    BM25Okapi = None


# BM25Ingestor：BM25索引构建与保存工具
class BM25Ingestor:
    def __init__(self):
        pass

    def create_bm25_index(self, chunks: List[str]) -> BM25Okapi:
        """从文本块列表创建BM25索引"""
        if BM25Okapi is None:
            raise ImportError("BM25 ingestion requires the 'rank-bm25' package.")
        tokenized_chunks = [technical_tokenize(chunk) for chunk in chunks]
        return BM25Okapi(tokenized_chunks)
    
    def process_reports(self, all_reports_dir: Path, output_dir: Path):
        """
        批量处理所有报告，生成并保存BM25索引。
        参数：
            all_reports_dir (Path): 存放JSON报告的目录
            output_dir (Path): 保存BM25索引的目录
        """
        output_dir.mkdir(parents=True, exist_ok=True)
        all_report_paths = list(all_reports_dir.glob("*.json"))

        for report_path in tqdm(all_report_paths, desc="Processing reports for BM25"):
            # 加载报告
            with open(report_path, 'r', encoding='utf-8') as f:
                report_data = json.load(f)
                
            # 提取文本块并创建BM25索引
            text_chunks = [chunk['text'] for chunk in report_data['content']['chunks']]
            bm25_index = self.create_bm25_index(text_chunks)
            
            # 保存BM25索引，文件名用sha1_name
            sha1_name = report_data["metainfo"]["sha1_name"]
            output_file = output_dir / f"{sha1_name}.pkl"
            with open(output_file, 'wb') as f:
                pickle.dump(bm25_index, f)
                
        print(f"Processed {len(all_report_paths)} reports")

# VectorDBIngestor：向量库构建与保存工具
class VectorDBIngestor:
    def __init__(
        self,
        embedding_provider: str = "dashscope",
        embedding_model: str = None,
    ):
        load_dotenv()
        self.embedding_provider, self.embedding_model = resolve_provider_model(
            embedding_provider,
            embedding_model,
            "embedding",
        )
        self.llm = None
        if self.embedding_provider == "dashscope" and dashscope is not None:
            dashscope.api_key = os.getenv("DASHSCOPE_API_KEY")

    @staticmethod
    def _write_safe_embedding_error(log_file: str, batch: List[str], text_index: int, message: str):
        text = batch[text_index] if 0 <= text_index < len(batch) else ""
        digest = hashlib.sha256(text.encode("utf-8")).hexdigest()[:16] if text else "unavailable"
        with open(log_file, "a", encoding="utf-8") as file:
            file.write(
                f"{message}; text_index={text_index}; text_length={len(text)}; "
                f"text_sha256_prefix={digest}\n"
            )

    @retry(wait=wait_fixed(20), stop=stop_after_attempt(2))
    def _get_embeddings(self, text: Union[str, List[str]], model: str = None) -> List[float]:
        # 获取文本或文本块的嵌入向量，支持重试（使用阿里云DashScope，分批处理）
        if isinstance(text, str) and not text.strip():
            raise ValueError("Input text cannot be an empty string.")
        
        # 保证 input 为一维字符串列表或单个字符串
        if isinstance(text, list):
            text_chunks = text
        else:
            text_chunks = [text]

        # 类型检查，确保每一项都是字符串
        if not all(isinstance(x, str) for x in text_chunks):
            raise ValueError("所有待嵌入文本必须为字符串类型！实际类型: {}".format([type(x) for x in text_chunks]))

        # 过滤空字符串
        text_chunks = [x for x in text_chunks if x.strip()]
        if not text_chunks:
            raise ValueError("所有待嵌入文本均为空字符串！")
        # print('start embedding ================================')
        _, model = resolve_provider_model(
            self.embedding_provider,
            model or self.embedding_model,
            "embedding",
        )
        embeddings = []
        MAX_BATCH_SIZE = 25
        LOG_FILE = 'embedding_error.log'

        if self.embedding_provider == "openai" and self.llm is None:
            self.llm = OpenAI(api_key=os.getenv("OPENAI_API_KEY"), timeout=None, max_retries=2)
        if self.embedding_provider == "dashscope" and TextEmbedding is None:
            raise ImportError("DashScope embeddings require the 'dashscope' package.")

        for i in range(0, len(text_chunks), MAX_BATCH_SIZE):
            batch = text_chunks[i:i+MAX_BATCH_SIZE]
            if self.embedding_provider == "openai":
                response = self.llm.embeddings.create(input=batch, model=model)
                ordered = sorted(response.data, key=lambda item: item.index)
                embeddings.extend(item.embedding for item in ordered)
                continue

            response = TextEmbedding.call(model=model, input=batch)
            try:
                output = response['output']
            except (KeyError, TypeError):
                output = getattr(response, 'output', None)

            if isinstance(output, dict) and output.get('embeddings') is not None:
                for position, item in enumerate(output['embeddings']):
                    value = item.get('embedding') if isinstance(item, dict) else getattr(item, 'embedding', None)
                    text_index = item.get('text_index', position) if isinstance(item, dict) else getattr(item, 'text_index', position)
                    if not value:
                        self._write_safe_embedding_error(
                            LOG_FILE, batch, text_index, "DashScope returned an empty embedding"
                        )
                        raise RuntimeError(
                            f"DashScope returned an empty embedding at text_index={text_index}; "
                            f"safe diagnostics were written to {LOG_FILE}."
                        )
                    embeddings.append(value)
            elif isinstance(output, dict) and output.get('embedding') is not None:
                value = output.get('embedding')
                if not value:
                    self._write_safe_embedding_error(
                        LOG_FILE, batch, 0, "DashScope returned an empty embedding"
                    )
                    raise RuntimeError(
                        f"DashScope returned an empty embedding; safe diagnostics were written to {LOG_FILE}."
                    )
                embeddings.append(value)
            else:
                raise RuntimeError("DashScope embedding API returned an unexpected response schema.")
        return embeddings

    def _create_vector_db(self, embeddings: List[float]):
        # 单位向量的内积等价于 cosine similarity
        embeddings_array = l2_normalize_rows(embeddings)
        dimension = len(embeddings[0])
        index = faiss.IndexFlatIP(dimension)
        index.add(embeddings_array)
        return index
    
    def _process_report(self, report: dict):
        # 针对单份报告，提取文本块并生成向量库
        text_chunks = [chunk['text'] for chunk in report['content']['chunks']]
        embeddings = self._get_embeddings(text_chunks)
        index = self._create_vector_db(embeddings)
        return index

    def process_reports(self, all_reports_dir: Path, output_dir: Path):
        # 批量处理所有报告，生成并保存faiss向量库
        all_report_paths = list(all_reports_dir.glob("*.json"))
        output_dir.mkdir(parents=True, exist_ok=True)

        for report_path in tqdm(all_report_paths, desc="Processing reports"):
            with open(report_path, 'r', encoding='utf-8') as file:
                report_data = json.load(file)
            index = self._process_report(report_data)
            metainfo = normalize_document_metadata(
                report_data.get("metainfo"), source_identifier=report_path.name
            )
            faiss_file_path = output_dir / f"{metainfo['document_id']}.faiss"
            faiss.write_index(index, str(faiss_file_path))

        print(f"Processed {len(all_report_paths)} reports")
