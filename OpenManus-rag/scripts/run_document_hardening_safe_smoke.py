"""One local HTTP smoke against the already frozen synthetic RAG artifact."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[1]
RAG_ROOT = ROOT.parent / "RAG-Challenge-2-main"
SAFE_ARTIFACT = RAG_ROOT / "data/rd_v2_corpus/retrieval_artifacts/rd-v2-retrieval-final-v1.0-safe-integration"
OUTPUT = ROOT / "project_delivery/document_workflow_v2/final/demo"
SOURCE = ROOT / "project_delivery/document_workflow_v2/integration/demo/template.docx"
BASE_URL = "http://127.0.0.1:8765"
sys.path.insert(0, str(ROOT))

from app.document_workflow.configuration import DocumentWorkflowConfig
from app.document_workflow.rag import HTTPRetrieveClient
from app.document_workflow.workflow import DocumentWorkflow


def main() -> None:
    if not SAFE_ARTIFACT.joinpath("artifact_manifest.json").is_file() or not SOURCE.is_file():
        raise FileNotFoundError("existing synthetic artifact or template missing")
    if OUTPUT.joinpath("draft.docx").exists():
        raise FileExistsError("final safe smoke already ran; refusing duplicate run")
    OUTPUT.mkdir(parents=True, exist_ok=True)
    shutil.copy2(SOURCE, OUTPUT / "template.docx")
    before = hashlib.sha256((OUTPUT / "template.docx").read_bytes()).hexdigest()
    env = os.environ.copy()
    env["RD_V2_ARTIFACT_ROOT"] = str(SAFE_ARTIFACT)
    env["RD_V2_ALLOW_EXTERNAL_GENERATION"] = "false"
    env["RD_V2_PROJECT_ROOT"] = str(RAG_ROOT)
    python = RAG_ROOT / ".venv/Scripts/python.exe"
    flags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
    process = subprocess.Popen(
        [str(python), "-m", "uvicorn", "src.rd_v2_api:app", "--host", "127.0.0.1", "--port", "8765"],
        cwd=RAG_ROOT, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        creationflags=flags,
    )
    try:
        deadline = time.monotonic() + 90
        while time.monotonic() < deadline:
            if process.poll() is not None:
                raise RuntimeError("synthetic RAG service failed to start")
            try:
                health = httpx.get(BASE_URL + "/health", timeout=2)
                if health.status_code == 200:
                    break
            except httpx.HTTPError:
                pass
            time.sleep(1)
        else:
            raise TimeoutError("synthetic RAG service health timeout")
        status = httpx.get(BASE_URL + "/artifacts/status", timeout=5).json()
        if (status.get("artifact_status") != "COMPLETE"
                or status.get("retrieval_policy") != "DENSE_ONLY"
                or status.get("dense_representation") != "SECTION_PATH"):
            raise RuntimeError("frozen safe RAG artifact or policy invalid")
        config = DocumentWorkflowConfig(rag_base_url=BASE_URL, rag_retry_limit=1).validate()
        result = DocumentWorkflow(HTTPRetrieveClient(BASE_URL), config=config).run(
            OUTPUT / "template.docx", OUTPUT)
        trace = result["trace"]
        if (trace["total_rag_calls"] < 5 or len(trace["sections"]) != 5
                or trace["workflow_status"] != "PARTIAL"
                or not any("吞吐能力" in section["missing_fields"] for section in trace["sections"])
                or not result["draft_path"].is_file()
                or hashlib.sha256((OUTPUT / "template.docx").read_bytes()).hexdigest() != before):
            raise AssertionError("safe final E2E contract failed")
        print(json.dumps({
            "safe_final_e2e": "PASS", "workflow_id": result["state"].workflow_id,
            "workflow_status": result["state"].workflow_status,
            "rag_calls": trace["total_rag_calls"], "unique_evidence": trace["total_unique_evidence"],
            "sections": len(trace["sections"]), "draft": str(result["draft_path"]),
            "template_hash_unchanged": True,
        }))
    finally:
        process.terminate()
        try:
            process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=10)


if __name__ == "__main__":
    main()
