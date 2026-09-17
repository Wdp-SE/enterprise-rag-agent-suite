"""Evidence-only deterministic and optional one-call LLM synthesis."""

from __future__ import annotations

import json
from time import monotonic
from typing import Any

from app.reliability.budget import BudgetDimension
from app.reliability.retry import RetryOwner
from app.research.live_models import (
    ResearchFinding,
    ResearchSynthesis,
    TokenUsage,
)
from app.research.models import Evidence, ResearchProfile, normalize_text


SYNTHESIS_SYSTEM_PROMPT = (
    "You produce extractive research findings from supplied Evidence only. "
    "Return JSON and do not add outside facts."
)
SYNTHESIS_MAX_FINDINGS = 8


class GroundingValidationError(ValueError):
    pass


class SynthesisInputTooLarge(ValueError):
    pass


def estimate_text_tokens(text: str, counter=None) -> int:
    """Estimate text tokens, preferring an injected project/model counter."""

    if not text:
        return 0
    if callable(counter):
        return max(0, int(counter(text)))
    cjk_count = sum(1 for char in text if "\u3400" <= char <= "\u9fff")
    non_cjk_count = len(text) - cjk_count
    return cjk_count + (non_cjk_count + 3) // 4


def synthesis_evidence_payload(item: Evidence) -> dict[str, object]:
    """Return the exact Evidence shape sent to the synthesis model."""

    return {
        "evidence_id": item.evidence_id,
        "content": item.content,
        "source_url": item.source_url,
        "page_number": item.page_number,
        "section": item.section,
    }


def build_synthesis_prompt(
    profile: ResearchProfile,
    evidence: list[Evidence],
) -> str:
    """Build the one-call, Evidence-only synthesis prompt."""

    payload = [
        synthesis_evidence_payload(item)
        for item in sorted(evidence, key=lambda value: value.evidence_id or "")
    ]
    return (
        "Research topic: "
        + profile.research_topic
        + "\nResearch questions: "
        + json.dumps(profile.research_questions, ensure_ascii=False)
        + "\nEvidence: "
        + json.dumps(payload, ensure_ascii=False, sort_keys=True)
        + "\nReturn exactly one JSON object with keys findings, limitations, "
        "unresolved_questions. Each finding must contain statement and evidence_ids. "
        f"Return at most {SYNTHESIS_MAX_FINDINGS} concise findings. "
        "Every statement must be an exact contiguous excerpt copied from the cited "
        "Evidence content. Do not paraphrase. Do not return a finding unsupported by Evidence."
    )


class GroundingValidator:
    """Use a deliberately strict extractive contract for the first live version."""

    def validate(
        self,
        synthesis: ResearchSynthesis,
        evidence: list[Evidence],
    ) -> ResearchSynthesis:
        evidence_by_id = {
            item.evidence_id: item for item in evidence if item.evidence_id is not None
        }
        for finding in synthesis.key_findings:
            if not finding.evidence_ids:
                raise GroundingValidationError("finding has no Evidence")
            unknown = set(finding.evidence_ids) - set(evidence_by_id)
            if unknown:
                raise GroundingValidationError(
                    f"finding references unknown evidence_id: {', '.join(sorted(unknown))}"
                )
            statement = normalize_text(finding.statement).casefold()
            supported_text = " ".join(
                normalize_text(evidence_by_id[evidence_id].content)
                for evidence_id in finding.evidence_ids
            ).casefold()
            if statement not in supported_text:
                raise GroundingValidationError(
                    "finding statement is not an extractive span of its cited Evidence"
                )
        return synthesis


class DeterministicResearchSynthesizer:
    reliability_retry_owner = RetryOwner.NONE

    def __init__(self, grounding_validator: GroundingValidator | None = None):
        self.grounding_validator = grounding_validator or GroundingValidator()

    async def synthesize(
        self,
        profile: ResearchProfile,
        evidence: list[Evidence],
    ) -> ResearchSynthesis:
        ordered = sorted(evidence, key=lambda item: item.evidence_id or "")
        findings = [
            ResearchFinding(statement=item.content, evidence_ids=[item.evidence_id])
            for item in ordered
            if item.evidence_id is not None
        ]
        summary = (
            f"本次调研从 {len(ordered)} 条可追溯 Evidence 中形成了"
            f" {len(findings)} 项公开资料发现。"
            if ordered
            else ""
        )
        synthesis = ResearchSynthesis(
            summary=summary,
            key_findings=findings,
            unresolved_questions=[] if ordered else list(profile.research_questions),
        )
        return self.grounding_validator.validate(synthesis, ordered)


class OpenManusLLMSynthesisClient:
    """Small adapter that records the token delta of one existing LLM.ask call."""

    def __init__(self, llm: Any):
        self.llm = llm
        self.model = str(llm.model)

    def count_tokens(self, prompt: str) -> int:
        return int(self.llm.count_tokens(prompt))

    def reliable_token_upper_bounds(self) -> tuple[int | None, int | None]:
        """Expose only limits that the underlying LLM request enforces."""

        max_input = getattr(self.llm, "max_input_tokens", None)
        used_input = int(getattr(self.llm, "total_input_tokens", 0))
        prompt_upper = (
            max(0, int(max_input) - used_input) if max_input is not None else None
        )
        max_completion = getattr(self.llm, "max_tokens", None)
        completion_upper = (
            max(0, int(max_completion)) if max_completion is not None else None
        )
        return prompt_upper, completion_upper

    async def complete(self, prompt: str) -> tuple[str, TokenUsage]:
        before_input = int(self.llm.total_input_tokens)
        before_completion = int(self.llm.total_completion_tokens)
        started = monotonic()
        ask_once = getattr(self.llm.ask, "__wrapped__", None)
        call_args = {
            "messages": [{"role": "user", "content": prompt}],
            "system_msgs": [
                {"role": "system", "content": SYNTHESIS_SYSTEM_PROMPT}
            ],
            "stream": False,
            "temperature": 0,
        }
        if callable(ask_once):
            # OpenManus LLM.ask has a six-attempt retry decorator. This closure
            # explicitly requires one API attempt, so only this Research adapter
            # invokes the undecorated coroutine. Agent Core remains unchanged.
            response = await ask_once(self.llm, **call_args)
        else:
            response = await self.llm.ask(**call_args)
        prompt_tokens = int(self.llm.total_input_tokens) - before_input
        completion_tokens = int(self.llm.total_completion_tokens) - before_completion
        return response, TokenUsage(
            model=self.model,
            prompt_tokens=max(0, prompt_tokens),
            completion_tokens=max(0, completion_tokens),
            total_tokens=max(0, prompt_tokens) + max(0, completion_tokens),
            latency_seconds=monotonic() - started,
        )


class LLMResearchSynthesizer:
    """Make exactly one synthesis-client call over already persisted Evidence."""

    # OpenManusLLMSynthesisClient deliberately calls the undecorated one-shot
    # LLM coroutine, so the optional Reliability executor is the sole retry
    # owner for this Research-specific operation. Regular OpenManus LLM calls
    # retain their existing Tenacity behavior.
    reliability_retry_owner = RetryOwner.RELIABILITY

    def __init__(
        self,
        client: Any,
        *,
        grounding_validator: GroundingValidator | None = None,
        max_prompt_tokens: int = 20_000,
    ):
        self.client = client
        self.grounding_validator = grounding_validator or GroundingValidator()
        self.max_prompt_tokens = max_prompt_tokens

    @staticmethod
    def _strip_code_fence(response: str) -> str:
        stripped = response.strip()
        if stripped.startswith("```"):
            lines = stripped.splitlines()
            if lines and lines[0].startswith("```"):
                lines = lines[1:]
            if lines and lines[-1].strip() == "```":
                lines = lines[:-1]
            return "\n".join(lines).strip()
        return stripped

    def _prompt(self, profile: ResearchProfile, evidence: list[Evidence]) -> str:
        return build_synthesis_prompt(profile, evidence)

    def estimate_prompt_tokens(
        self,
        profile: ResearchProfile,
        evidence: list[Evidence],
    ) -> int:
        prompt = self._prompt(profile, evidence)
        counter = getattr(self.client, "count_tokens", None)
        if callable(counter):
            return int(counter(prompt))
        return estimate_text_tokens(prompt)

    def reliability_budget_contract(
        self,
        profile: ResearchProfile,
        evidence: list[Evidence],
    ) -> tuple[dict[BudgetDimension, int], frozenset[BudgetDimension]]:
        """Return reliable reservations separately from observational usage.

        The prompt estimate is deliberately not presented as a hard upper
        bound. Only limits enforced by the injected client qualify.
        """

        del profile, evidence
        costs: dict[BudgetDimension, int] = {BudgetDimension.LLM_CALLS: 1}
        observational: set[BudgetDimension] = set()
        upper_bound_provider = getattr(
            self.client, "reliable_token_upper_bounds", None
        )
        prompt_upper: int | None = None
        completion_upper: int | None = None
        if callable(upper_bound_provider):
            prompt_upper, completion_upper = upper_bound_provider()
        if prompt_upper is None or prompt_upper <= 0:
            observational.add(BudgetDimension.PROMPT_TOKENS)
        else:
            costs[BudgetDimension.PROMPT_TOKENS] = prompt_upper
        if completion_upper is None or completion_upper <= 0:
            observational.add(BudgetDimension.COMPLETION_TOKENS)
        else:
            costs[BudgetDimension.COMPLETION_TOKENS] = completion_upper
        if (
            prompt_upper is not None
            and prompt_upper > 0
            and completion_upper is not None
            and completion_upper > 0
        ):
            total_upper = prompt_upper + completion_upper
            if total_upper > 0:
                costs[BudgetDimension.TOTAL_TOKENS] = total_upper
        else:
            observational.add(BudgetDimension.TOTAL_TOKENS)
        return costs, frozenset(observational)

    async def synthesize(
        self,
        profile: ResearchProfile,
        evidence: list[Evidence],
    ) -> ResearchSynthesis:
        if not evidence:
            return ResearchSynthesis(
                unresolved_questions=list(profile.research_questions),
            )
        prompt = self._prompt(profile, evidence)
        estimated = self.estimate_prompt_tokens(profile, evidence)
        if estimated > self.max_prompt_tokens:
            raise SynthesisInputTooLarge(
                f"LLM synthesis input is estimated at {estimated} tokens; limit is {self.max_prompt_tokens}"
            )

        response, usage = await self.client.complete(prompt)
        try:
            payload = json.loads(self._strip_code_fence(response))
            findings = [ResearchFinding.model_validate(item) for item in payload["findings"]]
            synthesis = ResearchSynthesis(
                summary=" ".join(finding.statement for finding in findings),
                key_findings=findings,
                limitations=payload.get("limitations", []),
                unresolved_questions=payload.get("unresolved_questions", []),
                token_usage=usage,
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise GroundingValidationError(f"invalid LLM synthesis response: {exc}") from exc
        return self.grounding_validator.validate(synthesis, evidence)
