"""Session-only review of hypothetical changes to official public knowledge.

The Agent orchestrates RAG HTTP search, existing engineering Diff/Impact APIs,
and human review. It never calls candidate activation or writes upstream data.
"""

from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from typing import Protocol


class PublicKnowledgeGateway(Protocol):
    def workspace(self) -> dict: ...
    def document(self, document_id: str) -> list[dict]: ...
    def search(self, question: str, *, version: str, language: str, top_k: int = 5) -> dict: ...
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


def _confirmed_dsip_link(
    gateway: PublicKnowledgeGateway, selected: dict, current_version: str,
) -> tuple[dict | None, dict | None]:
    proposal = "proposals/dsip-107-proposal"
    implementation = "proposals/dsip-107-implementation"
    if selected["document_key"] not in (proposal, implementation):
        return None, None
    other = implementation if selected["document_key"] == proposal else proposal
    other_id = f"{current_version}:en:{other}"
    candidates = gateway.document(other_id)
    if other == implementation:
        counterpart = next(
            (row for row in candidates if "DSIP #18454" in row["content"]), None
        )
    else:
        counterpart = next(iter(candidates), None)
    if counterpart is None:
        return None, None
    # The PR body explicitly states it is an independent part of DSIP #18454.
    # This confirms the proposal/implementation reference, not automatic impact.
    canonical = json.dumps({
        "source_item_id": selected["chunk_id"],
        "target_item_id": counterpart["chunk_id"],
        "provenance": "EXPLICIT",
    }, sort_keys=True, separators=(",", ":"))
    link = {
        "trace_link_id": f"trace_{hashlib.sha256(canonical.encode()).hexdigest()[:20]}",
        "source_item_id": selected["chunk_id"],
        "target_item_id": counterpart["chunk_id"],
        "provenance": "EXPLICIT", "status": "CONFIRMED",
        "metadata": {
            "evidence_ids": [counterpart["chunk_id"]],
            "source_url": "https://github.com/apache/dolphinscheduler/pull/18464",
            "reason": "官方实现 PR #18464 正文明确引用 DSIP #18454。",
        },
    }
    return counterpart, link


class PublicReviewAgent:
    def __init__(self, gateway: PublicKnowledgeGateway):
        self.gateway = gateway

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
        counterpart, confirmed = _confirmed_dsip_link(self.gateway, selected, current_version)
        if counterpart:
            related = [counterpart] + [row for row in related if row["chunk_id"] != counterpart["chunk_id"]][:4]
        links = [confirmed] if confirmed else []
        impacts = self.gateway.engineering_impacts({
            "changed_item_id": selected["chunk_id"],
            "items": [old_item] + [_item(row, row["content"]) for row in related],
            "trace_links": links,
            # Existing API field name is historical; candidates come from the
            # measured public BM25 retrieval policy, not a Dense claim.
            "dense_item_ids": [row["chunk_id"] for row in related],
            "evidence_by_item": {row["chunk_id"]: [row["chunk_id"]] for row in related},
        })["impacts"]
        by_id = {row["chunk_id"]: row for row in related}
        return {
            "change": change,
            "selected_source": selected,
            "impacts": [{
                "status": row["review_status"],
                "relation": "confirmed" if row["review_status"] == "CONFIRMED" else "suggested",
                "reason": (
                    "官方实现 PR #18464 正文明确引用 DSIP #18454。"
                    if row["review_status"] == "CONFIRMED"
                    else "检索发现主题相关，可能受影响；尚无可核验的显式引用。"
                ),
                "evidence": by_id[row["impacted_item_id"]],
            } for row in impacts],
            "confirmed_relations": links,
            "patch_candidate": {
                "target_chunk_id": selected["chunk_id"],
                "before": selected["content"], "proposed_after": proposed,
                "status": "REQUIRES_HUMAN_REVIEW",
            },
            "sandbox_only": True,
            "public_baseline_written": False,
        }
