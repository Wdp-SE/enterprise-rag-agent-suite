"""Small business allowlist for the final document workflow."""

from __future__ import annotations

from enum import Enum


class CapabilityId(str, Enum):
    RAG_QUERY = "RAG_QUERY"
    TEMPLATE_READ = "TEMPLATE_READ"
    DRAFT_WRITE = "DRAFT_WRITE"
    REVIEW_WRITE = "REVIEW_WRITE"
    FINALIZE = "FINALIZE"


ALLOWED_CAPABILITIES = frozenset(CapabilityId)


def require_capability(capability: CapabilityId, **_: object) -> None:
    if capability not in ALLOWED_CAPABILITIES:
        raise PermissionError(f"document workflow policy denied {capability.value}")
