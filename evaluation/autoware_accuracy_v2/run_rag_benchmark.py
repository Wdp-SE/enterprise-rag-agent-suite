"""Measure retrieval quality on the independently locked Autoware V2 cases."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
import statistics
import sys
import time
import unicodedata
from collections import defaultdict
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SERVICE = ROOT / "versioned-rag-service"
CORPUS = SERVICE / "public_corpus_autoware"
HERE = Path(__file__).resolve().parent
RAG_CASES = HERE / "rag_cases.jsonl"
IMAGE_REGRESSION_CASES = HERE / "image_regression_cases.jsonl"
SPLIT_LOCK = HERE / "split_lock.json"
QUALITY_V1 = ROOT / "evaluation" / "autoware_quality_v1"
RAG_CATEGORIES = frozenset({
    "single_fact", "cross_source", "explicit_version", "zh_query_en_evidence",
    "en_query_zh_evidence", "translation_relation_state", "unanswerable_scope",
})
IMAGE_CATEGORIES = frozenset({"image_evidence"})
RELATION_STATES = frozenset({"verified", "candidate", "unknown", "none"})
OFFLINE_EXPERIMENT_POLICIES = frozenset({"hybrid_figure_ocr"})

sys.path.insert(0, str(SERVICE))
from src.document_relations import DocumentRelationIndex  # noqa: E402
from src.public_knowledge import PublicKnowledgeIndex  # noqa: E402
from src.public_retrieval_runtime import POLICIES, PublicRetrievalRuntime  # noqa: E402


def _portable_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes().replace(b"\r\n", b"\n")).hexdigest()


def _binary_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def normalize_query(query: str) -> str:
    normalized = unicodedata.normalize("NFKC", query).casefold()
    return "".join(character for character in normalized if character.isalnum())


def _source_id(source: dict) -> str:
    return f"{source['version']}:{source['language']}:{source['document_key']}"


def _source_family(source_id: str) -> str:
    parts = source_id.split(":", 2)
    if len(parts) != 3:
        raise ValueError(f"invalid source ID: {source_id}")
    return f"{_component_for_document(parts[2])}:{parts[2]}"


def _component_for_document(document_key: str) -> str:
    return "universe" if document_key.startswith("planning/") else "documentation"


def load_rag_cases(path: Path = RAG_CASES) -> list[dict]:
    return [json.loads(line) for line in Path(path).read_text(encoding="utf-8").splitlines() if line.strip()]


def load_image_regression_cases(path: Path = IMAGE_REGRESSION_CASES) -> list[dict]:
    return [json.loads(line) for line in Path(path).read_text(encoding="utf-8").splitlines() if line.strip()]


def validate_rag_cases(
    cases: list[dict],
    known_sources: dict[str, dict | str],
    *,
    forbidden_families: set[str],
    forbidden_queries: set[str],
    known_images: set[str] | None = None,
    allowed_splits: set[str] | None = None,
    forbidden_source_families: set[str] | None = None,
) -> None:
    """Validate new text cases against exact corpus sources and locked family/query splits."""
    required_fields = {
        "case_id", "family_id", "split", "category", "query", "query_language",
        "version", "expected_component_versions", "language", "required_sources",
        "required_answer_points", "answerable", "expected_relation_state",
    }
    ids: set[str] = set()
    queries: set[str] = set()
    family_splits: dict[str, set[str]] = defaultdict(set)
    source_family_splits: dict[str, set[str]] = defaultdict(set)
    permitted_splits = allowed_splits or {"dev", "holdout"}
    for case in cases:
        if not isinstance(case, dict) or not required_fields.issubset(case):
            raise ValueError("RAG case is missing required fields")
        case_id = case["case_id"]
        family_id = case["family_id"]
        if not isinstance(case_id, str) or not case_id.strip() or case_id in ids:
            raise ValueError("RAG case IDs must be unique non-empty strings")
        if not isinstance(family_id, str) or not family_id.strip():
            raise ValueError(f"invalid family_id for {case_id}")
        ids.add(case_id)
        split = case["split"]
        permitted_categories = RAG_CATEGORIES | (IMAGE_CATEGORIES if permitted_splits == {"regression"} else frozenset())
        if split not in permitted_splits or case["category"] not in permitted_categories:
            raise ValueError(f"invalid split/category for {case_id}")
        if split == "holdout" and family_id in forbidden_families:
            raise ValueError(f"family is present in the forbidden V1 HOLDOUT set: {family_id}")
        family_splits[family_id].add(split)
        if len(family_splits[family_id]) > 1:
            raise ValueError(f"family split leakage: {family_id}")

        query = case["query"]
        if not isinstance(query, str) or not query.strip():
            raise ValueError(f"empty query for {case_id}")
        normalized = normalize_query(query)
        if not normalized or normalized in queries:
            raise ValueError(f"duplicate normalized query for {case_id}")
        if normalized in forbidden_queries:
            raise ValueError(f"query overlaps the V1 set: {case_id}")
        queries.add(normalized)

        if case["query_language"] not in {"zh", "en"} or case["language"] not in {"zh", "en", "all"}:
            raise ValueError(f"invalid query/evidence language for {case_id}")
        if not isinstance(case["answerable"], bool) or not isinstance(case["required_sources"], list):
            raise ValueError(f"invalid answerability/source annotation for {case_id}")
        if any(not isinstance(source_id, str) for source_id in case["required_sources"]):
            raise ValueError(f"required source IDs must be strings for {case_id}")
        if len(case["required_sources"]) != len(set(case["required_sources"])):
            raise ValueError(f"duplicate required sources for {case_id}")
        if case["answerable"] != bool(case["required_sources"]):
            raise ValueError(f"answerability disagrees with required sources for {case_id}")
        points = case["required_answer_points"]
        if not isinstance(points, list) or any(not isinstance(point, str) or not point.strip() for point in points):
            raise ValueError(f"invalid required answer points for {case_id}")
        if case["answerable"] and not points:
            raise ValueError(f"answerable RAG case has no required answer points: {case_id}")
        if not case["answerable"] and points:
            raise ValueError(f"unanswerable RAG case must not have required answer points: {case_id}")
        if case["expected_relation_state"] not in RELATION_STATES:
            raise ValueError(f"invalid relation state for {case_id}")

        versions = case["expected_component_versions"]
        if not isinstance(versions, dict) or not versions or not set(versions).issubset({"documentation", "universe"}):
            raise ValueError(f"missing/invalid component version map for {case_id}")
        for source_id in case["required_sources"]:
            if source_id not in known_sources:
                raise ValueError(f"unknown required source {source_id} for {case_id}")
            source = known_sources[source_id]
            if isinstance(source, str):
                source_version = source
                component = _component_for_document(source_id.split(":", 2)[2])
            else:
                source_version = source.get("version")
                component = str(source.get("component") or _component_for_document(str(source.get("document_key", ""))))
            if versions.get(component) != source_version:
                raise ValueError(f"required source version is outside expected component scope: {source_id}")
            source_family = _source_family(source_id)
            source_family_splits[source_family].add(split)
            if len(source_family_splits[source_family]) > 1:
                raise ValueError(f"source family split leakage: {source_family}")
            if split == "holdout" and source_family in (forbidden_source_families or set()):
                raise ValueError(f"source family is present in the forbidden V1 HOLDOUT set: {source_family}")

        expected_images = case.get("expected_image_ids", [])
        if not isinstance(expected_images, list):
            raise ValueError(f"invalid expected image IDs for {case_id}")
        if expected_images and known_images is not None and not set(expected_images).issubset(known_images):
            raise ValueError(f"unknown or unreviewed expected figure for {case_id}")
        if expected_images and case["category"] != "image_evidence":
            raise ValueError(f"image evidence case has the wrong category: {case_id}")
        if case["category"] == "image_evidence" and (split != "regression" or not expected_images):
            raise ValueError(f"image cases must be standalone regression probes: {case_id}")


def validate_image_regression_cases(cases: list[dict], known_sources: dict[str, dict | str], known_images: set[str]) -> None:
    """Validate the tiny, manually reviewed image probe set outside promotion metrics."""
    validate_rag_cases(
        cases, known_sources, forbidden_families=set(), forbidden_queries=set(),
        known_images=known_images, allowed_splits={"regression"},
    )


def _positive_scored_hits(hits: list[dict]) -> list[dict]:
    ordered = [
        row for row in hits
        if isinstance(row, dict)
        and isinstance(row.get("retrieval_score", 0), (int, float))
        and not isinstance(row.get("retrieval_score", 0), bool)
        and math.isfinite(row.get("retrieval_score", 0))
        and row.get("retrieval_score", 0) > 0
    ]
    ordered.sort(key=lambda row: row.get("rank") if isinstance(row.get("rank"), int) and row.get("rank") > 0 else 10**9)
    return ordered


def _positive_hits(hits: list[dict]) -> list[dict]:
    ordered = _positive_scored_hits(hits)
    unique: list[dict] = []
    seen: set[str] = set()
    for row in ordered:
        document_id = str(row.get("document_id", ""))
        if document_id and document_id not in seen:
            seen.add(document_id)
            unique.append(row)
    return unique


def _percentile_ms(values: list[float], percentile: float) -> float | None:
    finite = sorted(value for value in values if isinstance(value, (int, float)) and math.isfinite(value) and value >= 0)
    if not finite:
        return None
    index = max(0, math.ceil(len(finite) * percentile) - 1)
    return round(finite[index], 3)


def _summary(
    cases: list[dict], hits_by_case: dict[str, list[dict]],
    latency_by_case: dict[str, list[float]], *, include_categories: bool = True,
) -> dict:
    required_total = required_hit_5 = required_hit_20 = 0
    answerable_count = complete_5 = complete_20 = 0
    unanswerable_count = unanswerable_candidates = 0
    explicit_version_mismatches = version_mismatches = 0
    image_expected = image_hit = 0
    relation_state_total = relation_state_correct = 0
    reciprocal_ranks: list[float] = []
    ndcgs: list[float] = []
    ranked_result_count = 0
    per_case = []
    latencies = []
    for case in cases:
        hits = _positive_hits(hits_by_case.get(case["case_id"], []))
        top5, top20 = hits[:5], hits[:20]
        required = set(case["required_sources"])
        found5 = {str(row.get("document_id", "")) for row in top5} & required
        found20 = {str(row.get("document_id", "")) for row in top20} & required
        if case["answerable"]:
            answerable_count += 1
            required_total += len(required)
            required_hit_5 += len(found5)
            required_hit_20 += len(found20)
            complete_5 += int(found5 == required)
            complete_20 += int(found20 == required)
            ranks = [rank for rank, row in enumerate(top5, start=1) if str(row.get("document_id", "")) in required]
            reciprocal_ranks.append(sum(1 / rank for rank in ranks) / len(required) if required else 0.0)
            gains = [1.0 if str(row.get("document_id", "")) in required else 0.0 for row in top5]
            dcg = sum(gain / math.log2(rank + 1) for rank, gain in enumerate(gains, start=1))
            ideal = sum(1 / math.log2(rank + 1) for rank in range(1, min(len(required), 5) + 1))
            ndcgs.append(dcg / ideal if ideal else 0.0)
        else:
            unanswerable_count += 1
            unanswerable_candidates += int(bool(hits))

        expected_versions = case["expected_component_versions"]
        mismatches = []
        for row in top5:
            component = _component_for_document(str(row.get("document_key", "")))
            expected_version = expected_versions.get(component)
            if expected_version and row.get("version") != expected_version:
                version_mismatches += 1
                mismatch = {"document_id": row.get("document_id"), "actual": row.get("version"), "expected": expected_version}
                mismatches.append(mismatch)
                if case["category"] == "explicit_version":
                    explicit_version_mismatches += 1
            ranked_result_count += 1

        expected_images = set(case.get("expected_image_ids", []))
        hit_images = {
            str(row.get("figure_id")) for row in top5
            if row.get("modality") == "image_ocr" and row.get("figure_id")
        }
        image_expected += len(expected_images)
        image_hit += len(expected_images & hit_images)
        expected_relation = case["expected_relation_state"]
        if expected_relation != "none":
            relation_state_total += 1
            observed_states = set()
            for source_id in required:
                source_hit = next((row for row in top20 if row.get("document_id") == source_id), None)
                if source_hit is None:
                    continue
                rels = source_hit.get("document_relationships", [])
                if isinstance(rels, list):
                    observed_states.update(
                        row.get("verification_status") for row in rels
                        if isinstance(row, dict) and row.get("verification_status") in RELATION_STATES - {"none"}
                    )
            if not observed_states and required.issubset({str(row.get("document_id", "")) for row in top20}):
                observed_states.add("none")
            relation_state_correct += int(expected_relation in observed_states)
        case_latencies = latency_by_case.get(case["case_id"], [])
        latencies.extend(case_latencies)
        per_case.append({
            "case_id": case["case_id"],
            "required_sources": sorted(required),
            "found_sources_at_5": sorted(found5),
            "found_sources_at_20": sorted(found20),
            "expected_image_ids": sorted(expected_images),
            "found_image_ids_at_5": sorted(expected_images & hit_images),
            "expected_relation_state": expected_relation,
            "observed_relation_states": sorted(observed_states) if expected_relation != "none" else [],
            "version_mismatches_at_5": mismatches,
            "hit_document_ids_at_5": [row.get("document_id") for row in top5],
        })

    return {
        "case_count": len(cases),
        "answerable_count": answerable_count,
        "unanswerable_count": unanswerable_count,
        "metrics": {
            "required_source_recall_at_5": required_hit_5 / required_total if required_total else None,
            "required_source_recall_at_20": required_hit_20 / required_total if required_total else None,
            "complete_required_sources_at_5": complete_5 / answerable_count if answerable_count else None,
            "complete_required_sources_at_20": complete_20 / answerable_count if answerable_count else None,
            "explicit_version_mismatch_count": explicit_version_mismatches,
            "version_mismatch_count": version_mismatches,
            "version_mismatch_rate_at_5": version_mismatches / ranked_result_count if ranked_result_count else 0.0,
            "mrr_at_5": statistics.mean(reciprocal_ranks) if reciprocal_ranks else None,
            "ndcg_at_5": statistics.mean(ndcgs) if ndcgs else None,
            "image_evidence_hit_at_5": image_hit / image_expected if image_expected else None,
            "image_evidence_hits": f"{image_hit}/{image_expected}" if image_expected else None,
            "translation_relation_state_accuracy": relation_state_correct / relation_state_total if relation_state_total else None,
            "translation_relation_state_cases": relation_state_total,
            "unanswerable_candidate_rate": unanswerable_candidates / unanswerable_count if unanswerable_count else None,
            "search_p50_ms": _percentile_ms(latencies, 0.50),
            "search_p95_ms": _percentile_ms(latencies, 0.95),
            "answer_accuracy": None,
        },
        "by_category": {
            category: _summary(
                [case for case in cases if case["category"] == category],
                hits_by_case, latency_by_case, include_categories=False,
            )
            for category in sorted({case["category"] for case in cases})
        } if include_categories else {},
        "cases": per_case,
        "metric_scope": "offline retrieval only; candidate presence is not an answer and these metrics do not establish answer accuracy or hallucination rate",
    }


def evaluate_retrieval(cases: list[dict], hits_by_case: dict[str, list[dict]], latency_by_case: dict[str, list[float]]) -> dict:
    return _summary(cases, hits_by_case, latency_by_case)


def evaluate_image_regression(cases: list[dict], hits_by_case: dict[str, list[dict]]) -> dict:
    expected = 0
    matched = 0
    rows = []
    for case in cases:
        if case.get("split") != "regression" or case.get("category") != "image_evidence":
            raise ValueError("image regression rows must use split=regression and category=image_evidence")
        expected_ids = set(case.get("expected_image_ids", []))
        if not expected_ids:
            raise ValueError("image regression cases must have at least one reviewed figure id")
        actual_ids = {
            str(row.get("figure_id")) for row in _positive_scored_hits(hits_by_case.get(case["case_id"], []))[:5]
            if row.get("modality") == "image_ocr" and row.get("figure_id")
        }
        found = expected_ids & actual_ids
        expected += len(expected_ids)
        matched += len(found)
        rows.append({"case_id": case["case_id"], "expected_image_ids": sorted(expected_ids), "found_image_ids": sorted(found)})
    return {
        "case_count": len(cases),
        "expected_figure_count": expected,
        "hit_count": matched,
        "hit_rate": matched / expected if expected else None,
        "cases": rows,
        "interpretation": "small fixed regression probe over currently reviewed figures; it does not estimate image generalization",
    }


def _v1_exclusions() -> tuple[set[str], set[str]]:
    old_cases_path = QUALITY_V1 / "cases.jsonl"
    old_cases = [json.loads(line) for line in old_cases_path.read_text(encoding="utf-8").splitlines() if line.strip()]
    holdout_families = {
        str(case.get("family_id")) for case in old_cases
        if case.get("split") == "holdout" and case.get("family_id")
    }
    for case in old_cases:
        if case.get("split") != "holdout":
            continue
        for source_id in case.get("required_sources", []):
            try:
                holdout_families.add(_source_family(str(source_id)))
            except ValueError:
                continue
    old_queries = {normalize_query(str(case.get("query", ""))) for case in old_cases}
    return holdout_families, old_queries


def _runtime_fingerprint() -> dict:
    paths = {
        "corpus_manifest_sha256": CORPUS / "corpus_manifest.json",
        "relation_registry_sha256": CORPUS / "document_relations.json",
        "chunks_sha256": CORPUS / "chunks.json",
        "runtime_config_sha256": CORPUS / "public_retrieval_runtime.json",
        "policy_sha256": CORPUS / "retrieval_policy.json",
        "figure_sidecar_sha256": CORPUS / "figure_evidence_reviewed.json",
        "figure_lock_sha256": CORPUS / "figure_evidence_reviewed.lock.json",
        "runner_sha256": Path(__file__),
        "public_knowledge_sha256": SERVICE / "src" / "public_knowledge.py",
        "retrieval_runtime_sha256": SERVICE / "src" / "public_retrieval_runtime.py",
    }
    fingerprint = {key: _portable_sha256(path) for key, path in paths.items()}
    fingerprint["dense_vectors_sha256"] = _binary_sha256(CORPUS / "dense_vectors.npy")
    return fingerprint


def _selection_lock(path: Path | None, cases_sha256: str) -> dict | None:
    if path is None:
        return None
    lock = json.loads(path.read_text(encoding="utf-8"))
    if lock.get("rag_cases_sha256") != cases_sha256 or not lock.get("selected_candidate"):
        raise ValueError("selection lock does not match V2 RAG case hash or selected candidate")
    if lock.get("status") not in {"holdout_locked", "promoted", "not_promoted"}:
        raise ValueError("selection lock is not ready for the requested HOLDOUT run")
    return lock


def _search_policy(runtime, policy: str, query: str, *, top_k: int, version: str, language: str) -> list[dict]:
    """Run an online policy or an evaluation-only composition without exposing it to the API."""
    if policy != "hybrid_figure_ocr":
        return runtime.search(query, top_k=top_k, version=version, language=language, policy=policy)
    if not 1 <= top_k <= 20:
        raise ValueError("invalid search request")
    document_hits = runtime.base_index.search(
        query, top_k=top_k, version=version, language=language, policy="hybrid",
    )
    image_hits = runtime._search_images(query, top_k=top_k, version=version, language=language)
    runtime.last_retrieval_call_count = 2
    return [
        {**row, "retrieval_policy": policy}
        for row in runtime._add_image_evidence(document_hits, image_hits, top_k=top_k)
    ]


def run_benchmark(*, policies: tuple[str, ...], split: str, repeats: int, selection_lock_path: Path | None = None) -> dict:
    if split not in {"dev", "holdout"}:
        raise ValueError("split must be dev or holdout")
    if not 1 <= repeats <= 20:
        raise ValueError("repeats must be between 1 and 20")
    supported = set(POLICIES) | OFFLINE_EXPERIMENT_POLICIES
    if not policies or len(set(policies)) != len(policies) or any(policy not in supported for policy in policies):
        raise ValueError("policies must be unique supported retrieval policies")
    if split == "holdout" and selection_lock_path is None:
        raise ValueError("HOLDOUT is locked until a DEV selection lock is provided")
    cases = load_rag_cases()
    split_lock = json.loads(SPLIT_LOCK.read_text(encoding="utf-8"))
    cases_sha = _portable_sha256(RAG_CASES)
    if split_lock.get("rag_cases_sha256") != cases_sha:
        raise ValueError("RAG cases differ from split_lock.json")
    selection = _selection_lock(selection_lock_path, cases_sha)
    if split == "holdout":
        allowed = {"bm25", "bm25_figure_ocr", str(selection["selected_candidate"])}
        if set(policies) != allowed:
            raise ValueError("HOLDOUT may run only BM25, BM25+OCR, and the single locked selected candidate")

    index = PublicKnowledgeIndex(root=CORPUS)
    known_sources = {_source_id(row): row for row in index.manifest.get("sources", [])}
    relation_index = DocumentRelationIndex.from_corpus(CORPUS, index.manifest)
    if not relation_index.available:
        raise ValueError("document relationship registry is invalid; cannot evaluate relation-state cases")
    forbidden_families, forbidden_queries = _v1_exclusions()
    validate_rag_cases(cases, known_sources, forbidden_families=forbidden_families, forbidden_queries=forbidden_queries)
    runtime = PublicRetrievalRuntime(index, config_path=CORPUS / "public_retrieval_runtime.json", sidecar_path=CORPUS / "figure_evidence_reviewed.json")
    selected_cases = [case for case in cases if case["split"] == split]
    image_cases = load_image_regression_cases()
    known_images = {
        str(row.get("figure_id")) for row in json.loads((CORPUS / "figure_evidence_reviewed.json").read_text(encoding="utf-8")).get("chunks", [])
        if row.get("review_status") == "approved"
    }
    validate_image_regression_cases(image_cases, known_sources, known_images)
    report: dict = {
        "schema_version": 2,
        "evaluation": "autoware_accuracy_v2",
        "split": split,
        "corpus": index.manifest.get("workspace"),
        "cases_sha256": cases_sha,
        "split_lock_sha256": _portable_sha256(SPLIT_LOCK),
        "runtime_fingerprint": _runtime_fingerprint(),
        "selection_lock": selection,
        "repeats_per_case": repeats,
        "policies": {},
        "metric_scope": "offline retrieval only; no generated-answer accuracy claim",
        "image_regression": {},
    }
    for policy in policies:
        hits_by_case: dict[str, list[dict]] = {}
        latencies_by_case: dict[str, list[float]] = {}
        for case in selected_cases:
            samples = []
            hits = []
            for _ in range(repeats):
                started = time.perf_counter()
                hits = _search_policy(runtime, policy, case["query"], top_k=20, version=case["version"], language=case["language"])
                samples.append((time.perf_counter() - started) * 1000)
            for row in hits:
                row["document_relationships"] = relation_index.for_document(str(row.get("document_id", "")))
            hits_by_case[case["case_id"]] = hits
            latencies_by_case[case["case_id"]] = samples
        report["policies"][policy] = evaluate_retrieval(selected_cases, hits_by_case, latencies_by_case)
        image_hits: dict[str, list[dict]] = {}
        for case in image_cases:
            image_hits[case["case_id"]] = _search_policy(
                runtime, policy, case["query"], top_k=20, version=case["version"], language=case["language"],
            )
        report["image_regression"][policy] = evaluate_image_regression(image_cases, image_hits)
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--policies", default="bm25,bm25_figure_ocr")
    parser.add_argument("--split", choices=("dev", "holdout"), default="dev")
    parser.add_argument("--repeats", type=int, default=5)
    parser.add_argument("--output", type=Path, default=HERE / "results" / "baseline-dev.json")
    parser.add_argument("--selection-lock", type=Path)
    args = parser.parse_args()
    report = run_benchmark(
        policies=tuple(value.strip() for value in args.policies.split(",") if value.strip()),
        split=args.split,
        repeats=args.repeats,
        selection_lock_path=args.selection_lock,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")
    print(json.dumps({policy: row["metrics"] for policy, row in report["policies"].items()}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
