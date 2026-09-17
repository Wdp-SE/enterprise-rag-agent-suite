"""One executable task per section and bounded field-level queries."""

from __future__ import annotations

from .models import SectionTask, TemplateSchema


class SectionTaskPlanner:
    def plan(self, schema: TemplateSchema) -> list[SectionTask]:
        return [
            SectionTask(f"task_{section.section_id}", section.section_id,
                        section.title, [field for field in schema.fields if field.section_id == section.section_id])
            for section in schema.sections
            if any(field.section_id == section.section_id for field in schema.fields)
        ]


class QueryPlanner:
    def query(self, field_name: str, round_number: int) -> str:
        prefixes = ("", "项目计划 ", "研发资料 ", "项目实施 ")
        if not 0 <= round_number < len(prefixes):
            raise ValueError("query round out of range")
        return f"{prefixes[round_number]}{field_name}"
