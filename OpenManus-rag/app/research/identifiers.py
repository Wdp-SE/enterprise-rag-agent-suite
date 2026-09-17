"""Stable identities for Candidate Packages, documents, and source citations."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass

from app.research.models import Evidence, SourceLevel, normalize_text, sha256_text


SOURCE_LEVEL_ORDER = {
    SourceLevel.TIER1: 1,
    SourceLevel.TIER2: 2,
    SourceLevel.TIER3: 3,
}


def _domain_slug(domain: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", normalize_text(domain).casefold()).strip("-")
    return slug[:32] or "research"


def _identity_payload(
    *,
    domain: str,
    research_topic: str,
    category: str,
    evidence_list: list[Evidence],
) -> str:
    evidence_identities = sorted(
        ({
            "evidence_id": evidence.evidence_id,
            "content_hash": evidence.content_hash,
            "source_identity": evidence.canonical_source_identity(),
        } for evidence in evidence_list),
        key=lambda item: (
            item["evidence_id"] or "",
            item["content_hash"] or "",
            item["source_identity"],
        ),
    )
    payload = {
        "category": normalize_text(category).casefold(),
        "domain": normalize_text(domain).casefold(),
        "evidence": evidence_identities,
        "research_topic": normalize_text(research_topic),
    }
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def stable_candidate_id(
    *,
    domain: str,
    research_topic: str,
    category: str,
    evidence_list: list[Evidence],
) -> str:
    canonical = _identity_payload(
        domain=domain,
        research_topic=research_topic,
        category=category,
        evidence_list=evidence_list,
    )
    digest = sha256_text(f"candidate:{canonical}")[:16]
    return f"cand_{_domain_slug(domain)}_{digest}"


def stable_document_id(
    *,
    domain: str,
    research_topic: str,
    category: str,
    evidence_list: list[Evidence],
) -> str:
    canonical = _identity_payload(
        domain=domain,
        research_topic=research_topic,
        category=category,
        evidence_list=evidence_list,
    )
    digest = sha256_text(f"document:{canonical}")[:16]
    return f"doc_{_domain_slug(domain)}_{digest}"


@dataclass(frozen=True)
class SourceAssignment:
    source_id: str
    evidence: Evidence


def assign_source_ids(evidence_list: list[Evidence]) -> list[SourceAssignment]:
    """Assign Sxx after stable metadata sorting, independent of input order."""

    ordered = sorted(
        evidence_list,
        key=lambda evidence: (
            SOURCE_LEVEL_ORDER[evidence.source_level],
            evidence.organization.casefold(),
            evidence.canonical_source_identity(),
            evidence.content_hash or "",
            evidence.evidence_id or "",
        ),
    )
    return [
        SourceAssignment(source_id=f"S{index:02d}", evidence=evidence)
        for index, evidence in enumerate(ordered, start=1)
    ]
