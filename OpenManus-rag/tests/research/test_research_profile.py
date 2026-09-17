from pathlib import Path

import pytest

from app.research.profile_loader import ProfileLoadError, load_research_profile


PROJECT_ROOT = Path(__file__).resolve().parents[2]
PROFILE_PATH = (
    PROJECT_ROOT
    / "config"
    / "research_profiles"
    / "special_equipment_validation.toml"
)


def test_load_valid_research_profile() -> None:
    profile = load_research_profile(PROFILE_PATH)

    assert profile.domain == "special_equipment_validation"
    assert profile.max_sources == 3
    assert profile.output_requirements.minimum_evidence_count == 2
    assert profile.output_requirements.required_sections == [
        "概述",
        "核心知识",
        "主要要求",
        "注意事项",
        "资料边界",
        "来源",
    ]


@pytest.mark.parametrize(
    "body",
    [
        "domain = 'missing_required_fields'",
        """
profile_id = "invalid_extra"
domain = "generic_domain"
research_topic = "topic"
research_questions = ["question"]
preferred_source_types = ["official"]
knowledge_category = "category"
max_sources = 1
unexpected = true
[output_requirements]
document_type = "knowledge_note"
required_sections = ["核心知识"]
minimum_evidence_count = 1
""",
        """
profile_id = "invalid_limits"
domain = "generic_domain"
research_topic = "topic"
research_questions = ["question"]
preferred_source_types = ["official"]
knowledge_category = "category"
max_sources = 1
[output_requirements]
document_type = "knowledge_note"
required_sections = ["核心知识"]
minimum_evidence_count = 2
""",
    ],
)
def test_invalid_research_profile_is_rejected(tmp_path: Path, body: str) -> None:
    profile_path = tmp_path / "invalid.toml"
    profile_path.write_text(body, encoding="utf-8")

    with pytest.raises(ProfileLoadError):
        load_research_profile(profile_path)


def test_missing_research_profile_is_rejected(tmp_path: Path) -> None:
    with pytest.raises(ProfileLoadError):
        load_research_profile(tmp_path / "missing.toml")
