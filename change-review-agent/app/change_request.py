"""Deterministic change-request context and bounded query planning.

The rules here make requests easier to inspect and evaluate. They do not replace
RAG or claim to understand every engineering phrase; unknown requests stay in the
general category and retain the user's original wording.
"""

from __future__ import annotations

import re
from typing import Any

from app.domain_profile import categories_by_id


_CLAUSE_SPLIT = re.compile(
    r"[。！？?；;\n]+|[,，](?=\s*(?:同时|并且|并|然后|随后|接着|核对|检查|确认|验证|评估|also\b|and\b|then\b|check\b|verify\b|confirm\b|validate\b))",
    re.IGNORECASE,
)
_CLAUSE_PREFIX = re.compile(r"^(?:同时|并且|并|然后|随后|接着|also\s+|and\s+then\s+|and\s+|then\s+)", re.IGNORECASE)


CHANGE_TYPES: dict[str, dict[str, Any]] = {
    "parameter_config": {
        "label": "参数 / 配置变更",
        "keywords": ("参数", "配置", "并发", "容量", "超时", "重试", "阈值", "parameter", "config", "timeout", "concurrency"),
        "focus": "参数定义、默认值、配置示例与兼容性",
        "materials": "参数说明、配置参考、版本说明",
        "action": "核对参数定义、默认值、配置示例及版本差异；未命中的资料类型需人工补查。",
        "checklist": ["参数定义与默认值", "配置示例与适用范围", "兼容性与回归验证"],
    },
    "interface_compatibility": {
        "label": "接口 / 兼容性变更",
        "keywords": ("接口", "api", "协议", "字段", "请求", "响应", "兼容", "schema", "endpoint"),
        "focus": "API 契约、字段、调用方与兼容性",
        "materials": "API 文档、兼容性或升级说明",
        "action": "核对接口契约、上下游调用方、兼容性说明与示例；未命中的资料类型需人工补查。",
        "checklist": ["接口契约与字段", "上下游调用方", "兼容性与接口测试"],
    },
    "workflow_behavior": {
        "label": "工作流 / 行为变更",
        "keywords": ("工作流", "调度", "任务", "节点", "dag", "依赖", "恢复", "触发", "workflow", "task", "schedule"),
        "focus": "工作流执行、节点状态、依赖与恢复行为",
        "materials": "用户指南、运行行为说明、升级说明",
        "action": "核对执行行为、节点依赖、失败恢复与操作说明；未命中的资料类型需人工补查。",
        "checklist": ["状态转换与执行顺序", "依赖、重试与恢复", "操作说明与回归场景"],
    },
    "planning_behavior": {
        "label": "规划 / 轨迹行为变更",
        "keywords": (
            "规划", "路径", "轨迹", "障碍物", "避障", "可行驶区域", "驶出", "泊车",
            "planning", "planner", "trajectory", "obstacle", "collision", "drivable area",
            "pull-out", "pull out", "goal planner", "start planner", "path planning",
        ),
        "focus": "规划模块职责、轨迹生成与校验、障碍物处理和车辆行为边界",
        "materials": "规划模块设计说明、参数配置、轨迹验证与版本差异",
        "action": "核对相关规划模块、轨迹校验、参数配置及版本差异；未命中的验证资料需人工补查。",
        "checklist": ["模块职责与调用关系", "参数及输入输出边界", "场景验证与安全边界"],
    },
    "data_storage": {
        "label": "数据 / 存储变更",
        "keywords": ("数据", "存储", "数据库", "表结构", "迁移", "schema", "database", "storage"),
        "focus": "数据模型、持久化与迁移兼容性",
        "materials": "数据模型、部署配置、迁移或升级说明",
        "action": "核对数据结构、持久化行为、迁移步骤与回滚影响；未命中的资料类型需人工补查。",
        "checklist": ["数据模型与持久化行为", "迁移及回滚步骤", "兼容性与数据验证"],
    },
    "security_permission": {
        "label": "安全 / 权限变更",
        "keywords": ("安全", "权限", "鉴权", "认证", "授权", "密级", "加密", "security", "permission", "auth"),
        "focus": "身份认证、授权边界与安全配置",
        "materials": "安全指南、权限说明、配置参考",
        "action": "核对身份认证、授权边界、安全配置及受影响角色；未命中的资料类型需人工补查。",
        "checklist": ["身份认证与授权边界", "受影响角色与最小权限", "安全配置与审计验证"],
    },
    "general": {
        "label": "其他 / 待识别",
        "keywords": (),
        "focus": "按原始变更描述进行版本化检索",
        "materials": "当前版本相关官方资料",
        "action": "当前规则无法归类变更；请人工确认检索范围和需要补查的资料类型。",
        "checklist": ["变更对象与适用版本", "相关设计和配置资料", "验证方案及回滚影响"],
    },
}

AUTO_CHANGE_TYPE = "auto"

_CLASSIFICATION_RULES: dict[str, dict[str, tuple[str, ...]]] = {
    "parameter_config": {
        "strong": ("参数", "并发", "容量", "超时", "阈值", "parameter", "config", "timeout", "concurrency", "default value", "setvalue"),
        "context": ("变量", "默认值", "startup parameter", "global parameter"),
    },
    "interface_compatibility": {
        "strong": ("接口", "api", "协议", "请求", "响应", "兼容", "topic", "message type", "endpoint", "health-check", "health check"),
        "context": ("字段", "schema", "request", "response"),
    },
    "workflow_behavior": {
        "strong": ("调度", "依赖", "恢复", "触发", "失败", "重试", "dag", "schedule", "dependency", "retry", "workflow", "approval"),
        "context": ("工作流", "任务", "节点", "workflow", "task"),
    },
    "planning_behavior": {
        "strong": (
            "规划", "路径", "轨迹", "障碍物", "避障", "可行驶区域", "驶出", "泊车",
            "planning", "planner", "trajectory", "obstacle", "collision", "drivable area",
            "pull-out", "pull out", "goal planner", "start planner", "path planning",
            "路权", "intersection",
        ),
        "context": ("行为", "规划模块", "vehicle behavior", "planning module"),
    },
    "data_storage": {
        "strong": ("数据库", "存储", "迁移", "表结构", "持久化", "database", "storage", "migration", "data model"),
        "context": ("schema", "数据模型"),
    },
    "security_permission": {
        "strong": ("安全", "权限", "鉴权", "认证", "授权", "密级", "加密", "security", "permission", "auth", "authentication", "authorization", "oidc", "group-to-role", "role sync"),
        "context": ("角色", "访问控制", "access control"),
    },
}

_RETRIEVAL_ALIASES = (
    ("条件分支", "condition branch node"),
    ("任务依赖", "task dependency upstream task"),
    ("项目级参数", "project parameter"),
    ("全局参数", "global parameter"),
    ("启动参数", "startup parameter"),
    ("本地参数", "local parameter"),
    ("父子工作流", "parent child workflow SubWorkflow task"),
    ("子工作流", "SubWorkflow task parent child workflow"),
    ("工作流定义", "workflow definition"),
    ("DAG", "workflow definition task conditions"),
    ("健康检查", "health check healthcheck"),
    ("任务组", "task group"),
    ("missed_fire_policy", "misfireThreshold"),
)

_PRIVATE_ORG_CONTEXT = re.compile(
    r"(?:经纬恒润|本公司|公司|企业|组织|客户|本单位).{0,14}(?:内部|专属|私有|专有|自有)"
    r"|(?:内部|专属|私有|专有|自有).{0,10}(?:公司|企业|组织|客户|jira|工单|通讯录)",
    re.IGNORECASE,
)
_PRIVATE_DATA_SUBJECT = re.compile(
    r"(?:api|接口|jira|工单|审批|流程|制度|通讯录|手机号|授权名单|权限|密级|车辆|质量|配置|映射|数据)",
    re.IGNORECASE,
)
_PRIVATE_ORG_ENGLISH = re.compile(
    r"\b(?:internal|private|proprietary|company[- ]specific|organization[- ]specific)"
    r"\s+(?:company\s+)?(?:api|endpoint|ticket|workflow|policy|directory|phone|permission|data)\b"
    r"|\b(?:our\s+)?company(?:'s)?\s+jira\s+(?:access[- ]approval|approver|admin|reviewer)"
    r"\s+(?:audit\s+trail|list|directory)\b"
    r"|\b(?:our\s+)?internal\s+(?:company\s+)?jira\s+(?:approver|admin|reviewer)\s+(?:list|directory)\b",
    re.IGNORECASE,
)


def is_out_of_scope_public_request(text: str) -> bool:
    """Fail closed for explicitly private-company requests in the public-only demo."""
    normalized = re.sub(r"\s+", " ", text or "").strip()
    if not normalized:
        return False
    return bool(
        (_PRIVATE_ORG_CONTEXT.search(normalized) and _PRIVATE_DATA_SUBJECT.search(normalized))
        or _PRIVATE_ORG_ENGLISH.search(normalized)
    )


def _contains_term(text: str, term: str) -> bool:
    if re.fullmatch(r"[a-z0-9][a-z0-9 _-]*", term, flags=re.IGNORECASE):
        return re.search(
            rf"(?<![a-z0-9_]){re.escape(term.casefold())}(?![a-z0-9_])",
            text,
            flags=re.IGNORECASE,
        ) is not None
    return term.casefold() in text


def _expand_retrieval_query(query: str) -> str:
    aliases = list(dict.fromkeys(
        alias for source, alias in _RETRIEVAL_ALIASES
        if source.casefold() in query.casefold() and alias.casefold() not in query.casefold()
    ))
    return f"{query} {' '.join(aliases)}" if aliases else query


def _classify_change_type_clause(text: str) -> str:
    normalized = text.casefold()
    explicit_parameter_terms = (
        "参数", "parameter", "timeout", "concurrency", "并发", "容量", "阈值", "threshold",
        "setvalue", "重试参数",
    )
    if any(_contains_term(normalized, term) for term in explicit_parameter_terms):
        return "parameter_config"
    ranked = []
    for order, (key, terms) in enumerate(_CLASSIFICATION_RULES.items()):
        strong_hits = sum(_contains_term(normalized, term) for term in terms["strong"])
        if strong_hits == 0:
            continue
        context_hits = sum(_contains_term(normalized, term) for term in terms["context"])
        strong_weight = 4 if key in {"parameter_config", "security_permission"} else 3
        ranked.append((strong_hits * strong_weight + min(context_hits, 2), -order, key))
    return max(ranked, default=(0, 0, "general"))[2]


def classify_change_type(text: str) -> str:
    """Classify the primary change intent before its secondary audit checks.

    Requests often pair the actual change with checks to run (for example,
    changing trajectory validation and checking a numeric threshold). Letting
    every clause vote equally can incorrectly turn a planning change into a
    parameter change. Fall back to the complete request for audit-only prompts.
    """
    clauses = [
        part.strip()
        for part in _CLAUSE_SPLIT.split(text or "")
        if part.strip()
    ]
    if clauses:
        primary_type = _classify_change_type_clause(clauses[0])
        if primary_type != "general":
            return primary_type
    return _classify_change_type_clause(text or "")


def resolve_change_type(text: str, requested: str | None = None) -> tuple[str, str]:
    if requested and requested != AUTO_CHANGE_TYPE:
        if requested not in CHANGE_TYPES:
            raise ValueError("不支持的变更类型")
        return requested, "user_selected"
    inferred = classify_change_type(text)
    return inferred, "rule_inferred" if inferred != "general" else "unclassified"


def build_request_plan(
    summary: str,
    *,
    change_type: str | None = None,
    impact_scope: str | None = None,
    profile: dict[str, Any] | None = None,
    device_model: str | None = None,
    module_sku: str | None = None,
    carrier_board: str | None = None,
    software_baseline: str | None = None,
    target_snapshot: str = "current",
) -> dict[str, Any]:
    """Split a request into a stable, bounded set of searchable questions."""
    if profile is not None:
        return _build_profile_request_plan(
            summary,
            change_type=change_type,
            impact_scope=impact_scope,
            profile=profile,
            device_model=device_model,
            module_sku=module_sku,
            carrier_board=carrier_board,
            software_baseline=software_baseline,
            target_snapshot=target_snapshot,
        )
    resolved_type, classification_source = resolve_change_type(summary, change_type)
    clauses = []
    for part in _CLAUSE_SPLIT.split(summary):
        cleaned = _CLAUSE_PREFIX.sub("", part.strip()).strip(" ,，;；")
        if cleaned:
            clauses.append(cleaned)
    if len(clauses) > 3:
        clauses = [*clauses[:2], " ".join(clauses[2:])]
    category = CHANGE_TYPES[resolved_type]
    normalized_scope = (impact_scope or "").strip()
    if len(normalized_scope) > 160:
        raise ValueError("影响范围不超过 160 字")
    queries = list(dict.fromkeys([summary, *clauses])) if len(clauses) > 1 else [summary]
    if normalized_scope:
        contextual_query = f"{normalized_scope} {category['focus']} {summary}"
        queries[0] = contextual_query
    queries = list(dict.fromkeys(queries))[:4]
    return {
        "change_type": resolved_type,
        "change_type_label": category["label"],
        "classification_source": classification_source,
        "impact_scope": normalized_scope,
        "retrieval_focus": category["focus"],
        "expected_materials": category["materials"],
        "gap_action": category["action"],
        "checklist_items": list(category["checklist"]),
        "manual_review_required": resolved_type == "general",
        "planning_gap": category["action"] if resolved_type == "general" else None,
        "query_limit": 4,
        "queries": [
            {
                "query": query,
                # Preserve the original text for the trace, and add domain aliases
                # only to the tool call (including the full request query).
                "search_query": _expand_retrieval_query(query),
                "kind": "full_request" if index == 0 else "change_clause",
                "change_type": (
                    classify_change_type(query)
                    if classify_change_type(query) != "general" else resolved_type
                ),
            }
            for index, query in enumerate(queries)
        ],
    }


def _classify_profile_change_type(text: str, categories: list[dict[str, Any]]) -> str:
    normalized = (text or "").casefold()
    ranked: list[tuple[int, int, str]] = []
    for order, category in enumerate(categories):
        category_id = str(category["id"])
        if category_id == "general":
            continue
        hits = sum(_contains_term(normalized, term) for term in category.get("keywords", []))
        if hits:
            ranked.append((hits, -order, category_id))
    return max(ranked, default=(0, 0, "general"))[2]


def _build_profile_request_plan(
    summary: str,
    *,
    change_type: str | None,
    impact_scope: str | None,
    profile: dict[str, Any],
    device_model: str | None,
    module_sku: str | None,
    carrier_board: str | None,
    software_baseline: str | None,
    target_snapshot: str,
) -> dict[str, Any]:
    categories = categories_by_id(profile)
    normalized_scope = (impact_scope or "").strip()
    if len(normalized_scope) > 160:
        raise ValueError("影响范围不超过 160 字")
    if not isinstance(target_snapshot, str) or not target_snapshot.strip() or len(target_snapshot) > 128:
        raise ValueError("资料快照不能为空且不能超过 128 字")
    requested = (change_type or "auto").strip()
    if requested in {"", "auto"}:
        resolved_type = _classify_profile_change_type(summary, profile["change_types"])
        classification_source = "rule_inferred" if resolved_type != "general" else "unclassified"
    elif requested in categories:
        resolved_type = requested
        classification_source = "user_selected"
    else:
        raise ValueError("变更类型不在当前领域配置中")

    device_scope = {
        "device_model": (device_model or "").strip() or None,
        "module_sku": (module_sku or "").strip() or None,
        "carrier_board": (carrier_board or "").strip() or None,
        "software_baseline": (software_baseline or "").strip() or None,
    }
    declared_options = profile.get("scope_options", {})
    for field, value in device_scope.items():
        if value is None:
            continue
        if len(value) > 128:
            raise ValueError(f"{field} 不超过 128 字")
        allowed = declared_options.get(field)
        if isinstance(allowed, list) and value not in allowed:
            raise ValueError(f"{field} 不在当前知识空间的可选范围中")

    clauses = []
    for part in _CLAUSE_SPLIT.split(summary):
        cleaned = _CLAUSE_PREFIX.sub("", part.strip()).strip(" ,，;；")
        if cleaned:
            clauses.append(cleaned)
    if len(clauses) > 3:
        clauses = [*clauses[:2], " ".join(clauses[2:])]
    queries = list(dict.fromkeys([summary, *clauses])) if len(clauses) > 1 else [summary]
    category = categories[resolved_type]
    if normalized_scope:
        queries[0] = f"{normalized_scope} {category['focus']} {summary}"
    max_queries = int(profile["max_queries"])
    queries = list(dict.fromkeys(queries))[:max_queries]
    missing_scope = [field for field, value in device_scope.items() if value is None]
    scope_warnings = []
    if missing_scope:
        labels = {
            "device_model": "设备型号", "module_sku": "模组 SKU",
            "carrier_board": "载板", "software_baseline": "软件基线",
        }
        scope_warnings.append(
            "未指定" + "、".join(labels[field] for field in missing_scope)
            + "；检索结果只能作为候选线索，不能据此确认设备兼容或不受影响。"
        )
    query_terms = list(category.get("query_terms", []))
    return {
        "domain_profile_id": profile["id"],
        "original_request": summary,
        "change_type": resolved_type,
        "change_type_label": category["label"],
        "classification_source": classification_source,
        "impact_scope": normalized_scope,
        "retrieval_focus": category["focus"],
        "expected_materials": category["materials"],
        "gap_action": category["action"],
        "checklist_items": list(category["checklist"]),
        "manual_review_required": True,
        "planning_gap": category["action"] if resolved_type == "general" else None,
        "query_limit": max_queries,
        "target_snapshot": target_snapshot,
        "target_version": target_snapshot,
        "device_scope": device_scope,
        "scope_warnings": scope_warnings,
        "languages": list(profile["languages"]),
        "queries": [
            {
                "query": query,
                "search_query": " ".join([query, *query_terms]).strip(),
                "kind": "full_request" if index == 0 else "change_clause",
                "change_type": (
                    _classify_profile_change_type(query, profile["change_types"])
                    if _classify_profile_change_type(query, profile["change_types"]) != "general"
                    else resolved_type
                ),
            }
            for index, query in enumerate(queries)
        ],
    }


def request_queries(summary: str) -> list[str]:
    """Backward-compatible helper used by callers that only need query text."""
    return [row["query"] for row in build_request_plan(summary)["queries"]]
