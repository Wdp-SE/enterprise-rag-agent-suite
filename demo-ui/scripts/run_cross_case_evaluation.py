"""Run Case A and Case B through the same HTTP-backed change-review flow."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import tempfile
import time
import uuid
from pathlib import Path


UI_ROOT = Path(__file__).resolve().parents[1]
WORKSPACE_ROOT = UI_ROOT.parent
if str(UI_ROOT) not in sys.path:
    sys.path.insert(0, str(UI_ROOT))

from config import DemoConfig
from services.change_impact_client import ChangeImpactClient
from services.demo_cases import DemoCase, load_demo_cases


OUTPUT_PATH = WORKSPACE_ROOT / "project_delivery/public_value_prototype/cross_case_results.json"

EXPECTED = {
    "case-a": {
        "confirmed": {"DES-014", "API-008", "TC-102"},
        "suggested": {"OPS-006"},
    },
    "case-b": {
        "confirmed": {"DES-031", "TC-207"},
        "suggested": {"OPS-031"},
    },
}


def _hashes(case: DemoCase) -> dict[str, str]:
    return {
        name: hashlib.sha256((case.data_root / name).read_bytes()).hexdigest()
        for name in case.baseline_documents
    }


def _active_version(client: ChangeImpactClient, document_id: str) -> str | None:
    for document in client.rag.candidate_version_documents()["documents"]:
        if document.get("document_id") == document_id:
            return (document.get("active_version") or {}).get("version_id")
    return None


def run_case(case: DemoCase, base_url: str, runtime_root: Path) -> dict:
    session_id = f"eval_{case.case_id.replace('-', '_')}_{uuid.uuid4().hex[:12]}"
    config = DemoConfig(
        rag_base_url=base_url,
        runtime_root=runtime_root,
        app_env="public_demo",
        session_id=session_id,
        demo_case_id=case.case_id,
        rag_retry_limit=1,
    ).validate()
    client = ChangeImpactClient(config, case)
    before = _hashes(case)
    started = time.perf_counter()
    prepared = client.prepare_demo()
    state = prepared["state"]
    items = prepared["items"]
    patch = state["patches"][0]

    unauthorized_applied = 0
    try:
        unauthorized = client.apply(state["task_id"])
        unauthorized_applied = sum(
            row["status"] == "APPLIED"
            for row in unauthorized.get("apply_results", [])
        )
    except ValueError:
        pass
    reviewed = client.review_patch(
        state["task_id"],
        patch["patch_id"],
        action="APPROVE",
        reviewer="cross-case-evaluation",
        comment="synthetic evaluation approval",
    )
    first_apply = client.apply(reviewed["task_id"])
    repeated_apply = client.apply(reviewed["task_id"])
    published = client.publish(reviewed["task_id"])

    impacts = reviewed["impacts"]
    confirmed = {
        items[row["impacted_item_id"]]["external_identifier"]
        for row in impacts
        if row["discovery_source"] == "EXPLICIT_TRACE"
    }
    suggested = {
        items[row["impacted_item_id"]]["external_identifier"]
        for row in impacts
        if row["discovery_source"] == "RETRIEVAL_SUGGESTION"
    }
    expected = EXPECTED[case.case_id]

    candidate_results = client.rag.search_candidate_versions(
        case.patch_proposed_content,
        {"document_ids": [case.patch_target_document_id], "active_only": True},
        top_k=5,
    )["results"]
    active_requirement = _active_version(
        client,
        next(
            record["document_id"]
            for record in client._inventory()["documents"]
            if record["version_id"] == case.requirement_new_version_id
        ),
    )
    active_candidate = _active_version(client, case.patch_target_document_id)

    conflict_prepared = client.prepare_demo()
    conflict_state = conflict_prepared["state"]
    conflict_patch = conflict_state["patches"][0]
    conflict_reviewed = client.review_patch(
        conflict_state["task_id"],
        conflict_patch["patch_id"],
        action="APPROVE",
        reviewer="cross-case-conflict-check",
    )
    conflict_result = client.apply(conflict_reviewed["task_id"])
    conflict_blocks = sum(
        row["status"] == "CONFLICT"
        for row in conflict_result.get("apply_results", [])
    )

    after = _hashes(case)
    checks = {
        "requirement_change_detection": any(
            row.get("change_type") != "UNCHANGED" for row in prepared["changes"]
        ),
        "current_version_selection": active_requirement == case.requirement_new_version_id,
        "impact_candidate_generation": bool(impacts),
        "evidence_scope": all(
            evidence.get("project_id") == case.project_id
            for evidence in prepared["evidence"].values()
        ),
        "evidence_version": all(
            evidence.get("version_status") == "ACTIVE"
            for evidence in prepared["evidence"].values()
        ),
        "patch_target": (
            patch["target_document_id"] == case.patch_target_document_id
            and patch["base_version_id"] == case.patch_base_version_id
        ),
        "human_review_gate": unauthorized_applied == 0,
        "conflict_detection": conflict_blocks > 0,
        "idempotency": bool(repeated_apply["apply_results"]) and all(
            row["status"] == "SKIPPED_ALREADY_APPLIED"
            for row in repeated_apply["apply_results"]
        ),
        "candidate_version": (
            (published.get("candidate_version_record") or {}).get("status") == "ACTIVE"
        ),
        "safe_activation": active_candidate == case.candidate_version_id,
        "new_version_retrieval": any(
            row.get("version_id") == case.candidate_version_id
            for row in candidate_results
        ),
        "baseline_immutable": before == after,
        "confirmed_trace_expected": expected["confirmed"].issubset(confirmed),
        "suggested_impact_expected": expected["suggested"].issubset(suggested),
    }
    duplicate_blocks = sum(
        row["status"] == "SKIPPED_ALREADY_APPLIED"
        for row in repeated_apply["apply_results"]
    )
    elapsed_ms = round((time.perf_counter() - started) * 1000, 3)
    return {
        "case_id": case.case_id,
        "title": case.title,
        "session_id": session_id,
        "passed": all(checks.values()),
        "checks": checks,
        "observed": {
            "confirmed_impacts": sorted(confirmed),
            "suggested_impacts": sorted(suggested),
            "candidate_version_id": active_candidate,
            "first_apply_statuses": [
                row["status"] for row in first_apply["apply_results"]
            ],
        },
        "metrics": {
            "change_cases_completed": 1,
            "impact_candidates_found": len(impacts),
            "confirmed_trace_count": len(confirmed),
            "suggested_impact_count": len(suggested),
            "patch_candidates_generated": len(state["patches"]),
            "patches_approved": 1,
            "patches_edited": 0,
            "patches_rejected": 0,
            "conflict_blocks": conflict_blocks,
            "duplicate_apply_blocks": duplicate_blocks,
            "candidate_publish_success": int(
                (published.get("candidate_version_record") or {}).get("status") == "ACTIVE"
            ),
            "workflow_elapsed_ms": elapsed_ms,
            "rag_calls": published.get("rag_calls", 0),
            "llm_calls": published.get("llm_calls", 0),
            "evidence_retrieved": prepared["evidence_selection"]["retrieved_evidence_count"],
            "evidence_valid": prepared["evidence_selection"]["valid_evidence_count"],
            "evidence_deduplicated": prepared["evidence_selection"]["deduplicated_evidence_count"],
            "evidence_selected": prepared["evidence_selection"]["selected_evidence_count"],
        },
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default="http://127.0.0.1:8765")
    parser.add_argument("--output", type=Path, default=OUTPUT_PATH)
    arguments = parser.parse_args()

    cases = load_demo_cases()
    with tempfile.TemporaryDirectory(prefix="public-value-evaluation-") as temporary:
        root = Path(temporary)
        results = [
            run_case(case, arguments.base_url, root / case_id)
            for case_id, case in cases.items()
        ]
        isolated_session = DemoConfig(
            rag_base_url=arguments.base_url,
            runtime_root=root / "isolation",
            app_env="public_demo",
            session_id=f"isolation_{uuid.uuid4().hex[:12]}",
            demo_case_id="case-a",
        ).validate()
        isolated_catalog = ChangeImpactClient(
            isolated_session, cases["case-a"]
        ).rag.candidate_version_documents()["documents"]

    totals: dict[str, float] = {}
    for result in results:
        for name, value in result["metrics"].items():
            totals[name] = round(totals.get(name, 0) + value, 3)
    payload = {
        "schema_version": "public-value-cross-case-v1",
        "classification": "FULLY_SYNTHETIC",
        "claim_boundary": (
            "同一核心流程在两套结构不同的合成变更案例中通过；"
            "该结果不代表适用于所有企业研发场景。"
        ),
        "passed": all(result["passed"] for result in results) and not isolated_catalog,
        "session_isolation": {
            "fresh_session_catalog_empty": not isolated_catalog,
            "temporary_state": True,
        },
        "cases": results,
        "totals": totals,
    }
    arguments.output.parent.mkdir(parents=True, exist_ok=True)
    arguments.output.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(payload, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
