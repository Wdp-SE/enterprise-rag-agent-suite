"""Bounded section context expansion shared by legacy and frozen runtimes."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Dict, List, Mapping, Sequence, Tuple

from src.document_metadata import normalize_document_metadata


def _metadata_from_document(document: Dict) -> Dict:
    metainfo = normalize_document_metadata(document.get("metainfo"))
    result = {
        "document_id": metainfo["document_id"],
        "document_title": metainfo["title"],
        "document_type": metainfo["document_type"],
        "source": metainfo["source"],
        "source_url": metainfo.get("source_url"),
        "category": metainfo.get("category"),
        "tags": metainfo.get("tags", []),
    }
    for field in (
        "document_number",
        "publish_date",
        "effective_date",
        "version_family",
        "version",
        "status",
    ):
        if metainfo.get(field) is not None:
            result[field] = metainfo[field]
    return result


def _normalise_chunk(chunk: Mapping, metadata: Mapping | None = None) -> Dict:
    result = dict(metadata or {})
    result.update(dict(chunk))
    page_number = result.get("page_number", result.get("page"))
    result["page"] = page_number
    result["page_number"] = page_number
    result.setdefault("parent_id", result.get("section_id"))
    return result


def _dedupe_key(result: Mapping) -> Tuple:
    chunk_id = result.get("chunk_id")
    if chunk_id:
        return ("chunk", chunk_id)
    return (
        "fallback",
        result.get("document_id"),
        result.get("page", result.get("page_number")),
        result.get("text"),
    )


class SectionContextExpander:
    """Expand hits into traceable child evidence under a strict token budget."""

    def __init__(
        self,
        documents_dirs: Sequence[Path],
        *,
        neighbor_children: int = 1,
        max_tokens: int = 1800,
    ):
        self.neighbor_children = neighbor_children
        self.max_tokens = max_tokens
        self.chunk_by_id: Dict[str, Dict] = {}
        self.section_children: Dict[str, List[Dict]] = {}
        for directory in documents_dirs:
            for path in sorted(Path(directory).glob("*.json")):
                document = json.loads(path.read_text(encoding="utf-8"))
                if not (isinstance(document, dict) and "content" in document):
                    continue
                metadata = _metadata_from_document(document)
                for index, chunk in enumerate(document["content"].get("chunks", [])):
                    item = _normalise_chunk(chunk, metadata)
                    item.setdefault("id", index)
                    item.setdefault("chunk_id", f"{metadata['document_id']}:{index}")
                    self._register(item)
        for children in self.section_children.values():
            children.sort(key=lambda item: int(item.get("id", 0)))

    @classmethod
    def from_chunks(
        cls,
        chunks: Sequence[Mapping],
        *,
        neighbor_children: int = 1,
        max_tokens: int = 1800,
    ) -> "SectionContextExpander":
        """Load an existing frozen chunk artifact without parsing or splitting."""

        instance = cls(
            [], neighbor_children=neighbor_children, max_tokens=max_tokens
        )
        for chunk in chunks:
            instance._register(dict(chunk))
        for children in instance.section_children.values():
            children.sort(key=lambda item: int(item.get("id", 0)))
        return instance

    def _register(self, item: Dict) -> None:
        chunk_id = item.get("chunk_id")
        if not chunk_id:
            raise ValueError("context expansion chunk is missing chunk_id")
        self.chunk_by_id[str(chunk_id)] = item
        if item.get("section_id"):
            self.section_children.setdefault(str(item["section_id"]), []).append(item)

    @staticmethod
    def _token_cost(item: Mapping) -> int:
        value = item.get("length_tokens")
        if isinstance(value, (int, float)) and value > 0:
            return int(value)
        return max(1, len(str(item.get("text", ""))) // 3)

    def expand(self, hits: Sequence[Mapping]) -> List[Dict]:
        output: List[Dict] = []
        seen = set()
        used_tokens = 0

        def add(item: Mapping, *, role: str, source_hit: Mapping) -> bool:
            nonlocal used_tokens
            key = _dedupe_key(item)
            if key in seen:
                return True
            cost = self._token_cost(item)
            if output and used_tokens + cost > self.max_tokens:
                return False
            expanded = dict(item)
            for field in (
                "rrf_score",
                "dense_score",
                "bm25_score",
                "relevance_score",
                "combined_score",
                "retrieval_sources",
            ):
                if field in source_hit and field not in expanded:
                    expanded[field] = source_hit[field]
            expanded["context_role"] = role
            expanded["source_hit_chunk_id"] = source_hit.get("chunk_id")
            expanded["distance"] = source_hit.get(
                "distance", expanded.get("distance", 0.0)
            )
            seen.add(key)
            output.append(expanded)
            used_tokens += cost
            return True

        for raw_hit in hits:
            hit = self.chunk_by_id.get(raw_hit.get("chunk_id"), dict(raw_hit))
            scored_hit = {**hit, **dict(raw_hit)}
            if not add(scored_hit, role="hit", source_hit=scored_hit):
                break
            section_id = scored_hit.get("section_id")
            children = self.section_children.get(section_id, [])
            if not children:
                continue
            positions = {
                child.get("chunk_id"): index for index, child in enumerate(children)
            }
            position = positions.get(scored_hit.get("chunk_id"))
            add(children[0], role="parent_anchor", source_hit=scored_hit)
            if position is None:
                continue
            for offset in range(1, self.neighbor_children + 1):
                for neighbor_position in (position - offset, position + offset):
                    if 0 <= neighbor_position < len(children):
                        add(
                            children[neighbor_position],
                            role="neighbor",
                            source_hit=scored_hit,
                        )
        return output

