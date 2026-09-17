"""TOML loader for strict, domain-neutral research profiles."""

from __future__ import annotations

import tomllib
from pathlib import Path

from pydantic import ValidationError

from app.research.models import ResearchProfile


class ProfileLoadError(ValueError):
    """Raised when a profile cannot be parsed or validated."""


def load_research_profile(path: str | Path) -> ResearchProfile:
    """Load and validate a ResearchProfile from a TOML file."""

    profile_path = Path(path)
    if not profile_path.is_file():
        raise ProfileLoadError(f"research profile does not exist: {profile_path}")
    try:
        with profile_path.open("rb") as profile_file:
            payload = tomllib.load(profile_file)
        return ResearchProfile.model_validate(payload)
    except (OSError, tomllib.TOMLDecodeError, ValidationError) as exc:
        raise ProfileLoadError(f"invalid research profile {profile_path}: {exc}") from exc
