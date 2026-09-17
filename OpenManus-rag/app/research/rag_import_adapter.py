"""Narrow verification-only boundary around an external RAG import_candidate()."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Callable

from app.research.live_models import RagImportIssue, RagImportResult


class RagImportAdapterError(RuntimeError):
    pass


class RagCandidateImportVerifier:
    """Call only import_candidate; this adapter has no approval or ingestion API."""

    def __init__(self, import_candidate: Callable[[Path], Any]):
        self._import_candidate = import_candidate

    @staticmethod
    def _value(result: Any, name: str, default=None):
        if isinstance(result, dict):
            return result.get(name, default)
        return getattr(result, name, default)

    def import_candidate(self, package_path: str | Path) -> RagImportResult:
        package = Path(package_path).resolve()
        if not package.is_dir() or package.is_symlink():
            raise RagImportAdapterError("Candidate Package must be a regular directory")
        external_result = self._import_candidate(package)
        issues = []
        for issue in self._value(external_result, "issues", []) or []:
            issues.append(
                RagImportIssue(
                    code=str(self._value(issue, "code", "unknown_issue")),
                    message=str(self._value(issue, "message", "")),
                )
            )
        result = RagImportResult(
            accepted=bool(self._value(external_result, "accepted", False)),
            candidate_id=self._value(external_result, "candidate_id"),
            document_id=self._value(external_result, "document_id"),
            issues=issues,
            ingestion_performed=bool(
                self._value(external_result, "ingestion_performed", False)
            ),
        )
        if result.ingestion_performed:
            raise RagImportAdapterError(
                "RAG import_candidate unexpectedly performed formal ingestion"
            )
        return result

