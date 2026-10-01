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


def _scope_versions(workspace: dict, selected_version: str) -> set[str]:
    scopes = workspace.get("version_scopes")
    definition = scopes.get(selected_version) if isinstance(scopes, dict) else None
    members = definition.get("versions") if isinstance(definition, dict) else None
    if isinstance(members, list) and members and all(isinstance(item, str) for item in members):
        return set(members)
    return {selected_version}


def _workspace_repositories(workspace: dict) -> set[str]:
    values = workspace.get("repositories")
    if isinstance(values, list):
        repositories = {
            value.strip() for value in values
            if isinstance(value, str) and re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", value.strip())
        }
    else:
        repositories = set()
    repository = workspace.get("repository")
    if isinstance(repository, str) and re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repository):
        repositories.add(repository)
    return repositories


def _official_hit(
    row: dict, current_version: str, repository: str | set[str], *, allowed_versions: set[str] | None = None,
) -> bool:
    score = row.get("retrieval_score")
    parsed = urlsplit(str(row.get("source_url", "")))
    repositories = {repository} if isinstance(repository, str) else set(repository)
    row_repository = row.get("repository")
    if isinstance(row_repository, str) and row_repository.strip():
        matched_repository = row_repository.strip()
    elif len(repositories) == 1:
        matched_repository = next(iter(repositories))
    else:
        matched_repository = ""
    repository_path = "/" + matched_repository.strip("/") + "/"
    commit = row.get("commit")
    pinned_blob = (
        not commit
        or isinstance(commit, str) and re.fullmatch(r"[0-9a-f]{40}", commit)
        and parsed.path.startswith(repository_path + "blob/" + commit + "/")
    )
    return (
        row.get("version") in (allowed_versions or {current_version})
        and matched_repository in repositories
        and bool(re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", matched_repository))
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
        "no_retrieval_match": ("NO_REQUIRED_SOURCE", "NO_MATCH", "当前版本未检索到匹配资料"),
        "candidate_outside_evidence_budget": (
            "NO_REQUIRED_SOURCE", "EVIDENCE_BUDGET", "检索命中未纳入本次模型证据上限",
        ),
        "search_unavailable": ("RETRIEVAL_FAILED", "SEARCH_UNAVAILABLE", "检索服务未完成"),
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
        gap_type, legacy_gap_code, label = definition
        suggested_query = trace["query"]
        details.append({
            "gap_type": gap_type,
            "legacy_gap_code": legacy_gap_code,
            "message": f"{label}：{trace['query']}",
            "description": f"{label}：{trace['query']}",
            "query": trace["query"],
            "suggested_query": suggested_query,
            "missing_source_type": material,
            "expected_version": (plan or {}).get("target_version"),
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


def _model_evidence_gap_details(advice: dict, *, expected_version: str | None = None) -> list[dict]:
    review = advice.get("review")
    if not isinstance(review, dict):
        return []
    details = []
    for gap in _model_evidence_gaps(advice):
        details.append({
            "gap_type": "NO_REQUIRED_SOURCE",
            "message": gap,
            "description": gap,
            "query": None,
            "suggested_query": None,
            "missing_source_type": None,
            "expected_version": expected_version,
            "expected_materials": None,
            "suggested_action": "模型提示尚未核验；请审核人根据原文确认是否确实缺少该资料。",
            "requires_human_review": True,
        })
    for ambiguity in review.get("version_ambiguities", []) or []:
        if not isinstance(ambiguity, str) or not ambiguity.strip():
            continue
        details.append({
            "gap_type": "VERSION_AMBIGUITY",
            "message": ambiguity.strip(),
            "description": ambiguity.strip(),
            "query": None,
            "suggested_query": None,
            "missing_source_type": "版本依据或版本间差异",
            "expected_version": expected_version,
            "expected_materials": "适用版本的官方资料及必要的历史版本",
            "suggested_action": "请人工逐版本对照原文，确认当前适用版本及差异原因。",
            "requires_human_review": True,
        })
    return details


def _unverified_translation_gap_details(
    sources: list[dict], *, expected_version: str | None = None,
) -> list[dict]:
    """Surface unverified bilingual relationships without inferring translation drift."""
    details = []
    seen: set[tuple[str, str]] = set()
    for source in sources:
        source_id = str(source.get("document_id") or "")
        source_relations = source.get("document_relationships", []) or []
        translation_relations = [
            relation for relation in source_relations
            if isinstance(relation, dict)
            if relation.get("relation_type") == "translation_of"
            and relation.get("verification_status") in {"candidate", "unknown"}
        ]
        # Community translations are useful searchable material, but their
        # existence alone does not prove page-by-page or paragraph alignment.
        if source.get("source_type") == "community_translation" and not translation_relations:
            translation_relations = [{
                "relation_type": "translation_of", "verification_status": "unknown",
            }]
        for relation in translation_relations:
            left = str(relation.get("source_document_id") or "")
            right = str(relation.get("target_document_id") or "")
            counterpart = right if source_id == left else left if source_id == right else right or left
            pair = tuple(sorted((source_id, counterpart or "unknown-counterpart")))
            if pair in seen:
                continue
            seen.add(pair)
            heading = source.get("heading") or source.get("document_key") or source_id
            if counterpart:
                description = (
                    f"{heading} 的中英文对应关系待核验；当前只能提示可能存在对应页面，"
                    "不能据此判定翻译漂移或内容不一致。"
                )
                suggested_query = f"核验对应语种资料：{counterpart}"
            else:
                description = (
                    f"{heading} 来自社区中文译本，尚无经人工核实的英文对应关系；"
                    "不能据此判定内容同步或漂移。"
                )
                suggested_query = f"按主题检索对应英文官方资料：{heading}"
            details.append({
                "gap_type": "UNVERIFIED_TRANSLATION",
                "message": description,
                "description": description,
                "query": None,
                "suggested_query": suggested_query,
                "missing_source_type": "经人工确认的中英文对应关系",
                "expected_version": source.get("version") or expected_version,
                "expected_materials": "对应语种的同范围官方资料",
                "suggested_action": "先人工确认两份资料确为同一内容范围，再检查版本和更新时间；未确认前不标记为同步遗漏。",
                "requires_human_review": True,
            })
    return details


def _invalid_citation_gap_details(count: int, *, expected_version: str | None = None) -> list[dict]:
    if not count:
        return []
    description = f"模型建议中有 {count} 项引用未出现在本次检索证据中，已移除这些候选。"
    return [{
        "gap_type": "INVALID_CITATION",
        "message": description,
        "description": description,
        "query": None,
        "suggested_query": None,
        "missing_source_type": "本次检索证据中的有效引用 ID",
        "expected_version": expected_version,
        "expected_materials": None,
        "suggested_action": "只审核仍绑定本次检索证据的候选；如需补充依据，请重新检索并核对原文。",
        "requires_human_review": True,
    }]


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


def _normalize_review_advice(
    advice: dict, allowed_sources: dict[str, dict], *, expected_version: str | None = None,
) -> tuple[dict, list[dict], list[dict]]:
    """Keep only structured model suggestions tied to this request's RAG evidence."""
    review = advice.get("review")
    if (
        advice.get("status") == "ABSTAINED"
        and isinstance(review, dict)
        and review.get("review_status") == "REQUIRES_HUMAN_REVIEW"
        and review.get("impact_candidates") == []
    ):
        return {**advice, "answer": "N/A", "sources": [], "review": review}, [], []
    if advice.get("status") != "OK":
        return {**advice, "sources": [], "review": None}, [], []
    candidates = review.get("impact_candidates") if isinstance(review, dict) else None
    if (
        not isinstance(candidates, list)
        or review.get("review_status") != "REQUIRES_HUMAN_REVIEW"
        or not candidates
    ):
        return {
            **advice, "status": "ABSTAINED", "answer": "N/A",
            "sources": [], "review": None,
        }, [], []

    impacts = []
    sources = []
    valid_candidates = []
    seen = set()
    invalid_citation_count = 0
    for candidate in candidates:
        if not isinstance(candidate, dict):
            invalid_citation_count += 1
            continue
        chunk_id = candidate.get("evidence_chunk_id")
        reason = candidate.get("reason")
        action = candidate.get("suggested_action")
        if (
            not isinstance(chunk_id, str) or chunk_id not in allowed_sources
            or not isinstance(reason, str) or not reason.strip()
            or not isinstance(action, str) or not action.strip()
        ):
            invalid_citation_count += 1
            continue
        if chunk_id in seen:
            continue
        seen.add(chunk_id)
        source = allowed_sources[chunk_id]
        sources.append(source)
        valid_candidates.append(candidate)
        impacts.append({
            "status": "SUGGESTED", "relation": "suggested", "reason": reason,
            "suggested_action": action, "evidence": source,
        })
    validation_gaps = _invalid_citation_gap_details(
        invalid_citation_count, expected_version=expected_version,
    )
    if not valid_candidates:
        safe_review = dict(review) if isinstance(review, dict) else {}
        safe_review["impact_candidates"] = []
        safe_review.pop("change_interpretation", None)
        return {
            **advice, "status": "ABSTAINED", "answer": "N/A", "sources": [], "review": safe_review,
        }, [], validation_gaps
    safe_review = dict(review)
    safe_review["impact_candidates"] = valid_candidates
    if invalid_citation_count:
        # Do not present a free-form summary that may have relied on a rejected citation.
        safe_review.pop("change_interpretation", None)
        advice = {**advice, "answer": "N/A"}
    return {**advice, "sources": sources, "review": safe_review}, impacts, validation_gaps


def _generation_stage_status(advice_status: str) -> str:
    if advice_status == "OK":
        return "OK"
    if advice_status in {"ABSTAINED", "NO_EVIDENCE"}:
        return "EMPTY"
    if advice_status == "OUT_OF_SCOPE":
        return "OUT_OF_SCOPE"
    if advice_status in {"NOT_CALLED", "NOT_CALLED_OUT_OF_SCOPE"}:
        return "SKIPPED"
    return "FAILED"


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
                "description": explanation,
                "query": summary,
                "suggested_query": None,
                "missing_source_type": "经授权并脱敏的企业内部资料",
                "expected_version": None,
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
                "stage_status": {
                    "planning": "OK", "retrieval": "OUT_OF_SCOPE", "generation": "OUT_OF_SCOPE",
                },
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
        repositories = _workspace_repositories(workspace)
        available_versions = [
            str(value) for value in workspace.get("available_versions", [current_version])
        ]
        selected_version = current_version if not target_version or target_version == "current" else target_version
        if selected_version not in available_versions:
            raise ValueError("目标版本不在当前知识空间的已收录版本中")
        allowed_versions = _scope_versions(workspace, selected_version)
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
                    if _official_hit(
                        row, selected_version, repositories, allowed_versions=allowed_versions,
                    )
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
                "stage_status": {
                    "planning": "OK",
                "retrieval": "FAILED" if any(
                    trace["status"] == "search_unavailable" for trace, _rows in searches
                ) else "EMPTY",
                    "generation": "SKIPPED",
                },
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
                f"知识空间：{workspace.get('workspace', next(iter(repositories), '公开知识空间'))}\n目标版本：{selected_version}"
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
        advice, grounded_impacts, validation_gap_details = _normalize_review_advice(
            advice, allowed, expected_version=selected_version,
        )
        retrieval_trace["model_status"] = advice.get("status", "UNKNOWN")
        model_gap_details = _model_evidence_gap_details(advice, expected_version=selected_version)
        translation_gap_details = _unverified_translation_gap_details(
            candidates, expected_version=selected_version,
        )
        evidence_gap_details.extend(model_gap_details)
        evidence_gap_details.extend(translation_gap_details)
        evidence_gap_details.extend(validation_gap_details)
        evidence_gaps.extend(row["message"] for row in [*model_gap_details, *translation_gap_details, *validation_gap_details])

        return {
            "task_id": task_id,
            "request_fingerprint": fingerprint,
            "request_mode": "natural_language",
            "request_summary": summary,
            "request_plan": plan,
            "request_context": request_context,
            "stage_status": {
                "planning": "OK",
                "retrieval": "FAILED" if any(
                    trace["status"] == "search_unavailable" for trace, _rows in searches
                ) else "OK",
                "generation": _generation_stage_status(str(advice.get("status", "UNKNOWN"))),
            },
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
        repositories = _workspace_repositories(workspace)
        allowed_versions = _scope_versions(workspace, current_version)
        if selected.get("version") not in allowed_versions:
            raise ValueError("只能选择当前知识空间最新已收录范围内的资料")
        source_url = urlsplit(str(selected.get("source_url") or ""))
        selected_repository = str(selected.get("repository") or "")
        expected_prefix = "/" + selected_repository.strip("/") + "/"
        if (
            selected_repository not in repositories
            or not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", selected_repository)
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
        retrieval_failed = False
        try:
            retrieved = self.gateway.search(
                related_query,
                version=current_version, language="all", top_k=12,
            )["results"]
        except Exception:
            retrieved = []
            retrieval_failed = True
        related = [
            row for row in retrieved
            if row["chunk_id"] != selected["chunk_id"]
            and _official_hit(
                row, current_version, repositories, allowed_versions=allowed_versions,
            )
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
            review_advice, _grounded_impacts, invalid_citation_gaps = _normalize_review_advice(
                review_advice, by_id, expected_version=current_version,
            )
        else:
            invalid_citation_gaps = []
        model_candidates = {
            row["evidence"]["chunk_id"]: row
            for row in _grounded_impacts
        } if related else {}
        retrieval_trace = {
            "queries": [{
                "query": related_query,
                "status": (
                    "search_unavailable" if retrieval_failed else
                    "candidate_found" if related else "no_retrieval_match"
                ),
                "top_chunk_ids": [row["chunk_id"] for row in related],
                "selected_chunk_ids": [row["chunk_id"] for row in related],
            }],
            "uncovered_queries": [] if related else [related_query],
            "model_status": review_advice.get("status", "NOT_CALLED") if related else "NOT_CALLED",
        }
        model_gap_details = _model_evidence_gap_details(
            review_advice, expected_version=current_version,
        )
        translation_gap_details = _unverified_translation_gap_details(
            related, expected_version=current_version,
        )
        exact_retrieval_gap_details = [] if related else [{
            "gap_type": "RETRIEVAL_FAILED" if retrieval_failed else "NO_REQUIRED_SOURCE",
            "legacy_gap_code": "SEARCH_UNAVAILABLE" if retrieval_failed else "NO_RELATED_MATERIAL",
            "message": "关联资料检索服务未完成。" if retrieval_failed else "当前版本未检索到其他需要核对的资料。",
            "description": "关联资料检索服务未完成。" if retrieval_failed else "当前版本未检索到其他需要核对的资料。",
            "query": related_query,
            "suggested_query": related_query,
            "missing_source_type": "当前版本相关官方资料",
            "expected_version": current_version,
            "expected_materials": "当前版本相关官方资料",
            "suggested_action": (
                "请检查知识服务连接后重试；当前仅保留所选原文，不把未完成的检索当作无命中。"
                if retrieval_failed else "请人工确认是否需要扩大检索范围或补充资料。"
            ),
            "requires_human_review": True,
        }]
        all_gap_details = [
            *exact_retrieval_gap_details, *model_gap_details, *translation_gap_details,
            *invalid_citation_gaps,
        ]
        return {
            "task_id": task_id,
            "request_fingerprint": fingerprint,
            "stage_status": {
                "planning": "SKIPPED",
                "retrieval": "FAILED" if retrieval_failed else "OK" if related else "EMPTY",
                "generation": _generation_stage_status(
                    str(review_advice.get("status", "NOT_CALLED")) if related else "NOT_CALLED",
                ),
            },
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
            "evidence_gaps": [row["message"] for row in all_gap_details],
            "evidence_gap_details": all_gap_details,
            "sandbox_only": True,
            "public_baseline_written": False,
        }
