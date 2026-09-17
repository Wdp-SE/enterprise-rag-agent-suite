"""Deterministic retrieval-only text construction for embedding experiments.

The builder never mutates the supplied child text.  It normalizes and bounds
only document/section metadata, and its output must not replace citation or
display evidence text.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
import re
from typing import Mapping, Sequence


class RetrievalTextMode(str, Enum):
    CHILD_ONLY = "CHILD_ONLY"
    SECTION_TITLE = "SECTION_TITLE"
    SECTION_PATH = "SECTION_PATH"
    DOCUMENT_SECTION_PATH = "DOCUMENT_SECTION_PATH"


@dataclass(frozen=True)
class RetrievalTextBuild:
    retrieval_text: str
    metadata_characters: int
    path_component_count: int
    path_was_limited: bool
    document_title_included: bool
    section_metadata_included: bool


class EmbeddingTextBuilder:
    """Build embedding input while keeping evidence text byte-for-byte intact."""

    def __init__(
        self,
        *,
        max_path_components: int = 8,
        max_path_characters: int = 320,
        max_title_characters: int = 160,
    ) -> None:
        if min(max_path_components, max_path_characters, max_title_characters) <= 0:
            raise ValueError("Retrieval metadata limits must be positive")
        self.max_path_components = max_path_components
        self.max_path_characters = max_path_characters
        self.max_title_characters = max_title_characters

    @staticmethod
    def _clean(value: object) -> str:
        return re.sub(r"\s+", " ", str(value or "")).strip()

    @classmethod
    def _path_title(cls, value: object) -> str:
        if isinstance(value, Mapping):
            for key in ("title", "section_title"):
                candidate = cls._clean(value.get(key))
                if candidate:
                    return candidate
            return ""
        return cls._clean(value)

    @classmethod
    def _deduplicate(cls, values: Sequence[str]) -> list[str]:
        output: list[str] = []
        seen: set[str] = set()
        for value in values:
            cleaned = cls._clean(value)
            key = cleaned.casefold()
            if not cleaned or key in seen:
                continue
            seen.add(key)
            output.append(cleaned)
        return output

    @staticmethod
    def _limit_text(value: str, limit: int) -> tuple[str, bool]:
        if len(value) <= limit:
            return value, False
        if limit == 1:
            return value[:1], True
        return value[: limit - 1].rstrip() + "…", True

    def _section_path(
        self,
        section_path: Sequence[object] | object | None,
        section_title: object,
    ) -> tuple[list[str], bool]:
        raw_path = (
            list(section_path)
            if isinstance(section_path, Sequence) and not isinstance(section_path, str)
            else [section_path]
            if section_path
            else []
        )
        values = [self._path_title(value) for value in raw_path]
        title = self._clean(section_title)
        if title:
            values.append(title)
        values = self._deduplicate(values)
        limited = False
        if len(values) > self.max_path_components:
            values = values[-self.max_path_components :]
            limited = True
        while len(values) > 1 and len(" > ".join(values)) > self.max_path_characters:
            values.pop(0)
            limited = True
        if values:
            values[-1], item_limited = self._limit_text(
                values[-1], self.max_path_characters
            )
            limited = limited or item_limited
        return values, limited

    def build(
        self,
        mode: RetrievalTextMode | str,
        *,
        child_text: str,
        section_title: object = "",
        section_path: Sequence[object] | object | None = None,
        document_title: object = "",
    ) -> RetrievalTextBuild:
        selected = RetrievalTextMode(mode)
        if not isinstance(child_text, str) or not child_text.strip():
            raise ValueError("child_text must be a non-empty string")
        if selected is RetrievalTextMode.CHILD_ONLY:
            return RetrievalTextBuild(
                retrieval_text=child_text,
                metadata_characters=0,
                path_component_count=0,
                path_was_limited=False,
                document_title_included=False,
                section_metadata_included=False,
            )

        clean_title, title_limited = self._limit_text(
            self._clean(section_title), self.max_title_characters
        )
        path_values: list[str] = []
        path_limited = False
        if selected in {
            RetrievalTextMode.SECTION_PATH,
            RetrievalTextMode.DOCUMENT_SECTION_PATH,
        }:
            path_values, path_limited = self._section_path(
                section_path, section_title
            )
        document = ""
        document_limited = False
        if selected is RetrievalTextMode.DOCUMENT_SECTION_PATH:
            document, document_limited = self._limit_text(
                self._clean(document_title), self.max_title_characters
            )
        metadata_blocks: list[str] = []
        section_value = ""
        if selected is RetrievalTextMode.SECTION_TITLE:
            section_value = clean_title
            if clean_title:
                path_values = [clean_title]
        else:
            if selected is RetrievalTextMode.DOCUMENT_SECTION_PATH and document:
                path_values = [
                    value
                    for value in path_values
                    if value.casefold() != document.casefold()
                ]
                metadata_blocks.append(f"[Document]\n{document}")
            section_value = " > ".join(path_values)
        if section_value:
            metadata_blocks.append(f"[Section]\n{section_value}")
        if not metadata_blocks:
            retrieval_text = child_text
        else:
            retrieval_text = "\n\n".join(
                [*metadata_blocks, f"[Content]\n{child_text}"]
            )
        if not retrieval_text.endswith(child_text):
            raise AssertionError("Retrieval text construction altered child evidence")
        metadata_characters = len(retrieval_text) - len(child_text)
        return RetrievalTextBuild(
            retrieval_text=retrieval_text,
            metadata_characters=metadata_characters,
            path_component_count=len(path_values),
            path_was_limited=path_limited or title_limited or document_limited,
            document_title_included=bool(
                selected is RetrievalTextMode.DOCUMENT_SECTION_PATH and document
            ),
            section_metadata_included=bool(section_value),
        )
