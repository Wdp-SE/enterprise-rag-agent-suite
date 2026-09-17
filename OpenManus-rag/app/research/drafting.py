"""Replaceable, Evidence-grounded draft generation interfaces."""

from __future__ import annotations

from typing import Protocol

from app.research.identifiers import SourceAssignment
from app.research.models import normalize_text


EVIDENCE_GROUNDING_CONTRACT = """
Use only the supplied Evidence content for professional facts.
Every factual Evidence statement must carry its assigned [source:Sxx] citation.
Do not invent facts, sources, file paths, identifiers, review status, or approval status.
If Evidence is insufficient, the caller must stop before draft generation.
""".strip()


class DraftGenerator(Protocol):
    """Interface that can later be replaced without changing package construction."""

    def generate(
        self,
        *,
        title: str,
        domain: str,
        category: str,
        sources: list[SourceAssignment],
        required_sections: list[str],
    ) -> str:
        ...


class DeterministicDraftGenerator:
    """Offline generator that copies facts from Evidence and adds citations."""

    OVERVIEW_SECTION = "概述"
    CORE_SECTION = "核心知识"
    REQUIREMENTS_SECTION = "主要要求"
    CAUTIONS_SECTION = "注意事项"
    BOUNDARY_SECTION = "资料边界"
    SOURCES_SECTION = "来源"

    def generate(
        self,
        *,
        title: str,
        domain: str,
        category: str,
        sources: list[SourceAssignment],
        required_sections: list[str],
    ) -> str:
        del domain, category  # Identity inputs are intentionally not converted into facts.
        if not sources:
            raise ValueError("DeterministicDraftGenerator requires Evidence sources")

        sections = list(dict.fromkeys(required_sections))
        for mandatory in (
            self.OVERVIEW_SECTION,
            self.CORE_SECTION,
            self.REQUIREMENTS_SECTION,
            self.CAUTIONS_SECTION,
            self.BOUNDARY_SECTION,
            self.SOURCES_SECTION,
        ):
            if mandatory not in sections:
                sections.append(mandatory)

        lines = [f"# {normalize_text(title)}", ""]
        for section in sections:
            lines.extend([f"## {section}", ""])
            if section == self.OVERVIEW_SECTION:
                lines.append(
                    f"本草稿围绕“{normalize_text(title)}”整理当前已归档的公开 Evidence。"
                )
            elif section in {self.CORE_SECTION, self.REQUIREMENTS_SECTION}:
                lines.extend(
                    f"- {assignment.evidence.content} [source:{assignment.source_id}]"
                    for assignment in sources
                )
            elif section in {self.CAUTIONS_SECTION, self.BOUNDARY_SECTION}:
                lines.append(
                    "本文是基于所列公开 Evidence 形成的行业调研知识草稿，"
                    "不代表任何企业内部业务流程；未获 Evidence 支持的专业事实未写入本文。"
                )
            elif section == self.SOURCES_SECTION:
                lines.extend(
                    f"- [source:{assignment.source_id}] {assignment.evidence.title} — "
                    f"{assignment.evidence.organization}"
                    for assignment in sources
                )
            else:
                lines.append("当前 Evidence 未支持在此章节形成独立的确定性专业结论。")
            lines.append("")
        return "\n".join(lines).rstrip() + "\n"
