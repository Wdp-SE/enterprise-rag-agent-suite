from __future__ import annotations

import json
from pathlib import Path

from app.change_request import build_request_plan, classify_change_type
from app.domain_profile import load_change_profile
from app.public_review import PublicReviewAgent


ROOT = Path(__file__).resolve().parents[1]
PROFILE_PATH = ROOT / "config" / "pphuman_change_profile.json"
VERSION = "v2.9.0"
COMMIT = "b25522a0f4bde8c80603f3ba5e3472059972e3b5"
REPOSITORY = "PaddlePaddle/PaddleDetection"
SOURCE = {
    "chunk_id": f"{VERSION}:zh:deploy/pipeline/docs/tutorials/pphuman_mot:1",
    "document_id": f"{VERSION}:zh:deploy/pipeline/docs/tutorials/pphuman_mot",
    "document_key": "deploy/pipeline/docs/tutorials/pphuman_mot",
    "document_title": "行人跟踪部署",
    "version": VERSION,
    "source_snapshot": VERSION,
    "source_id": "pphuman-source-v2-9-mot",
    "repository": REPOSITORY,
    "document_path": "deploy/pipeline/docs/tutorials/pphuman_mot.md",
    "source_url": f"https://github.com/{REPOSITORY}/blob/{COMMIT}/deploy/pipeline/docs/tutorials/pphuman_mot.md",
    "commit": COMMIT,
    "source_sha256": "a" * 64,
    "language": "zh",
    "locale": "zh-CN",
    "heading": "行人跟踪部署",
    "content": "变更跟踪器配置后，需要核对检测输入、跟踪参数和部署流程。",
    "retrieval_score": 1.25,
}
REGISTRY = [{
    "source_id": SOURCE["source_id"],
    "source_url": SOURCE["source_url"],
    "repository": REPOSITORY,
    "version": VERSION,
    "source_snapshot": VERSION,
    "commit": COMMIT,
    "path": SOURCE["document_path"],
    "sha256": SOURCE["source_sha256"],
}]


def test_active_profile_and_rules_are_specific_to_pphuman():
    profile = load_change_profile(PROFILE_PATH)

    assert profile["id"] == "pphuman"
    assert profile["languages"] == ["zh"]
    assert {row["id"] for row in profile["change_types"]} == {
        "model_config", "behavior_pipeline", "tracking", "deployment", "general",
    }
    assert classify_change_type("调整行人跟踪器配置并检查跨镜跟踪流程") == "tracking"
    assert classify_change_type("更换行为识别模型并核对行为分析配置") == "behavior_pipeline"


def test_request_plan_does_not_invent_hardware_scope_for_software_docs():
    profile = load_change_profile(PROFILE_PATH)
    plan = build_request_plan(
        "变更行人跟踪的配置，核查相关部署步骤和验证项。",
        profile=profile,
        target_snapshot=VERSION,
    )

    assert plan["domain_profile_id"] == "pphuman"
    assert plan["target_version"] == VERSION
    assert plan["device_scope"] == {}
    assert plan["scope_warnings"] == []
    assert plan["manual_review_required"] is True


class PPHumanGateway:
    def __init__(self):
        self.calls = []

    def workspace(self):
        return {
            "workspace_id": "pphuman",
            "workspace": "PP-Human 行人分析工程知识",
            "domain_profile": {"id": "pphuman"},
            "repository": REPOSITORY,
            "repositories": [REPOSITORY],
            "current_version": VERSION,
            "available_versions": [VERSION, "v2.8.1"],
            "version_scopes": {"latest": {"versions": [VERSION]}},
            "languages": ["zh"],
            "source_registry": REGISTRY,
        }

    def search(self, question, *, version, language, top_k=5,
               device_model=None, module_sku=None, carrier_board=None, software_baseline=None):
        self.calls.append((question, version, language, top_k))
        return {"retrieval_policy": "bm25", "results": [SOURCE]}

    def review_advice_for_version(self, summary, evidence_chunk_ids, *, version, **_scope):
        return {
            "status": "OK",
            "answer": "跟踪配置变更需要人工核对输入、参数和部署验证。",
            "sources": [SOURCE],
            "review": {
                "impact_candidates": [{
                    "evidence_chunk_id": evidence_chunk_ids[0],
                    "reason": "该来源说明跟踪器配置与部署步骤。",
                    "suggested_action": "检查相关配置并执行回归验证。",
                }],
                "evidence_gaps": [],
                "version_ambiguities": [],
                "reviewer_actions": ["由研发人员确认并记录结论。"],
                "review_status": "REQUIRES_HUMAN_REVIEW",
            },
        }


def test_agent_runs_version_scoped_pphuman_review_with_manifest_evidence():
    gateway = PPHumanGateway()
    result = PublicReviewAgent(gateway).analyze_request(
        "调整 PP-Human 行人跟踪器配置，核对相关部署和回归验证。",
        target_version=VERSION,
    )

    assert result["request_plan"]["domain_profile_id"] == "pphuman"
    assert result["request_plan"]["change_type"] == "tracking"
    assert gateway.calls
    assert all(call[1:3] == (VERSION, "zh") for call in gateway.calls)
    assert result["retrieved_results"] == [SOURCE]
    assert result["impacts"][0]["evidence"]["source_id"] == SOURCE["source_id"]
    assert result["sandbox_only"] is True
    assert result["public_baseline_written"] is False
