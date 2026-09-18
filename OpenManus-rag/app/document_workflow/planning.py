"""Bounded SectionTask, FieldTask and retrieval-query planning."""

from __future__ import annotations

from dataclasses import dataclass

from .evidence_models import Evidence
from .models import FieldTask, SectionTask, TemplateSchema, TemplateSection
from .scope import WorkflowScope


@dataclass(frozen=True)
class RetrievalQuery:
    field_id: str
    text: str
    kind: str


class SectionTaskPlanner:
    def plan(self, schema: TemplateSchema) -> list[SectionTask]:
        result: list[SectionTask] = []
        for section in schema.sections:
            fields = [
                FieldTask(item.field_id, item.field_name, item.field_type, item.required, item.section_id)
                for item in schema.fields if item.section_id == section.section_id
            ]
            if fields:
                result.append(SectionTask(f"task_{section.section_id}", section.section_id, section.title, fields))
        return result


class QueryPlanner:
    """Create one primary and at most two deterministic fallback queries."""

    def plan(
        self,
        section: TemplateSection,
        field: FieldTask,
        scope: WorkflowScope,
        existing_evidence: list[Evidence],
    ) -> list[RetrievalQuery]:
        document_hint = " ".join(scope.document_types or field.document_types)
        project_hint = " ".join(scope.project_ids)
        candidates = [
            ("PRIMARY", f"{section.title} {field.field_name}"),
            ("FALLBACK_CONTEXT", f"{project_hint} {document_hint} {field.field_name} 要求"),
            ("FALLBACK_SECTION", f"{section.title} {field.field_name} 相关说明"),
        ]
        seen: set[str] = set()
        output: list[RetrievalQuery] = []
        existing_queries = {item.query for item in existing_evidence if item.query}
        for kind, text in candidates:
            normalized = " ".join(text.split())
            if normalized and normalized not in seen and normalized not in existing_queries:
                seen.add(normalized)
                output.append(RetrievalQuery(field.field_id, normalized, kind))
        return output[:3]
