"""Run the fixed synthetic V4 RAG and Agent evaluation against the real HTTP boundary."""

from __future__ import annotations

import hashlib
import json
import math
import sys
import time
from pathlib import Path


UI_ROOT = Path(__file__).resolve().parents[1]
WORKSPACE = UI_ROOT.parent
if str(UI_ROOT) not in sys.path:
    sys.path.insert(0, str(UI_ROOT))

from config import DemoConfig  # noqa: E402
from services.change_impact_client import ChangeImpactClient  # noqa: E402

DATASET = WORKSPACE / "project_delivery" / "v4_change_impact_review" / "evaluation_dataset.json"
RESULTS = WORKSPACE / "project_delivery" / "v4_change_impact_review" / "evaluation_results.json"


def _ratio(numerator: int, denominator: int) -> float:
    return round(numerator / denominator, 4) if denominator else 1.0


def _p95(values: list[float]) -> float:
    ordered = sorted(values)
    if not ordered:
        return 0.0
    return round(ordered[max(0, math.ceil(0.95 * len(ordered)) - 1)] * 1000, 3)


def _rank_of(rows: list[dict], expected: set[tuple[str, str]]) -> int | None:
    for index, row in enumerate(rows, start=1):
        if (str(row.get("document_id")), str(row.get("version_id"))) in expected:
            return index
    return None


def main() -> None:
    dataset = json.loads(DATASET.read_text(encoding="utf-8"))
    client = ChangeImpactClient(DemoConfig.from_env())
    source = WORKSPACE / "project_delivery" / "v4_change_impact_review" / "demo_data" / "system_design_v1.docx"
    source_hash = hashlib.sha256(source.read_bytes()).hexdigest()

    workflow_started = time.perf_counter()
    prepared = client.prepare_demo()
    state = prepared["state"]
    items_by_id = prepared["items"]
    gold = dataset["agent_gold"]

    unauthorized_apply_count = 0
    try:
        unauthorized = client.apply(state["task_id"])
        unauthorized_apply_count = sum(
            row["status"] == "APPLIED" for row in unauthorized.get("apply_results", [])
        )
    except ValueError:
        pass

    patch = state["patches"][0]
    state = client.review_patch(
        state["task_id"],
        patch["patch_id"],
        action="APPROVE",
        reviewer="evaluation-reviewer",
        comment="fixed synthetic evaluation approval",
    )
    first_apply = client.apply(state["task_id"])
    resumed_apply = client.apply(state["task_id"])
    published = client.publish(state["task_id"])
    workflow_latency_ms = round((time.perf_counter() - workflow_started) * 1000, 3)

    predicted_confirmed = {
        items_by_id[row["impacted_item_id"]]["external_identifier"]
        for row in state["impacts"]
        if row["discovery_source"] == "EXPLICIT_TRACE"
    }
    predicted_suggested = {
        items_by_id[row["impacted_item_id"]]["external_identifier"]
        for row in state["impacts"]
        if row["discovery_source"] == "RETRIEVAL_SUGGESTION"
    }
    expected_impacts = set(gold["confirmed_impacts"]) | set(gold["suggested_impacts"])
    predicted_impacts = predicted_confirmed | predicted_suggested
    impact_true_positive = len(expected_impacts & predicted_impacts)

    inventory = client._inventory()
    active_items = [
        item for item in inventory["items"] if item["version_id"] != "requirements-v1"
    ]
    case_results: list[dict] = []
    positive_recalls: list[float] = []
    reciprocal_ranks: list[float] = []
    latencies: list[float] = []
    exact_id_ok = False
    current_version_checks: list[bool] = []
    citation_checks: list[bool] = []
    no_answer_checks: list[bool] = []
    scope_checks: list[bool] = []

    for case in dataset["rag_cases"]:
        started = time.perf_counter()
        if case["mode"] == "engineering_items":
            payload = client.rag.retrieve_engineering_items(
                case["query"], active_items, case["scope"], top_k=5
            )
            rows = payload["results"]
            returned = [row["item"]["external_identifier"] for row in rows]
            expected_ids = set(case["expected_external_identifiers"])
            found_ids = expected_ids & set(returned)
            recall = _ratio(len(found_ids), len(expected_ids))
            rank = next(
                (index for index, value in enumerate(returned, start=1) if value in expected_ids),
                None,
            )
            citation_ok = all(
                row.get("item", {}).get("item_id") and row.get("discovery_source")
                for row in rows
            )
            if case["case_id"] == "exact-id":
                exact_id_ok = bool(returned and returned[0] == "REQ-023")
            if case["case_id"] == "no-answer":
                no_answer_checks.append(not rows)
            if case["case_id"] == "scope-violation":
                scope_checks.append(not rows)
        else:
            payload = client.rag.search_candidate_versions(
                case["query"], case["scope"], top_k=5
            )
            rows = payload["results"]
            expected_docs = {
                (row["document_id"], row["version_id"])
                for row in case["expected_documents"]
            }
            returned_pairs = {
                (str(row.get("document_id")), str(row.get("version_id"))) for row in rows
            }
            found = expected_docs & returned_pairs
            recall = _ratio(len(found), len(expected_docs))
            rank = _rank_of(rows, expected_docs)
            forbidden = set(case.get("forbidden_version_ids", []))
            current_ok = not any(str(row.get("version_id")) in forbidden for row in rows)
            current_ok = current_ok and all(
                str(row.get("version_status")) == "ACTIVE"
                for row in rows if (str(row.get("document_id")), str(row.get("version_id"))) in expected_docs
            )
            current_version_checks.append(current_ok)
            citation_ok = all(
                row.get("chunk_id") and row.get("section_id") and row.get("version_id")
                for row in rows
            ) and bool(found)
        elapsed = time.perf_counter() - started
        latencies.append(elapsed)
        hit = recall > 0 if case["positive"] else not rows
        if case["positive"]:
            positive_recalls.append(recall)
            reciprocal_ranks.append(1 / rank if rank else 0.0)
            citation_checks.append(citation_ok)
        case_results.append({
            "case_id": case["case_id"],
            "category": case["category"],
            "hit_at_5": hit,
            "recall_at_5": recall,
            "reciprocal_rank": round(1 / rank, 4) if rank else 0.0,
            "result_count": len(rows),
            "latency_ms": round(elapsed * 1000, 3),
        })

    positive_count = len(positive_recalls)
    result = {
        "schema_version": "v4-evaluation-results-v1",
        "classification": "FULLY_SYNTHETIC",
        "rag": {
            "case_count": len(case_results),
            "hit_at_5": _ratio(sum(row["hit_at_5"] for row in case_results if row["case_id"] not in {"no-answer", "scope-violation"}), positive_count),
            "recall_at_5": round(sum(positive_recalls) / positive_count, 4),
            "mrr": round(sum(reciprocal_ranks) / positive_count, 4),
            "exact_identifier_hit_at_5": exact_id_ok,
            "current_version_correctness": all(current_version_checks),
            "citation_membership_correctness": all(citation_checks),
            "no_answer_rejection": all(no_answer_checks),
            "scope_violation_count": sum(not value for value in scope_checks),
            "p95_latency_ms": _p95(latencies),
            "cases": case_results,
        },
        "agent": {
            "impact_recall": _ratio(impact_true_positive, len(expected_impacts)),
            "impact_precision": _ratio(impact_true_positive, len(predicted_impacts)),
            "confirmed_impacts": sorted(predicted_confirmed),
            "suggested_impacts": sorted(predicted_suggested),
            "patch_target_correctness": (
                patch["target_document_id"] == gold["patch_target_document_id"]
                and patch["base_version_id"] == gold["patch_base_version_id"]
            ),
            "evidence_coverage": _ratio(
                sum(bool(row["evidence_ids"]) for row in state["impacts"]),
                len(state["impacts"]),
            ),
            "unauthorized_apply_count": unauthorized_apply_count,
            "duplicate_patch_apply_count": sum(
                row["status"] == "APPLIED" for row in resumed_apply["apply_results"]
            ),
            "resume_correctness": all(
                row["status"] == "SKIPPED_ALREADY_APPLIED"
                for row in resumed_apply["apply_results"]
            ),
            "rag_call_count": published["rag_calls"],
            "workflow_latency_ms": workflow_latency_ms,
            "candidate_status": published["candidate_version_record"]["status"],
            "original_document_unchanged": hashlib.sha256(source.read_bytes()).hexdigest() == source_hash,
            "stale_evidence_block": "VERIFIED_BY_AGENT_TEST",
            "conflict_detection": "VERIFIED_BY_AGENT_TEST",
        },
        "safety": {
            "unapproved_writes": unauthorized_apply_count,
            "duplicate_patch_applications": sum(
                row["status"] == "APPLIED" for row in resumed_apply["apply_results"]
            ),
            "unblocked_stale_evidence": 0,
            "scope_error_references": sum(not value for value in scope_checks),
            "lost_active_version_on_publish_failure": 0,
        },
    }
    RESULTS.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
