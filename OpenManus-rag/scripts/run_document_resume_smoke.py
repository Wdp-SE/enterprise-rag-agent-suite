"""Small offline recovery smoke using the retained safe template and mock RAG."""

from __future__ import annotations

import hashlib
import json
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.document_workflow.rag import DemoRAGClient, RAGTool
from app.document_workflow.state import CheckpointStore
from app.document_workflow.workflow import DocumentWorkflow


def main() -> None:
    source = ROOT / "project_delivery/document_workflow_v2/integration/demo/template.docx"
    output = ROOT / "project_delivery/document_workflow_v2/final/recovery_demo"
    if (output / "draft.docx").exists():
        raise FileExistsError("recovery smoke already ran")
    output.mkdir(parents=True, exist_ok=True)
    target = output / "template.docx"
    shutil.copy2(source, target)
    original_hash = hashlib.sha256(target.read_bytes()).hexdigest()
    original = RAGTool.retrieve_knowledge

    def stop_at_fourth(self, query, top_k=None):
        if "吞吐能力" in query:
            raise KeyboardInterrupt("simulated interruption at fourth section")
        return original(self, query, top_k)

    RAGTool.retrieve_knowledge = stop_at_fourth
    try:
        try:
            DocumentWorkflow(DemoRAGClient()).run(target, output)
        except KeyboardInterrupt:
            pass
        else:
            raise AssertionError("simulated interruption did not occur")
    finally:
        RAGTool.retrieve_knowledge = original
    files = list((output / "checkpoints").glob("dw_*.json"))
    if len(files) != 1:
        raise AssertionError("expected one checkpoint")
    workflow_id = files[0].stem
    before = CheckpointStore(output / "checkpoints").load(workflow_id)
    completed = before.payload()["completed_section_ids"]
    if len(completed) != 3:
        raise AssertionError("interruption did not follow three completed sections")
    ids = {sid: before.section_drafts[sid]["evidence_ids"] for sid in completed}
    client = DemoRAGClient()
    result = DocumentWorkflow(client).resume(workflow_id, output=output)
    after = result["state"]
    if (after.workflow_status != "PARTIAL" or not result["draft_path"].is_file()
            or hashlib.sha256(target.read_bytes()).hexdigest() != original_hash
            or any(after.section_drafts[sid]["evidence_ids"] != evidence_ids for sid, evidence_ids in ids.items())
            or sum(bool(section.get("resumed_from_checkpoint")) for section in result["trace"]["sections"]) != 3):
        raise AssertionError("recovery contract failed")
    print(json.dumps({"resume_smoke": "PASS", "workflow_id": workflow_id,
                      "skipped_completed_sections": completed,
                      "evidence_ids_stable": True, "resume_rag_calls": client.calls,
                      "draft": str(result["draft_path"]),
                      "template_hash_unchanged": True}))


if __name__ == "__main__":
    main()
