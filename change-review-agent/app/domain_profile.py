"""Load and validate the small, auditable domain policy used by the review Agent."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def load_change_profile(path: Path) -> dict[str, Any]:
    """Load a domain profile and reject incomplete or ambiguous categories."""
    try:
        profile = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError("无法读取变更审查领域配置") from exc
    if not isinstance(profile, dict) or profile.get("schema_version") != 1:
        raise ValueError("不支持的变更审查领域配置版本")
    if not isinstance(profile.get("id"), str) or not profile["id"].strip():
        raise ValueError("领域配置必须声明 id")
    if profile.get("languages") != ["zh"]:
        raise ValueError("边缘 AI 设备领域配置仅支持中文语料")
    max_queries = profile.get("max_queries")
    evidence_budget = profile.get("evidence_budget")
    if not isinstance(max_queries, int) or not 1 <= max_queries <= 4:
        raise ValueError("变更审查检索问题数必须在 1 到 4 之间")
    if not isinstance(evidence_budget, int) or not 1 <= evidence_budget <= 20:
        raise ValueError("证据预算必须在 1 到 20 之间")
    categories = profile.get("change_types")
    if not isinstance(categories, list) or not categories:
        raise ValueError("领域配置必须包含变更分类")
    seen: set[str] = set()
    required = ("id", "label", "keywords", "focus", "materials", "action", "checklist", "query_terms")
    for category in categories:
        if not isinstance(category, dict) or any(key not in category for key in required):
            raise ValueError("变更分类缺少必要字段")
        key = category["id"]
        if not isinstance(key, str) or not key or key in seen:
            raise ValueError("变更分类 id 必须唯一")
        seen.add(key)
        for field in ("keywords", "checklist", "query_terms"):
            if not isinstance(category[field], list) or any(not isinstance(value, str) for value in category[field]):
                raise ValueError(f"变更分类 {field} 必须是字符串列表")
        if not category["checklist"] or len(category["checklist"]) > 5:
            raise ValueError("每种变更分类需要 1 到 5 个审核检查项")
    if "general" not in seen:
        raise ValueError("领域配置必须包含 general 兜底分类")
    return profile


def categories_by_id(profile: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {category["id"]: category for category in profile["change_types"]}
