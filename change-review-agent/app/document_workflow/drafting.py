"""Evidence-bounded field drafting with safe extractive and injectable generative modes."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from .evidence_models import Evidence, normalize_text
from .models import DraftingMode, FieldDraft, FieldDraftStatus, FieldTask, TemplateSection
from .sufficiency import EvidenceSufficiency, SufficiencyDecision


MISSING = "[MISSING: 当前知识库中未发现相关证据]"
INSUFFICIENT = "[INSUFFICIENT_EVIDENCE: 当前证据不足以形成可靠草稿]"
SAFE_GENERATIVE_CLASSIFICATIONS = {"synthetic", "public", "approved-redacted", "local-model"}


@dataclass(frozen=True)
class DraftPolicy:
    mode: DraftingMode = DraftingMode.EXTRACTIVE
    data_classification: str = "synthetic"
    max_evidence: int = 3


@dataclass(frozen=True)
class GeneratedDraft:
    content: str
    evidence_ids: tuple[str, ...]


class GenerativeDraftingBackend(Protocol):
    def generate(self, *, field: FieldTask, section: TemplateSection, evidence: list[Evidence]) -> GeneratedDraft: ...


class FieldDraftingService:
    def __init__(self, policy: DraftPolicy | None = None, backend: GenerativeDraftingBackend | None = None):
        self.policy = policy or DraftPolicy()
        self.backend = backend

    def draft(
        self,
        field: FieldTask,
        section: TemplateSection,
        evidence: list[Evidence],
        decision: SufficiencyDecision,
    ) -> FieldDraft:
        if decision.status is EvidenceSufficiency.MISSING:
            return FieldDraft(field.field_id, MISSING, [], FieldDraftStatus.MISSING, decision.reason, self.policy.mode)
        if decision.status is EvidenceSufficiency.INSUFFICIENT:
            return FieldDraft(field.field_id, INSUFFICIENT, list(decision.evidence_ids), FieldDraftStatus.INSUFFICIENT_EVIDENCE, decision.reason, self.policy.mode)
        allowed = {item.evidence_id: item for item in evidence if item.evidence_id}
        selected = [allowed[item] for item in decision.evidence_ids if item in allowed][: self.policy.max_evidence]
        if self.policy.mode is DraftingMode.EXTRACTIVE:
            parts: list[str] = []
            for item in selected:
                text = normalize_text(item.content)
                if text not in parts:
                    parts.append(text)
            content = "；".join(parts)
            ids = [item.evidence_id for item in selected if item.evidence_id]
        else:
            if self.policy.data_classification.casefold() not in SAFE_GENERATIVE_CLASSIFICATIONS:
                raise PermissionError("GENERATIVE drafting is not allowed for this data classification")
            if self.backend is None:
                raise RuntimeError("GENERATIVE drafting requires an explicit local or approved backend")
            generated = self.backend.generate(field=field, section=section, evidence=selected)
            if not normalize_text(generated.content) or not set(generated.evidence_ids).issubset(allowed):
                return FieldDraft(field.field_id, "[INVALID: 生成结果引用了任务外证据]", list(generated.evidence_ids), FieldDraftStatus.INVALID, "INVALID_EVIDENCE_REFERENCE", self.policy.mode)
            content, ids = normalize_text(generated.content), list(generated.evidence_ids)
        if not content or not ids:
            return FieldDraft(field.field_id, MISSING, [], FieldDraftStatus.MISSING, "NO_DRAFTABLE_EVIDENCE", self.policy.mode)
        return FieldDraft(field.field_id, content, ids, FieldDraftStatus.DRAFTED, None, self.policy.mode)
