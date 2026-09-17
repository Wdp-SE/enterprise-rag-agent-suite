"""Offline evaluation utilities for the generic document RAG baseline."""

from src.evaluation.corpus import CorpusManifest, load_corpus_manifest
from src.evaluation.dataset import EvaluationItem, ExpectedPage, load_evaluation_dataset
from src.evaluation.retrieval_evaluator import evaluate_retrieval
from src.evaluation.citation_evaluator import evaluate_citations
from src.evaluation.answer_evaluator import evaluate_answers
from src.evaluation.failure import FailureCase, FailureType, classify_failures
from src.evaluation.report import write_evaluation_report

__all__ = [
    "CorpusManifest",
    "EvaluationItem",
    "ExpectedPage",
    "FailureCase",
    "FailureType",
    "classify_failures",
    "evaluate_answers",
    "evaluate_citations",
    "evaluate_retrieval",
    "load_corpus_manifest",
    "load_evaluation_dataset",
    "write_evaluation_report",
]

