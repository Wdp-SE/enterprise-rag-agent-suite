"""Offline, frozen Autoware retrieval-quality benchmark. It never calls an LLM."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import statistics
import sys
import time
from collections import Counter, defaultdict
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SERVICE = ROOT / "versioned-rag-service"
sys.path.insert(0, str(SERVICE))

from src.document_relations import DocumentRelationIndex  # noqa: E402
from src.public_knowledge import PublicKnowledgeIndex  # noqa: E402
from src.public_retrieval_runtime import PublicRetrievalRuntime, POLICIES  # noqa: E402


HERE = Path(__file__).resolve().parent
CORPUS = SERVICE / "public_corpus_autoware"
CATEGORIES = frozenset({
    "single_fact", "cross_source", "explicit_version", "zh_query_en_evidence",
    "en_query_zh_evidence", "translation_relation_state", "image_evidence",
    "unanswerable_scope",
})
RELATION_STATES = frozenset({"verified", "candidate", "unknown", "none"})
DEFAULT_POLICIES = ("bm25", "bm25_faceted_rrf", "bm25_figure_ocr", "bm25_faceted_figure_ocr", "hybrid")


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _portable_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes().replace(b"\r\n", b"\n")).hexdigest()


def validate_cases(cases: list[dict], known_sources: dict[str, dict | str]) -> None:
    """Validate exact source identities and ensure no document family crosses splits."""
    required_fields = {
        "case_id", "family_id", "split", "category", "query", "query_language",
        "version", "language", "required_sources", "required_answer_points",
        "expected_image_ids", "answerable", "expected_relation_state",
        "expected_component_versions",
    }
    ids = set()
    family_splits: dict[str, set[str]] = defaultdict(set)
    for case in cases:
        if not isinstance(case, dict) or not required_fields.issubset(case):
            raise ValueError("quality case is missing required fields")
        case_id = case["case_id"]
        family_id = case["family_id"]
        if not isinstance(case_id, str) or not case_id or case_id in ids:
            raise ValueError("quality case IDs must be unique non-empty strings")
        if not isinstance(family_id, str) or not family_id:
            raise ValueError(f"invalid family_id for {case_id}")
        ids.add(case_id)
        if case["split"] not in {"dev", "holdout"} or case["category"] not in CATEGORIES:
            raise ValueError(f"invalid split/category for {case_id}")
        family_splits[family_id].add(case["split"])
        if family_splits[family_id] - {case["split"]}:
            raise ValueError(f"family split leakage: {family_id}")
        if not isinstance(case["query"], str) or not case["query"].strip():
            raise ValueError(f"empty query for {case_id}")
        if not isinstance(case["answerable"], bool) or not isinstance(case["required_sources"], list):
            raise ValueError(f"invalid answerability/source annotations for {case_id}")
        if case["answerable"] != bool(case["required_sources"]):
            raise ValueError(f"answerability disagrees with required sources for {case_id}")
        if case["expected_relation_state"] not in RELATION_STATES:
            raise ValueError(f"invalid relation state for {case_id}")
        versions = case["expected_component_versions"]
        if not isinstance(versions, dict) or not versions:
            raise ValueError(f"missing component version map for {case_id}")
        if not set(versions).issubset({"documentation", "universe"}):
            raise ValueError(f"unknown component in version map for {case_id}")
        for source_id in case["required_sources"]:
            if source_id not in known_sources:
                raise ValueError(f"unknown required source {source_id} for {case_id}")
            row = known_sources[source_id]
            source_version = row if isinstance(row, str) else row.get("version")
            if source_version not in versions.values():
                raise ValueError(f"source version is outside selected scope for {case_id}: {source_id}")


def _component_for_document(document_key: str) -> str:
    return "universe" if document_key.startswith("planning/") else "documentation"


def _summary(cases: list[dict], hits_by_case: dict[str, list[dict]],
             latency_by_case: dict[str, list[float]], operations_by_case: dict[str, int]) -> dict:
    required_total = required_hit_total = complete_count = 0
    answerable_count = no_answer_count = no_answer_candidates = 0
    expected_image_total = image_hit_total = wrong_version_count = explicit_wrong_version_count = 0
    total_hit_count = 0
    reciprocal_ranks = []
    ndcgs = []
    case_rows = []
    all_latencies = []
    for case in cases:
        hits = [row for row in hits_by_case.get(case["case_id"], []) if _positive_hit(row)]
        # Retrieval is chunk-level, while source coverage/rank metrics are
        # document-level. A document can contribute multiple chunks, but it
        # must occupy only its best rank once in MRR/NDCG and source metrics.
        ranked_hits = []
        seen_document_ids = set()
        for row in hits[:5]:
            document_id = str(row.get("document_id", ""))
            if not document_id or document_id in seen_document_ids:
                continue
            seen_document_ids.add(document_id)
            ranked_hits.append(row)
        required = set(case["required_sources"])
        ranked_ids = [str(row.get("document_id", "")) for row in ranked_hits]
        found = required.intersection(ranked_ids)
        if case["answerable"]:
            answerable_count += 1
            required_total += len(required)
            required_hit_total += len(found)
            complete_count += int(found == required)
            ranks = [rank for rank, doc_id in enumerate(ranked_ids, start=1) if doc_id in required]
            reciprocal_ranks.append(sum(1 / rank for rank in ranks) / len(required) if required else 0.0)
            gains = [1.0 if doc_id in required else 0.0 for doc_id in ranked_ids]
            dcg = sum(gain / math.log2(rank + 1) for rank, gain in enumerate(gains, start=1))
            ideal = sum(1 / math.log2(rank + 1) for rank in range(1, min(len(required), 5) + 1))
            ndcgs.append(dcg / ideal if ideal else 0.0)
        else:
            no_answer_count += 1
            no_answer_candidates += int(bool(hits))
        expected_images = set(case["expected_image_ids"])
        found_images = {
            str(row.get("figure_id")) for row in hits
            if row.get("modality") == "image_ocr" and row.get("figure_id")
        }
        expected_image_total += len(expected_images)
        image_hit_total += len(expected_images & found_images)
        mismatches = []
        component_versions = case["expected_component_versions"]
        for row in ranked_hits:
            total_hit_count += 1
            component = _component_for_document(str(row.get("document_key", "")))
            expected_version = component_versions.get(component)
            if expected_version and row.get("version") != expected_version:
                wrong_version_count += 1
                mismatches.append({"document_id": row.get("document_id"), "version": row.get("version")})
                if case["category"] == "explicit_version":
                    explicit_wrong_version_count += 1
        samples = latency_by_case.get(case["case_id"], [])
        all_latencies.extend(samples)
        case_rows.append({
            "case_id": case["case_id"], "required_sources": sorted(required),
            "found_sources_at_5": sorted(found),
            "expected_image_ids": sorted(expected_images),
            "found_image_ids_at_5": sorted(expected_images & found_images),
            "hit_document_ids_at_5": ranked_ids,
            "version_mismatches_at_5": mismatches,
        })
    ordered_latencies = sorted(all_latencies)
    p95 = ordered_latencies[max(0, math.ceil(len(ordered_latencies) * 0.95) - 1)] if ordered_latencies else 0.0
    return {
        "query_count": len(cases),
        "answerable_count": answerable_count,
        "no_answer_count": no_answer_count,
        "required_source_recall_at_5": round(required_hit_total / required_total, 4) if required_total else 1.0,
        "complete_required_sources_at_5": round(complete_count / answerable_count, 4) if answerable_count else 1.0,
        "mrr_at_5": round(statistics.mean(reciprocal_ranks), 4) if reciprocal_ranks else 1.0,
        "ndcg_at_5": round(statistics.mean(ndcgs), 4) if ndcgs else 1.0,
        "version_mismatch_count": wrong_version_count,
        "version_mismatch_rate_at_5": round(wrong_version_count / total_hit_count, 4) if total_hit_count else 0.0,
        "explicit_version_mismatch_count": explicit_wrong_version_count,
        "image_evidence_hit_at_5": round(image_hit_total / expected_image_total, 4) if expected_image_total else 1.0,
        "image_evidence_hits": f"{image_hit_total}/{expected_image_total}",
        "no_answer_nonempty_candidate_rate": round(no_answer_candidates / no_answer_count, 4) if no_answer_count else 0.0,
        "no_answer_nonempty_candidates": f"{no_answer_candidates}/{no_answer_count}",
        "search_p50_ms": round(statistics.median(all_latencies), 3) if all_latencies else 0.0,
        "search_p95_ms": round(p95, 3),
        "mean_retrieval_operations_per_query": round(
            statistics.mean(operations_by_case.get(case["case_id"], 1) for case in cases), 3
        ) if cases else 0.0,
        "cases": case_rows,
    }


def _positive_hit(row: dict) -> bool:
    score = row.get("retrieval_score", 0)
    return isinstance(score, (int, float)) and not isinstance(score, bool) and math.isfinite(score) and score > 0


def evaluate_results(cases: list[dict], hits_by_case: dict[str, list[dict]],
                     latency_by_case: dict[str, list[float]],
                     operations_by_case: dict[str, int] | None = None) -> dict:
    operations_by_case = operations_by_case or {}
    result = _summary(cases, hits_by_case, latency_by_case, operations_by_case)
    result["by_category"] = {
        category: _summary(
            [row for row in cases if row["category"] == category],
            hits_by_case, latency_by_case, operations_by_case,
        )
        for category in sorted({row["category"] for row in cases})
    }
    result["metric_scope"] = (
        "retrieval candidate coverage only; a non-empty no-answer result is not a false answer, "
        "and these metrics do not establish generated-answer accuracy"
    )
    return result


def select_policy(results: dict, policy_order: tuple[str, ...] | None = None) -> dict:
    """Promote only a candidate that wins on holdout and passes every safety gate."""
    if "bm25" not in results or "dev" not in results["bm25"] or "holdout" not in results["bm25"]:
        raise ValueError("BM25 dev and holdout baselines are required")
    baseline = results["bm25"]
    order = policy_order or tuple(results)
    decisions = {}
    eligible = []
    for policy in order:
        if policy == "bm25" or policy not in results:
            continue
        reasons = []
        gains = []
        for split in ("dev", "holdout"):
            candidate = results[policy].get(split, {})
            control = baseline[split]
            checks = {
                "required_source_recall_noninferior": candidate.get("required_source_recall_at_5", -1) >= control.get("required_source_recall_at_5", 0),
                "complete_source_rate_noninferior": candidate.get("complete_required_sources_at_5", -1) >= control.get("complete_required_sources_at_5", 0),
                "no_answer_candidate_rate_noninferior": candidate.get("no_answer_nonempty_candidate_rate", math.inf) <= control.get("no_answer_nonempty_candidate_rate", 0),
                "explicit_version_errors_zero": candidate.get("explicit_version_mismatch_count", -1) == 0,
                "all_version_errors_zero": candidate.get("version_mismatch_count", -1) == 0,
                "retrieval_latency_within_20_percent": candidate.get("search_p95_ms", math.inf) <= max(control.get("search_p95_ms", 0) * 1.2, 1.0),
            }
            for name, passed in checks.items():
                if not passed:
                    reasons.append(f"{split}:{name}")
            if split == "holdout":
                gains = [
                    candidate.get("required_source_recall_at_5", 0) > control.get("required_source_recall_at_5", 0),
                    candidate.get("complete_required_sources_at_5", 0) > control.get("complete_required_sources_at_5", 0),
                    candidate.get("image_evidence_hit_at_5", 0) > control.get("image_evidence_hit_at_5", 0),
                ]
        if not any(gains):
            reasons.append("holdout:no_objective_gain")
        decisions[policy] = {"eligible": not reasons, "failed_gates": reasons}
        if not reasons:
            eligible.append(policy)
    eligible.sort(key=lambda policy: (
        results[policy]["holdout"].get("mean_retrieval_operations_per_query", 1),
        results[policy]["holdout"].get("search_p95_ms", math.inf),
        order.index(policy),
    ))
    selected = eligible[0] if eligible else "bm25"
    return {
        "selected_policy": selected,
        "eligible_candidates": eligible,
        "candidate_decisions": decisions,
        "reason": (
            "Selected the simplest candidate with a holdout gain after dev/holdout source-coverage, "
            "version-correctness, no-answer-candidate and latency gates."
            if eligible else "No candidate passed every dev and holdout gate; keep BM25."
        ),
    }


def _load_cases() -> tuple[list[dict], dict]:
    cases_path = HERE / "cases.jsonl"
    lock_path = HERE / "split_lock.json"
    lock = json.loads(lock_path.read_text(encoding="utf-8"))
    cases = [json.loads(line) for line in cases_path.read_text(encoding="utf-8").splitlines() if line.strip()]
    if lock.get("cases_sha256") != _portable_sha256(cases_path):
        raise ValueError("quality-v1 cases differ from the frozen split lock")
    ids = [row.get("case_id") for row in cases]
    if len(cases) != lock.get("case_count") or sorted(ids) != lock.get("case_ids"):
        raise ValueError("quality-v1 case IDs/count differ from the frozen split lock")
    if lock.get("corpus_manifest_sha256") != _portable_sha256(CORPUS / "corpus_manifest.json"):
        raise ValueError("quality-v1 split lock does not match current corpus manifest")
    if lock.get("relation_registry_sha256") != _portable_sha256(CORPUS / "document_relations.json"):
        raise ValueError("quality-v1 split lock does not match current relationship registry")
    return cases, lock


def _fingerprint() -> dict:
    runtime_config = json.loads((CORPUS / "public_retrieval_runtime.json").read_text(encoding="utf-8"))
    behavior = dict(runtime_config)
    behavior.pop("default_policy", None)
    behavior_sha = hashlib.sha256(json.dumps(behavior, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()
    paths = {
        "corpus_manifest": CORPUS / "corpus_manifest.json",
        "relation_registry": CORPUS / "document_relations.json",
        "retrieval_policy": CORPUS / "retrieval_policy.json",
        "chunks": CORPUS / "chunks.json",
        "dense_vectors": CORPUS / "dense_vectors.npy",
        "figure_inventory": CORPUS / "figure_evidence.json",
        "reviewed_figure_sidecar": CORPUS / "figure_evidence_reviewed.json",
        "reviewed_figure_lock": CORPUS / "figure_evidence_reviewed.lock.json",
        "public_knowledge": SERVICE / "src" / "public_knowledge.py",
        "public_retrieval_runtime": SERVICE / "src" / "public_retrieval_runtime.py",
        "retrieval_fusion": SERVICE / "src" / "retrieval_fusion.py",
        "document_relations": SERVICE / "src" / "document_relations.py",
        "case_curator": HERE / "curate_cases.py",
        "cases": HERE / "cases.jsonl",
        "split_lock": HERE / "split_lock.json",
        "runner": Path(__file__),
    }
    result = {key: _portable_sha256(path) for key, path in paths.items()}
    # Binary NumPy indexes are hashed byte-for-byte; CRLF normalization is only
    # for portable text artifacts and could otherwise alter arbitrary binary data.
    result["dense_vectors"] = _sha256(paths["dense_vectors"])
    result["runtime_config_behavior"] = behavior_sha
    return result


def run_benchmark(*, repeats: int = 3, policies: tuple[str, ...] = DEFAULT_POLICIES) -> dict:
    if not 1 <= repeats <= 20:
        raise ValueError("repeats must be between 1 and 20")
    if "bm25" not in policies or len(set(policies)) != len(policies) or any(policy not in POLICIES for policy in policies):
        raise ValueError("policies must be unique supported policies and include bm25")
    cases, lock = _load_cases()
    index = PublicKnowledgeIndex(root=CORPUS)
    known_sources = {
        f"{row['version']}:{row['language']}:{row['document_key']}": row
        for row in index.manifest["sources"]
    }
    validate_cases(cases, known_sources)
    relation_index = DocumentRelationIndex.from_corpus(CORPUS, index.manifest)
    if not relation_index.available:
        raise ValueError("document relationship registry is invalid; cannot evaluate relation-state cases")
    runtime = PublicRetrievalRuntime(
        index,
        config_path=CORPUS / "public_retrieval_runtime.json",
        sidecar_path=CORPUS / "figure_evidence_reviewed.json",
    )
    report = {
        "schema_version": 1,
        "name": "autoware_quality_v1",
        "workspace": index.manifest["workspace"],
        "scope": "Pinned Autoware public snapshots; latest = Documentation main + Universe 0.52.0.",
        "metric_scope": "Retrieval coverage only; answer semantics require the separate human-reviewed saved-answer evaluator.",
        "case_count": len(cases), "case_split_counts": lock["split_counts"],
        "category_counts": dict(sorted(Counter(row["category"] for row in cases).items())),
        "corpus_manifest_sha256": _portable_sha256(CORPUS / "corpus_manifest.json"),
        "relation_registry_sha256": _portable_sha256(CORPUS / "document_relations.json"),
        "cases_sha256": _portable_sha256(HERE / "cases.jsonl"),
        "runtime_fingerprint": _fingerprint(),
        "repeats_per_case": repeats,
        "splits": {},
    }
    for split in ("dev", "holdout"):
        selected = [case for case in cases if case["split"] == split]
        report["splits"][split] = {}
        for policy in policies:
            hits_by_case: dict[str, list[dict]] = {}
            latency_by_case: dict[str, list[float]] = {}
            operations_by_case: dict[str, int] = {}
            for case in selected:
                samples = []
                last_hits = []
                calls = []
                for _ in range(repeats):
                    started = time.perf_counter()
                    rows = runtime.search(
                        case["query"], top_k=5, version=case["version"],
                        language=case["language"], policy=policy,
                    )
                    samples.append((time.perf_counter() - started) * 1000)
                    calls.append(runtime.last_retrieval_call_count)
                    last_hits = rows
                for row in last_hits:
                    row["document_relationships"] = relation_index.for_document(str(row.get("document_id", "")))
                hits_by_case[case["case_id"]] = last_hits
                latency_by_case[case["case_id"]] = samples
                operations_by_case[case["case_id"]] = max(calls, default=0)
            report["splits"][split][policy] = evaluate_results(
                selected, hits_by_case, latency_by_case, operations_by_case,
            )
    policies_results = {
        policy: {
            split: report["splits"][split][policy]
            for split in ("dev", "holdout")
        }
        for policy in policies
    }
    report["selection"] = select_policy(policies_results, policies)
    report["limitations"] = [
        "Cases are curated diagnostic examples, not a representative production request distribution.",
        "Retrieval results do not establish answer accuracy or hallucination rate.",
        "A non-empty candidate set on an unanswerable query is not itself a generated false answer.",
        "Latency is local process-level warm/first-run timing, not hosted end-to-end latency.",
        "Only manually reviewed figure text in the pinned sidecar is counted as image evidence.",
    ]
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--policy", choices=POLICIES, help="run one policy; defaults to the full comparison")
    parser.add_argument("--repeats", type=int, default=3)
    parser.add_argument("--output", type=Path, default=HERE / "results" / "benchmark.json")
    args = parser.parse_args()
    policies = (args.policy,) if args.policy else DEFAULT_POLICIES
    report = run_benchmark(repeats=args.repeats, policies=policies)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")
    print(json.dumps({
        "selection": report["selection"],
        "splits": {
            split: {
                policy: {key: value for key, value in metrics.items() if key not in {"cases", "by_category"}}
                for policy, metrics in rows.items()
            }
            for split, rows in report["splits"].items()
        },
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
