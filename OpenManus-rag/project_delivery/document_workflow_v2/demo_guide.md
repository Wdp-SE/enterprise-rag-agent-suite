# Demo guide

Run from the repository root with the project virtual environment:

```powershell
.venv\Scripts\python.exe scripts\create_document_demo_template.py
.venv\Scripts\python.exe run_document_workflow.py --template project_delivery\document_workflow_v2\demo\template.docx --output project_delivery\document_workflow_v2\demo --demo-rag
```

The demo uses simulated project snippets and makes no online LLM call. Open `demo/draft.docx` to review the filled sections and the `吞吐能力` MISSING marker. `demo/evidence.json` contains the cited text and source metadata; `demo/execution_trace.json` contains task counts, stop reasons, and hashed queries. `requires_human_review` is true in both JSON outputs and all SectionDraft objects.

For an authorized frozen RAG V2 service, replace `--demo-rag` with `--rag-url http://HOST:PORT`. The service must return `status=OK`, cited `sources`, and an answer or source text; otherwise fields remain MISSING. Do not point it at real internal material if its generation settings would send that material to an unapproved external model.

Install the added `python-docx` dependency from `requirements.txt` before running on a fresh environment. The CLI writes a new `draft.docx` and never writes to the input template path.
