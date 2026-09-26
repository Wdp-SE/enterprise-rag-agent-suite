"""Session-only review of hypothetical changes to official public knowledge.

The Agent orchestrates RAG HTTP search, existing engineering Diff/Impact APIs,
and human review. It never calls candidate activation or writes upstream data.
"""

from __future__ import annotations

import hashlib
import re
import unicodedata
from typing import Protocol


class PublicKnowledgeGateway(Protocol):
    def workspace(self) -> dict: ...
    def document(self, document_id: str) -> list[dict]: ...
    def search(self, question: str, *, version: str, language: str, top_k: int = 5) -> dict: ...
    def review_advice(self, change_summary: str, evidence_chunk_ids: list[str]) -> dict: ...
    def engineering_diff(self, old_items: list[dict], new_items: list[dict]) -> dict: ...
    def engineering_impacts(self, payload: dict) -> dict: ...


def _normalized_hash(content: str) -> str:
    normalized = re.sub(r"\s+", " ", unicodedata.normalize("NFKC", content)).strip()
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def _item(source: dict, content: str) -> dict:
    return {
        "item_id": source["chunk_id"],
        "item_type": "API" if "/api/" in source["document_key"] else "DESIGN",
        "organization_id": "apache-public-materials",
        "project_id": "Apache DolphinScheduler",
        "document_id": source["document_id"],
        "version_id": source["version"],
        "section_id": source["heading"] or source["chunk_id"],
        "external_identifier": source["chunk_id"],
        "title": source["heading"] or source["document_key"],
        "content": content,
        "content_hash": _normalized_hash(content),
        "metadata": {"source_url": source["source_url"]},
    }


def _confirmed_dsip_document_reference(
    gateway: PublicKnowledgeGateway, selected: dict, current_version: str,
) -> dict | None:
    proposal = "proposals/dsip-107-proposal"
    implementation = "proposals/dsip-107-implementation"
    if selected["document_key"] not in (proposal, implementation):
        return None
    implementation_id = f"{current_version}:en:{implementation}"
    source = next(
        (
            row for row in gateway.document(implementation_id)
            if row["document_key"] == implementation
            and row["source_url"] == "https://github.com/apache/dolphinscheduler/pull/18464"
            and "independent part of DSIP #18454" in row["content"]
        ),
        None,
    )
    if source is None:
        return None
    return {
        "relation_type": "DOCUMENT_REFERENCE",
        "source_document_id": implementation_id,
        "target_document_id": f"{current_version}:en:{proposal}",
        "source_chunk_id": source["chunk_id"],
        "source_heading": source["heading"],
        "source_url": source["source_url"],
        "source_excerpt": source["content"],
    }


class PublicReviewAgent:
    def __init__(self, gateway: PublicKnowledgeGateway):
        self.gateway = gateway

    def analyze_request(self, change_summary: str) -> dict:
        """Find current-version candidates from a natural-language change request."""
        summary = change_summary.strip()
        if not summary or len(summary) > 4000:
            raise ValueError("变更描述应为 1 到 4000 字")

        current_version = self.gateway.workspace()["current_version"]
        search_result = self.gateway.search(
            summary, version=current_version, language="zh_preferred", top_k=5,
        )
        retrieved = search_result.get("results", [])
        candidates = [
            row for row in retrieved
            if row.get("version") == current_version
            and row.get("source_url", "").startswith("https://github.com/apache/dolphinscheduler/")
            and row.get("chunk_id")
        ]
        base_advice = {"status": "NO_EVIDENCE", "answer": "N/A", "sources": []}
        if not candidates:
            return {
                "request_mode": "natural_language",
                "request_summary": summary,
                "retrieval_policy": search_result.get("retrieval_policy", "bm25"),
                "retrieved_results": [],
                "impacts": [],
                "review_advice": base_advice,
                "sandbox_only": True,
                "public_baseline_written": False,
            }

        try:
            advice = self.gateway.review_advice(
                summary, [row["chunk_id"] for row in candidates]
            )
        except Exception:
            # Model assistance is optional; the underlying RAG candidates remain visible.
            advice = {"status": "GENERATION_PROVIDER_UNAVAILABLE", "answer": "N/A", "sources": []}
        allowed = {row["chunk_id"]: row for row in candidates}
        cited = [
            allowed[row["chunk_id"]]
            for row in advice.get("sources", [])
            if row.get("chunk_id") in allowed
        ]
        if advice.get("status") == "OK" and not cited:
            advice = {**advice, "status": "ABSTAINED", "answer": "N/A", "sources": []}
        else:
            advice = {**advice, "sources": cited}

        return {
            "request_mode": "natural_language",
            "request_summary": summary,
            "retrieval_policy": search_result.get("retrieval_policy", "bm25"),
            "retrieved_results": candidates,
            "impacts": [{
                "status": "SUGGESTED",
                "relation": "suggested",
                "reason": "模型依据此官方片段建议进一步核对；检索相关性不代表已确认实际影响。",
                "evidence": row,
            } for row in cited],
            "review_advice": advice,
            "sandbox_only": True,
            "public_baseline_written": False,
        }

    def analyze(self, selected: dict, proposed_text: str) -> dict:
        current_version = self.gateway.workspace()["current_version"]
        if selected.get("version") != current_version:
            raise ValueError("只能选择当前固定版本的官方资料")
        if not selected.get("source_url", "").startswith("https://github.com/apache/dolphinscheduler/"):
            raise ValueError("资料来源不是已登记的 Apache 官方地址")
        proposed = proposed_text.strip()
        if not proposed or len(proposed) > 4000:
            raise ValueError("假设性变更内容应为 1 到 4000 字")
        old_item, new_item = _item(selected, selected["content"]), _item(selected, proposed)
        if old_item["content_hash"] == new_item["content_hash"]:
            raise ValueError("修改后内容与原文相同")
        changes = self.gateway.engineering_diff([old_item], [new_item])["changes"]
        change = changes[0]
        if change["change_type"] == "UNCHANGED":
            raise ValueError("修改后内容与原文相同")
        retrieved = self.gateway.search(
            (selected["heading"] + " " + proposed)[:1000],
            version=current_version, language="all", top_k=12,
        )["results"]
        related = [
            row for row in retrieved
            if row["chunk_id"] != selected["chunk_id"]
            and row["document_id"] != selected["document_id"]
        ][:5]
        document_reference = _confirmed_dsip_document_reference(
            self.gateway, selected, current_version
        )
        impacts = self.gateway.engineering_impacts({
            "changed_item_id": selected["chunk_id"],
            "items": [old_item] + [_item(row, row["content"]) for row in related],
            "trace_links": [],
            # Existing API field name is historical; candidates come from the
            # measured public BM25 retrieval policy, not a Dense claim.
            "dense_item_ids": [row["chunk_id"] for row in related],
            "evidence_by_item": {row["chunk_id"]: [row["chunk_id"]] for row in related},
        })["impacts"]
        by_id = {row["chunk_id"]: row for row in related}
        review_advice = {"status": "NO_EVIDENCE", "answer": "N/A", "sources": []}
        if related:
            change_summary = (
                f"资料章节：{selected['heading']}\n变更类型：{change['change_type']}\n"
                f"原文：{selected['content'][:1400]}\n"
                f"拟议内容：{proposed[:1400]}"
            )
            try:
                review_advice = self.gateway.review_advice(
                    change_summary, [row["chunk_id"] for row in related]
                )
            except Exception:
                # Optional model advice must never block the deterministic review flow.
                review_advice = {"status": "GENERATION_PROVIDER_UNAVAILABLE", "answer": "N/A", "sources": []}
            allowed_ids = {row["chunk_id"] for row in related}
            cited_sources = [
                row for row in review_advice.get("sources", [])
                if row.get("chunk_id") in allowed_ids
            ]
            if review_advice.get("status") == "OK" and not cited_sources:
                review_advice = {"status": "ABSTAINED", "answer": "N/A", "sources": []}
            else:
                review_advice = {**review_advice, "sources": cited_sources}
        return {
            "change": change,
            "selected_source": selected,
            "impacts": [{
                "status": row["review_status"],
                "relation": "suggested",
                "reason": "检索发现主题相关，可能受影响；尚无可核验的段落级显式引用。",
                "evidence": by_id[row["impacted_item_id"]],
            } for row in impacts],
            "confirmed_relations": [document_reference] if document_reference else [],
            "patch_candidate": {
                "target_chunk_id": selected["chunk_id"],
                "before": selected["content"], "proposed_after": proposed,
                "status": "REQUIRES_HUMAN_REVIEW",
            },
            "review_advice": review_advice,
            "sandbox_only": True,
            "public_baseline_written": False,
        }
