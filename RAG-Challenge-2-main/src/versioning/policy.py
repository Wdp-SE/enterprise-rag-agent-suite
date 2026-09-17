"""Apply an already-resolved deterministic version action to one candidate."""

from __future__ import annotations

from typing import Dict

from src.versioning.models import VersionResolutionPlan


def apply_version_policy(candidate: Dict, plan: VersionResolutionPlan) -> Dict:
    decision = plan.decision_for(candidate["document_id"])
    if decision is None:
        adjustment = 0.0
        action = "ALLOW"
    else:
        adjustment = decision.adjustment
        action = decision.action.value

    original_score = float(candidate["distance"])
    result = dict(candidate)
    result.update(
        {
            "original_score": original_score,
            "version_action": action,
            "version_adjustment": adjustment,
            "final_pre_rerank_score": round(original_score + adjustment, 4),
        }
    )
    if decision is not None:
        if decision.version_family is not None:
            result.setdefault("version_family", decision.version_family)
        if decision.version is not None:
            result.setdefault("version", decision.version)
        if decision.document_status is not None:
            result.setdefault("status", decision.document_status)
    return result
