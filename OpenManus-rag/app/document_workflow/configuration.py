"""Validated, small configuration boundary for the document workflow."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlsplit


@dataclass(frozen=True)
class DocumentWorkflowConfig:
    rag_base_url: str | None = None
    rag_retrieve_endpoint: str = "/retrieve"
    rag_timeout_seconds: float = 30.0
    rag_retry_limit: int = 1
    rag_top_k: int = 5
    no_progress_threshold: int = 3
    max_workflow_steps: int = 80
    max_section_steps: int = 20
    execution_budget: int = 60
    token_budget: int = 0
    workflow_timeout_seconds: float = 180.0
    output_root: Path | None = None
    checkpoint_root: Path | None = None
    trace_root: Path | None = None
    persist_full_evidence_text: bool = False
    document_workflow_profile: str = "document_workflow"
    requires_human_review: bool = True

    @classmethod
    def from_env(cls) -> "DocumentWorkflowConfig":
        prefix = "DOCUMENT_WORKFLOW_"
        def get(name: str, default: str) -> str:
            return os.environ.get(prefix + name, default)
        persist = get("PERSIST_FULL_EVIDENCE_TEXT", "false").strip().lower()
        if persist not in {"true", "false"}:
            raise ValueError("PERSIST_FULL_EVIDENCE_TEXT must be true or false")
        return cls(
            rag_base_url=os.environ.get("RAG_BASE_URL"),
            rag_retrieve_endpoint=get("RAG_RETRIEVE_ENDPOINT", "/retrieve"),
            rag_timeout_seconds=float(get("RAG_TIMEOUT_SECONDS", "30")),
            rag_retry_limit=int(get("RAG_RETRY_LIMIT", "1")),
            rag_top_k=int(get("RAG_TOP_K", "5")),
            no_progress_threshold=int(get("NO_PROGRESS_THRESHOLD", "3")),
            max_workflow_steps=int(get("MAX_WORKFLOW_STEPS", "80")),
            max_section_steps=int(get("MAX_SECTION_STEPS", "20")),
            execution_budget=int(get("EXECUTION_BUDGET", "60")),
            token_budget=int(get("TOKEN_BUDGET", "0")),
            workflow_timeout_seconds=float(get("WORKFLOW_TIMEOUT_SECONDS", "180")),
            output_root=Path(value) if (value := os.environ.get(prefix + "OUTPUT_ROOT")) else None,
            checkpoint_root=Path(value) if (value := os.environ.get(prefix + "CHECKPOINT_ROOT")) else None,
            trace_root=Path(value) if (value := os.environ.get(prefix + "TRACE_ROOT")) else None,
            persist_full_evidence_text=persist == "true",
            document_workflow_profile=get("PROFILE", "document_workflow"),
        ).validate()

    def validate(self) -> "DocumentWorkflowConfig":
        if self.rag_base_url is not None:
            parts = urlsplit(self.rag_base_url)
            if parts.scheme not in {"http", "https"} or not parts.hostname or parts.username or parts.password or parts.query or parts.fragment:
                raise ValueError("invalid RAG_BASE_URL")
        if self.rag_retrieve_endpoint != "/retrieve":
            raise ValueError("frozen RAG endpoint must be /retrieve")
        if not (0 < self.rag_timeout_seconds and 0 < self.workflow_timeout_seconds):
            raise ValueError("timeouts must be positive")
        if self.rag_retry_limit < 0 or not 1 <= self.rag_top_k <= 20:
            raise ValueError("invalid RAG retry limit or top_k")
        if min(self.no_progress_threshold, self.max_workflow_steps, self.max_section_steps, self.execution_budget) <= 0 or self.token_budget < 0:
            raise ValueError("invalid workflow limit or budget")
        if self.document_workflow_profile != "document_workflow" or self.requires_human_review is not True:
            raise ValueError("document workflow profile and human review are mandatory")
        for root in (self.output_root, self.checkpoint_root, self.trace_root):
            if root is not None:
                root.mkdir(parents=True, exist_ok=True)
                if not root.is_dir():
                    raise ValueError("configured root is not a directory")
        return self

    def fingerprint(self) -> str:
        import hashlib
        import json
        critical = (self.rag_base_url, self.rag_retrieve_endpoint, self.rag_top_k,
                    self.no_progress_threshold, self.max_workflow_steps,
                    self.max_section_steps, self.execution_budget, self.token_budget,
                    self.document_workflow_profile, self.requires_human_review)
        return hashlib.sha256(json.dumps(critical).encode()).hexdigest()
