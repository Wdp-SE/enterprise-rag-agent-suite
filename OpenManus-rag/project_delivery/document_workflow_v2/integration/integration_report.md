# RAG × Document Workflow integration report

The structured Word workflow now obtains raw Evidence through the frozen RAG V2 `POST /retrieve` service boundary. The existing Agent prototype components and the RAG dense retrieval algorithm were retained. One safe, real-HTTP E2E generated a human-reviewable draft from a separate synthetic/public artifact namespace and stopped at this integration sprint.

## Acceptance results

```text
WORKSPACE_AGENT_REPO = ../OpenManus-rag
WORKSPACE_RAG_REPO = ../RAG-Challenge-2-main
RAG_RETRIEVE_API = PASS
RETRIEVAL_ONLY_NO_LLM = PASS
RAG_CORE_UNCHANGED = YES
FINAL_RETRIEVAL_POLICY = DENSE_ONLY
FINAL_DENSE_REPRESENTATION = SECTION_PATH
RAG_ARTIFACT_VALIDATION_PRESERVED = YES
EXISTING_QUERY_API_PRESERVED = YES
REAL_RAGTOOL_ADAPTER = PASS
MOCK_RAGTOOL_PRESERVED = YES
AGENT_DIRECT_FAISS_ACCESS = NO
EVIDENCE_METADATA_PRESERVED = PASS
EVIDENCE_ID_STABLE = PASS
EVIDENCE_CACHE = PASS
EVIDENCE_DEDUP = PASS
EVIDENCE_MEMBERSHIP = PASS
MULTI_SECTION_REAL_RAG_CALLS = PASS
NO_PROGRESS = PASS
MISSING_FIELD = PASS
DOCX_RENDER = PASS
ORIGINAL_TEMPLATE_UNCHANGED = YES
REQUIRES_HUMAN_REVIEW = TRUE
DOCUMENT_WORKFLOW_POLICY = PASS
OLD_RESEARCH_WORKFLOW_PRESERVED = YES
REAL_INTERNAL_DATA_SENT_TO_ONLINE_LLM = NO
DATA_POLICY = PASS
SAFE_END_TO_END_DEMO = PASS
RAG_TEST_RESULT = 290 passed / 0 failed
AGENT_TEST_RESULT = 271 passed / 0 failed
TOTAL_RELEVANT_REGRESSION = 561 passed / 0 failed
READY_FOR_ENGINEERING_HARDENING = YES
PRODUCTION_READY = NO CLAIM
```

## Evidence for the decision

The private frozen service started with a validated 5090-chunk, 512-dimensional formal artifact. Four local queries returned raw chunk text and metadata matching the artifact; the API unit test forbids generator invocation. `/query` behavior remained covered by the old API test. No runtime, embedding, chunk, FAISS, or retrieval policy source was changed, and the completed official artifact was not rebuilt or overwritten.

The Agent CLI used `HTTPRetrieveClient`, and the safe E2E Trace records `/retrieve`, five section tasks, eight RAG calls, 14 unique Evidence items, and repeated-hit reuse. The source template hash remained unchanged. Four cited IDs appear in the current Evidence output, while the throughput field is visibly MISSING. The retained offline test verifies the NoProgress stop condition; the safe E2E itself reached MISSING without triggering NoProgress. A read-only cross-boundary check matched every emitted Evidence item's chunk ID, document ID, section ID/path, physical page, normalized content, and content hash to the safe frozen artifact.

The Word-exported one-page draft was inspected for heading, paragraph, citation, table, and missing-marker layout. The policy still allows only RAG query, template read, and draft write in this business workflow; old knowledge research, browser, source acquisition, and candidate importer code remains present. The full RAG suite and selected Agent document/reliability/offline-research suites had no failures. The readiness decision means the integration has met the listed entry conditions for a later engineering-hardening sprint; it is not a deployment or correctness claim.

## Deliverables

- `demo/template.docx`, `demo/draft.docx`, `demo/evidence.json`, `demo/execution_trace.json`
- `architecture_integration.md`, `integration_test_summary.md`, `known_limitations.md`
- RAG service contract in `RAG-Challenge-2-main/docs/retrieval_api.md`

No retrieval benchmark, new business scenario, or production deployment was undertaken.
