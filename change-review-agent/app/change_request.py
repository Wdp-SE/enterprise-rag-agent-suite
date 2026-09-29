"""Deterministic change-request context and bounded query planning.

The rules here make requests easier to inspect and evaluate. They do not replace
RAG or claim to understand every engineering phrase; unknown requests stay in the
general category and retain the user's original wording.
"""

from __future__ import annotations

import re
from typing import Any


CHANGE_TYPES: dict[str, dict[str, Any]] = {
    "parameter_config": {
        "label": "参数 / 配置变更",
        "keywords": ("参数", "配置", "并发", "容量", "超时", "重试", "阈值", "parameter", "config", "timeout", "concurrency"),
        "focus": "参数定义、默认值、配置示例与兼容性",
        "materials": "参数说明、配置参考、版本说明",
        "action": "核对参数定义、默认值、配置示例及版本差异；未命中的资料类型需人工补查。",
    },
    "interface_compatibility": {
        "label": "接口 / 兼容性变更",
        "keywords": ("接口", "api", "协议", "字段", "请求", "响应", "兼容", "schema", "endpoint"),
        "focus": "API 契约、字段、调用方与兼容性",
        "materials": "API 文档、兼容性或升级说明",
        "action": "核对接口契约、上下游调用方、兼容性说明与示例；未命中的资料类型需人工补查。",
    },
    "workflow_behavior": {
        "label": "工作流 / 行为变更",
        "keywords": ("工作流", "调度", "任务", "节点", "dag", "依赖", "恢复", "触发", "workflow", "task", "schedule"),
        "focus": "工作流执行、节点状态、依赖与恢复行为",
        "materials": "用户指南、运行行为说明、升级说明",
        "action": "核对执行行为、节点依赖、失败恢复与操作说明；未命中的资料类型需人工补查。",
    },
    "data_storage": {
        "label": "数据 / 存储变更",
        "keywords": ("数据", "存储", "数据库", "表结构", "迁移", "schema", "database", "storage"),
        "focus": "数据模型、持久化与迁移兼容性",
        "materials": "数据模型、部署配置、迁移或升级说明",
        "action": "核对数据结构、持久化行为、迁移步骤与回滚影响；未命中的资料类型需人工补查。",
    },
    "security_permission": {
        "label": "安全 / 权限变更",
        "keywords": ("安全", "权限", "鉴权", "认证", "授权", "密级", "加密", "security", "permission", "auth"),
        "focus": "身份认证、授权边界与安全配置",
        "materials": "安全指南、权限说明、配置参考",
        "action": "核对身份认证、授权边界、安全配置及受影响角色；未命中的资料类型需人工补查。",
    },
    "general": {
        "label": "其他 / 待识别",
        "keywords": (),
        "focus": "按原始变更描述进行版本化检索",
        "materials": "当前版本相关官方资料",
        "action": "当前规则无法归类变更；请人工确认检索范围和需要补查的资料类型。",
    },
}

AUTO_CHANGE_TYPE = "auto"


def classify_change_type(text: str) -> str:
    normalized = text.casefold()
    ranked = [
        (sum(keyword.casefold() in normalized for keyword in data["keywords"]), key)
        for key, data in CHANGE_TYPES.items()
        if key != "general"
    ]
    matches = [(score, key) for score, key in ranked if score]
    return max(matches, default=(0, "general"))[1]


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
) -> dict[str, Any]:
    """Split a request into a stable, bounded set of searchable questions."""
    resolved_type, classification_source = resolve_change_type(summary, change_type)
    clauses = [part.strip() for part in re.split(r"[。！？；;\n]+", summary) if part.strip()]
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
        "query_limit": 4,
        "queries": [
            {
                "query": query,
                "kind": "full_request" if index == 0 else "change_clause",
                "change_type": (
                    classify_change_type(query)
                    if classify_change_type(query) != "general" else resolved_type
                ),
            }
            for index, query in enumerate(queries)
        ],
    }


def request_queries(summary: str) -> list[str]:
    """Backward-compatible helper used by callers that only need query text."""
    return [row["query"] for row in build_request_plan(summary)["queries"]]
