from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.change_request import (
    CHANGE_TYPES,
    build_request_plan,
    classify_change_type,
    is_out_of_scope_public_request,
)
from app.domain_profile import load_change_profile


PROFILE_PATH = Path(__file__).resolve().parents[1] / "config" / "edge_ai_device_change_profile.json"


def test_active_profile_is_chinese_edge_device_engineering_only():
    profile = load_change_profile(PROFILE_PATH)

    assert profile["id"] == "edge_ai_device"
    assert profile["languages"] == ["zh"]
    assert set(CHANGE_TYPES) == {
        "software_baseline", "device_configuration", "deployment_operations", "general",
    }
    assert all(row["checklist"] for row in profile["change_types"])


@pytest.mark.parametrize(("summary", "expected"), [
    ("将 JetPack 从 6.2 升级到 7.2，并核对 L4T 和刷写步骤。", "software_baseline"),
    ("调整 J4012 的 CAN 接口与供电配置。", "device_configuration"),
    ("变更 Jetson 边缘推理容器的 OTA 部署与故障恢复。", "deployment_operations"),
    ("检查当前资料里是否有对应的工程说明。", "general"),
])
def test_change_type_classification_uses_only_current_device_profile(summary, expected):
    assert classify_change_type(summary) == expected


def test_compound_request_keeps_full_text_and_stops_at_profile_query_limit():
    summary = "升级 JetPack 并核对刷写流程；更新工业视觉容器部署；检查故障恢复；补充回归测试。"

    plan = build_request_plan(summary)

    assert plan["queries"][0]["query"] == summary
    assert len(plan["queries"]) <= 4
    assert plan["query_limit"] == 4
    assert plan["languages"] == ["zh"]
    assert plan["manual_review_required"] is True


def test_profile_scope_rejects_an_unknown_device_instead_of_dropping_filter():
    profile = load_change_profile(PROFILE_PATH)
    profile["scope_options"] = {"device_model": ["reComputer Industrial J4012"]}

    with pytest.raises(ValueError, match="不在当前知识空间"):
        build_request_plan("升级 JetPack 前核对刷写要求。", profile=profile, device_model="Unknown Board X")


def test_private_company_material_is_stopped_but_public_device_questions_are_allowed():
    assert is_out_of_scope_public_request("查询本公司的内部 API 和私有工单。")
    assert not is_out_of_scope_public_request("核对 Jetson 设备内部温度传感器的公开配置说明。")
