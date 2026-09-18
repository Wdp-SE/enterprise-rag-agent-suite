"""Shared, dependency-free helpers for controlled engineering benchmarks."""

from __future__ import annotations

import json
import math
import statistics
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def percentile(values: list[float], percent: float) -> float:
    if not values:
        raise ValueError("cannot calculate percentile of an empty sample")
    ordered = sorted(float(value) for value in values)
    if len(ordered) == 1:
        return ordered[0]
    position = (len(ordered) - 1) * percent / 100.0
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return ordered[lower]
    fraction = position - lower
    return ordered[lower] + (ordered[upper] - ordered[lower]) * fraction


def stats(values: Iterable[float], *, digits: int = 3) -> dict:
    sample = [float(value) for value in values]
    if not sample:
        raise ValueError("benchmark sample is empty")
    result = {
        "count": len(sample),
        "mean": statistics.fmean(sample),
        "p50": percentile(sample, 50),
        "p90": percentile(sample, 90),
        "p95": percentile(sample, 95),
        "min": min(sample),
        "max": max(sample),
        "std": statistics.pstdev(sample),
    }
    return {key: round(value, digits) if isinstance(value, float) else value for key, value in result.items()}


def reduction_percent(baseline: float, optimized: float) -> float:
    if baseline <= 0:
        raise ValueError("baseline must be positive")
    return round((baseline - optimized) / baseline * 100.0, 3)


def write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def read_json(path: Path) -> object:
    return json.loads(path.read_text(encoding="utf-8"))
