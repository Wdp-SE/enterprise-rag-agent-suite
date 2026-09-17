import hashlib
import json
from pathlib import Path

import pytest

from src.evaluation.answer_evaluator import evaluate_answers
from src.evaluation.citation_evaluator import evaluate_citations
from src.evaluation.corpus import load_corpus_manifest
from src.evaluation.dataset import EvaluationItem, load_evaluation_dataset
from src.evaluation.failure import FailureType, classify_failures
from src.evaluation.report import write_evaluation_report
from src.evaluation.retrieval_evaluator import evaluate_retrieval


def _item(
    question_id="q1",
    question_type="single_document",
    answerable=True,
    expected_document_ids=None,
    expected_pages=None,
    key_points=None,
):
    expected_document_ids = (
        ["doc-a"] if expected_document_ids is None and answerable else expected_document_ids or []
    )
    expected_pages = (
        [{"document_id": expected_document_ids[0], "page_number": 2}]
        if expected_pages is None and answerable
        else expected_pages or []
    )
    return EvaluationItem.model_validate(
        {
            "question_id": question_id,
            "question": f"Question {question_id}",
            "question_type": question_type,
            "answerable": answerable,
            "expected_document_ids": expected_document_ids,
            "expected_pages": expected_pages,
            "reference_answer": "reference" if answerable else None,
            "key_points": key_points or [],
            "schema": "text",
        }
    )


def _manifest_payload(source_name: str, digest: str, size: int) -> dict:
    return {
        "schema_version": "1.0",
        "corpus_id": "fixture",
        "corpus_version": "0.1",
        "frozen_at": "2026-01-01T00:00:00+08:00",
        "status": "FROZEN",
        "scenario": "fixture",
        "identity_note": "fixture",
        "source_directory": "source_pdfs",
        "default_index_document_ids": ["doc-a"],
        "target_current_document_ids_blocked_by_ocr": [],
        "version_test_document_ids": [],
        "reference_document_ids_blocked_by_ocr": [],
        "duplicate_audit": {
            "exact_sha256_duplicate_groups": [],
            "normalized_text_sha256_duplicate_groups": [],
            "result": "NO_EXACT_DUPLICATES_FOUND",
            "note": "fixture",
        },
        "version_relations": [],
        "documents": [
            {
                "document_id": "doc-a",
                "title": "Doc A",
                "source_filename": source_name,
                "document_type": "law",
                "organization": "Org",
                "document_number": None,
                "publish_date": None,
                "effective_date": None,
                "version": None,
                "status": "ACTIVE",
                "source_level": "LAW",
                "source_path": f"source_pdfs/{source_name}",
                "source_url": None,
                "sha256": digest,
                "size_bytes": size,
                "pages_total": 1,
                "pages_with_text": 1,
                "empty_pages": 0,
                "parse_status": "READY",
                "included_in_default_index": True,
                "evaluation_role": None,
                "target_default_priority": None,
            }
        ],
    }


def test_corpus_manifest_validates_identity_and_source_hash(tmp_path):
    source_dir = tmp_path / "source_pdfs"
    source_dir.mkdir()
    source = source_dir / "source.pdf"
    source.write_bytes(b"fixture-pdf")
    digest = hashlib.sha256(source.read_bytes()).hexdigest()
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(
        json.dumps(_manifest_payload(source.name, digest, source.stat().st_size)),
        encoding="utf-8",
    )

    manifest = load_corpus_manifest(manifest_path, verify_source_files=True)
    assert manifest.default_index_document_ids == ["doc-a"]

    source.write_bytes(b"changed")
    with pytest.raises(ValueError, match="size mismatch|hash mismatch"):
        load_corpus_manifest(manifest_path, verify_source_files=True)


def test_dataset_jsonl_parsing_and_unanswerable_invariants(tmp_path):
    path = tmp_path / "dataset.jsonl"
    items = [
        _item().model_dump_json(by_alias=True),
        _item(
            "u1", question_type="unanswerable", answerable=False
        ).model_dump_json(by_alias=True),
    ]
    path.write_text("\n".join(items), encoding="utf-8")

    loaded = load_evaluation_dataset(path)
    assert [item.question_id for item in loaded] == ["q1", "u1"]
    assert loaded[0].answer_schema == "text"

    with pytest.raises(ValueError, match="cannot declare expected evidence"):
        _item(
            "bad",
            question_type="unanswerable",
            answerable=False,
            expected_document_ids=["doc-a"],
            expected_pages=[{"document_id": "doc-a", "page_number": 1}],
        )


def test_retrieval_hit_recall_and_mrr_are_computed_at_requested_k():
    items = [
        _item(expected_document_ids=["doc-a", "doc-b"]),
        _item("q2", expected_document_ids=["doc-c"]),
    ]
    results = {
        "q1": [
            {"document_id": "doc-x", "distance": 0.9},
            {"document_id": "doc-a", "distance": 0.8},
            {"document_id": "doc-b", "distance": 0.7},
        ],
        "q2": [{"document_id": "doc-c", "distance": 0.6}],
    }

    metrics = evaluate_retrieval(items, results, ks=(1, 3, 5))

    assert metrics["overall"]["hit_at_k"] == {"1": 0.5, "3": 1.0, "5": 1.0}
    assert metrics["overall"]["recall_at_k"] == {"1": 0.5, "3": 1.0, "5": 1.0}
    assert metrics["overall"]["mrr"] == 0.75


def test_unanswerable_is_excluded_from_hit_metrics_and_scores_are_recorded():
    items = [
        _item(),
        _item("u1", question_type="unanswerable", answerable=False),
    ]
    results = {
        "q1": [{"document_id": "doc-a", "distance": 0.8}],
        "u1": [{"document_id": "doc-x", "distance": 0.55}],
    }

    metrics = evaluate_retrieval(items, results)

    assert metrics["overall"]["evaluated_questions"] == 1
    assert metrics["unanswerable_behavior"]["any_retrieval_rate"] == 1.0
    assert metrics["score_distribution"]["cosine_top1"]["unanswerable"]["mean"] == 0.55
    assert metrics["score_distribution"]["threshold_selected"] is False


def test_citation_metrics_use_composite_document_page_identity():
    items = [_item()]
    citations = {
        "q1": [
            {"document_id": "doc-a", "page_number": 2},
            {"document_id": "doc-a", "page_number": 9},
            {"document_id": "doc-x", "page_number": 2},
        ]
    }

    metrics = evaluate_citations(items, citations)

    assert metrics["document_citation_accuracy"] == pytest.approx(2 / 3, abs=1e-6)
    assert metrics["page_citation_accuracy"] == pytest.approx(1 / 3, abs=1e-6)
    assert metrics["document_citation_hit_rate"] == 1.0
    assert metrics["page_citation_hit_rate"] == 1.0


def test_answer_metrics_observe_refusal_without_adding_reject_policy():
    items = [
        _item(key_points=["alpha", "beta"]),
        _item("u1", question_type="unanswerable", answerable=False),
    ]
    answers = {
        "q1": {
            "answer": "alpha beta",
            "unsupported_claim": False,
            "citation_correct": True,
        },
        "u1": {
            "answer": "N/A",
            "unsupported_claim": False,
            "citation_correct": True,
        },
    }

    metrics = evaluate_answers(items, answers)

    assert metrics["answerable_accuracy"] == 1.0
    assert metrics["unanswerable_refusal_rate"] == 1.0
    assert metrics["key_point_coverage"] == 1.0


def test_failure_classification_distinguishes_parse_version_and_hallucination():
    parse_item = _item(
        "parse",
        question_type="version_temporal",
        expected_document_ids=["doc-scan"],
        expected_pages=[{"document_id": "doc-scan", "page_number": 1}],
    )
    version_item = _item(
        "version",
        question_type="version_temporal",
        expected_document_ids=["doc-old"],
        expected_pages=[{"document_id": "doc-old", "page_number": 2}],
    )
    unanswerable = _item("u1", question_type="unanswerable", answerable=False)

    failures = classify_failures(
        [parse_item, version_item, unanswerable],
        {"parse": [], "version": [], "u1": [{"document_id": "doc-a", "page": 1}]},
        answers_by_question={"u1": {"answer": "invented"}},
        parse_blocked_document_ids={"doc-scan"},
    )

    assert [failure.failure_type for failure in failures] == [
        FailureType.PARSE_FAILURE,
        FailureType.VERSION_AMBIGUITY,
        FailureType.UNANSWERABLE_HALLUCINATION,
    ]


def test_version_failure_taxonomy_uses_resolver_trace():
    item = _item(
        "historical",
        question_type="version_temporal",
        expected_document_ids=["doc-old"],
    )
    failures = classify_failures(
        [item],
        {"historical": [{"document_id": "doc-new", "page": 1}]},
        version_traces_by_question={
            "historical": {
                "version_intent": "EXPLICIT_VERSION",
                "issues": [],
                "temporal_ambiguity": False,
                "candidate_documents": [
                    {
                        "candidate_document_id": "doc-old",
                        "document_status": "SUPERSEDED",
                    }
                ],
            }
        },
    )
    assert failures[0].failure_type == FailureType.WRONG_HISTORICAL_VERSION


def test_missing_historical_index_is_dataset_source_missing():
    item = _item(
        "missing-source",
        question_type="version_temporal",
        expected_document_ids=["notice-doc"],
    )
    failures = classify_failures(
        [item],
        {"missing-source": []},
        version_traces_by_question={
            "missing-source": {
                "version_intent": "TEMPORAL_DATE",
                "issues": ["DATASET_SOURCE_MISSING:notice-doc"],
                "candidate_documents": [],
            }
        },
    )
    assert failures[0].failure_type == FailureType.DATASET_SOURCE_MISSING


def test_evaluation_report_serializes_all_required_artifacts(tmp_path):
    source_dir = tmp_path / "source_pdfs"
    source_dir.mkdir()
    source = source_dir / "source.pdf"
    source.write_bytes(b"fixture-pdf")
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(
        json.dumps(
            _manifest_payload(
                source.name,
                hashlib.sha256(source.read_bytes()).hexdigest(),
                source.stat().st_size,
            )
        ),
        encoding="utf-8",
    )
    manifest = load_corpus_manifest(manifest_path)
    manifest = manifest.model_copy(update={"corpus_version": "0.2"})
    item = _item()
    retrieval = evaluate_retrieval(
        [item], {"q1": [{"document_id": "doc-a", "page": 2, "distance": 0.8}]}
    )
    citation = evaluate_citations(
        [item], {"q1": [{"document_id": "doc-a", "page_number": 2}]}
    )

    summary = write_evaluation_report(
        tmp_path / "report",
        corpus_manifest=manifest,
        dataset=[item],
        retrieval_metrics=retrieval,
        citation_metrics=citation,
        answer_metrics=None,
        failure_cases=[],
        ingestion_statistics={"pages": 1, "chunks": 1},
    )

    assert summary.is_file()
    assert summary.read_text(encoding="utf-8").startswith("# Domain Evaluation v0.2")
    for filename in (
        "corpus_manifest.json",
        "retrieval_metrics.json",
        "citation_metrics.json",
        "answer_metrics.json",
        "failure_cases.json",
        "evaluation_summary.md",
    ):
        assert (summary.parent / filename).is_file()
