"""Run the complete synthetic V4 business loop against the local RAG HTTP API."""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path


UI_ROOT = Path(__file__).resolve().parents[1]
if str(UI_ROOT) not in sys.path:
    sys.path.insert(0, str(UI_ROOT))

from config import DemoConfig, WORKSPACE_ROOT  # noqa: E402
from services.change_impact_client import ChangeImpactClient  # noqa: E402


def main() -> None:
    config = DemoConfig.from_env()
    client = ChangeImpactClient(config)
    original = (
        WORKSPACE_ROOT
        / "project_delivery"
        / "v4_change_impact_review"
        / "demo_data"
        / "system_design_v1.docx"
    )
    original_hash = hashlib.sha256(original.read_bytes()).hexdigest()

    result = client.prepare_demo()
    state = result["state"]
    assert any(change["change_type"] == "MODIFIED" for change in result["changes"])
    sources = {impact["discovery_source"] for impact in state["impacts"]}
    assert "EXPLICIT_TRACE" in sources
    assert "RETRIEVAL_SUGGESTION" in sources

    patch = state["patches"][0]
    state = client.review_patch(
        state["task_id"],
        patch["patch_id"],
        action="APPROVE",
        reviewer="smoke-reviewer",
        comment="synthetic smoke approval",
    )
    assert state["status"] == "APPLY_READY"
    first = client.apply(state["task_id"])
    assert first["state"]["status"] == "CANDIDATE_READY"
    assert first["apply_results"][0]["status"] == "APPLIED"
    resumed = client.apply(state["task_id"])
    assert resumed["apply_results"][0]["status"] == "SKIPPED_ALREADY_APPLIED"

    published = client.publish(state["task_id"])
    assert published["status"] == "COMPLETED"
    assert published["candidate_version_record"]["status"] == "ACTIVE"
    assert hashlib.sha256(original.read_bytes()).hexdigest() == original_hash

    current = client.rag.search_candidate_versions(
        "DES-014 1000 并发异步任务状态",
        {"document_ids": ["system_design"], "active_only": True},
        top_k=5,
    )["results"]
    historical = client.rag.search_candidate_versions(
        "DES-014 500 并发同步返回",
        {"version_ids": ["design-v1"], "active_only": False},
        top_k=5,
    )["results"]
    assert {row["version_id"] for row in current} == {"design-v2"}
    assert {row["version_id"] for row in historical} == {"design-v1"}
    print(json.dumps({
        "status": "PASS",
        "task_id": state["task_id"],
        "changed_items": sum(change["change_type"] != "UNCHANGED" for change in result["changes"]),
        "confirmed_impacts": sum(impact["discovery_source"] == "EXPLICIT_TRACE" for impact in state["impacts"]),
        "suggested_impacts": sum(impact["discovery_source"] == "RETRIEVAL_SUGGESTION" for impact in state["impacts"]),
        "current_versions": sorted({row["version_id"] for row in current}),
        "historical_versions": sorted({row["version_id"] for row in historical}),
        "original_unchanged": True,
        "duplicate_patch_apply_count": 0,
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
