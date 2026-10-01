"""Curate bounded Agent retrieval scenarios from the V2 source-locked RAG set.

These are scope-anchor scenarios for retrieval coverage, not human-confirmed
impact truth. Model impact quality remains unevaluated until a human reviews
saved outputs against an independent impact rubric.
"""

from __future__ import annotations

import hashlib
import json
from collections import Counter
from pathlib import Path

from run_rag_benchmark import CORPUS, HERE, load_rag_cases
from run_agent_evaluation import _source_family

import sys

AGENT_ROOT = HERE.parents[1] / "change-review-agent"
if str(AGENT_ROOT) not in sys.path:
    sys.path.insert(0, str(AGENT_ROOT))
from app.change_request import CHANGE_TYPES, classify_change_type  # noqa: E402
from src.document_relations import DocumentRelationIndex  # noqa: E402


def _jsonl_bytes(rows: list[dict]) -> bytes:
    return "".join(
        json.dumps(row, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n"
        for row in rows
    ).encode("utf-8")


def _relation_state(registry: DocumentRelationIndex, source_id: str) -> str:
    rows = registry.for_document(source_id)
    if not rows:
        return "none"
    priority = {"verified": 0, "candidate": 1, "unknown": 2}
    return min((row["verification_status"] for row in rows), key=priority.__getitem__)


def curate_agent_cases() -> dict:
    manifest = json.loads((CORPUS / "corpus_manifest.json").read_text(encoding="utf-8"))
    registry = DocumentRelationIndex.from_corpus(CORPUS, manifest)
    rag_cases = load_rag_cases()
    rows: list[dict] = []
    used_families: set[tuple[str, str]] = set()
    for split in ("dev", "holdout"):
        answerable = {}
        no_answer = []
        for case in rag_cases:
            if case["split"] != split:
                continue
            if not case["answerable"]:
                no_answer.append(case)
                continue
            # One scenario per independently assigned source family. Cross-source
            # expectations remain grouped rather than multiplying near-duplicates.
            answerable.setdefault(case["family_id"], case)
        for index, case in enumerate(answerable.values(), 1):
            sources = list(dict.fromkeys(case["required_sources"]))
            query = case["query"].strip().rstrip("？?。")
            if case["query_language"] == "zh":
                summary = f"假设相关功能或接口发生变更，请核对以下资料问题：{query}。"
            else:
                summary = f"Assume a change to the related behavior or interface; verify these source facts: {query}."
            change_type = classify_change_type(summary)
            if change_type not in CHANGE_TYPES:
                change_type = "general"
            severity = (
                "high" if change_type in {"planning_behavior", "security_permission"}
                else "medium" if change_type in {"interface_compatibility", "data_storage"}
                else "low"
            )
            relation_states = {source_id: _relation_state(registry, source_id) for source_id in sources}
            rows.append({
                "case_id": f"{split}-review-anchor-{index:02d}",
                "family_id": f"review:{case['family_id']}",
                "split": split,
                "language": "bilingual",
                "target_version": case["version"],
                "change_type": change_type,
                "severity": severity,
                "change_summary": summary,
                "required_impact_sources": sources,
                "required_checklist_items": list(CHANGE_TYPES[change_type]["checklist"]),
                "expected_relation_states": relation_states,
                "expected_gaps": (
                    ["UNVERIFIED_TRANSLATION"]
                    if any(state in {"candidate", "unknown"} for state in relation_states.values())
                    else []
                ),
                "critical_source_ids": sources[:1] if severity == "high" else [],
                "expected_abstain": False,
                "label_scope": "retrieval_scope_anchor_only_not_confirmed_impact",
                "source_rag_case_id": case["case_id"],
            })
            used_families.add((split, case["family_id"]))
        for index, case in enumerate(no_answer, 1):
            summary = (
                f"请从当前公开资料确认以下问题；若语料没有证据，不得推测：{case['query']}"
            )
            rows.append({
                "case_id": f"{split}-review-no-answer-{index:02d}",
                "family_id": f"review:no-answer:{split}:{index:02d}",
                "split": split,
                "language": "bilingual",
                "target_version": case["version"],
                "change_type": "general",
                "severity": "high",
                "change_summary": summary,
                "required_impact_sources": [],
                "required_checklist_items": list(CHANGE_TYPES["general"]["checklist"]),
                "expected_relation_states": {},
                "expected_gaps": ["OUT_OF_SCOPE_PUBLIC_CORPUS"],
                "critical_source_ids": [],
                "expected_abstain": True,
                "label_scope": "public_scope_guard_probe_not_impact_truth",
                "source_rag_case_id": case["case_id"],
            })
    rows.sort(key=lambda row: row["case_id"])
    raw = _jsonl_bytes(rows)
    (HERE / "agent_cases.jsonl").write_bytes(raw)
    lock_path = HERE / "split_lock.json"
    lock = json.loads(lock_path.read_text(encoding="utf-8"))
    lock["agent_cases_sha256"] = hashlib.sha256(raw).hexdigest()
    lock["agent_case_count"] = len(rows)
    lock["agent_split_counts"] = dict(sorted(Counter(row["split"] for row in rows).items()))
    lock["agent_label_scope"] = (
        "source anchors transferred from RAG cases; not independently confirmed true impact; "
        "model impact metrics unavailable until human-reviewed saved answers"
    )
    lock_path.write_text(json.dumps(lock, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")
    return {
        "case_count": len(rows),
        "split_counts": dict(sorted(Counter(row["split"] for row in rows).items())),
        "label_scope": lock["agent_label_scope"],
    }


if __name__ == "__main__":
    print(json.dumps(curate_agent_cases(), ensure_ascii=False, indent=2))
