"""Configurable source-tier classification without trusted-site hardcoding."""

from __future__ import annotations

import fnmatch
import tomllib
from pathlib import Path
from urllib.parse import urlsplit

from pydantic import Field, ValidationError, field_validator

from app.research.models import SourceLevel, StrictModel


class SourcePolicyRule(StrictModel):
    rule_id: str = Field(pattern=r"^[a-z0-9][a-z0-9_-]{2,63}$")
    priority: int = 0
    level: SourceLevel
    reason: str = Field(min_length=1)
    domain_patterns: list[str] = Field(default_factory=list)
    organization_types: list[str] = Field(default_factory=list)
    source_types: list[str] = Field(default_factory=list)

    @field_validator("domain_patterns", "organization_types", "source_types")
    @classmethod
    def normalize_values(cls, values: list[str]) -> list[str]:
        normalized = [value.strip().casefold() for value in values]
        if any(not value for value in normalized):
            raise ValueError("source policy match values cannot be blank")
        return normalized

    def matches(
        self,
        *,
        hostname: str | None,
        organization_type: str | None,
        source_type: str | None,
    ) -> bool:
        checks: list[bool] = []
        if self.domain_patterns:
            checks.append(
                bool(hostname)
                and any(fnmatch.fnmatchcase(hostname, pattern) for pattern in self.domain_patterns)
            )
        if self.organization_types:
            checks.append(
                bool(organization_type)
                and organization_type.casefold() in self.organization_types
            )
        if self.source_types:
            checks.append(bool(source_type) and source_type.casefold() in self.source_types)
        return any(checks)


class SourcePolicyConfig(StrictModel):
    policy_id: str = Field(pattern=r"^[a-z0-9][a-z0-9_-]{2,63}$")
    fallback_level: SourceLevel = SourceLevel.TIER3
    fallback_reason: str = Field(min_length=1)
    rules: list[SourcePolicyRule] = Field(default_factory=list)


class SourcePolicyDecision(StrictModel):
    level: SourceLevel
    reason: str
    rule_id: str | None = None


class SourcePolicyError(ValueError):
    pass


class SourcePolicy:
    """Evaluate source metadata using only externally supplied policy rules."""

    def __init__(self, config: SourcePolicyConfig):
        self.config = config
        self._rules = sorted(config.rules, key=lambda rule: (-rule.priority, rule.rule_id))

    @classmethod
    def from_toml(cls, path: str | Path) -> "SourcePolicy":
        policy_path = Path(path)
        if not policy_path.is_file():
            raise SourcePolicyError(f"source policy does not exist: {policy_path}")
        try:
            with policy_path.open("rb") as policy_file:
                payload = tomllib.load(policy_file)
            return cls(SourcePolicyConfig.model_validate(payload))
        except (OSError, tomllib.TOMLDecodeError, ValidationError) as exc:
            raise SourcePolicyError(f"invalid source policy {policy_path}: {exc}") from exc

    def classify(
        self,
        *,
        source_url: str | None,
        organization_type: str | None = None,
        source_type: str | None = None,
    ) -> SourcePolicyDecision:
        hostname: str | None = None
        if source_url:
            parsed = urlsplit(source_url)
            hostname = parsed.hostname.casefold() if parsed.hostname else None
        for rule in self._rules:
            if rule.matches(
                hostname=hostname,
                organization_type=organization_type,
                source_type=source_type,
            ):
                return SourcePolicyDecision(
                    level=rule.level,
                    reason=rule.reason,
                    rule_id=rule.rule_id,
                )
        return SourcePolicyDecision(
            level=self.config.fallback_level,
            reason=self.config.fallback_reason,
        )
