"""Evidence-based review of hypothetical changes to official public knowledge.

The Agent orchestrates RAG HTTP search, existing engineering Diff/Impact APIs,
and human review. It never calls candidate activation or writes upstream data.
The public workbench persists anonymous review decisions in a local SQLite store.
"""

from __future__ import annotations

import hashlib
import json
import re
import unicodedata
import uuid
from typing import Protocol
from urllib.parse import urlsplit

from app.change_request import (
    CHANGE_TYPES,
    build_request_plan,
    is_out_of_scope_public_request,
    request_queries,
)


class PublicKnowledgeGateway(Protocol):
    def workspace(self) -> dict: ...
    def document(self, document_id: str) -> list[dict]: ...
    def search(self, question: str, *, version: str, language: str, top_k: int = 5) -> dict: ...
    def review_advice(self, change_summary: str, evidence_chunk_ids: list[str]) -> dict: ...
    def review_advice_for_version(
        self, change_summary: str, evidence_chunk_ids: list[str], *, version: str,
    ) -> dict: ...
    def engineering_diff(self, old_items: list[dict], new_items: list[dict]) -> dict: ...
    def engineering_impacts(self, payload: dict) -> dict: ...


def _normalized_hash(content: str) -> str:
    normalized = re.sub(r"\s+", " ", unicodedata.normalize("NFKC", content)).strip()
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def _request_queries(summary: str) -> list[str]:
    """Search the whole change and up to three distinct clauses of a compound request."""
    return request_queries(summary)


def _official_hit(row: dict, current_version: str, repository: str) -> bool:
    score = row.get("retrieval_score")
    parsed = urlsplit(str(row.get("source_url", "")))
    repository_path = "/" + repository.strip("/") + "/"
    commit = row.get("commit")
    pinned_blob = (
        not commit
        or isinstance(commit, str) and re.fullmatch(r"[0-9a-f]{40}", commit)
        and parsed.path.startswith(repository_path + "blob/" + commit + "/")
    )
    return (
        row.get("version") == current_version
        and bool(re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repository))
        and parsed.scheme == "https" and parsed.netloc == "github.com"
        and parsed.path.startswith(repository_path)
        and pinned_blob
        and bool(row.get("chunk_id"))
        and (score is None or isinstance(score, (int, float)) and score > 0)
    )


_SOURCE_OVERLAP_STOP_WORDS = {
    "guide", "task", "docs", "official", "check", "verify", "and", "the",
    "what", "does", "how", "is", "for", "with", "parent", "child",
}


def _source_path_overlap(trace: dict, row: dict) -> int:
    """Use query-specific heading/path token overlap as a tie-break among RAG hits."""
    query = str(trace.get("search_query") or trace.get("query") or "").casefold()
    source = " ".join((
        str(row.get("document_key") or ""),
        str(row.get("heading") or ""),
    )).casefold()
    normalized_source = re.sub(r"[^a-z0-9]+", "", source)
    terms = {
        term for term in re.findall(r"[a-z][a-z0-9]*", query)
        if len(term) > 2 and term not in _SOURCE_OVERLAP_STOP_WORDS
    }
    return sum(
        re.sub(r"[^a-z0-9]+", "", term) in normalized_source
        for term in terms
    )


def _select_request_evidence(searches: list[tuple[dict, list[dict]]]) -> list[dict]:
    """Reserve distinct, query-aligned sources across subqueries, then fill five items."""
    selected: dict[str, dict] = {}
    query_results = searches[1:] if len(searches) > 1 else searches
    selected_documents: set[str] = set()
    for _trace, rows in query_results:
        if len(selected) >= 5:
            break
        eligible = [
            row for row in rows
            if (row.get("document_key") or row["chunk_id"]) not in selected_documents
        ]
        if eligible:
            best = max(eligible, key=lambda row: _source_path_overlap(_trace, row))
            selected[best["chunk_id"]] = best
            selected_documents.add(best.get("document_key") or best["chunk_id"])
    # Prefer another previously unseen document when the result pool has one.
    for trace, rows in searches:
        for row in rows:
            if len(selected) >= 5:
                return list(selected.values())
            document_key = row.get("document_key") or row["chunk_id"]
            if (
                row["chunk_id"] not in selected
                and document_key not in selected_documents
                and _source_path_overlap(trace, row) > 0
            ):
                selected[row["chunk_id"]] = row
                selected_documents.add(document_key)
    for _trace, rows in searches:
        for row in rows:
            if len(selected) >= 5:
                return list(selected.values())
            selected.setdefault(row["chunk_id"], row)
    return list(selected.values())


def _retrieval_gaps(searches: list[tuple[dict, list[dict]]]) -> list[str]:
    return [row["message"] for row in _retrieval_gap_details(searches)]


def _retrieval_gap_details(
    searches: list[tuple[dict, list[dict]]], plan: dict | None = None,
) -> list[dict]:
    scope = searches[1:] if len(searches) > 1 else searches
    labels = {
        "no_retrieval_match": ("NO_MATCH", "当前版本未检索到匹配资料"),
        "candidate_outside_evidence_budget": ("EVIDENCE_BUDGET", "检索命中未纳入本次模型证据上限"),
        "search_unavailable": ("SEARCH_UNAVAILABLE", "检索服务未完成"),
    }
    material = (CHANGE_TYPES.get((plan or {}).get("change_type"), CHANGE_TYPES["general"]) or {}).get(
        "materials", CHANGE_TYPES["general"]["materials"]
    )
    action = (plan or {}).get("gap_action", CHANGE_TYPES["general"]["action"])
    details = []
    for trace, _rows in scope:
        definition = labels.get(trace["status"])
        if definition is None:
            continue
        gap_type, label = definition
        details.append({
            "gap_type": gap_type,
            "message": f"{label}：{trace['query']}",
            "query": trace["query"],
            "expected_materials": material,
            "suggested_action": action,
            "requires_human_review": True,
        })
    return details


def _model_evidence_gaps(advice: dict) -> list[str]:
    review = advice.get("review")
    if not isinstance(review, dict):
        return []
    gaps = review.get("evidence_gaps")
    return [gap.strip() for gap in gaps if isinstance(gap, str) and gap.strip()] if isinstance(gaps, list) else []


def _model_evidence_gap_details(advice: dict) -> list[dict]:
    return [
        {
            "gap_type": "MODEL_REPORTED",
            "message": gap,
            "query": None,
            "expected_materials": None,
            "suggested_action": "模型提示尚未核验；请审核人根据原文确认是否确实缺少该资料。",
            "requires_human_review": True,
        }
        for gap in _model_evidence_gaps(advice)
    ]


def _item(source: dict, content: str) -> dict:
    repository = str(source.get("repository") or "public-materials")
    owner, _, repository_name = repository.partition("/")
    return {
        "item_id": source["chunk_id"],
        "item_type": "API" if "/api/" in source["document_key"] else "DESIGN",
        "organization_id": owner or "public-materials",
        "project_id": repository_name or repository,
        "document_id": source["document_id"],
        "version_id": source["version"],
        "section_id": source["heading"] or source["chunk_id"],
        "external_identifier": source["chunk_id"],
        "title": source["heading"] or source["document_key"],
        "content": content,
        "content_hash": _normalized_hash(content),
        "metadata": {"source_url": source["source_url"]},
    }


def _normalize_review_advice(advice: dict, allowed_sources: dict[str, dict]) -> tuple[dict, list[dict]]:
    """Keep only structured model suggestions tied to this request's RAG evidence."""
    review = advice.get("review")
    if (
        advice.get("status") == "ABSTAINED"
        and isinstance(review, dict)
        and review.get("review_status") == "REQUIRES_HUMAN_REVIEW"
        and review.get("impact_candidates") == []
    ):
        return {**advice, "answer": "N/A", "sources": [], "review": review}, []
    if advice.get("status") != "OK":
        return {**advice, "sources": [], "review": None}, []
    candidates = review.get("impact_candidates") if isinstance(review, dict) else None
    if (
        not isinstance(candidates, list)
        or review.get("review_status") != "REQUIRES_HUMAN_REVIEW"
        or not candidates
    ):
        return {
            **advice, "status": "ABSTAINED", "answer": "N/A",
            "sources": [], "review": None,
        }, []

    impacts = []
    sources = []
    seen = set()
    for candidate in candidates:
        if not isinstance(candidate, dict):
            return {**advice, "status": "ABSTAINED", "answer": "N/A", "sources": [], "review": None}, []
        chunk_id = candidate.get("evidence_chunk_id")
        reason = candidate.get("reason")
        action = candidate.get("suggested_action")
        if (
            not isinstance(chunk_id, str) or chunk_id not in allowed_sources or chunk_id in seen
            or not isinstance(reason, str) or not reason.strip()
            or not isinstance(action, str) or not action.strip()
        ):
            return {**advice, "status": "ABSTAINED", "answer": "N/A", "sources": [], "review": None}, []
        seen.add(chunk_id)
        source = allowed_sources[chunk_id]
        sources.append(source)
        impacts.append({
            "status": "SUGGESTED", "relation": "suggested", "reason": reason,
            "suggested_action": action, "evidence": source,
        })
    return {**advice, "sources": sources, "review": review}, impacts


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

    def analyze_request(
        self,
        change_summary: str,
        *,
        change_type: str | None = None,
        impact_scope: str | None = None,
        target_version: str | None = None,
        objective: str | None = None,
        constraints: str | None = None,
        validation_plan: str | None = None,
    ) -> dict:
        """Find current-version candidates from a natural-language change request."""
        summary = change_summary.strip()
        if not summary or len(summary) > 4000:
            raise ValueError("变更描述应为 1 到 4000 字")

        plan = build_request_plan(summary, change_type=change_type, impact_scope=impact_scope)

        if is_out_of_scope_public_request(summary):
            task_id = uuid.uuid4().hex
            fingerprint = _normalized_hash(f"out_of_scope_public:{summary}")[:20]
            explanation = (
                "本工作台当前只检索已配置知识空间的官方公开资料，未接入公司内部 API、"
                "Jira、通讯录或内部制度。为避免把企业私有问题误交给公开语料或模型，已在检索前停止。"
            )
            gap = {
                "gap_type": "OUT_OF_SCOPE_PUBLIC_CORPUS",
                "message": explanation,
                "query": summary,
                "expected_materials": "经授权并脱敏的企业内部资料",
                "suggested_action": "请改问公开文档可回答的问题；企业场景需先接入经授权的知识源并配置访问控制。",
                "requires_human_review": True,
            }
            return {
                "task_id": task_id,
                "request_fingerprint": fingerprint,
                "request_mode": "natural_language",
                "request_summary": summary,
                "request_plan": plan,
                "scope_status": "OUT_OF_SCOPE",
                "retrieval_policy": "not_run_scope_guard",
                "retrieval_trace": {
                    "queries": [],
                    "uncovered_queries": [summary],
                    "model_status": "NOT_CALLED_OUT_OF_SCOPE",
                    "query_limit": plan["query_limit"],
                    "scope_status": "OUT_OF_SCOPE",
                },
                "retrieved_results": [],
                "impacts": [],
                "review_advice": {
                    "status": "OUT_OF_SCOPE",
                    "answer": "未执行检索或模型生成。",
                    "sources": [],
                    "message": explanation,
                },
                "evidence_gaps": [explanation],
                "evidence_gap_details": [gap],
                "sandbox_only": True,
                "public_baseline_written": False,
            }

        workspace = self.gateway.workspace()
        current_version = workspace["current_version"]
        repository = str(workspace.get("repository") or "")
        available_versions = [
            str(value) for value in workspace.get("available_versions", [current_version])
        ]
        selected_version = current_version if not target_version or target_version == "current" else target_version
        if selected_version not in available_versions:
            raise ValueError("目标版本不在当前知识空间的已收录版本中")
        context_values = {}
        for name, raw_value in (
            ("objective", objective),
            ("constraints", constraints),
            ("validation_plan", validation_plan),
        ):
            value = (raw_value or "").strip()
            if len(value) > 800:
                raise ValueError("提案补充信息每项不超过 800 字")
            context_values[name] = value or None
        missing_fields = [name for name, value in context_values.items() if value is None]
        request_context = {
            **context_values,
            "target_version": selected_version,
            "context_status": "needs_confirmation" if missing_fields else "provided",
            "missing_fields": missing_fields,
        }
        plan["target_version"] = selected_version
        plan["proposal_context_status"] = request_context["context_status"]
        task_id = uuid.uuid4().hex
        fingerprint = _normalized_hash(
            json.dumps({
                "version": selected_version, "change_type": plan["change_type"],
                "impact_scope": plan["impact_scope"], "summary": summary,
                **context_values,
            }, ensure_ascii=False, sort_keys=True)
        )[:20]
        searches: list[tuple[dict, list[dict]]] = []
        retrieval_policy = "bm25"
        for query_step in plan["queries"]:
            query = query_step["query"]
            search_query = query_step.get("search_query", query)
            trace = {
                **query_step,
                "status": "no_retrieval_match",
                "top_chunk_ids": [],
                "selected_chunk_ids": [],
            }
            try:
                search_result = self.gateway.search(
                    search_query, version=selected_version, language="zh_preferred", top_k=5,
                )
                retrieval_policy = search_result.get("retrieval_policy", retrieval_policy)
                rows = [
                    row for row in search_result.get("results", [])
                    if _official_hit(row, selected_version, repository)
                ]
                trace["top_chunk_ids"] = [row["chunk_id"] for row in rows]
            except Exception:
                # A failed search is distinct from a successful search without matches.
                rows = []
                trace["status"] = "search_unavailable"
            searches.append((trace, rows))

        candidates = _select_request_evidence(searches)
        candidate_ids = {row["chunk_id"] for row in candidates}
        for trace, rows in searches:
            trace["selected_chunk_ids"] = [row["chunk_id"] for row in rows if row["chunk_id"] in candidate_ids]
            if trace["status"] != "search_unavailable" and rows:
                trace["status"] = "candidate_found" if trace["selected_chunk_ids"] else "candidate_outside_evidence_budget"
        scope_traces = searches[1:] if len(searches) > 1 else searches
        retrieval_trace = {
            "queries": [trace for trace, _rows in searches],
            "uncovered_queries": [
                trace["query"] for trace, _rows in scope_traces
                if trace["status"] != "candidate_found"
            ],
            "model_status": "NOT_CALLED",
            "query_limit": plan["query_limit"],
        }
        evidence_gap_details = _retrieval_gap_details(searches, plan)
        evidence_gaps = [row["message"] for row in evidence_gap_details]
        base_advice = {"status": "NO_EVIDENCE", "answer": "N/A", "sources": []}
        if not candidates:
            if all(trace["status"] == "search_unavailable" for trace, _rows in searches):
                base_advice["status"] = "RETRIEVAL_UNAVAILABLE"
            return {
                "task_id": task_id,
                "request_fingerprint": fingerprint,
                "request_mode": "natural_language",
                "request_summary": summary,
                "request_plan": plan,
                "request_context": request_context,
                "retrieval_policy": retrieval_policy,
                "retrieval_trace": retrieval_trace,
                "retrieved_results": [],
                "impacts": [],
                "review_advice": base_advice,
                "evidence_gaps": evidence_gaps,
                "evidence_gap_details": evidence_gap_details,
                "sandbox_only": True,
                "public_baseline_written": False,
            }

        try:
            advice_summary = (
                f"知识空间：{workspace.get('workspace', repository)}\n目标版本：{selected_version}"
                f"\n变更描述：{summary}\n变更类型：{plan['change_type_label']}"
                f"（{plan['classification_source']}）\n影响范围：{plan['impact_scope'] or '待补充'}"
                f"\n变更目标：{context_values['objective'] or '待补充'}"
                f"\n约束条件：{context_values['constraints'] or '待补充'}"
                f"\n验证计划：{context_values['validation_plan'] or '待补充'}"
                f"\n检索关注点：{plan['retrieval_focus']}"
            )
            evidence_ids = [row["chunk_id"] for row in candidates]
            versioned_review = getattr(self.gateway, "review_advice_for_version", None)
            advice = (
                versioned_review(advice_summary, evidence_ids, version=selected_version)
                if callable(versioned_review)
                else self.gateway.review_advice(advice_summary, evidence_ids)
            )
        except Exception:
            # Model assistance is optional; the underlying RAG candidates remain visible.
            advice = {"status": "GENERATION_PROVIDER_UNAVAILABLE", "answer": "N/A", "sources": []}
        allowed = {row["chunk_id"]: row for row in candidates}
        advice, grounded_impacts = _normalize_review_advice(advice, allowed)
        retrieval_trace["model_status"] = advice.get("status", "UNKNOWN")
        model_gap_details = _model_evidence_gap_details(advice)
        evidence_gap_details.extend(model_gap_details)
        evidence_gaps.extend(row["message"] for row in model_gap_details)

        return {
            "task_id": task_id,
            "request_fingerprint": fingerprint,
            "request_mode": "natural_language",
            "request_summary": summary,
            "request_plan": plan,
            "request_context": request_context,
            "retrieval_policy": retrieval_policy,
            "retrieval_trace": retrieval_trace,
            "retrieved_results": candidates,
            "impacts": grounded_impacts,
            "review_advice": advice,
            "evidence_gaps": evidence_gaps,
            "evidence_gap_details": evidence_gap_details,
            "sandbox_only": True,
            "public_baseline_written": False,
        }

    def analyze(self, selected: dict, proposed_text: str) -> dict:
        workspace = self.gateway.workspace()
        current_version = workspace["current_version"]
        repository = str(workspace.get("repository") or "")
        if selected.get("version") != current_version:
            raise ValueError("只能选择当前知识空间固定版本的官方资料")
        source_url = urlsplit(str(selected.get("source_url") or ""))
        expected_prefix = "/" + repository.strip("/") + "/"
        if (
            not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repository)
            or source_url.scheme != "https" or source_url.netloc != "github.com"
            or not source_url.path.startswith(expected_prefix)
        ):
            raise ValueError("资料来源与当前知识空间的官方仓库不匹配")
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
        task_id = uuid.uuid4().hex
        fingerprint = _normalized_hash(
            f"exact:{current_version}:{selected['chunk_id']}:{old_item['content_hash']}:{new_item['content_hash']}"
        )[:20]
        related_query = (selected["heading"] + " " + proposed)[:1000]
        retrieved = self.gateway.search(
            related_query,
            version=current_version, language="all", top_k=12,
        )["results"]
        related = [
            row for row in retrieved
            if row["chunk_id"] != selected["chunk_id"]
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
            review_advice, _grounded_impacts = _normalize_review_advice(review_advice, by_id)
        model_candidates = {
            row["evidence"]["chunk_id"]: row
            for row in _grounded_impacts
        } if related else {}
        retrieval_trace = {
            "queries": [{
                "query": related_query,
                "status": "candidate_found" if related else "no_retrieval_match",
                "top_chunk_ids": [row["chunk_id"] for row in related],
                "selected_chunk_ids": [row["chunk_id"] for row in related],
            }],
            "uncovered_queries": [] if related else [related_query],
            "model_status": review_advice.get("status", "NOT_CALLED") if related else "NOT_CALLED",
        }
        return {
            "task_id": task_id,
            "request_fingerprint": fingerprint,
            "retrieval_trace": retrieval_trace,
            "change": change,
            "selected_source": selected,
            "impacts": [{
                "status": row["review_status"],
                "relation": "suggested",
                "reason": model_candidates.get(row["impacted_item_id"], {}).get(
                    "reason", "RAG 检索到主题相关候选；模型未将其列为优先核对项，仍需人工确认。"
                ),
                "suggested_action": model_candidates.get(row["impacted_item_id"], {}).get(
                    "suggested_action", "人工确认该资料是否涉及本次变更。"
                ),
                "evidence": by_id[row["impacted_item_id"]],
            } for row in impacts],
            "confirmed_relations": [document_reference] if document_reference else [],
            "patch_candidate": {
                "target_chunk_id": selected["chunk_id"],
                "before": selected["content"], "proposed_after": proposed,
                "status": "REQUIRES_HUMAN_REVIEW",
            },
            "review_advice": review_advice,
            "evidence_gaps": (
                ([] if related else ["当前版本未检索到其他需要核对的资料。"])
                + _model_evidence_gaps(review_advice)
            ),
            "evidence_gap_details": (
                ([] if related else [{
                    "gap_type": "NO_RELATED_MATERIAL",
                    "message": "当前版本未检索到其他需要核对的资料。",
                    "query": related_query,
                    "expected_materials": "当前版本相关官方资料",
                    "suggested_action": "请人工确认是否需要扩大检索范围或补充资料。",
                    "requires_human_review": True,
                }])
                + _model_evidence_gap_details(review_advice)
            ),
            "sandbox_only": True,
            "public_baseline_written": False,
        }
