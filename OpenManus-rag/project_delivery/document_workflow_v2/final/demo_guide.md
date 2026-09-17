# Safe demo guide

From `OpenManus-rag`, use the project virtual environment. The final artifacts from the single safe smoke are in `final/demo/`: `template.docx`, `draft.docx`, metadata-only `evidence.json`, `execution_trace.json`, and local recovery state. Open `draft.docx` to see four cited sections and the `吞吐能力` MISSING table cell. The one-page Word-exported PDF and page image are under `final/qa/`. All content is synthetic/public and requires human review.

For a fresh offline CLI demo, choose a new output directory:

```powershell
.venv\Scripts\python.exe run_document_workflow.py --template project_delivery\document_workflow_v2\integration\demo\template.docx --output workspace\new-document-demo --demo-rag
```

For an authorized local frozen RAG service, pass `--rag-url http://127.0.0.1:PORT` instead of `--demo-rag`. The Agent calls only `/retrieve`; RAG startup and artifact readiness were checked in the final safe smoke. The CLI prints the workflow ID and status. If interrupted, use the same RAG mode, template/config, and output path:

```powershell
.venv\Scripts\python.exe run_document_workflow.py --resume dw_WORKFLOW_ID --output workspace\new-document-demo --demo-rag
```

The normal safe HTTP smoke can be reviewed with `scripts/validate_document_integration_demo.py` pointed at `project_delivery/document_workflow_v2/final/demo`. `scripts/run_document_hardening_safe_smoke.py` and `scripts/run_document_resume_smoke.py` refuse a duplicate run in their fixed final output directories. They are validation scripts, not a service deployment. No real internal R&D body may be sent to an online model without explicit authorization.
