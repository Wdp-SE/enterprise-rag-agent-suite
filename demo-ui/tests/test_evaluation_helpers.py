from __future__ import annotations

from scripts.run_v4_evaluation import _baseline_case, _p50


def test_p50_uses_real_latency_samples() -> None:
    assert _p50([0.109, 0.041, 0.052, 0.063]) == 57.5
    assert _p50([]) == 0.0


def test_offline_baseline_case_reports_real_version_conflict_without_runtime_claims() -> None:
    baseline = [
        {
            "document_id": "requirements",
            "version_id": "requirements-v1",
            "version_label": "V1.0",
            "version_status": "SUPERSEDED",
            "text": "最大并发 500",
        },
        {
            "document_id": "requirements",
            "version_id": "requirements-v2",
            "version_label": "V2.0",
            "version_status": "ACTIVE",
            "text": "最大并发 1000",
        },
    ]
    version_aware = [baseline[1]]

    result = _baseline_case("系统最大并发是多少？", baseline, version_aware)

    assert result["meaningful"] is True
    assert result["baseline_versions"] == ["requirements-v1", "requirements-v2"]
    assert result["version_aware_versions"] == ["requirements-v2"]
    assert "500" in result["baseline_summary"]
    assert "1000" in result["version_aware_summary"]
