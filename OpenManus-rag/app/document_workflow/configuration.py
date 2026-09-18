"""Validated configuration boundary for the document workflow product."""

from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlsplit

from .models import DraftingMode


@dataclass(frozen=True)
class DocumentWorkflowConfig:
    rag_base_url: str | None = None
    rag_timeout_seconds: float = 30.0
    rag_retry_limit: int = 1
    rag_top_k: int = 5
    no_progress_threshold: int = 3
    max_workflow_steps: int = 80
    max_section_steps: int = 20
    execution_budget: int = 60
    workflow_timeout_seconds: float = 180.0
    output_root: Path | None = None
    checkpoint_root: Path | None = None
    trace_root: Path | None = None
    drafting_mode: DraftingMode = DraftingMode.EXTRACTIVE
    data_classification: str = "synthetic"

    @classmethod
    def from_env(cls) -> "DocumentWorkflowConfig":
        prefix = "DOCUMENT_WORKFLOW_"
        get = lambda name, default: os.environ.get(prefix + name, default)
        return cls(
            rag_base_url=os.environ.get("RAG_BASE_URL"),
            rag_timeout_seconds=float(get("RAG_TIMEOUT_SECONDS", "30")),
            rag_retry_limit=int(get("RAG_RETRY_LIMIT", "1")),
            rag_top_k=int(get("RAG_TOP_K", "5")),
            no_progress_threshold=int(get("NO_PROGRESS_THRESHOLD", "3")),
            max_workflow_steps=int(get("MAX_WORKFLOW_STEPS", "80")),
            max_section_steps=int(get("MAX_SECTION_STEPS", "20")),
            execution_budget=int(get("EXECUTION_BUDGET", "60")),
            workflow_timeout_seconds=float(get("WORKFLOW_TIMEOUT_SECONDS", "180")),
            output_root=Path(value) if (value := os.environ.get(prefix + "OUTPUT_ROOT")) else None,
            checkpoint_root=Path(value) if (value := os.environ.get(prefix + "CHECKPOINT_ROOT")) else None,
            trace_root=Path(value) if (value := os.environ.get(prefix + "TRACE_ROOT")) else None,
            drafting_mode=DraftingMode(get("DRAFTING_MODE", "EXTRACTIVE")),
            data_classification=get("DATA_CLASSIFICATION", "synthetic"),
        ).validate()

    def validate(self) -> "DocumentWorkflowConfig":
        if self.rag_base_url is not None:
            parts = urlsplit(self.rag_base_url)
            if parts.scheme not in {"http", "https"} or not parts.hostname or parts.username or parts.password or parts.query or parts.fragment:
                raise ValueError("invalid RAG_BASE_URL")
        if self.rag_timeout_seconds <= 0 or self.workflow_timeout_seconds <= 0:
            raise ValueError("timeouts must be positive")
        if self.rag_retry_limit < 0 or not 1 <= self.rag_top_k <= 20:
            raise ValueError("invalid RAG retry limit or top_k")
        if min(self.no_progress_threshold, self.max_workflow_steps, self.max_section_steps, self.execution_budget) <= 0:
            raise ValueError("invalid workflow limit or budget")
        if not self.data_classification.strip():
            raise ValueError("data_classification is required")
        for root in (self.output_root, self.checkpoint_root, self.trace_root):
            if root is not None:
                root.mkdir(parents=True, exist_ok=True)
                if not root.is_dir():
                    raise ValueError("configured root is not a directory")
        return self

    def fingerprint(self) -> str:
        critical = (
            self.rag_base_url, self.rag_top_k, self.no_progress_threshold,
            self.max_workflow_steps, self.max_section_steps, self.execution_budget,
            self.drafting_mode.value, self.data_classification,
        )
        return hashlib.sha256(json.dumps(critical).encode()).hexdigest()
