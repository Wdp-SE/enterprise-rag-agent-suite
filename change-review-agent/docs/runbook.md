# Runbook

1. Start the external version-aware RAG service on `127.0.0.1:8765`.
2. Set `RAG_BASE_URL` or pass `--rag-url` to the CLI.
3. Start Streamlit from `demo-ui`.
4. Select project and document/version scope before loading a template.
5. Run the workflow, inspect Query/Evidence/Draft/Freshness for every section.
6. Enter a reviewer, edit fields when necessary, then approve or reject.
7. Generate Approved DOCX only after every section is approved.

For offline verification:

```powershell
.venv\Scripts\python.exe scripts\run_business_e2e.py
.venv\Scripts\python.exe -m pytest tests -q
```

Runtime uploads, checkpoints and output files belong under ignored runtime
directories. Do not commit API credentials or unauthorized enterprise data.
