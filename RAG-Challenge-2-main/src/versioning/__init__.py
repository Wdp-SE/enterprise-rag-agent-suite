"""Deterministic document-version governance for generic retrieval."""

from src.versioning.models import (
    DatePrecision,
    VersionAction,
    VersionContext,
    VersionDecision,
    VersionIntent,
    VersionMetadata,
    VersionResolutionPlan,
)
from src.versioning.policy import apply_version_policy
from src.versioning.query_intent import VersionIntentDetector
from src.versioning.resolver import VersionResolver

__all__ = [
    "DatePrecision",
    "VersionAction",
    "VersionContext",
    "VersionDecision",
    "VersionIntent",
    "VersionIntentDetector",
    "VersionMetadata",
    "VersionResolutionPlan",
    "VersionResolver",
    "apply_version_policy",
]
