"""Small deterministic metric helpers used by the evaluators."""

from __future__ import annotations

from statistics import mean, median
from typing import Iterable, Optional


def safe_ratio(numerator: int | float, denominator: int | float) -> Optional[float]:
    if denominator == 0:
        return None
    return round(float(numerator) / float(denominator), 6)


def summarize_scores(values: Iterable[float]) -> dict:
    scores = [float(value) for value in values]
    if not scores:
        return {
            "count": 0,
            "minimum": None,
            "maximum": None,
            "mean": None,
            "median": None,
        }
    return {
        "count": len(scores),
        "minimum": round(min(scores), 6),
        "maximum": round(max(scores), 6),
        "mean": round(mean(scores), 6),
        "median": round(median(scores), 6),
    }

