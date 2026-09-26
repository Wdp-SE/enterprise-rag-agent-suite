"""Configuration shared by the local and public interview demo profiles."""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass, replace
from pathlib import Path
from urllib.parse import urlsplit


UI_ROOT = Path(__file__).resolve().parent
WORKSPACE_ROOT = UI_ROOT.parent
AGENT_ROOT = WORKSPACE_ROOT / "change-review-agent"
RAG_ROOT = WORKSPACE_ROOT / "versioned-rag-service"
SAFE_TEMPLATE = AGENT_ROOT / "project_delivery/document_workflow_business_refactor/demo/requirement_change_impact_template.docx"
SAFE_ARTIFACT = RAG_ROOT / "data/rd_v2_corpus/retrieval_artifacts/rd-v2-retrieval-final-v1.0-safe-integration"
NORMALIZATION_MANIFEST = RAG_ROOT / "data/rd_v2_corpus/manifest/normalization_manifest.json"

SAFE_DOCUMENT_NAMES = {
    "safe-demo-12p": "RAG-RD-V2 合成规格说明.pdf",
    "safe-project-plan": "示例研发项目计划.txt",
}
_SAFE_ID = re.compile(r"^[A-Za-z0-9_-]{8,64}$")
_CASE_ID = re.compile(r"^[a-z0-9][a-z0-9-]{0,31}$")


@dataclass(frozen=True)
class DemoConfig:
    rag_base_url: str = "http://127.0.0.1:8765"
    request_timeout_seconds: float = 45.0
    runtime_root: Path = UI_ROOT / "runtime"
    demo_data_classification: str = "Synthetic / Public"
    allow_rag_query: bool = False
    app_env: str = "local"
    rag_retry_limit: int = 0
    max_llm_calls_per_session: int | None = None
    session_id: str | None = None
    demo_case_id: str = "case-a"

    @classmethod
    def from_env(cls) -> "DemoConfig":
        return cls(
            rag_base_url=os.environ.get(
                "RAG_API_BASE_URL",
                os.environ.get("DEMO_RAG_BASE_URL", "http://127.0.0.1:8765"),
            ),
            request_timeout_seconds=float(os.environ.get("DEMO_REQUEST_TIMEOUT_SECONDS", "45")),
            runtime_root=Path(os.environ.get("DEMO_RUNTIME_ROOT", str(UI_ROOT / "runtime"))),
            demo_data_classification=os.environ.get("DEMO_DATA_CLASSIFICATION", "Synthetic / Public"),
            allow_rag_query=os.environ.get("DEMO_ALLOW_RAG_QUERY", "false").strip().casefold()
            in {"1", "true", "yes", "on"},
            app_env=os.environ.get("APP_ENV", "local").strip().casefold(),
            rag_retry_limit=int(os.environ.get("RAG_RETRY_LIMIT", "1")),
            max_llm_calls_per_session=_optional_call_limit(),
        ).validate()

    def validate(self) -> "DemoConfig":
        parsed = urlsplit(self.rag_base_url)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.username or parsed.password:
            raise ValueError("RAG_API_BASE_URL must be a valid HTTP(S) service URL")
        if self.request_timeout_seconds <= 0:
            raise ValueError("DEMO_REQUEST_TIMEOUT_SECONDS must be positive")
        if self.app_env not in {"local", "public_demo"}:
            raise ValueError("APP_ENV must be local or public_demo")
        if self.rag_retry_limit < 0 or self.rag_retry_limit > 3:
            raise ValueError("RAG_RETRY_LIMIT must be between 0 and 3")
        if self.max_llm_calls_per_session is not None and self.max_llm_calls_per_session < 0:
            raise ValueError("MAX_LLM_CALLS_PER_SESSION must not be negative")
        if self.session_id is not None and not _SAFE_ID.fullmatch(self.session_id):
            raise ValueError("session_id contains unsafe characters")
        if not _CASE_ID.fullmatch(self.demo_case_id):
            raise ValueError("demo_case_id contains unsafe characters")
        self.runtime_root.mkdir(parents=True, exist_ok=True)
        (self.runtime_root / "uploads").mkdir(exist_ok=True)
        (self.runtime_root / "outputs").mkdir(exist_ok=True)
        return self

    def for_session(self, session_id: str, demo_case_id: str) -> "DemoConfig":
        if not _SAFE_ID.fullmatch(session_id):
            raise ValueError("session_id contains unsafe characters")
        if not _CASE_ID.fullmatch(demo_case_id):
            raise ValueError("demo_case_id contains unsafe characters")
        return replace(
            self,
            runtime_root=self.runtime_root / "sessions" / session_id / demo_case_id,
            session_id=session_id,
            demo_case_id=demo_case_id,
        ).validate()

    @property
    def is_public_demo(self) -> bool:
        return self.app_env == "public_demo"

    @property
    def online_generation_allowed(self) -> bool:
        if self.is_public_demo:
            return self.allow_rag_query
        return self.allow_rag_query or self.demo_data_classification.casefold() in {
            "synthetic", "public", "synthetic / public", "approved redacted"
        }


def _optional_call_limit() -> int | None:
    value = os.environ.get("MAX_LLM_CALLS_PER_SESSION", "").strip()
    if not value or value.casefold() in {"none", "unlimited", "off"}:
        return None
    return int(value)


def example_questions(limit: int = 5) -> list[str]:
    """Derive examples from the retained safe artifact instead of inventing a corpus."""
    path = SAFE_ARTIFACT / "child_chunks.jsonl"
    preferred = ["项目背景", "项目目标", "阶段划分", "验收依据", "测试"]
    available: list[str] = []
    if path.is_file():
        for line in path.read_text(encoding="utf-8").splitlines():
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            section_path = row.get("section_path") or []
            title = section_path[-1] if section_path else row.get("section_title")
            if isinstance(title, str) and title.strip() and title not in available:
                available.append(title.strip())
    ordered = [item for item in preferred if item in available]
    ordered.extend(item for item in available if item not in ordered)
    return [f"{title}是什么？" for title in ordered[:limit]] or ["项目背景是什么？"]


def document_display_names() -> dict[str, str]:
    """Return user-facing source names without exposing absolute source paths."""
    names = dict(SAFE_DOCUMENT_NAMES)
    if not NORMALIZATION_MANIFEST.is_file():
        return names
    try:
        payload = json.loads(NORMALIZATION_MANIFEST.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError):
        return names
    for document in payload.get("documents", []):
        document_id = str(document.get("document_id") or "").strip()
        source_name = str(document.get("source_file_name") or "").strip()
        if document_id and source_name:
            names[document_id] = source_name.replace("\\", "/").rsplit("/", 1)[-1]
    return names
