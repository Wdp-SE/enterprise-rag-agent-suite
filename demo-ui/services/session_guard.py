"""Small public-demo session guards without external state."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class LLMSessionBudget:
    limit: int | None = None
    used: int = 0

    def __post_init__(self) -> None:
        if (self.limit is not None and self.limit < 0) or self.used < 0:
            raise ValueError("LLM session budget values must not be negative")

    @property
    def remaining(self) -> int | None:
        if self.limit is None:
            return None
        return max(0, self.limit - self.used)

    def reserve(self) -> bool:
        if self.limit is not None and self.used >= self.limit:
            return False
        self.used += 1
        return True
