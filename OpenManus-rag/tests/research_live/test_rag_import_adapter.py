from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from app.research.rag_import_adapter import (
    RagCandidateImportVerifier,
    RagImportAdapterError,
)


def test_rag_verifier_calls_only_injected_import_candidate(tmp_path: Path) -> None:
    package = tmp_path / "candidate"
    package.mkdir()
    calls = []

    def import_candidate(path):
        calls.append(path)
        return SimpleNamespace(
            accepted=True,
            candidate_id="cand_example_1234567890abcdef",
            document_id="doc_example_1234567890abcdef",
            issues=[],
            ingestion_performed=False,
        )

    result = RagCandidateImportVerifier(import_candidate).import_candidate(package)

    assert result.accepted is True
    assert calls == [package.resolve()]


def test_rag_verifier_preserves_rejection_issue_codes(tmp_path: Path) -> None:
    package = tmp_path / "candidate"
    package.mkdir()
    result = RagCandidateImportVerifier(
        lambda path: {
            "accepted": False,
            "issues": [{"code": "source_hash_invalid", "message": "hash mismatch"}],
            "ingestion_performed": False,
        }
    ).import_candidate(package)

    assert result.accepted is False
    assert result.issues[0].code == "source_hash_invalid"


def test_rag_verifier_rejects_unexpected_formal_ingestion(tmp_path: Path) -> None:
    package = tmp_path / "candidate"
    package.mkdir()

    with pytest.raises(RagImportAdapterError, match="formal ingestion"):
        RagCandidateImportVerifier(
            lambda path: {"accepted": True, "ingestion_performed": True}
        ).import_candidate(package)

