# Document Workflow V2 prototype report

This prototype drafts a structured research project plan from a DOCX template and simulated local RAG evidence. The draft remains subject to human review. It does not claim formal document approval, semantic entailment, or production readiness.

## Observed demo run

- Input: `demo/template.docx`; output: `demo/draft.docx`, `demo/evidence.json`, `demo/execution_trace.json`.
- Five section tasks ran in order. `RAGTool` made seven separate query calls against the offline simulated demo service.
- Four Evidence records were stored. The unsupported `吞吐能力` field stopped after three rounds without evidence growth and appears as `[MISSING: ...]` in the Word table.
- Every draft citation ID belongs to the EvidenceCache for its task. The original template SHA256 stayed unchanged.
- The generated DOCX and template were exported through installed Word and visually inspected as one-page documents with no clipping or missing fields. The bundled `render_docx.py` was attempted first but this Windows environment has no LibreOffice executable; Word and Poppler provided the render fallback.
- The selected new and legacy core tests finished with **342 passed, 0 failed**. Scope: `tests/document_workflow`, `tests/reliability`, `tests/research`, `tests/research_live`; sandbox/integration tests were not run.

| Acceptance item | Result |
|---|---|
| TEMPLATE_PARSE | PASS |
| SECTION_TASK_PLANNING | PASS |
| RAG_TOOL | PASS — public `/query` adapter contract tested; demo uses simulated offline RAG |
| MULTI_STEP_RETRIEVAL | PASS — seven demo RAGTool calls |
| EVIDENCE_CACHE | PASS |
| NO_PROGRESS | PASS |
| MISSING_FIELD | PASS |
| EVIDENCE_MEMBERSHIP | PASS |
| DOCX_RENDER | PASS |
| ORIGINAL_TEMPLATE_UNCHANGED | YES |
| DOCUMENT_WORKFLOW_POLICY | PASS |
| OLD_RESEARCH_WORKFLOW_PRESERVED | YES |
| CURRENT_TEST_RESULT | 342 passed / 0 failed (selected suites) |
| PROTOTYPE_MAIN_CHAIN | PASS — offline simulated corpus |
| READY_FOR_ENGINEERING_HARDENING | NO |

The frozen RAG V2 API was inspected but not connected to its real research corpus in this demo. Its `/query` response has cited document/page metadata and an answer only when generation is enabled; with external generation disabled by data policy it returns `N/A` and no cited sources. A source-text retrieval boundary or an approved safe generation configuration is needed before the workflow can draft from that real corpus. The HTTP adapter never opens or modifies RAG artifacts.
