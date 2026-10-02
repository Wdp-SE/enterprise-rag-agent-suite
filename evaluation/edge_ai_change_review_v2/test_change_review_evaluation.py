from __future__ import annotations

import json
import tempfile
from pathlib import Path

import pytest

import run_evaluation as runner
from app.domain_profile import load_change_profile


def _write_rows(rows):
    handle = tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", suffix=".jsonl", dir=runner.EVAL, delete=False)
    path = Path(handle.name)
    try:
        handle.write("\n".join(json.dumps(row, ensure_ascii=False) for row in rows))
        handle.close()
        return path
    except Exception:
        handle.close()
        path.unlink(missing_ok=True)
        raise


def _rows():
    return [
        {
            "case_id": "dev-1", "family_id": "family-a", "split": "dev", "category": "software_baseline",
            "summary": "升级 JetPack 前检查刷写步骤", "expected_change_type": "software_baseline",
            "impact_scope": "software_baseline", "device_scope": {"device_model": "J4012"},
            "target_snapshot": "current", "required_source_ids": ["source-a"],
            "expected_scope_gap": False, "expected_manual_review": True,
        },
        {
            "case_id": "holdout-1", "family_id": "family-b", "split": "holdout", "category": "device_configuration",
            "summary": "调整 J4012 设备接口后核对兼容性", "expected_change_type": "device_configuration",
            "impact_scope": "device_configuration", "device_scope": {},
            "target_snapshot": "current", "required_source_ids": [],
            "expected_scope_gap": False, "expected_manual_review": True,
        },
    ]


class _Runtime:
    def search(self, query, **kwargs):
        return [{"source_id": "source-a"}]


def test_cases_require_separate_source_families():
    rows = _rows()
    rows[1]["family_id"] = rows[0]["family_id"]
    path = _write_rows(rows)
    try:
        with pytest.raises(ValueError, match="source family"):
            runner.read_cases(path)
    finally:
        path.unlink(missing_ok=True)


def test_evaluation_reports_planning_and_source_coverage_separately():
    report = runner.evaluate(_rows(), runtime=_Runtime(), profile=load_change_profile(runner.PROFILE_PATH))
    dev = report["splits"]["dev"]
    assert dev["required_source_recall_across_planned_queries"] == 1.0
    assert dev["complete_required_source_set_count"] == 1
    assert dev["human_quality_scoring"]["status"] == "not_scored"
    assert "impact-candidate precision" in dev["human_quality_scoring"]["note"]


def test_evaluation_keeps_no_required_sources_out_of_recall_denominator():
    report = runner.evaluate(_rows(), runtime=_Runtime(), profile=load_change_profile(runner.PROFILE_PATH))
    holdout = report["splits"]["holdout"]
    assert holdout["answerable_case_count"] == 0
    assert holdout["required_source_recall_across_planned_queries"] is None


def test_case_ids_must_be_unique():
    rows = _rows()
    rows[1]["case_id"] = rows[0]["case_id"]
    path = _write_rows(rows)
    try:
        with pytest.raises(ValueError, match="unique case_id"):
            runner.read_cases(path)
    finally:
        path.unlink(missing_ok=True)
