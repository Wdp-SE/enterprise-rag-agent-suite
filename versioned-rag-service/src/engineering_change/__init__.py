"""Engineering change domain public surface."""

from .analysis import (
    ChangeType,
    DiscoverySource,
    EngineeringImpactService,
    EngineeringItemChange,
    EngineeringItemRetriever,
    EngineeringRetrievalHit,
    EngineeringRetrievalScope,
    ImpactDiscovery,
    TraceLink,
    TraceProvenance,
    TraceStatus,
    compare_engineering_items,
)
from .candidates import CandidateStatus, CandidateVersionRecord, CandidateVersionService
from .extraction import DocxEngineeringParser, EngineeringItemFactory, IdentifierExtractor
from .models import (
    EngineeringItem,
    EngineeringItemType,
    IdentifierMatch,
    OrganizationProfile,
    ParsedEngineeringSection,
    content_hash,
    normalize_text,
)

__all__ = [
    "CandidateStatus",
    "CandidateVersionRecord",
    "CandidateVersionService",
    "ChangeType",
    "DiscoverySource",
    "DocxEngineeringParser",
    "EngineeringImpactService",
    "EngineeringItem",
    "EngineeringItemChange",
    "EngineeringItemFactory",
    "EngineeringItemRetriever",
    "EngineeringItemType",
    "EngineeringRetrievalHit",
    "EngineeringRetrievalScope",
    "IdentifierExtractor",
    "IdentifierMatch",
    "ImpactDiscovery",
    "OrganizationProfile",
    "ParsedEngineeringSection",
    "TraceLink",
    "TraceProvenance",
    "TraceStatus",
    "compare_engineering_items",
    "content_hash",
    "normalize_text",
]
