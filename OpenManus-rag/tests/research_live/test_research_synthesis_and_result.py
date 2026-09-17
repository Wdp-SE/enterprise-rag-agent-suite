from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from app.reliability.budget import BudgetDimension
from app.research.live_models import (
    AcquisitionMethod,
    AcquiredSource,
    ResearchFinding,
    ResearchSynthesis,
    TokenUsage,
)
from app.research.models import Evidence, SourceLevel
from app.research.profile_loader import load_research_profile
from app.research.research_result import ResearchResultBuilder
from app.research.research_synthesis import (
    DeterministicResearchSynthesizer,
    GroundingValidationError,
    GroundingValidator,
    LLMResearchSynthesizer,
    OpenManusLLMSynthesisClient,
    SynthesisInputTooLarge,
)


PROJECT_ROOT = Path(__file__).resolve().parents[2]
PROFILE = load_research_profile(
    PROJECT_ROOT / "config/research_profiles/special_equipment_validation.toml"
)
NOW = datetime(2026, 8, 28, tzinfo=timezone.utc)
RUN_ID = "kr_20260828T010203123456Z_1234abcd"


def evidence(content: str, url: str = "https://example.gov.cn/a") -> Evidence:
    return Evidence(
        title="Fixture",
        content=content,
        organization="example.gov.cn",
        source_url=url,
        source_type="webpage",
        retrieved_at=NOW,
        local_file="research_runs/run/raw_sources/" + "a" * 64 + ".html",
        section="Requirements",
        source_level=SourceLevel.TIER1,
    )


def acquired(item: Evidence) -> AcquiredSource:
    return AcquiredSource(
        search_result_id="sr_11111111111111111111",
        title=item.title,
        organization=item.organization,
        source_url=item.source_url,
        final_url=item.source_url,
        source_type=item.source_type,
        source_level=item.source_level,
        media_type="text/html",
        acquisition_method=AcquisitionMethod.HTTP,
        retrieved_at=item.retrieved_at,
        local_file=item.local_file,
        raw_file_hash="a" * 64,
    )


@pytest.mark.asyncio
async def test_deterministic_synthesis_and_research_result_are_grounded() -> None:
    items = [
        evidence("First public-source fact."),
        evidence("Second public-source fact.", "https://example.gov.cn/b"),
    ]
    # A different source must have a different raw artifact path.
    items[1] = items[1].model_copy(
        update={"local_file": "research_runs/run/raw_sources/" + "b" * 64 + ".html"}
    )
    synthesis = await DeterministicResearchSynthesizer().synthesize(PROFILE, items)
    result = ResearchResultBuilder(clock=lambda: NOW).build(
        run_id=RUN_ID,
        profile=PROFILE,
        evidence=items,
        acquired_sources=[acquired(item) for item in items],
        synthesis=synthesis,
        failures=[],
    )

    assert result.status.value == "COMPLETED"
    assert len(result.key_findings) == 2
    assert set(result.evidence_ids) == {item.evidence_id for item in items}
    assert all(finding.evidence_ids for finding in result.key_findings)


def test_grounding_validator_rejects_unknown_evidence_id() -> None:
    item = evidence("Supported public-source fact.")
    synthesis = ResearchSynthesis(
        key_findings=[
            ResearchFinding(
                statement=item.content,
                evidence_ids=["ev_99999999999999999999"],
            )
        ]
    )

    with pytest.raises(GroundingValidationError, match="unknown evidence_id"):
        GroundingValidator().validate(synthesis, [item])


def test_grounding_validator_rejects_unsupported_statement() -> None:
    item = evidence("Supported public-source fact.")
    synthesis = ResearchSynthesis(
        key_findings=[
            ResearchFinding(
                statement="A fact not present in Evidence.",
                evidence_ids=[item.evidence_id],
            )
        ]
    )

    with pytest.raises(GroundingValidationError, match="not an extractive span"):
        GroundingValidator().validate(synthesis, [item])


class FakeLLMClient:
    model = "fake-grounded-model"

    def __init__(self, payload: dict):
        self.payload = payload
        self.calls = 0

    def count_tokens(self, prompt: str) -> int:
        return 100

    async def complete(self, prompt: str):
        self.calls += 1
        return json.dumps(self.payload), TokenUsage(
            model=self.model,
            prompt_tokens=100,
            completion_tokens=20,
            total_tokens=120,
            latency_seconds=0.1,
        )


@pytest.mark.asyncio
async def test_llm_synthesizer_makes_one_call_and_accepts_grounded_extract() -> None:
    item = evidence("Supported public-source fact.")
    client = FakeLLMClient(
        {
            "findings": [
                {"statement": item.content, "evidence_ids": [item.evidence_id]}
            ],
            "limitations": [],
            "unresolved_questions": [],
        }
    )

    synthesis = await LLMResearchSynthesizer(client).synthesize(PROFILE, [item])

    assert client.calls == 1
    assert synthesis.token_usage.total_tokens == 120


@pytest.mark.asyncio
async def test_llm_synthesizer_rejects_unknown_evidence_id() -> None:
    item = evidence("Supported public-source fact.")
    client = FakeLLMClient(
        {
            "findings": [
                {
                    "statement": item.content,
                    "evidence_ids": ["ev_99999999999999999999"],
                }
            ],
            "limitations": [],
            "unresolved_questions": [],
        }
    )

    with pytest.raises(GroundingValidationError, match="unknown evidence_id"):
        await LLMResearchSynthesizer(client).synthesize(PROFILE, [item])


def test_conservative_preflight_counts_cjk_before_llm_initialization() -> None:
    item = evidence("中文" * 20_001)
    synthesizer = LLMResearchSynthesizer(object(), max_prompt_tokens=20_000)

    assert synthesizer.estimate_prompt_tokens(PROFILE, [item]) > 20_000


class RetryWrappedAsk:
    def __init__(self, owner):
        self.owner = owner

        async def undecorated(llm, **kwargs):
            llm.raw_calls += 1
            llm.total_input_tokens += 7
            llm.total_completion_tokens += 3
            return "{}"

        self.__wrapped__ = undecorated

    async def __call__(self, **kwargs):
        self.owner.decorated_calls += 1
        raise AssertionError("retry wrapper must not be used by one-call synthesis")


class RetryDecoratedLLM:
    model = "fixture-one-attempt-model"
    total_input_tokens = 0
    total_completion_tokens = 0
    raw_calls = 0
    decorated_calls = 0

    def __init__(self):
        self.ask = RetryWrappedAsk(self)

    def count_tokens(self, text: str) -> int:
        return len(text)


@pytest.mark.asyncio
async def test_openmanus_synthesis_client_bypasses_retry_wrapper_for_one_attempt() -> None:
    llm = RetryDecoratedLLM()

    _, usage = await OpenManusLLMSynthesisClient(llm).complete("prompt")

    assert llm.raw_calls == 1
    assert llm.decorated_calls == 0
    assert usage.prompt_tokens == 7
    assert usage.completion_tokens == 3


def test_llm_synthesis_without_enforced_upper_bounds_is_observational() -> None:
    client = FakeLLMClient({"findings": []})
    costs, observational = LLMResearchSynthesizer(
        client
    ).reliability_budget_contract(PROFILE, [evidence("Fact.")])
    assert costs == {BudgetDimension.LLM_CALLS: 1}
    assert observational == frozenset(
        {
            BudgetDimension.PROMPT_TOKENS,
            BudgetDimension.COMPLETION_TOKENS,
            BudgetDimension.TOTAL_TOKENS,
        }
    )


def test_openmanus_client_exposes_enforced_remaining_token_upper_bounds() -> None:
    llm = RetryDecoratedLLM()
    llm.max_input_tokens = 1_000
    llm.total_input_tokens = 125
    llm.max_tokens = 200
    client = OpenManusLLMSynthesisClient(llm)
    assert client.reliable_token_upper_bounds() == (875, 200)

    costs, observational = LLMResearchSynthesizer(
        client
    ).reliability_budget_contract(PROFILE, [evidence("Fact.")])
    assert costs[BudgetDimension.LLM_CALLS] == 1
    assert costs[BudgetDimension.PROMPT_TOKENS] == 875
    assert costs[BudgetDimension.COMPLETION_TOKENS] == 200
    assert costs[BudgetDimension.TOTAL_TOKENS] == 1_075
    assert observational == frozenset()
