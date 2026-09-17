"""Small deterministic contracts for structured Word templates."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class TaskStatus(str, Enum):
    PENDING = "PENDING"
    RUNNING = "RUNNING"
    PARTIAL = "PARTIAL"
    COMPLETE = "COMPLETE"
    NO_PROGRESS = "NO_PROGRESS"
    FAILED = "FAILED"


class WorkflowStatus(str, Enum):
    PENDING = "PENDING"
    RUNNING = "RUNNING"
    PARTIAL = "PARTIAL"
    COMPLETE = "COMPLETE"
    FAILED = "FAILED"


@dataclass
class TemplateField:
    field_id: str
    field_name: str
    field_type: str
    required: bool
    placeholder: str | None
    location: dict
    section_id: str


@dataclass
class TemplateSection:
    section_id: str
    title: str
    level: int
    order: int
    parent_section_id: str | None
    heading_location: int


@dataclass
class TemplateTable:
    table_id: str
    rows: int
    fillable_cells: list[dict] = field(default_factory=list)


@dataclass
class TemplateSchema:
    template_id: str
    template_name: str
    sections: list[TemplateSection]
    fields: list[TemplateField]
    tables: list[TemplateTable]


@dataclass
class SectionTask:
    task_id: str
    section_id: str
    section_title: str
    required_fields: list[TemplateField]
    status: TaskStatus = TaskStatus.PENDING
    queries: list[str] = field(default_factory=list)
    evidence_ids: list[str] = field(default_factory=list)
    missing_fields: list[str] = field(default_factory=list)
    started_at: str | None = None
    completed_at: str | None = None
    attempt_count: int = 0
    stop_reason: str | None = None
    error_code: str | None = None
    error_summary: str | None = None


@dataclass
class SectionDraft:
    section_id: str
    title: str
    field_values: dict[str, str]
    evidence_ids: list[str]
    missing_fields: list[str]
    status: TaskStatus
    requires_human_review: bool = True

    @property
    def content(self) -> str:
        return "\n".join(self.field_values.values())
