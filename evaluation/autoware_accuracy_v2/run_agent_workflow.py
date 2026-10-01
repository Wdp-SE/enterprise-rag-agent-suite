"""Run the bounded Agent planner/retrieval workflow locally without any LLM calls."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import time
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
CORPUS = ROOT / "versioned-rag-service" / "public_corpus_autoware"
SERVICE = ROOT / "versioned-rag-service"
AGENT = ROOT / "change-review-agent"
for import_root in (SERVICE, AGENT, HERE):
    if str(import_root) not in sys.path:
        sys.path.insert(0, str(import_root))

from app.public_review import PublicReviewAgent  # noqa: E402
from run_agent_evaluation import load_jsonl  # noqa: E402
from src.public_knowledge import PublicKnowledgeIndex  # noqa: E402
from src.public_retrieval_runtime import PublicRetrievalRuntime  # noqa: E402


def _relation_state(rows: list[dict]) -> str:
    if not rows:
        return "none"
    priority = {"verified": 0, "candidate": 1, "unknown": 2}
    return min((row["verification_status"] for row in rows), key=priority.__getitem__)


def effective_language_mode(case: dict, override: str | None) -> str:
    return override or str(case["language"])


def to_agent_evaluation_row(case: dict, review: dict, *, latency_ms: float) -> dict:
    """Project a workflow trace into evaluation fields without inventing impacts."""
    retrieved = review.get("retrieved_results", [])
    source_ids = sorted({
        str(row.get("document_id") or f"{row['version']}:{row['language']}:{row['document_key']}")
        for row in retrieved
    })
    relation_states = {
        str(row.get("document_id") or f"{row['version']}:{row['language']}:{row['document_key']}"):
        _relation_state(row.get("document_relationships", []))
        for row in retrieved
    }
    gaps = sorted({
        str(row.get("gap_type")) for row in review.get("evidence_gap_details", [])
        if isinstance(row, dict) and row.get("gap_type")
    })
    trace = review.get("retrieval_trace", {})
    trace_status = str(trace.get("model_status", "NOT_CALLED"))
    if not trace_status.startswith("NOT_CALLED") and trace_status != "GENERATION_NOT_CONFIGURED":
        raise ValueError("workflow baseline unexpectedly invoked generation")
    scope_guarded = review.get("scope_status") == "OUT_OF_SCOPE"
    coverage = review.get("coverage")
    return {
        "case_id": case["case_id"],
        "retrieved_source_ids": source_ids,
        "impact_candidates": [],
        "covered_checklist_items": [],
        "relation_states": relation_states,
        "gap_types": gaps,
        "coverage": coverage,
        "complete": bool(coverage and coverage.get("complete")),
        "abstained": scope_guarded,
        "abstention_evaluated": scope_guarded,
        "declared_no_impact": False,
        "model_status": "NOT_CALLED",
        "search_calls": len(trace.get("queries", [])),
        "selected_evidence_count": len(retrieved),
        "latency_ms": round(max(0.0, latency_ms), 3),
        "workflow_status": review.get("stage_status", {}).get("retrieval", "UNKNOWN"),
        "label_scope": case.get("label_scope", "unspecified"),
    }


class LocalCorpusGateway:
    """Adapt the pinned corpus runtime to PublicReviewAgent for offline evaluation."""

    def __init__(self):
        manifest = json.loads((CORPUS / "corpus_manifest.json").read_text(encoding="utf-8"))
        self.manifest = manifest
        self.index = PublicKnowledgeIndex(root=CORPUS)
        self.runtime = PublicRetrievalRuntime(
            self.index,
            config_path=CORPUS / "public_retrieval_runtime.json",
            sidecar_path=CORPUS / "figure_evidence_reviewed.json",
        )
        if not self.index.document_relations.available:
            raise ValueError("document relationship registry is unavailable")

    def workspace(self) -> dict:
        return self.manifest

    def search(self, question: str, *, version: str, language: str, top_k: int = 5) -> dict:
        rows = self.runtime.search(
            question, top_k=top_k, version=version, language=language,
        )
        for row in rows:
            row["document_relationships"] = self.index.document_relations.for_document(
                str(row.get("document_id") or ""),
            )
        return {"results": rows, "retrieval_policy": self.runtime.runtime_policy}

    @staticmethod
    def review_advice(change_summary: str, evidence_chunk_ids: list[str]) -> dict:
        return {
            "status": "GENERATION_NOT_CONFIGURED", "answer": "N/A", "sources": [],
        }

    @staticmethod
    def review_advice_for_version(
        change_summary: str, evidence_chunk_ids: list[str], *, version: str,
    ) -> dict:
        return LocalCorpusGateway.review_advice(change_summary, evidence_chunk_ids)

    def document(self, document_id: str) -> list[dict]:
        return [row for row in self.index.chunks if row.get("document_id") == document_id]

    @staticmethod
    def engineering_diff(old_items: list[dict], new_items: list[dict]) -> dict:
        raise AssertionError("local workflow benchmark must not call engineering diff")

    @staticmethod
    def engineering_impacts(payload: dict) -> dict:
        raise AssertionError("local workflow benchmark must not call engineering impact API")


def run_workflow(
    cases: list[dict], *, split: str = "dev", language_mode: str | None = None,
) -> tuple[list[dict], dict]:
    if split not in {"dev", "holdout", "all"}:
        raise ValueError("split must be dev, holdout, or all")
    if language_mode not in {None, "bilingual", "zh", "en"}:
        raise ValueError("language_mode must be bilingual, zh, or en")
    gateway = LocalCorpusGateway()
    agent = PublicReviewAgent(gateway)
    selected = [case for case in cases if split == "all" or case["split"] == split]
    rows = []
    for case in selected:
        started = time.perf_counter()
        review = agent.analyze_request(
            case["change_summary"],
            change_type=case["change_type"],
            target_version=case["target_version"],
            language_mode=effective_language_mode(case, language_mode),
        )
        elapsed = (time.perf_counter() - started) * 1000
        rows.append(to_agent_evaluation_row(case, review, latency_ms=elapsed))
    cases_path = HERE / "agent_cases.jsonl"
    run_manifest = {
        "schema_version": 1,
        "split": split,
        "language_mode": language_mode or "per_case",
        "case_count": len(rows),
        "cases_sha256": hashlib.sha256(cases_path.read_bytes()).hexdigest(),
        "corpus_manifest_sha256": hashlib.sha256((CORPUS / "corpus_manifest.json").read_bytes()).hexdigest(),
        "retrieval_policy": gateway.runtime.runtime_policy,
        "llm_calls": 0,
        "model_impact_metrics": "NOT_EVALUATED",
        "label_scope": "source anchors and deterministic public-scope probes; not confirmed impacts",
        "timing_scope": "local planner plus bilingual RAG retrieval; excludes model generation and network latency",
    }
    return rows, run_manifest


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--split", choices=("dev", "holdout", "all"), default="dev")
    parser.add_argument("--language-mode", choices=("bilingual", "zh", "en"))
    parser.add_argument("--cases", type=Path, default=HERE / "agent_cases.jsonl")
    parser.add_argument("--output", type=Path, default=HERE / "results" / "agent-baseline.jsonl")
    parser.add_argument("--manifest", type=Path, default=HERE / "results" / "agent-baseline-run.json")
    args = parser.parse_args()
    rows, run_manifest = run_workflow(
        load_jsonl(args.cases), split=args.split, language_mode=args.language_mode,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        "".join(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n" for row in rows),
        encoding="utf-8", newline="\n",
    )
    args.manifest.write_text(
        json.dumps(run_manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8", newline="\n",
    )
    print(json.dumps(run_manifest, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
