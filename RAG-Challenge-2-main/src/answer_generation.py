"""Evidence-only structured answer generation for the formal RAG runtime."""

from __future__ import annotations

import json
import os
from typing import Any


SYSTEM_PROMPT = """你是企业研发文档知识服务的问答助手。
只能依据给定检索证据回答，不得使用证据之外的知识补全事实。
证据不足时将 final_answer 设为 N/A，并返回空的 relevant_sources。
每个引用只能使用证据中真实存在的 document_id 与 page_number。
只返回 JSON 对象，格式为：
{"final_answer":"回答或 N/A","relevant_sources":[{"document_id":"文档ID","page_number":1}]}
"""


class StructuredAnswerGenerator:
    """Call DashScope with a strict, citation-bearing JSON contract."""

    def __init__(self, *, provider: str, model: str):
        if provider.casefold() != "dashscope":
            raise ValueError("only the dashscope generation provider is supported")
        api_key = os.environ.get("DASHSCOPE_API_KEY", "").strip()
        if not api_key:
            raise ValueError("DASHSCOPE_API_KEY is required for external generation")
        self.api_key = api_key
        self.model = model

    @staticmethod
    def _decode(payload: Any) -> dict:
        if isinstance(payload, dict):
            value = payload
        elif isinstance(payload, str):
            value = json.loads(payload.strip())
        else:
            raise ValueError("generation result is not a JSON object")
        if set(value) != {"final_answer", "relevant_sources"}:
            raise ValueError("generation result violates the answer schema")
        if not isinstance(value["final_answer"], str):
            raise ValueError("final_answer must be a string")
        if not isinstance(value["relevant_sources"], list):
            raise ValueError("relevant_sources must be a list")
        for source in value["relevant_sources"]:
            if not isinstance(source, dict) or set(source) != {
                "document_id",
                "page_number",
            }:
                raise ValueError("citation violates the source schema")
            if not isinstance(source["document_id"], str):
                raise ValueError("citation document_id must be a string")
            page = source["page_number"]
            if not isinstance(page, int) or isinstance(page, bool) or page < 1:
                raise ValueError("citation page_number must be a positive integer")
        return value

    def generate(self, *, question: str, context: str) -> dict:
        from dashscope import Generation

        response = Generation.call(
            api_key=self.api_key,
            model=self.model,
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {
                    "role": "user",
                    "content": f"问题：\n{question}\n\n检索证据：\n{context}",
                },
            ],
            result_format="message",
        )
        status_code = getattr(response, "status_code", None)
        if status_code != 200:
            raise RuntimeError("generation provider request failed")
        output = getattr(response, "output", None)
        try:
            content = output["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as exc:
            raise ValueError("generation provider returned an invalid response") from exc
        return self._decode(content)
