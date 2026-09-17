from pathlib import Path

from app.research.models import SourceLevel
from app.research.source_policy import SourcePolicy


PROJECT_ROOT = Path(__file__).resolve().parents[2]
POLICY_PATH = PROJECT_ROOT / "config" / "research_policies" / "default.toml"


def test_source_policy_classifies_tier1_by_configured_domain_pattern() -> None:
    policy = SourcePolicy.from_toml(POLICY_PATH)

    decision = policy.classify(source_url="https://agency.example.gov/public/document")

    assert decision.level is SourceLevel.TIER1
    assert decision.rule_id == "government_and_regulators"


def test_source_policy_classifies_tier1_by_source_type() -> None:
    policy = SourcePolicy.from_toml(POLICY_PATH)

    decision = policy.classify(
        source_url="https://standards.example.org/document",
        source_type="official_standard",
    )

    assert decision.level is SourceLevel.TIER1
    assert decision.rule_id == "official_standards_bodies"


def test_source_policy_classifies_tier2_from_configured_metadata() -> None:
    policy = SourcePolicy.from_toml(POLICY_PATH)

    decision = policy.classify(
        source_url="https://association.example.org/guidance",
        organization_type="industry_association",
    )

    assert decision.level is SourceLevel.TIER2
    assert decision.rule_id == "industry_and_official_organizations"


def test_source_policy_falls_back_to_tier3() -> None:
    policy = SourcePolicy.from_toml(POLICY_PATH)

    decision = policy.classify(source_url="https://public.example.com/article")

    assert decision.level is SourceLevel.TIER3
    assert decision.rule_id is None
