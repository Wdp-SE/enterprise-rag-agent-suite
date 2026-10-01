"""Frozen offline evaluation of Autoware change-request planning; no model calls."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
AGENT_ROOT = ROOT / "change-review-agent"
SERVICE_ROOT = ROOT / "versioned-rag-service"
for path in (AGENT_ROOT, SERVICE_ROOT):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from app.change_request import build_request_plan, is_out_of_scope_public_request  # noqa: E402

HERE = Path(__file__).resolve().parent
CASES = HERE / "cases.jsonl"
LOCK = HERE / "split_lock.json"
CORPUS = SERVICE_ROOT / "public_corpus_autoware"
RELATION_STATES = {"verified", "candidate", "unknown", "none"}


def _normalize(text: str) -> str:
    without_connectors = re.sub(r"\b(?:and|or)\b|和", "", text.casefold())
    return re.sub(r"[^\w\u3400-\u9fff]+", "", without_connectors)


def _digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def load_cases() -> list[dict]:
    return [json.loads(line) for line in CASES.read_text(encoding="utf-8").splitlines() if line.strip()]


def validate_cases(cases: list[dict], manifest: dict) -> None:
    ids: set[str] = set()
    family_splits: dict[str, set[str]] = defaultdict(set)
    allowed_versions = set(manifest.get("available_versions", []))
    for case in cases:
        required = {
            "case_id", "family_id", "split", "category", "summary", "expected_change_type",
            "required_clauses", "expected_scope", "expected_relation_state", "target_version", "language",
        }
        if not isinstance(case, dict) or not required.issubset(case):
            raise ValueError("Autoware Agent planning case is missing required fields")
        if not isinstance(case["case_id"], str) or not case["case_id"] or case["case_id"] in ids:
            raise ValueError("case IDs must be unique non-empty strings")
        ids.add(case["case_id"])
        if case["split"] not in {"dev", "holdout"}:
            raise ValueError(f"invalid split in {case['case_id']}")
        family_splits[case["family_id"]].add(case["split"])
        if family_splits[case["family_id"]] - {case["split"]}:
            raise ValueError(f"family split leakage: {case['family_id']}")
        if case["target_version"] not in allowed_versions:
            raise ValueError(f"unknown target version in {case['case_id']}")
        if case["language"] not in {"zh", "en", "all"}:
            raise ValueError(f"invalid language in {case['case_id']}")
        if case["expected_scope"] not in {"public", "out_of_scope"}:
            raise ValueError(f"invalid scope in {case['case_id']}")
        if case["expected_relation_state"] not in RELATION_STATES:
            raise ValueError(f"invalid relationship state in {case['case_id']}")
        if not isinstance(case["required_clauses"], list) or not case["required_clauses"]:
            raise ValueError(f"required clauses missing in {case['case_id']}")


def evaluate(cases: list[dict]) -> dict:
    details = []
    totals: Counter[str] = Counter()
    by_category: dict[str, Counter[str]] = defaultdict(Counter)
    by_language: dict[str, Counter[str]] = defaultdict(Counter)
    for case in cases:
        plan = build_request_plan(case["summary"])
        guarded = is_out_of_scope_public_request(case["summary"])
        actual_type = plan["change_type"]
        type_ok = actual_type == case["expected_change_type"]
        scope_ok = ("out_of_scope" if guarded else "public") == case["expected_scope"]
        clause_queries = [row["query"] for row in plan["queries"] if row["kind"] == "change_clause"]
        normalized_query_text = "".join(_normalize(query) for query in clause_queries)
        matched = [
            _normalize(clause) in normalized_query_text
            for clause in case["required_clauses"]
        ]
        budget_ok = len(plan["queries"]) <= plan["query_limit"] <= 4
        for name, passed in (("type_correct", type_ok), ("scope_correct", scope_ok), ("within_budget", budget_ok)):
            totals[name] += int(passed)
            by_category[case["category"]][name] += int(passed)
            by_language[case["language"]][name] += int(passed)
        totals["cases"] += 1
        totals["clauses_covered"] += sum(matched)
        totals["clauses_total"] += len(matched)
        for group in (by_category[case["category"]], by_language[case["language"]]):
            group["cases"] += 1
            group["clauses_covered"] += sum(matched)
            group["clauses_total"] += len(matched)
        details.append({
            "case_id": case["case_id"], "category": case["category"],
            "language": case["language"], "expected_change_type": case["expected_change_type"],
            "actual_change_type": actual_type, "type_correct": type_ok,
            "expected_scope": case["expected_scope"], "scope_guard_triggered": guarded,
            "scope_correct": scope_ok,
            "required_clause_coverage": f"{sum(matched)}/{len(matched)}",
            "query_count": len(plan["queries"]), "query_budget": plan["query_limit"],
            "within_budget": budget_ok, "target_version": case["target_version"],
            "expected_relation_state": case["expected_relation_state"],
        })

    def summarize(groups: dict[str, Counter[str]]) -> dict:
        result = {}
        for key, values in sorted(groups.items()):
            count = values["cases"]
            result[key] = {
                "case_count": count,
                "change_type_accuracy": round(values["type_correct"] / count, 4) if count else 0,
                "scope_guard_accuracy": round(values["scope_correct"] / count, 4) if count else 0,
                "query_budget_compliance": round(values["within_budget"] / count, 4) if count else 0,
                "required_clause_coverage": round(values["clauses_covered"] / values["clauses_total"], 4) if values["clauses_total"] else 0,
            }
        return result

    count = totals["cases"]
    return {
        "schema_version": 1,
        "evaluation": "autoware_agent_query_planning_v1",
        "scope": "Hand-curated deterministic planner and public-scope guard cases; no RAG retrieval or model generation is executed.",
        "case_count": count,
        "generation_api_calls": 0,
        "metrics": {
            "change_type_accuracy": round(sum(row["type_correct"] for row in details) / count, 4) if count else 0,
            "scope_guard_accuracy": round(sum(row["scope_correct"] for row in details) / count, 4) if count else 0,
            "query_budget_compliance": round(sum(row["within_budget"] for row in details) / count, 4) if count else 0,
            "required_clause_coverage": round(totals["clauses_covered"] / totals["clauses_total"], 4) if totals["clauses_total"] else 0,
            "required_clauses_covered": totals["clauses_covered"],
            "required_clauses_total": totals["clauses_total"],
        },
        "by_category": summarize(by_category),
        "by_language": summarize(by_language),
        "details": details,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--split", choices=("all", "dev", "holdout"), default="all")
    parser.add_argument("--output", type=Path, default=HERE / "results" / "report.json")
    args = parser.parse_args()
    cases = load_cases()
    validate_cases(cases, json.loads((CORPUS / "corpus_manifest.json").read_text(encoding="utf-8")))
    lock = json.loads(LOCK.read_text(encoding="utf-8"))
    if _digest(CASES.read_bytes()) != lock.get("cases_sha256"):
        raise ValueError("frozen Agent cases changed; create a new evaluation version")
    selected = [row for row in cases if args.split == "all" or row["split"] == args.split]
    report = evaluate(selected)
    report["run_metadata"] = {
        "split": args.split, "cases_sha256": lock["cases_sha256"],
        "corpus_manifest_sha256": _digest((CORPUS / "corpus_manifest.json").read_bytes()),
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")
    print(json.dumps({"metrics": report["metrics"], "by_category": report["by_category"], "by_language": report["by_language"]}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
