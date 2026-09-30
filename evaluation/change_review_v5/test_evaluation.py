from __future__ import annotations

import importlib.util
from pathlib import Path


RUNNER = Path(__file__).with_name("run_evaluation.py")


def _module():
    spec = importlib.util.spec_from_file_location("change_review_v5", RUNNER)
    assert spec and spec.loader, "V5 change-review evaluator is not implemented"
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _case(case_id: str, family_id: str, *, answerable=True):
    return {
        "case_id": case_id,
        "family_id": family_id,
        "category": "single_source",
        "summary": "将参数优先级调整为最高，同时核对配置示例。",
        "change_type": "parameter_config",
        "required_clauses": ["参数优先级调整", "核对配置示例"],
        "required_sources": ["guide/parameter/priority"] if answerable else [],
        "expected_image_ids": [],
        "answerable": answerable,
        "expected_scope": "public",
        "version": "current",
        "language": "zh_preferred",
    }


class FakeIndex:
    def __init__(self, rows_by_query=None):
        self.rows_by_query = rows_by_query or {}
        self.manifest = {
            "current_version": "3.4.3",
            "repository": "apache/dolphinscheduler",
        }
        self.calls = []

    def search(self, query, *, top_k, version, language, policy=None):
        self.calls.append(query)
        assert version == "current"
        assert language == "zh_preferred"
        return self.rows_by_query.get(query, [])[:top_k]


def test_frozen_split_never_separates_cases_from_same_family():
    module = _module()
    cases = [
        _case("a1", "same"), _case("a2", "same"),
        _case("b1", "other"), _case("c1", "last", answerable=False),
    ]

    split = module.split_cases(cases, seed="v5-test-seed")

    assert set(split["dev"]) | set(split["holdout"]) == {case["case_id"] for case in cases}
    assert not (set(split["dev"]) & set(split["holdout"]))
    for family in {case["family_id"] for case in cases}:
        family_ids = {case["case_id"] for case in cases if case["family_id"] == family}
        assert family_ids <= set(split["dev"]) or family_ids <= set(split["holdout"])


def test_evaluation_reports_source_coverage_versions_and_no_answer_noise():
    module = _module()
    summary = "将参数优先级调整为最高，同时核对配置示例。"
    rows = [{
        "chunk_id": "chunk-1", "version": "3.4.3", "language": "zh",
        "document_key": "guide/parameter/priority", "retrieval_score": 2.0,
        "source_url": "https://github.com/apache/dolphinscheduler/blob/abc/doc.md",
    }]
    index = FakeIndex({summary: rows})

    report = module.evaluate_cases([_case("a1", "same")], index)

    assert report["metrics"]["change_type_accuracy"] == 1.0
    assert report["metrics"]["query_budget_compliance"] == 1.0
    assert report["metrics"]["complete_required_sources_at_5"] == 1.0
    assert report["metrics"]["version_mismatch_count"] == 0
    assert report["metrics"]["required_source_recall_at_5"] == 1.0
    assert report["scope"]["generation_api_calls"] == 0


def test_private_scope_guard_is_evaluated_and_skips_retrieval():
    module = _module()
    case = _case("private-1", "private-family", answerable=False)
    case["summary"] = "查询公司内部 Jira 审批人的手机号和私有工单权限"
    case["expected_scope"] = "out_of_scope"
    index = FakeIndex()

    report = module.evaluate_cases([case], index)

    assert report["metrics"]["scope_guard_accuracy"] == 1.0
    assert report["metrics"]["out_of_scope_retrieval_attempt_count"] == 0
    assert report["metrics"]["unanswerable_nonempty_candidate_rate"] == 0
    assert report["metrics"]["retrieval_call_count"] == 0
    assert index.calls == []
