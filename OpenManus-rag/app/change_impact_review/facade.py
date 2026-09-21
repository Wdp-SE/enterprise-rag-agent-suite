"""Stable facade for the engineering change review workbench."""

from __future__ import annotations

from pathlib import Path

from .workflow import ChangeImpactWorkflow


class ChangeImpactReviewFacade(ChangeImpactWorkflow):
    """The UI-facing surface; orchestration remains in ChangeImpactWorkflow."""

    def __init__(self, runtime_root: str | Path, *, active_version_for_document):
        super().__init__(
            runtime_root,
            active_version_for_document=active_version_for_document,
        )

