# RAG + Document Workflow Agent Streamlit Demo UI report

The workspace now contains an independent `demo-ui/` interview layer. It reads and calls the two frozen projects through their existing public boundaries: HTTP `/health`, `/artifacts/status`, `/query`, and `/retrieve` for RAG; public `TemplateParser`, `SectionTaskPlanner`, and `DocumentWorkflow` Python entrypoints for the Agent. No RAG or Agent Core file was edited in this UI sprint.

## Acceptance results

```text
DEMO_UI_READY = YES
STREAMLIT_READY = YES
DEMO_UI_DIRECTORY_CREATED = YES
RAG_SERVICE_STATUS_READY = YES
RAG_ARTIFACT_STATUS_READY = YES
RAG_TAB_READY = YES
RAG_QUERY_READY = NOT_USED
RAG_RETRIEVAL_READY = YES
RETRIEVAL_EVIDENCE_VISUALIZED = YES
DOCUMENT_PAGE_VISUALIZED = YES
SECTION_PATH_VISUALIZED = YES
SIMILARITY_VISUALIZED = YES
AGENT_TAB_READY = YES
DOCX_UPLOAD_READY = YES
SAFE_DEMO_TEMPLATE_READY = YES
TEMPLATE_PARSE_VISUALIZED = YES
SECTION_TASK_VISUALIZED = YES
REAL_RAG_CALLS_VISUALIZED = YES
AGENT_EVIDENCE_VISUALIZED = YES
MISSING_VISUALIZED = YES
WORKFLOW_STATUS_VISUALIZED = YES
PARTIAL_STATUS_PRESERVED = YES
HUMAN_REVIEW_VISUALIZED = YES
DRAFT_DOWNLOAD_READY = YES
EVIDENCE_DOWNLOAD_READY = YES
TRACE_DOWNLOAD_READY = YES
SESSION_STATE_GUARD = PASS
RAG_UNAVAILABLE_HANDLING = PASS
INVALID_DOCX_HANDLING = PASS
SAFE_DEMO_DATA = YES
REAL_INTERNAL_DATA_SENT_TO_ONLINE_LLM = NO
RAG_CORE_UNCHANGED = YES
AGENT_CORE_BUSINESS_LOGIC_UNCHANGED = YES
FINAL_UI_SMOKE = PASS
DOCX_RENDER = PASS
READY_FOR_INTERVIEW_DEMO = YES
PRODUCTION_READY = NO CLAIM
```

`RAG_QUERY_READY = NOT_USED` means the tab and client support the frozen `/query` endpoint, but the final safe service explicitly used `RD_V2_ALLOW_EXTERNAL_GENERATION=false`; no online generation was triggered. The interview-ready acceptance path relies on retrieval-only `/retrieve`.

## What was implemented

- Enterprise-style Streamlit page with system status sidebar, restrained blue/white/gray styling, RAG and Agent tabs, and short interface-boundary explanations.
- A thin RAG HTTP client with timeout, connection/HTTP/malformed-response handling and contract validation.
- A thin Agent adapter that imports the existing workflow, saves uploads in isolated runtime directories, calls the real runner, and serializes its result for display. It contains no workflow, Evidence, lifecycle, or finalization reimplementation.
- Evidence cards showing actual IDs, document, page, section path, similarity/content preview where applicable, with full content inside expanders.
- Template summary and PENDING SectionTask plan from the existing Parser/Planner, followed by real result status, query/RAG/Evidence/MISSING counts, stop reasons, draft previews, and actual Trace events.
- DOCX, Evidence JSON, and Trace JSON downloads. `st.session_state` keeps one result until the user explicitly loads/runs another template.
- Upload/output isolation under ignored `runtime/`; original files are never used as renderer targets.

## Real smoke evidence

Both services were started locally. Streamlit returned HTTP 200 from `/_stcore/health` and its root page. The RAG service returned HTTP 200 with `READY`, artifact `COMPLETE`, retrieval policy `DENSE_ONLY`, and dense representation `SECTION_PATH`.

The running Streamlit app was exercised through its actual widgets using Streamlit AppTest against that live RAG service:

1. `项目背景是什么？` returned 5 results. Rank 1 was `safe-project-plan`, physical page 1, section path `项目背景`, similarity `0.6290019750595093`.
2. `项目目标是什么？` returned 5 results. Rank 1 was `safe-project-plan`, physical page 2, section path `项目目标`, similarity `0.6486618518829346`.
3. The Agent tab loaded the retained safe template, displayed 8 parsed template sections and 5 planned SectionTasks, then ran the existing workflow through real HTTP `/retrieve` calls. Result: 5 tasks, 8 RAG calls, 14 unique Evidence records, 1 missing field (`吞吐能力`), status PARTIAL, and `requires_human_review=true`.
4. All three downloads were present and readable. The DOCX was a valid ZIP/OpenXML document; Evidence/Trace JSON parsed successfully. A plain Streamlit rerun retained the same workflow ID, call count, and artifact paths, so it did not repeat the workflow.

The UI adapter tests passed **4/4**. They cover app import/rendering, unavailable RAG behavior, health/retrieve contracts, malformed responses, invalid DOCX, safe Agent execution, and readable output artifacts.

Microsoft Word opened the UI-produced DOCX and exported it to a one-page PDF. Visual inspection found readable headings, body text, four Evidence citations, the table, and the visible MISSING marker without clipping or overlap. The PDF is a temporary QA artifact under ignored runtime output.

## Core integrity and data boundary

No file under `change-review-agent/app/document_workflow` or `versioned-rag-service/src` was changed on the UI sprint date. All source additions are under `demo-ui/`. Runtime execution writes only under `demo-ui/runtime/`, which `.gitignore` excludes. No Agent facade was added to the frozen project because its public Python runner was sufficient.

The smoke used the retained synthetic/public artifact and template. External RAG generation was disabled, so no internal or demo text was sent to an online LLM. The UI can disable `/query` for any classification other than Synthetic, Public, Synthetic / Public, or Approved Redacted.

The previously established selected relevant regression remains RAG 290 + Agent 286 = 576 passed / 0 failed; those suites were not rerun because neither frozen core was changed. This count does not include all live/sandbox suites.

The UI is ready for a local interview demonstration. It is not a production frontend or a production readiness claim. Development stops at this report.
