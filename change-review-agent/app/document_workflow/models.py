"""Domain contracts for evidence-driven document workflows."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
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
    REVIEW_REQUIRED = "REVIEW_REQUIRED"
    REJECTED = "REJECTED"
    APPROVED = "APPROVED"
    FAILED = "FAILED"


class DraftingMode(str, Enum):
    EXTRACTIVE = "EXTRACTIVE"
    GENERATIVE = "GENERATIVE"


class FieldDraftStatus(str, Enum):
    DRAFTED = "DRAFTED"
    MISSING = "MISSING"
    INSUFFICIENT_EVIDENCE = "INSUFFICIENT_EVIDENCE"
    MANUAL = "MANUAL"
    INVALID = "INVALID"


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
class FieldTask:
    field_id: str
    field_name: str
    field_type: str
    required: bool
    section_id: str
    document_types: tuple[str, ...] = ()


@dataclass
class SectionTask:
    task_id: str
    section_id: str
    section_title: str
    required_fields: list[FieldTask]
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
class FieldDraft:
    field_id: str
    content: str
    evidence_ids: list[str]
    status: FieldDraftStatus
    missing_reason: str | None
    drafting_mode: DraftingMode
    requires_review: bool = True

    def to_dict(self) -> dict:
        value = asdict(self)
        value["status"] = self.status.value
        value["drafting_mode"] = self.drafting_mode.value
        return value

    @classmethod
    def from_dict(cls, value: dict) -> "FieldDraft":
        return cls(
            field_id=value["field_id"], content=value["content"],
            evidence_ids=list(value.get("evidence_ids", [])),
            status=FieldDraftStatus(value["status"]),
            missing_reason=value.get("missing_reason"),
            drafting_mode=DraftingMode(value["drafting_mode"]),
            requires_review=bool(value.get("requires_review", True)),
        )


@dataclass
class SectionDraft:
    section_id: str
    title: str
    fields: list[FieldDraft]
    status: TaskStatus
    requires_human_review: bool = True

    @property
    def field_values(self) -> dict[str, str]:
        return {item.field_id: item.content for item in self.fields}

    @property
    def evidence_ids(self) -> list[str]:
        return sorted({evidence_id for item in self.fields for evidence_id in item.evidence_ids})

    @property
    def missing_fields(self) -> list[str]:
        return [item.field_id for item in self.fields if item.status in {FieldDraftStatus.MISSING, FieldDraftStatus.INSUFFICIENT_EVIDENCE}]

    @property
    def content(self) -> str:
        return "\n".join(item.content for item in self.fields)

    def to_dict(self) -> dict:
        return {
            "section_id": self.section_id, "title": self.title,
            "fields": [item.to_dict() for item in self.fields],
            "status": self.status.value,
            "requires_human_review": self.requires_human_review,
        }

    @classmethod
    def from_dict(cls, value: dict) -> "SectionDraft":
        return cls(
            section_id=value["section_id"], title=value["title"],
            fields=[FieldDraft.from_dict(item) for item in value["fields"]],
            status=TaskStatus(value["status"]),
            requires_human_review=bool(value.get("requires_human_review", True)),
        )
