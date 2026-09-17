# RAG + Document Workflow Agent Streamlit Demo

This is a local interview/demo layer over two frozen projects. It calls the existing RAG HTTP API and the existing Document Workflow Agent runner. It does not implement retrieval, Evidence identity, workflow, checkpoint, or finalization logic.

## Install

From the workspace root, install only the UI dependency into the existing Agent environment:

```powershell
OpenManus-rag\.venv\Scripts\python.exe -m pip install -r demo-ui\requirements.txt
```

## Start the safe RAG service

The commands below select the retained synthetic/public artifact and disable external generation. Keep this terminal open:

```powershell
cd RAG-Challenge-2-main
$env:RD_V2_PROJECT_ROOT = (Get-Location).Path
$env:RD_V2_ARTIFACT_ROOT = (Resolve-Path 'data\rd_v2_corpus\retrieval_artifacts\rd-v2-retrieval-final-v1.0-safe-integration').Path
$env:RD_V2_ALLOW_EXTERNAL_GENERATION = 'false'
.venv\Scripts\python.exe -m uvicorn src.rd_v2_api:app --host 127.0.0.1 --port 8765
```

Confirm `http://127.0.0.1:8765/health` and `/artifacts/status` before the demo. With external generation disabled, `/retrieve` is the primary safe demo path. `/query` remains visible in the UI because it is part of the frozen API, but a successful answer depends on the RAG service generation configuration.

## Start Streamlit

In a second terminal:

```powershell
cd demo-ui
..\OpenManus-rag\.venv\Scripts\python.exe -m streamlit run app.py --server.address 127.0.0.1 --server.port 8501
```

Or run `powershell -ExecutionPolicy Bypass -File .\start_demo.ps1`. No separate Agent service is needed: `services/agent_client.py` calls the existing public Python runner synchronously. The UI uses `st.session_state`; ordinary expand/download interactions do not rerun the workflow.

## Demo data and outputs

The default data label is `Synthetic / Public`. Uploaded templates and outputs go under `demo-ui/runtime/`, which is ignored by Git. Each upload/run gets a new directory and the original template is never overwritten. Generated drafts always require human review. Do not point `/query` at unauthorized internal material if the configured RAG generation provider may send context to an external model. Set `DEMO_DATA_CLASSIFICATION` to a non-safe value to disable the `/query` button.

## Troubleshooting

- **RAG Service Unavailable**: start the RAG command above and refresh Streamlit.
- **Artifact Not Ready**: verify `RD_V2_ARTIFACT_ROOT` points to the completed safe artifact.
- **Invalid DOCX**: use a valid structured `.docx` with supported headings/placeholders.
- **Workflow PARTIAL**: this is expected when Evidence is insufficient; inspect MISSING and stop reason.
- **Port occupied**: select another Streamlit port. If the RAG port changes, set `DEMO_RAG_BASE_URL` before starting Streamlit.

Run the small adapter tests with:

```powershell
..\OpenManus-rag\.venv\Scripts\python.exe -m pytest tests -q
```

