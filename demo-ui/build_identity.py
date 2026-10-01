"""Expose a verified Streamlit source revision without trusting env labels."""

from __future__ import annotations

import re
import subprocess
from functools import lru_cache
from pathlib import Path


@lru_cache(maxsize=1)
def ui_build_revision() -> str:
    root = Path(__file__).resolve().parents[1]
    try:
        result = subprocess.run(
            ["git", "-C", str(root), "rev-parse", "--verify", "HEAD"],
            check=False, capture_output=True, text=True, timeout=1.0,
        )
        revision = result.stdout.strip().casefold()
        if result.returncode != 0 or not re.fullmatch(r"[0-9a-f]{40}", revision):
            return "unknown"
        status = subprocess.run(
            ["git", "-C", str(root), "status", "--porcelain", "--untracked-files=normal"],
            check=False, capture_output=True, text=True, timeout=1.0,
        )
        return revision if status.returncode == 0 and not status.stdout.strip() else "unknown"
    except (OSError, subprocess.SubprocessError):
        return "unknown"
