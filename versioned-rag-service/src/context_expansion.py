"""Bounded context expansion for validated frozen dense-retrieval chunks."""

from __future__ import annotations

from collections import defaultdict
from typing import Mapping, Sequence


def _dedupe_key(item: Mapping[str, object]) -> tuple[object, ...]:
    chunk_id = item.get("chunk_id")
    if chunk_id:
        return ("chunk", chunk_id)
    return (
        "fallback",
        item.get("document_id"),
        item.get("page_number"),
        item.get("text"),
    )


class SectionContextExpander:
    """Add a section anchor and nearby chunks within a strict text budget."""

    def __init__(
        self,
        chunks: Sequence[Mapping[str, object]],
        *,
        neighbor_children: int = 1,
        max_tokens: int = 1800,
    ):
        if neighbor_children < 0 or max_tokens < 1:
            raise ValueError("invalid context expansion settings")
        self.neighbor_children = neighbor_children
        self.max_tokens = max_tokens
        self.chunk_by_id: dict[str, dict] = {}
        self.section_children: dict[tuple[str, str, str], list[dict]] = defaultdict(list)
        for position, raw_chunk in enumerate(chunks):
            item = dict(raw_chunk)
            chunk_id = item.get("chunk_id")
            if not isinstance(chunk_id, str) or not chunk_id:
                raise ValueError("context expansion chunk is missing chunk_id")
            item.setdefault("position", position)
            self.chunk_by_id[chunk_id] = item
            section_id = item.get("section_id")
            if section_id:
                key = (
                    str(item.get("document_id", "")),
                    str(item.get("version_id", "")),
                    str(section_id),
                )
                self.section_children[key].append(item)
        for children in self.section_children.values():
            children.sort(key=lambda item: int(item.get("position", 0)))

    @classmethod
    def from_chunks(
        cls,
        chunks: Sequence[Mapping[str, object]],
        *,
        neighbor_children: int = 1,
        max_tokens: int = 1800,
    ) -> "SectionContextExpander":
        return cls(
            chunks,
            neighbor_children=neighbor_children,
            max_tokens=max_tokens,
        )

    @staticmethod
    def _token_cost(item: Mapping[str, object]) -> int:
        value = item.get("length_tokens")
        if isinstance(value, (int, float)) and value > 0:
            return int(value)
        return max(1, len(str(item.get("text", ""))) // 3)

    def expand(self, hits: Sequence[Mapping[str, object]]) -> list[dict]:
        output: list[dict] = []
        seen: set[tuple[object, ...]] = set()
        used_tokens = 0

        def add(
            item: Mapping[str, object],
            *,
            role: str,
            source_hit: Mapping[str, object],
        ) -> bool:
            nonlocal used_tokens
            key = _dedupe_key(item)
            if key in seen:
                return True
            cost = self._token_cost(item)
            if output and used_tokens + cost > self.max_tokens:
                return False
            expanded = dict(item)
            for field in (
                "bm25_score",
                "rrf_score",
                "relevance_score",
                "combined_score",
            ):
                expanded.pop(field, None)
            for field in ("distance", "dense_score", "retrieval_rank"):
                if field in source_hit and field not in expanded:
                    expanded[field] = source_hit[field]
            expanded["retrieval_sources"] = ["dense"]
            expanded["context_role"] = role
            expanded["source_hit_chunk_id"] = source_hit.get("chunk_id")
            seen.add(key)
            output.append(expanded)
            used_tokens += cost
            return True

        for raw_hit in hits:
            chunk_id = raw_hit.get("chunk_id")
            hit = self.chunk_by_id.get(str(chunk_id), dict(raw_hit))
            scored_hit = {**hit, **dict(raw_hit)}
            if not add(scored_hit, role="hit", source_hit=scored_hit):
                break
            section_id = scored_hit.get("section_id")
            key = (
                str(scored_hit.get("document_id", "")),
                str(scored_hit.get("version_id", "")),
                str(section_id or ""),
            )
            children = self.section_children.get(key, [])
            if not children:
                continue
            positions = {item["chunk_id"]: index for index, item in enumerate(children)}
            position = positions.get(scored_hit.get("chunk_id"))
            add(children[0], role="section_anchor", source_hit=scored_hit)
            if position is None:
                continue
            for offset in range(1, self.neighbor_children + 1):
                for candidate in (position - offset, position + offset):
                    if 0 <= candidate < len(children):
                        add(children[candidate], role="neighbor", source_hit=scored_hit)
        return output

