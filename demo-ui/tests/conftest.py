"""Keep historical synthetic Case A/B assertions in an explicit fixture profile."""

from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def legacy_fixture_profile(monkeypatch):
    monkeypatch.setenv("DEMO_LEGACY_FIXTURES", "true")
