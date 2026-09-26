from __future__ import annotations

from pathlib import Path

import pytest

from config import DemoConfig
from services.demo_cases import load_demo_cases
from services.session_guard import LLMSessionBudget


def test_public_profile_uses_canonical_remote_url_and_session_workspace(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("APP_ENV", "public_demo")
    monkeypatch.setenv("RAG_API_BASE_URL", "https://rag.example.test")
    monkeypatch.setenv("DEMO_RAG_BASE_URL", "http://legacy.invalid")
    monkeypatch.setenv("DEMO_RUNTIME_ROOT", str(tmp_path))
    monkeypatch.setenv("RAG_RETRY_LIMIT", "2")
    monkeypatch.setenv("MAX_LLM_CALLS_PER_SESSION", "3")

    base = DemoConfig.from_env()
    scoped = base.for_session("session_12345678", "case-b")

    assert base.is_public_demo is True
    assert base.rag_base_url == "https://rag.example.test"
    assert base.rag_retry_limit == 2
    assert base.max_llm_calls_per_session == 3
    assert scoped.session_id == "session_12345678"
    assert scoped.demo_case_id == "case-b"
    assert scoped.runtime_root == tmp_path / "sessions" / "session_12345678" / "case-b"
    with pytest.raises(ValueError, match="session_id"):
        base.for_session("../escape", "case-a")


def test_llm_budget_fails_closed_without_fake_result() -> None:
    budget = LLMSessionBudget(limit=2)
    assert budget.reserve() is True
    assert budget.reserve() is True
    assert budget.reserve() is False
    assert budget.used == 2
    assert budget.remaining == 0


def test_llm_session_guard_is_unbounded_when_no_limit_is_configured() -> None:
    budget = LLMSessionBudget()
    assert budget.remaining is None
    assert all(budget.reserve() for _ in range(100))
    assert budget.used == 100
    assert budget.remaining is None


def test_public_profile_defaults_to_no_fixed_generation_limit(monkeypatch) -> None:
    monkeypatch.delenv("MAX_LLM_CALLS_PER_SESSION", raising=False)

    from config import _optional_call_limit
    assert _optional_call_limit() is None


def test_public_query_requires_explicit_enablement_for_synthetic_data() -> None:
    disabled = DemoConfig(app_env="public_demo", allow_rag_query=False)
    enabled = DemoConfig(app_env="public_demo", allow_rag_query=True)

    assert disabled.online_generation_allowed is False
    assert enabled.online_generation_allowed is True


def test_two_demo_cases_are_independent_and_reference_existing_synthetic_files() -> None:
    cases = load_demo_cases()
    assert list(cases) == ["case-a", "case-b"]
    case_a, case_b = cases["case-a"], cases["case-b"]
    assert case_a.changed_external_identifier == "REQ-023"
    assert case_b.changed_external_identifier != case_a.changed_external_identifier
    assert case_b.project_id != case_a.project_id
    assert case_b.requirement_old_version_id != case_a.requirement_old_version_id
    assert case_b.patch_target_external_identifier != case_a.patch_target_external_identifier
    assert case_b.data_root.is_dir()
    assert case_b.inventory_path.is_file()
    assert all((case_b.data_root / name).is_file() for name in case_b.baseline_documents)
    serialized = case_b.config_path.read_text(encoding="utf-8")
    assert "REQ-023" not in serialized
    assert "500" not in serialized
    assert "1000" not in serialized
