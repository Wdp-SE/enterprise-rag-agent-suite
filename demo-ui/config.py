"""Configuration for the local interview demo layer."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlsplit


UI_ROOT = Path(__file__).resolve().parent
WORKSPACE_ROOT = UI_ROOT.parent
AGENT_ROOT = WORKSPACE_ROOT / "OpenManus-rag"
RAG_ROOT = WORKSPACE_ROOT / "RAG-Challenge-2-main"
SAFE_TEMPLATE = AGENT_ROOT / "project_delivery/document_workflow_v2/integration/demo/template.docx"
SAFE_ARTIFACT = RAG_ROOT / "data/rd_v2_corpus/retrieval_artifacts/rd-v2-retrieval-final-v1.0-safe-integration"
NORMALIZATION_MANIFEST = RAG_ROOT / "data/rd_v2_corpus/manifest/normalization_manifest.json"

SAFE_DOCUMENT_NAMES = {
    "safe-demo-12p": "RAG-RD-V2 合成规格说明.pdf",
    "safe-project-plan": "示例研发项目计划.txt",
}


@dataclass(frozen=True)
class DemoConfig:
    rag_base_url: str = "http://127.0.0.1:8765"
    request_timeout_seconds: float = 45.0
    runtime_root: Path = UI_ROOT / "runtime"
    demo_data_classification: str = "Synthetic / Public"
    allow_rag_query: bool = False

    @classmethod
    def from_env(cls) -> "DemoConfig":
        return cls(
            rag_base_url=os.environ.get("DEMO_RAG_BASE_URL", "http://127.0.0.1:8765"),
            request_timeout_seconds=float(os.environ.get("DEMO_REQUEST_TIMEOUT_SECONDS", "45")),
            runtime_root=Path(os.environ.get("DEMO_RUNTIME_ROOT", str(UI_ROOT / "runtime"))),
            demo_data_classification=os.environ.get("DEMO_DATA_CLASSIFICATION", "Synthetic / Public"),
            allow_rag_query=os.environ.get("DEMO_ALLOW_RAG_QUERY", "false").strip().casefold()
            in {"1", "true", "yes", "on"},
        ).validate()

    def validate(self) -> "DemoConfig":
        parsed = urlsplit(self.rag_base_url)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.username or parsed.password:
            raise ValueError("DEMO_RAG_BASE_URL must be a valid HTTP(S) service URL")
        if self.request_timeout_seconds <= 0:
            raise ValueError("DEMO_REQUEST_TIMEOUT_SECONDS must be positive")
        self.runtime_root.mkdir(parents=True, exist_ok=True)
        (self.runtime_root / "uploads").mkdir(exist_ok=True)
        (self.runtime_root / "outputs").mkdir(exist_ok=True)
        return self

    @property
    def online_generation_allowed(self) -> bool:
        return self.allow_rag_query or self.demo_data_classification.casefold() in {
            "synthetic", "public", "synthetic / public", "approved redacted"
        }


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
