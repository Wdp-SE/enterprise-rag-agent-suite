import importlib.util
import json
import sys
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[2]
MODULE_PATH = Path(__file__).with_name("run_evaluation.py")
spec = importlib.util.spec_from_file_location("autoware_agent_planning_evaluation", MODULE_PATH)
evaluation = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = evaluation
spec.loader.exec_module(evaluation)


def _manifest():
    path = ROOT / "versioned-rag-service" / "public_corpus_autoware" / "corpus_manifest.json"
    return json.loads(path.read_text(encoding="utf-8"))


def test_frozen_cases_keep_document_families_in_one_split_and_match_hash():
    cases = evaluation.load_cases()
    evaluation.validate_cases(cases, _manifest())
    lock = json.loads(evaluation.LOCK.read_text(encoding="utf-8"))

    assert evaluation._digest(evaluation.CASES.read_bytes()) == lock["cases_sha256"]
    assert len(cases) >= 24
    assert {row["split"] for row in cases} == {"dev", "holdout"}


def test_current_autoware_planner_covers_all_curated_types_scope_and_clauses():
    report = evaluation.evaluate(evaluation.load_cases())

    assert report["metrics"]["change_type_accuracy"] == 1.0
    assert report["metrics"]["scope_guard_accuracy"] == 1.0
    assert report["metrics"]["query_budget_compliance"] == 1.0
    assert report["metrics"]["required_clause_coverage"] == 1.0
    assert report["generation_api_calls"] == 0


def test_family_split_leakage_is_rejected():
    cases = evaluation.load_cases()
    cases[1]["split"] = "holdout" if cases[0]["split"] == "dev" else "dev"

    with pytest.raises(ValueError, match="family split leakage"):
        evaluation.validate_cases(cases, _manifest())
