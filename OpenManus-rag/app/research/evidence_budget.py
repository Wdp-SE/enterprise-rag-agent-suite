"""Deterministic, synthesis-local Evidence selection under a token budget."""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum
from typing import Callable

from pydantic import Field

from app.research.identifiers import SOURCE_LEVEL_ORDER
from app.research.models import Evidence, ResearchProfile, StrictModel, normalize_text
from app.research.research_synthesis import (
    SYNTHESIS_SYSTEM_PROMPT,
    build_synthesis_prompt,
    estimate_text_tokens,
)


_ASCII_TOKEN_PATTERN = re.compile(r"[a-z0-9][a-z0-9._+-]*")
_CJK_SEQUENCE_PATTERN = re.compile(r"[\u3400-\u9fff]+")
_SOURCE_TYPE_SPLIT_PATTERN = re.compile(r"[^a-z0-9]+")
_MESSAGE_FORMAT_RESERVE_TOKENS = 12


class EvidenceSelectionStatus(str, Enum):
    SELECTED = "SELECTED"
    INSUFFICIENT_EVIDENCE = "INSUFFICIENT_EVIDENCE"


class EvidenceSelectionReport(StrictModel):
    """Auditable record of one local synthesis-input selection."""

    status: EvidenceSelectionStatus
    total_evidence_count: int = Field(ge=0)
    selected_evidence_count: int = Field(ge=0)
    total_estimated_tokens: int = Field(ge=0)
    selected_estimated_tokens: int = Field(ge=0)
    fixed_prompt_estimated_tokens: int = Field(ge=0)
    selected_prompt_estimated_tokens: int = Field(ge=0)
    max_context_budget: int = Field(gt=0)
    max_evidence_budget: int = Field(ge=0)
    completion_reserve_tokens: int = Field(ge=0)
    safety_margin_tokens: int = Field(ge=0)
    token_estimation_method: str = Field(min_length=1)
    selected_evidence_ids: list[str]
    excluded_evidence_ids: list[str]
    source_distribution: dict[str, int]
    selection_reasons: dict[str, str]


@dataclass(frozen=True)
class _ScoredEvidence:
    evidence: Evidence
    source_key: str
    relevance: float
    source_type_preferred: bool
    estimated_tokens: int
    content_relevant: bool

    @property
    def evidence_id(self) -> str:
        assert self.evidence.evidence_id is not None
        return self.evidence.evidence_id

    @property
    def rank_key(self) -> tuple[float, int, int, int, str]:
        return (
            -self.relevance,
            SOURCE_LEVEL_ORDER[self.evidence.source_level],
            -int(self.source_type_preferred),
            self.estimated_tokens,
            self.evidence_id,
        )


def _text_terms(value: str) -> set[str]:
    normalized = normalize_text(value).casefold()
    terms = set(_ASCII_TOKEN_PATTERN.findall(normalized))
    for sequence in _CJK_SEQUENCE_PATTERN.findall(normalized):
        if len(sequence) == 1:
            terms.add(sequence)
            continue
        for width in (2, 3, 4):
            if len(sequence) < width:
                continue
            terms.update(
                sequence[index : index + width]
                for index in range(len(sequence) - width + 1)
            )
    return terms


def _coverage(query_terms: set[str], document_terms: set[str]) -> float:
    if not query_terms:
        return 0.0
    return len(query_terms & document_terms) / len(query_terms)


class EvidenceBudgetPlanner:
    """Select an immutable Evidence subset for one LLM synthesis call.

    This component is intentionally local to Research synthesis. It does not
    manage Agent steps, tools, retries, execution time, or persisted Evidence.
    """

    def __init__(
        self,
        *,
        max_context_budget: int = 20_000,
        completion_reserve_tokens: int = 4_000,
        safety_margin_tokens: int = 1_500,
        max_source_share: float = 0.70,
        max_single_evidence_share: float = 0.35,
        min_relevance_score: float = 0.10,
        token_counter: Callable[[str], int] | None = None,
    ):
        if max_context_budget <= 0:
            raise ValueError("max_context_budget must be positive")
        if completion_reserve_tokens < 0 or safety_margin_tokens < 0:
            raise ValueError("token reserves cannot be negative")
        if not 0 < max_source_share <= 1:
            raise ValueError("max_source_share must be in (0, 1]")
        if not 0 < max_single_evidence_share <= 1:
            raise ValueError("max_single_evidence_share must be in (0, 1]")
        if not 0 <= min_relevance_score <= 1:
            raise ValueError("min_relevance_score must be in [0, 1]")
        self.max_context_budget = max_context_budget
        self.completion_reserve_tokens = completion_reserve_tokens
        self.safety_margin_tokens = safety_margin_tokens
        self.max_source_share = max_source_share
        self.max_single_evidence_share = max_single_evidence_share
        self.min_relevance_score = min_relevance_score
        self.token_counter = token_counter
        self.token_estimation_method = (
            "project_model_token_counter"
            if token_counter is not None
            else "cjk_character_plus_non_cjk_quarter_estimate"
        )

    def _estimate(self, text: str) -> int:
        return estimate_text_tokens(text, self.token_counter)

    def _prompt_tokens(
        self,
        profile: ResearchProfile,
        evidence: list[Evidence],
    ) -> int:
        return (
            self._estimate(SYNTHESIS_SYSTEM_PROMPT)
            + self._estimate(build_synthesis_prompt(profile, evidence))
            + _MESSAGE_FORMAT_RESERVE_TOKENS
        )

    def _evidence_tokens(
        self,
        profile: ResearchProfile,
        evidence: list[Evidence],
        *,
        fixed_prompt_tokens: int,
    ) -> int:
        return max(0, self._prompt_tokens(profile, evidence) - fixed_prompt_tokens)

    @staticmethod
    def _source_type_preferred(
        source_type: str,
        preferred_source_types: list[str],
    ) -> bool:
        normalized_source = normalize_text(source_type).casefold()
        source_parts = {
            part for part in _SOURCE_TYPE_SPLIT_PATTERN.split(normalized_source) if part
        }
        for preferred in preferred_source_types:
            normalized_preferred = normalize_text(preferred).casefold()
            preferred_parts = {
                part
                for part in _SOURCE_TYPE_SPLIT_PATTERN.split(normalized_preferred)
                if part
            }
            if normalized_source == normalized_preferred or source_parts & preferred_parts:
                return True
        return False

    def _score(
        self,
        profile: ResearchProfile,
        evidence: Evidence,
        *,
        fixed_prompt_tokens: int,
    ) -> _ScoredEvidence:
        topic_terms = _text_terms(profile.research_topic)
        question_terms = _text_terms(" ".join(profile.research_questions))
        content_terms = _text_terms(evidence.content)
        title_terms = _text_terms(
            " ".join(value for value in (evidence.title, evidence.section) if value)
        )
        topic_matches = topic_terms & content_terms
        question_matches = question_terms & content_terms
        relevance = (
            0.55 * _coverage(topic_terms, content_terms)
            + 0.25 * _coverage(question_terms, content_terms)
            + 0.15 * _coverage(topic_terms | question_terms, title_terms)
            + 0.05
            * float(
                self._source_type_preferred(
                    evidence.source_type,
                    profile.preferred_source_types,
                )
            )
        )
        content_relevant = (
            len(topic_matches | question_matches) >= 2
            and relevance >= self.min_relevance_score
        )
        token_count = self._evidence_tokens(
            profile,
            [evidence],
            fixed_prompt_tokens=fixed_prompt_tokens,
        )
        return _ScoredEvidence(
            evidence=evidence,
            source_key=evidence.canonical_source_identity(),
            relevance=round(relevance, 8),
            source_type_preferred=self._source_type_preferred(
                evidence.source_type,
                profile.preferred_source_types,
            ),
            estimated_tokens=max(1, token_count),
            content_relevant=content_relevant,
        )

    @staticmethod
    def _selected_reason(record: _ScoredEvidence, reason: str) -> str:
        return (
            f"selected: {reason}; relevance={record.relevance:.8f}; "
            f"source_level={record.evidence.source_level.value}; "
            f"preferred_source_type={str(record.source_type_preferred).lower()}; "
            f"estimated_tokens={record.estimated_tokens}"
        )

    def plan(
        self,
        profile: ResearchProfile,
        evidence: list[Evidence],
    ) -> tuple[list[Evidence], EvidenceSelectionReport]:
        ordered_input = sorted(evidence, key=lambda item: item.evidence_id or "")
        fixed_prompt_tokens = self._prompt_tokens(profile, [])
        max_evidence_budget = max(
            0,
            self.max_context_budget
            - fixed_prompt_tokens
            - self.completion_reserve_tokens
            - self.safety_margin_tokens,
        )
        total_tokens = self._evidence_tokens(
            profile,
            ordered_input,
            fixed_prompt_tokens=fixed_prompt_tokens,
        )
        if not ordered_input or max_evidence_budget <= 0:
            reasons = {
                item.evidence_id: "excluded: no Evidence input budget is available"
                for item in ordered_input
                if item.evidence_id is not None
            }
            return [], EvidenceSelectionReport(
                status=EvidenceSelectionStatus.INSUFFICIENT_EVIDENCE,
                total_evidence_count=len(ordered_input),
                selected_evidence_count=0,
                total_estimated_tokens=total_tokens,
                selected_estimated_tokens=0,
                fixed_prompt_estimated_tokens=fixed_prompt_tokens,
                selected_prompt_estimated_tokens=fixed_prompt_tokens,
                max_context_budget=self.max_context_budget,
                max_evidence_budget=max_evidence_budget,
                completion_reserve_tokens=self.completion_reserve_tokens,
                safety_margin_tokens=self.safety_margin_tokens,
                token_estimation_method=self.token_estimation_method,
                selected_evidence_ids=[],
                excluded_evidence_ids=[
                    item.evidence_id
                    for item in ordered_input
                    if item.evidence_id is not None
                ],
                source_distribution={},
                selection_reasons=dict(sorted(reasons.items())),
            )

        records = sorted(
            (
                self._score(
                    profile,
                    item,
                    fixed_prompt_tokens=fixed_prompt_tokens,
                )
                for item in ordered_input
            ),
            key=lambda item: item.rank_key,
        )
        reasons: dict[str, str] = {}
        eligible: list[_ScoredEvidence] = []
        canonical_content: dict[str, str] = {}
        max_single_tokens = int(max_evidence_budget * self.max_single_evidence_share)
        for record in records:
            if not record.content_relevant:
                reasons[record.evidence_id] = (
                    f"excluded: low topic/question relevance; relevance={record.relevance:.8f}"
                )
                continue
            content_hash = record.evidence.content_hash
            assert content_hash is not None
            if content_hash in canonical_content:
                reasons[record.evidence_id] = (
                    "excluded: duplicate content of " + canonical_content[content_hash]
                )
                continue
            canonical_content[content_hash] = record.evidence_id
            if record.estimated_tokens > max_single_tokens:
                reasons[record.evidence_id] = (
                    f"excluded: single Evidence estimate {record.estimated_tokens} exceeds "
                    f"fair-share limit {max_single_tokens}"
                )
                continue
            eligible.append(record)

        selected: list[_ScoredEvidence] = []
        selected_ids: set[str] = set()
        source_tokens: dict[str, int] = {}
        relevant_sources = {record.source_key for record in eligible}
        source_token_limit = (
            int(max_evidence_budget * self.max_source_share)
            if len(relevant_sources) > 1
            else max_evidence_budget
        )

        def try_select(record: _ScoredEvidence, reason: str) -> bool:
            if record.evidence_id in selected_ids:
                return True
            next_source_tokens = source_tokens.get(record.source_key, 0) + record.estimated_tokens
            if next_source_tokens > source_token_limit:
                reasons[record.evidence_id] = (
                    f"excluded: source share limit {source_token_limit} would be exceeded"
                )
                return False
            proposed = [item.evidence for item in selected] + [record.evidence]
            proposed_tokens = self._evidence_tokens(
                profile,
                proposed,
                fixed_prompt_tokens=fixed_prompt_tokens,
            )
            if proposed_tokens >= max_evidence_budget:
                reasons[record.evidence_id] = (
                    f"excluded: token budget {max_evidence_budget} would be met or exceeded"
                )
                return False
            selected.append(record)
            selected_ids.add(record.evidence_id)
            source_tokens[record.source_key] = next_source_tokens
            reasons[record.evidence_id] = self._selected_reason(record, reason)
            return True

        by_source: dict[str, list[_ScoredEvidence]] = {}
        for record in eligible:
            by_source.setdefault(record.source_key, []).append(record)
        source_order = sorted(
            by_source,
            key=lambda source_key: by_source[source_key][0].rank_key + (source_key,),
        )
        for source_key in source_order:
            try_select(by_source[source_key][0], "source diversity representative")

        for record in eligible:
            if record.evidence_id not in selected_ids:
                try_select(record, "relevance/rank fit within budget")

        selected_evidence = sorted(
            (record.evidence for record in selected),
            key=lambda item: item.evidence_id or "",
        )
        selected_tokens = self._evidence_tokens(
            profile,
            selected_evidence,
            fixed_prompt_tokens=fixed_prompt_tokens,
        )
        selected_id_list = [
            item.evidence_id for item in selected_evidence if item.evidence_id is not None
        ]
        excluded_id_list = sorted(
            item.evidence_id
            for item in ordered_input
            if item.evidence_id is not None and item.evidence_id not in selected_ids
        )
        for evidence_id in excluded_id_list:
            reasons.setdefault(evidence_id, "excluded: lower-ranked Evidence not selected")
        distribution: dict[str, int] = {}
        for item in selected_evidence:
            source_key = item.canonical_source_identity()
            distribution[source_key] = distribution.get(source_key, 0) + 1
        status = (
            EvidenceSelectionStatus.SELECTED
            if selected_evidence
            else EvidenceSelectionStatus.INSUFFICIENT_EVIDENCE
        )
        report = EvidenceSelectionReport(
            status=status,
            total_evidence_count=len(ordered_input),
            selected_evidence_count=len(selected_evidence),
            total_estimated_tokens=total_tokens,
            selected_estimated_tokens=selected_tokens,
            fixed_prompt_estimated_tokens=fixed_prompt_tokens,
            selected_prompt_estimated_tokens=fixed_prompt_tokens + selected_tokens,
            max_context_budget=self.max_context_budget,
            max_evidence_budget=max_evidence_budget,
            completion_reserve_tokens=self.completion_reserve_tokens,
            safety_margin_tokens=self.safety_margin_tokens,
            token_estimation_method=self.token_estimation_method,
            selected_evidence_ids=selected_id_list,
            excluded_evidence_ids=excluded_id_list,
            source_distribution=dict(sorted(distribution.items())),
            selection_reasons=dict(sorted(reasons.items())),
        )
        return selected_evidence, report


__all__ = [
    "EvidenceBudgetPlanner",
    "EvidenceSelectionReport",
    "EvidenceSelectionStatus",
]
