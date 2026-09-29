"""Small deterministic evaluation of the change-request query planner.

This measures rule classification, preservation of annotated sub-requests, and
query-budget enforcement. It is not a RAG answer-quality or production KPI.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
AGENT_APP = ROOT / "change-review-agent"
CASES = Path(__file__).with_name("cases.jsonl")
if str(AGENT_APP) not in sys.path:
    sys.path.insert(0, str(AGENT_APP))

from app.change_request import build_request_plan  # noqa: E402


def evaluate(cases: list[dict]) -> dict:
    type_correct = 0
    covered_clauses = 0
    total_clauses = 0
    within_budget = 0
    rows = []
    for case in cases:
        plan = build_request_plan(case["summary"])
        actual_type = plan["change_type"]
        type_ok = actual_type == case["change_type"]
        type_correct += int(type_ok)
        clause_queries = [row["query"] for row in plan["queries"] if row["kind"] == "change_clause"]
        normalized_queries = [re.sub(r"[\W_]+", "", query.casefold()) for query in clause_queries]
        matched = [
            any(
                re.sub(r"[\W_]+", "", required.casefold()) in query
                for query in normalized_queries
            )
            for required in case["required_clauses"]
        ]
        covered_clauses += sum(matched)
        total_clauses += len(matched)
        budget_ok = len(plan["queries"]) <= plan["query_limit"]
        within_budget += int(budget_ok)
        rows.append({
            "case_id": case["case_id"],
            "expected_type": case["change_type"],
            "actual_type": actual_type,
            "type_correct": type_ok,
            "required_clause_coverage": f"{sum(matched)}/{len(matched)}",
            "query_count": len(plan["queries"]),
            "query_budget": plan["query_limit"],
            "within_budget": budget_ok,
        })
    count = len(cases)
    return {
        "evaluation": "agent_query_decomposition_v1",
        "scope": "hand-curated deterministic planner cases; not end-to-end retrieval or answer quality",
        "case_count": count,
        "change_type_accuracy": round(type_correct / count, 4) if count else 0,
        "required_clause_coverage": round(covered_clauses / total_clauses, 4) if total_clauses else 0,
        "query_budget_compliance": round(within_budget / count, 4) if count else 0,
        "covered_required_clauses": covered_clauses,
        "total_required_clauses": total_clauses,
        "details": rows,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    cases = [json.loads(line) for line in CASES.read_text(encoding="utf-8").splitlines() if line.strip()]
    report = evaluate(cases)
    rendered = json.dumps(report, ensure_ascii=False, indent=2) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered, encoding="utf-8")
    print(rendered, end="")


if __name__ == "__main__":
    main()
