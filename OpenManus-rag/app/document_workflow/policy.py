"""Business-layer allowlist for document drafting."""

from __future__ import annotations

from app.reliability.policy import (
    CapabilityId, PolicyContext, PolicyEvaluationPoint, TaskPolicy, TaskPolicyProfile,
)
from app.reliability.retry import SideEffectLevel


DOCUMENT_WORKFLOW_PROFILE = TaskPolicyProfile(
    profile_id="document_workflow_v2",
    allowed_tools=frozenset({
        CapabilityId.RAG_QUERY, CapabilityId.TEMPLATE_READ, CapabilityId.DRAFT_WRITE,
    }),
    denied_tools=frozenset({
        CapabilityId.WEB_SEARCH, CapabilityId.BROWSER_ACQUIRE,
        CapabilityId.PYTHON_EXECUTE, CapabilityId.EXTERNAL_PUBLISH,
        CapabilityId.APPROVE_CANDIDATE, CapabilityId.FAISS_WRITE,
        CapabilityId.RAG_INGESTION,
    }),
    network_access=True,
    allowed_side_effect_levels=frozenset({
        SideEffectLevel.READ_ONLY, SideEffectLevel.IDEMPOTENT_WRITE,
    }),
    allow_external_writes=False,
)


def require_capability(tool_name: CapabilityId, *, network: bool = False,
                       write: bool = False, target_domain: str | None = None) -> None:
    decision = TaskPolicy(DOCUMENT_WORKFLOW_PROFILE).evaluate(PolicyContext(
        workflow="document_workflow", evaluation_point=PolicyEvaluationPoint.PRE_OPERATION,
        operation=tool_name.value, tool_name=tool_name.value,
        side_effect_level=(SideEffectLevel.IDEMPOTENT_WRITE if write else SideEffectLevel.READ_ONLY),
        network_required=network, external_write=False, target_domain=target_domain,
    ))
    if not decision.allowed:
        raise PermissionError(f"document workflow policy denied {tool_name.value}: {decision.reason_code.value}")
