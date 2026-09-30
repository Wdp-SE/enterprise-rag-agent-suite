"""Offline, frozen-set retrieval comparison for the pinned Autoware corpus."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import statistics
import sys
import time
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SERVICE = ROOT / "versioned-rag-service"
sys.path.insert(0, str(SERVICE))

from src.public_knowledge import PublicKnowledgeIndex  # noqa: E402
from src.public_retrieval_runtime import PublicRetrievalRuntime  # noqa: E402


HERE = Path(__file__).resolve().parent
CORPUS = SERVICE / "public_corpus_autoware"
POLICIES = ("bm25", "bm25_faceted_rrf", "bm25_figure_ocr", "bm25_faceted_figure_ocr")


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _portable_text_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes().replace(b"\r\n", b"\n")).hexdigest()


def _runtime_fingerprint() -> dict:
    runtime_config_path = CORPUS / "public_retrieval_runtime.json"
    runtime_config = json.loads(runtime_config_path.read_text(encoding="utf-8"))
    config_behavior = dict(runtime_config)
    config_behavior.pop("default_policy", None)
    config_behavior_sha = hashlib.sha256(json.dumps(
        config_behavior, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
    ).encode("utf-8")).hexdigest()
    return {
        "corpus_manifest_sha256": _portable_text_sha256(CORPUS / "corpus_manifest.json"),
        "retrieval_policy_sha256": _portable_text_sha256(CORPUS / "retrieval_policy.json"),
        "chunks_sha256": _portable_text_sha256(CORPUS / "chunks.json"),
        "dense_vectors_sha256": _sha256(CORPUS / "dense_vectors.npy"),
        "figure_inventory_sha256": _portable_text_sha256(CORPUS / "figure_evidence.json"),
        "figure_sidecar_sha256": _portable_text_sha256(CORPUS / "figure_evidence_reviewed.json"),
        "figure_sidecar_lock_sha256": _portable_text_sha256(CORPUS / "figure_evidence_reviewed.lock.json"),
        "runtime_config_behavior_sha256": config_behavior_sha,
        "public_knowledge_sha256": _portable_text_sha256(SERVICE / "src" / "public_knowledge.py"),
        "public_retrieval_runtime_sha256": _portable_text_sha256(SERVICE / "src" / "public_retrieval_runtime.py"),
        "retrieval_fusion_sha256": _portable_text_sha256(SERVICE / "src" / "retrieval_fusion.py"),
        "figure_sidecar_integrity_sha256": _portable_text_sha256(SERVICE / "src" / "figure_sidecar_integrity.py"),
        "cases_sha256": _portable_text_sha256(HERE / "cases.jsonl"),
        "split_lock_sha256": _portable_text_sha256(HERE / "split_lock.json"),
        "runner_sha256": _portable_text_sha256(Path(__file__)),
    }


def _load_cases() -> list[dict]:
    cases_path = HERE / "cases.jsonl"
    lock = json.loads((HERE / "split_lock.json").read_text(encoding="utf-8"))
    if lock.get("cases_sha256") != _portable_text_sha256(cases_path):
        raise ValueError("frozen Autoware retrieval cases do not match split_lock.json")
    cases = [json.loads(line) for line in cases_path.read_text(encoding="utf-8").splitlines() if line.strip()]
    ids = [row.get("case_id") for row in cases]
    if len(ids) != len(set(ids)) or set(ids) != set(lock.get("case_ids", [])):
        raise ValueError("frozen Autoware retrieval case IDs do not match the lock")
    if len(cases) != lock.get("case_count"):
        raise ValueError("frozen Autoware retrieval case count does not match the lock")
    return cases


def _measure(runtime: PublicRetrievalRuntime, cases: list[dict], policy: str, repeats: int) -> dict:
    outputs = []
    durations = []
    call_counts = []
    total_required = total_hits = complete_cases = answerable_cases = 0
    image_expected = image_hits = version_mismatch = no_answer_total = no_answer_with_hits = 0
    for case in cases:
        samples = []
        last_hits = []
        for _ in range(repeats):
            started = time.perf_counter()
            hits = runtime.search(
                case["query"], top_k=5, version=case["version"], language="en", policy=policy,
            )
            samples.append((time.perf_counter() - started) * 1000)
            last_hits = hits
            call_counts.append(runtime.last_retrieval_call_count)
        durations.extend(samples)
        by_doc = {hit.get("document_key") for hit in last_hits if hit.get("retrieval_score", 0) > 0}
        required = set(case["required_sources"])
        found = required & by_doc
        total_required += len(required)
        total_hits += len(found)
        if case["answerable"]:
            answerable_cases += 1
            complete_cases += int(found == required)
        expected_images = set(case["expected_images"])
        found_images = {hit.get("figure_id") for hit in last_hits if hit.get("modality") == "image_ocr"}
        image_expected += len(expected_images)
        image_hits += len(expected_images & found_images)
        wrong_versions = [hit for hit in last_hits if hit.get("version") != case["version"]]
        version_mismatch += len(wrong_versions)
        if not case["answerable"]:
            no_answer_total += 1
            no_answer_with_hits += int(any(hit.get("retrieval_score", 0) > 0 for hit in last_hits))
        outputs.append({
            "case_id": case["case_id"],
            "required_sources": sorted(required),
            "found_sources_at_5": sorted(found),
            "expected_image_ids": sorted(expected_images),
            "found_image_ids_at_5": sorted(expected_images & found_images),
            "hit_versions_at_5": sorted({hit.get("version") for hit in last_hits}),
            "retrieved_chunk_ids_at_5": [hit.get("chunk_id") for hit in last_hits],
        })
    ordered = sorted(durations)
    p95_index = max(0, math.ceil(len(ordered) * 0.95) - 1)
    return {
        "query_count": len(cases),
        "required_source_recall_at_5": round(total_hits / total_required, 4) if total_required else 1.0,
        "complete_required_sources_at_5": round(complete_cases / answerable_cases, 4) if answerable_cases else 1.0,
        "image_evidence_hit_at_5": round(image_hits / image_expected, 4) if image_expected else 1.0,
        "image_evidence_hits": f"{image_hits}/{image_expected}",
        "version_mismatch_count": version_mismatch,
        "no_answer_nonempty_candidate_rate": round(no_answer_with_hits / no_answer_total, 4) if no_answer_total else 0.0,
        "no_answer_cases": no_answer_total,
        "search_p95_ms": round(ordered[p95_index], 3) if ordered else 0.0,
        "mean_retrieval_operations_per_query": round(statistics.mean(call_counts), 3) if call_counts else 0.0,
        "cases": outputs,
    }


def _passes(candidate: dict, baseline: dict) -> bool:
    return (
        candidate["required_source_recall_at_5"] >= baseline["required_source_recall_at_5"]
        and candidate["complete_required_sources_at_5"] >= baseline["complete_required_sources_at_5"]
        and candidate["no_answer_nonempty_candidate_rate"] <= baseline["no_answer_nonempty_candidate_rate"]
        and candidate["version_mismatch_count"] == 0
    )


def run_benchmark(*, repeats: int = 3) -> dict:
    cases = _load_cases()
    index = PublicKnowledgeIndex(root=CORPUS)
    runtime = PublicRetrievalRuntime(
        index,
        config_path=CORPUS / "public_retrieval_runtime.json",
        sidecar_path=CORPUS / "figure_evidence_reviewed.json",
    )
    report = {
        "schema_version": 1,
        "corpus": index.manifest["workspace"],
        "corpus_manifest_sha256": _sha256(CORPUS / "corpus_manifest.json"),
        "cases_sha256": _portable_text_sha256(HERE / "cases.jsonl"),
        "runtime_fingerprint": _runtime_fingerprint(),
        "metric_scope": "retrieval only; no LLM answer quality or hallucination claim",
        "repeats_per_case": repeats,
        "splits": {},
    }
    for split in ("dev", "holdout"):
        selected = [case for case in cases if case["split"] == split]
        report["splits"][split] = {
            policy: _measure(runtime, selected, policy, repeats) for policy in POLICIES
        }
        baseline = report["splits"][split]["bm25"]
        for policy in POLICIES[1:]:
            report["splits"][split][policy]["noninferior_to_bm25"] = _passes(
                report["splits"][split][policy], baseline,
            )
    eligible = [
        policy for policy in POLICIES[1:]
        if report["splits"]["dev"][policy]["noninferior_to_bm25"]
        and report["splits"]["holdout"][policy]["noninferior_to_bm25"]
        and report["splits"]["dev"][policy]["image_evidence_hit_at_5"]
        > report["splits"]["dev"]["bm25"]["image_evidence_hit_at_5"]
        and report["splits"]["holdout"][policy]["image_evidence_hit_at_5"]
        > report["splits"]["holdout"]["bm25"]["image_evidence_hit_at_5"]
    ]
    # Image coverage is the objective; ties favor the simpler, lower-call strategy.
    eligible.sort(key=lambda policy: (
        -report["splits"]["holdout"][policy]["image_evidence_hit_at_5"],
        report["splits"]["holdout"][policy]["mean_retrieval_operations_per_query"],
        POLICIES.index(policy),
    ))
    report["selection"] = {
        "selected_policy": eligible[0] if eligible else "bm25",
        "reason": (
            "best holdout image hit among candidates that are noninferior to BM25 on required-source recall, "
            "complete required-source rate, no-answer candidates, and version correctness"
            if eligible else "no candidate passed all dev and holdout noninferiority gates; retain BM25"
        ),
        "eligible_candidates": eligible,
    }
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repeats", type=int, default=3)
    parser.add_argument("--output", type=Path, default=HERE / "results" / "benchmark.json")
    args = parser.parse_args()
    if not 1 <= args.repeats <= 20:
        raise SystemExit("--repeats must be between 1 and 20")
    report = run_benchmark(repeats=args.repeats)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")
    summary = {
        split: {
            policy: {key: value for key, value in metrics.items() if key != "cases"}
            for policy, metrics in rows.items()
        }
        for split, rows in report["splits"].items()
    }
    print(json.dumps({"selection": report["selection"], "splits": summary}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
