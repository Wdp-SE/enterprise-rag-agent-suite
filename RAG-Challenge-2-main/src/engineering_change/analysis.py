"""Deterministic item diff, exact retrieval, trace expansion and impact discovery."""

from __future__ import annotations

import hashlib
import json
from enum import Enum
from typing import Any, Sequence

from pydantic import BaseModel, ConfigDict, Field, model_validator

from .models import EngineeringItem, normalize_text


class ChangeType(str, Enum):
    ADDED = "ADDED"
    MODIFIED = "MODIFIED"
    REMOVED = "REMOVED"
    UNCHANGED = "UNCHANGED"


class DiscoverySource(str, Enum):
    EXACT_IDENTIFIER = "EXACT_IDENTIFIER"
    EXPLICIT_TRACE = "EXPLICIT_TRACE"
    RETRIEVAL_SUGGESTION = "RETRIEVAL_SUGGESTION"


class TraceProvenance(str, Enum):
    EXPLICIT = "EXPLICIT"
    SEMANTIC = "SEMANTIC"


class TraceStatus(str, Enum):
    CONFIRMED = "CONFIRMED"
    SUGGESTED = "SUGGESTED"
    REJECTED = "REJECTED"


class EngineeringItemChange(BaseModel):
    model_config = ConfigDict(extra="forbid")

    external_identifier: str
    change_type: ChangeType
    old_item_id: str | None = None
    new_item_id: str | None = None
    old_content: str | None = None
    new_content: str | None = None
    old_version_id: str | None = None
    new_version_id: str | None = None
    old_content_hash: str | None = None
    new_content_hash: str | None = None


def _by_identifier(items: Sequence[EngineeringItem]) -> dict[str, EngineeringItem]:
    result: dict[str, EngineeringItem] = {}
    for item in items:
        key = item.external_identifier.casefold()
        if key in result:
            raise ValueError(f"duplicate EngineeringItem external_identifier: {item.external_identifier}")
        result[key] = item
    return result


def compare_engineering_items(
    old_items: Sequence[EngineeringItem], new_items: Sequence[EngineeringItem]
) -> list[EngineeringItemChange]:
    old = _by_identifier(old_items)
    new = _by_identifier(new_items)
    changes: list[EngineeringItemChange] = []
    for key in sorted(set(old) | set(new)):
        before = old.get(key)
        after = new.get(key)
        if before is None:
            change_type = ChangeType.ADDED
        elif after is None:
            change_type = ChangeType.REMOVED
        elif before.content_hash == after.content_hash:
            change_type = ChangeType.UNCHANGED
        else:
            change_type = ChangeType.MODIFIED
        representative = after or before
        assert representative is not None
        changes.append(EngineeringItemChange(
            external_identifier=representative.external_identifier,
            change_type=change_type,
            old_item_id=before.item_id if before else None,
            new_item_id=after.item_id if after else None,
            old_content=before.content if before else None,
            new_content=after.content if after else None,
            old_version_id=before.version_id if before else None,
            new_version_id=after.version_id if after else None,
            old_content_hash=before.content_hash if before else None,
            new_content_hash=after.content_hash if after else None,
        ))
    return changes


class TraceLink(BaseModel):
    model_config = ConfigDict(extra="forbid")

    trace_link_id: str
    source_item_id: str
    target_item_id: str
    provenance: TraceProvenance
    status: TraceStatus
    metadata: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def preserve_suggestion_boundary(self) -> "TraceLink":
        if self.source_item_id == self.target_item_id:
            raise ValueError("TraceLink cannot target itself")
        if self.provenance is TraceProvenance.SEMANTIC and self.status is TraceStatus.CONFIRMED:
            raise ValueError("semantic discovery cannot be created as a confirmed fact")
        return self

    @classmethod
    def create(
        cls,
        *,
        source_item_id: str,
        target_item_id: str,
        provenance: TraceProvenance,
        status: TraceStatus,
        metadata: dict[str, Any] | None = None,
    ) -> "TraceLink":
        canonical = json.dumps({
            "source_item_id": source_item_id,
            "target_item_id": target_item_id,
            "provenance": provenance.value,
        }, sort_keys=True, separators=(",", ":"))
        return cls(
            trace_link_id=f"trace_{hashlib.sha256(canonical.encode()).hexdigest()[:20]}",
            source_item_id=source_item_id,
            target_item_id=target_item_id,
            provenance=provenance,
            status=status,
            metadata=metadata or {},
        )


class EngineeringRetrievalScope(BaseModel):
    model_config = ConfigDict(extra="forbid")

    organization_ids: list[str] = Field(default_factory=list)
    project_ids: list[str] = Field(default_factory=list)
    document_ids: list[str] = Field(default_factory=list)
    version_ids: list[str] = Field(default_factory=list)

    def matches(self, item: EngineeringItem) -> bool:
        return (
            (not self.organization_ids or item.organization_id in self.organization_ids)
            and (not self.project_ids or item.project_id in self.project_ids)
            and (not self.document_ids or item.document_id in self.document_ids)
            and (not self.version_ids or item.version_id in self.version_ids)
        )


class EngineeringRetrievalHit(BaseModel):
    model_config = ConfigDict(extra="forbid")

    item: EngineeringItem
    discovery_source: DiscoverySource
    rank: int = Field(ge=1)


class EngineeringItemRetriever:
    """Scope first, exact identifier second, existing Dense results third."""

    def retrieve(
        self,
        query: str,
        items: Sequence[EngineeringItem],
        scope: EngineeringRetrievalScope,
        *,
        dense_item_ids: Sequence[str] = (),
        top_k: int = 5,
    ) -> list[EngineeringRetrievalHit]:
        if not normalize_text(query) or top_k < 1:
            raise ValueError("query and top_k must be valid")
        scoped = [item for item in items if scope.matches(item)]
        scoped_by_id = {item.item_id: item for item in scoped}
        query_folded = normalize_text(query).casefold()
        ordered: list[tuple[EngineeringItem, DiscoverySource]] = []
        seen: set[str] = set()
        for item in scoped:
            if item.external_identifier.casefold() in query_folded:
                ordered.append((item, DiscoverySource.EXACT_IDENTIFIER))
                seen.add(item.item_id)
        for item_id in dense_item_ids:
            item = scoped_by_id.get(item_id)
            if item is not None and item.item_id not in seen:
                ordered.append((item, DiscoverySource.RETRIEVAL_SUGGESTION))
                seen.add(item.item_id)
        return [
            EngineeringRetrievalHit(item=item, discovery_source=source, rank=rank)
            for rank, (item, source) in enumerate(ordered[:top_k], start=1)
        ]


class ImpactDiscovery(BaseModel):
    model_config = ConfigDict(extra="forbid")

    changed_item_id: str
    impacted_item_id: str
    discovery_source: DiscoverySource
    evidence_ids: list[str] = Field(default_factory=list)
    trace_link_id: str | None = None
    review_status: TraceStatus


class EngineeringImpactService:
    def discover(
        self,
        *,
        changed_item_id: str,
        items: Sequence[EngineeringItem],
        trace_links: Sequence[TraceLink],
        dense_item_ids: Sequence[str] = (),
        evidence_by_item: dict[str, list[str]] | None = None,
    ) -> list[ImpactDiscovery]:
        item_ids = {item.item_id for item in items}
        if changed_item_id not in item_ids:
            raise ValueError("changed_item_id is unknown")
        evidence_by_item = evidence_by_item or {}
        impacts: list[ImpactDiscovery] = []
        seen: set[str] = set()
        for link in trace_links:
            if (
                link.source_item_id == changed_item_id
                and link.target_item_id in item_ids
                and link.provenance is TraceProvenance.EXPLICIT
                and link.status is TraceStatus.CONFIRMED
            ):
                raw_evidence = link.metadata.get("evidence_ids", [])
                evidence = [str(item) for item in raw_evidence] if isinstance(raw_evidence, list) else []
                if not evidence:
                    evidence = list(evidence_by_item.get(link.target_item_id, []))
                impacts.append(ImpactDiscovery(
                    changed_item_id=changed_item_id,
                    impacted_item_id=link.target_item_id,
                    discovery_source=DiscoverySource.EXPLICIT_TRACE,
                    evidence_ids=evidence,
                    trace_link_id=link.trace_link_id,
                    review_status=TraceStatus.CONFIRMED,
                ))
                seen.add(link.target_item_id)
        for item_id in dense_item_ids:
            if item_id in item_ids and item_id != changed_item_id and item_id not in seen:
                impacts.append(ImpactDiscovery(
                    changed_item_id=changed_item_id,
                    impacted_item_id=item_id,
                    discovery_source=DiscoverySource.RETRIEVAL_SUGGESTION,
                    evidence_ids=list(evidence_by_item.get(item_id, [])),
                    review_status=TraceStatus.SUGGESTED,
                ))
                seen.add(item_id)
        return impacts

