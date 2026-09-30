"""Frozen offline evaluation for change-review planning and evidence retrieval.

This evaluation never calls an LLM or scores generated answer correctness.
It checks the deterministic request planner and evidence candidates only.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
import sys
import time
from pathlib import Path
from statistics import mean


ROOT = Path(__file__).resolve().parents[2]
AGENT_ROOT = ROOT / "change-review-agent"
SERVICE_ROOT = ROOT / "versioned-rag-service"
for candidate in (AGENT_ROOT, SERVICE_ROOT):
    if str(candidate) not in sys.path:
        sys.path.insert(0, str(candidate))

from app.change_request import build_request_plan, is_out_of_scope_public_request  # noqa: E402
from app.public_review import _official_hit, _select_request_evidence  # noqa: E402
from src.public_knowledge import PublicKnowledgeIndex  # noqa: E402
from src.public_retrieval_runtime import PublicRetrievalRuntime  # noqa: E402


CASE_PATH = Path(__file__).with_name("cases.jsonl")
LOCK_PATH = Path(__file__).with_name("split_lock.json")


def _normalized(text: str) -> str:
    return re.sub(r"[^\w\u3400-\u9fff]+", "", text.casefold())


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def load_cases(path: Path = CASE_PATH) -> list[dict]:
    cases = [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    validate_cases(cases)
    return cases


def validate_cases(cases: list[dict]) -> None:
    required_fields = {
        "case_id", "family_id", "category", "summary", "change_type",
        "required_clauses", "required_sources", "expected_image_ids", "answerable",
    }
    case_ids: set[str] = set()
    for case in cases:
        if not isinstance(case, dict) or not required_fields <= set(case):
            raise ValueError("V5 case is missing required fields")
        if not isinstance(case["case_id"], str) or not case["case_id"].strip() or case["case_id"] in case_ids:
            raise ValueError("V5 case IDs must be non-empty and unique")
        case_ids.add(case["case_id"])
        if not isinstance(case["family_id"], str) or not case["family_id"].strip():
            raise ValueError(f"invalid family_id in {case['case_id']}")
        if not isinstance(case["summary"], str) or not case["summary"].strip():
            raise ValueError(f"invalid summary in {case['case_id']}")
        if case["change_type"] not in {
            "parameter_config", "interface_compatibility", "workflow_behavior",
            "data_storage", "security_permission", "general",
        }:
            raise ValueError(f"invalid change_type in {case['case_id']}")
        if not isinstance(case["required_clauses"], list) or not all(
            isinstance(row, str) and row.strip() for row in case["required_clauses"]
        ):
            raise ValueError(f"invalid required_clauses in {case['case_id']}")
        if not isinstance(case["required_sources"], list) or not all(
            isinstance(row, str) and row.strip() for row in case["required_sources"]
        ):
            raise ValueError(f"invalid required_sources in {case['case_id']}")
        if not isinstance(case["expected_image_ids"], list):
            raise ValueError(f"invalid expected_image_ids in {case['case_id']}")
        if not isinstance(case["answerable"], bool):
            raise ValueError(f"invalid answerable flag in {case['case_id']}")
        case.setdefault("expected_scope", "public")
        if case["expected_scope"] not in {"public", "out_of_scope"}:
            raise ValueError(f"invalid expected_scope in {case['case_id']}")
        if not case["answerable"] and (case["required_sources"] or case["expected_image_ids"]):
            raise ValueError(f"unanswerable case cannot require sources: {case['case_id']}")


def split_cases(cases: list[dict], *, seed: str, holdout_fraction: float = 0.25) -> dict[str, list[str]]:
    if len(cases) < 2 or not 0 < holdout_fraction < 1:
        raise ValueError("at least two cases and a valid holdout fraction are required")
    families = sorted({case["family_id"] for case in cases})
    if len(families) < 2:
        raise ValueError("at least two case families are required")
    ranked = sorted(families, key=lambda family: _sha256(f"{seed}:{family}".encode("utf-8")))
    holdout_count = min(len(families) - 1, max(1, round(len(families) * holdout_fraction)))
    holdout_families = set(ranked[:holdout_count])
    return {
        "dev": [case["case_id"] for case in cases if case["family_id"] not in holdout_families],
        "holdout": [case["case_id"] for case in cases if case["family_id"] in holdout_families],
    }


def _percentile95(values: list[float]) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    return round(ordered[max(0, math.ceil(0.95 * len(ordered)) - 1)], 3)


def evaluate_cases(cases: list[dict], index, *, policy: str = "bm25") -> dict:
    current_version = index.manifest["current_version"]
    repository = str(index.manifest.get("repository") or "")
    type_correct = 0
    within_budget = 0
    covered_clauses = 0
    total_clauses = 0
    required_source_hits = 0
    required_source_total = 0
    complete_source_cases = 0
    answerable_cases = 0
    answerable_empty_candidates = 0
    no_answer_cases = 0
    no_answer_with_candidates = 0
    scope_correct = 0
    scope_case_count = 0
    out_of_scope_retrieval_attempts = 0
    out_of_scope_cases = 0
    public_cases_blocked = 0
    version_mismatches = 0
    image_hits = 0
    expected_image_total = 0
    retrieval_call_count = 0
    elapsed_ms: list[float] = []
    details = []

    for case in cases:
        plan = build_request_plan(case["summary"])
        expected_scope = case.get("expected_scope", "public")
        guarded = is_out_of_scope_public_request(case["summary"])
        actual_scope = "out_of_scope" if guarded else "public"
        scope_correct += int(actual_scope == expected_scope)
        scope_case_count += 1
        out_of_scope_cases += int(expected_scope == "out_of_scope")
        out_of_scope_retrieval_attempts += int(expected_scope == "out_of_scope" and not guarded) * len(plan["queries"])
        public_cases_blocked += int(expected_scope == "public" and guarded)
        type_ok = plan["change_type"] == case["change_type"]
        type_correct += int(type_ok)
        query_rows = plan["queries"]
        query_texts = [row["query"] for row in query_rows]
        clause_queries = [row["query"] for row in query_rows if row["kind"] == "change_clause"]
        normalized_clause_queries = [_normalized(query) for query in clause_queries]
        covered = [
            any(_normalized(required) in query for query in normalized_clause_queries)
            for required in case["required_clauses"]
        ]
        covered_clauses += sum(covered)
        total_clauses += len(covered)
        budget_ok = len(query_rows) <= plan["query_limit"] == 4
        within_budget += int(budget_ok)

        searches: list[tuple[dict, list[dict]]] = []
        case_latency: list[float] = []
        for row in ([] if guarded else query_rows):
            started = time.perf_counter()
            raw_hits = index.search(
                row.get("search_query", row["query"]), top_k=5, version="current",
                language=case.get("language", "zh_preferred"), policy=policy,
            )
            case_latency.append((time.perf_counter() - started) * 1000)
            retrieval_call_count += 1
            version_mismatches += sum(hit.get("version") != current_version for hit in raw_hits)
            hits = [hit for hit in raw_hits if _official_hit(hit, current_version, repository)]
            searches.append(({
                **row,
                "status": "candidate_found" if hits else "no_retrieval_match",
                "top_chunk_ids": [hit.get("chunk_id") for hit in hits],
            }, hits))
        elapsed_ms.extend(case_latency)
        selected = _select_request_evidence(searches)
        selected_ids = {hit.get("chunk_id") for hit in selected}
        selected = [hit for hit in selected if hit.get("chunk_id") in selected_ids][:5]
        selected_docs = {hit.get("document_key") for hit in selected}
        expected_docs = set(case["required_sources"])
        found_docs = expected_docs & selected_docs
        required_source_hits += len(found_docs)
        required_source_total += len(expected_docs)
        complete = bool(expected_docs) and found_docs == expected_docs
        complete_source_cases += int(complete)
        if case["answerable"] and expected_scope == "public":
            answerable_cases += 1
            answerable_empty_candidates += int(not selected)
        elif not case["answerable"] and expected_scope == "public":
            no_answer_cases += 1
            no_answer_with_candidates += int(bool(selected))
        expected_images = set(case["expected_image_ids"])
        found_images = expected_images & {
            hit.get("figure_id") for hit in selected if hit.get("figure_id")
        }
        image_hits += len(found_images)
        expected_image_total += len(expected_images)
        details.append({
            "case_id": case["case_id"],
            "category": case["category"],
            "expected_scope": expected_scope,
            "scope_guard_triggered": guarded,
            "scope_guard_correct": actual_scope == expected_scope,
            "expected_change_type": case["change_type"],
            "actual_change_type": plan["change_type"],
            "type_correct": type_ok,
            "required_clause_coverage": f"{sum(covered)}/{len(covered)}",
            "queries": query_texts,
            "query_count": len(query_rows),
            "query_budget": plan["query_limit"],
            "within_budget": budget_ok,
            "required_sources": sorted(expected_docs),
            "retrieved_sources_at_5": sorted(selected_docs),
            "complete_required_sources_at_5": complete,
            "expected_image_ids": sorted(expected_images),
            "retrieved_image_ids_at_5": sorted(found_images),
            "candidate_count": len(selected),
            "version_mismatch_count": sum(hit.get("version") != current_version for _, hits in searches for hit in hits),
            "warm_retrieval_p95_ms": _percentile95(case_latency),
        })

    count = len(cases)
    return {
        "evaluation": "change_review_v5_offline",
        "scope": {
            "case_count": count,
            "policy": policy,
            "current_version": current_version,
            "generation_api_calls": 0,
            "measures_generated_answer_accuracy": False,
            "uses_paid_model": False,
        },
        "metrics": {
            "change_type_accuracy": round(type_correct / count, 4) if count else 0,
            "required_clause_coverage": round(covered_clauses / total_clauses, 4) if total_clauses else 0,
            "query_budget_compliance": round(within_budget / count, 4) if count else 0,
            "scope_guard_accuracy": round(scope_correct / scope_case_count, 4) if scope_case_count else 0,
            "out_of_scope_case_count": out_of_scope_cases,
            "out_of_scope_retrieval_attempt_count": out_of_scope_retrieval_attempts,
            "public_case_false_block_count": public_cases_blocked,
            "required_source_recall_at_5": round(required_source_hits / required_source_total, 4) if required_source_total else 0,
            "complete_required_sources_at_5": round(complete_source_cases / answerable_cases, 4) if answerable_cases else 0,
            "answerable_zero_candidate_rate": round(answerable_empty_candidates / answerable_cases, 4) if answerable_cases else 0,
            "unanswerable_nonempty_candidate_rate": round(no_answer_with_candidates / no_answer_cases, 4) if no_answer_cases else 0,
            "image_hit_at_5": round(image_hits / expected_image_total, 4) if expected_image_total else None,
            "version_mismatch_count": version_mismatches,
            "retrieval_call_count": retrieval_call_count,
            "warm_retrieval_p95_ms": _percentile95(elapsed_ms),
            "warm_retrieval_mean_ms": round(mean(elapsed_ms), 3) if elapsed_ms else 0,
        },
        "details": details,
    }


def _validate_frozen_lock(cases: list[dict]) -> tuple[dict, dict[str, list[str]]]:
    raw_cases = CASE_PATH.read_bytes()
    lock = json.loads(LOCK_PATH.read_text(encoding="utf-8"))
    actual_sha = _sha256(raw_cases)
    if lock.get("cases_sha256") != actual_sha:
        raise ValueError("V5 cases changed after freeze; create a new evaluation version")
    split = split_cases(cases, seed=lock["seed"], holdout_fraction=lock["holdout_fraction"])
    if split != {"dev": lock.get("dev_ids"), "holdout": lock.get("holdout_ids")}:
        raise ValueError("V5 split does not match the frozen split lock")
    return lock, split


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--split", choices=("all", "dev", "holdout"), default="all")
    parser.add_argument("--policy", choices=("bm25", "bm25_figure_ocr"), default="bm25")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()

    cases = load_cases()
    lock, split = _validate_frozen_lock(cases)
    selected_ids = set(cases_by_split(split, args.split))
    selected_cases = [case for case in cases if case["case_id"] in selected_ids]
    base_index = PublicKnowledgeIndex()
    index = PublicRetrievalRuntime(base_index) if args.policy == "bm25_figure_ocr" else base_index
    report = evaluate_cases(selected_cases, index, policy=args.policy)
    report["scope"].update({
        "split": args.split,
        "seed": lock["seed"],
        "cases_sha256": lock["cases_sha256"],
        "split_sha256": _sha256(json.dumps(split, sort_keys=True).encode("utf-8")),
    })
    rendered = json.dumps(report, ensure_ascii=False, indent=2) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered, encoding="utf-8", newline="\n")
    print(rendered, end="")


def cases_by_split(split: dict[str, list[str]], selection: str) -> list[str]:
    if selection == "all":
        return [*split["dev"], *split["holdout"]]
    return list(split[selection])


if __name__ == "__main__":
    main()
