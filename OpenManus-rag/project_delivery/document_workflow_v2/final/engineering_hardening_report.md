# Document Workflow Agent V2 engineering hardening

The fixed template-to-RAG-to-DOCX chain now has validated central configuration, explicit lifecycle state, atomic section checkpoints, resume, and a finalization contract. The Agent still obtains raw Evidence only through the frozen RAG `/retrieve` API; this sprint made no RAG Core edits or retrieval research changes. The safe final result is a **PARTIAL**, human-reviewed draft because the throughput field has no explicit Evidence. This is a demo and interview engineering result, not a production certification.

## Acceptance record

```text
CENTRAL_CONFIG_READY = YES
CONFIG_FAIL_FAST = PASS
WORKFLOW_LIFECYCLE_READY = YES
SECTION_LIFECYCLE_READY = YES
DURABLE_WORKFLOW_STATE = YES
CHECKPOINT_READY = YES
CHECKPOINT_ATOMIC = YES
CHECKPOINT_VERSIONED = YES
RESUME_READY = YES
RESUME_SKIPS_COMPLETED_SECTIONS = PASS
EVIDENCE_ID_STABLE_AFTER_RESUME = PASS
OUTPUT_VALIDATION_READY = YES
EVIDENCE_FAIL_CLOSED = YES
FINALIZATION_GUARD = PASS
ORIGINAL_TEMPLATE_PROTECTED = PASS
REQUIRES_HUMAN_REVIEW = TRUE
RAG_FAILURE_RECOVERY = PASS
RETRY_OWNERSHIP_PRESERVED = YES
NO_PROGRESS_PRESERVED = YES
TRACE_DATA_MINIMIZATION = PASS
SECRET_HANDLING = PASS
DOCUMENT_WORKFLOW_POLICY = PASS
RAG_CORE_UNCHANGED = YES (no RAG source or artifact edit in this sprint; workspace has no Git metadata for diff verification)
FINAL_RETRIEVAL_POLICY = DENSE_ONLY
FINAL_DENSE_REPRESENTATION = SECTION_PATH
SAFE_FINAL_E2E = PASS
RESUME_SMOKE = PASS
DOCX_RENDER = PASS
OLD_RESEARCH_WORKFLOW_PRESERVED = YES
REAL_INTERNAL_DATA_SENT_TO_ONLINE_LLM = NO
DATA_POLICY = PASS
RAG_TEST_RESULT = 290 passed / 0 failed
AGENT_TEST_RESULT = 286 passed / 0 failed
TOTAL_RELEVANT_REGRESSION = 576 passed / 0 failed
TEST_SCOPE = RAG tests/; Agent tests/document_workflow, tests/reliability, tests/research
NOT_RUN_TEST_SCOPE = Agent tests/research_live, tests/sandbox; no holdout or live credentials suite
READY_FOR_RESUME = YES
READY_FOR_INTERVIEW = YES
READY_FOR_DEMO = YES
PRODUCTION_READY = NO CLAIM
```

## Evidence and limits of the checks

The final local HTTP smoke reused the existing synthetic/public RAG artifact and Word template. `/health` and `/artifacts/status` reported a COMPLETE artifact with DENSE_ONLY + SECTION_PATH. Five section tasks made eight real `/retrieve` calls, stored 14 unique Evidence identities, cited four IDs, and marked `吞吐能力` MISSING. The finalization guard passed and returned PARTIAL, `requires_human_review=true`; `draft.docx`, Evidence JSON, and Trace JSON exist. The original template SHA256 remained `c933d53ae806bdc3b937e30879e800e07a00f01c496df1b3b8eead21f1ced2e4`. The retained integration validator passed against the new outputs. NoProgress was covered by offline tests and did not trigger in this HTTP smoke.

An independent recovery smoke interrupted the safe mock workflow after three completed section checkpoints, restored EvidenceCache from the versioned recovery state, skipped those sections, preserved their Evidence IDs, and generated a final draft. The recovery smoke used the offline safe mock RAG, while the normal smoke used the real local HTTP RAG service. A corrupt JSON checkpoint, incompatible version, template hash change, invalid Evidence references, and atomic replacement failure are covered by focused tests.

Microsoft Word exported the final DOCX to a one-page PDF. Visual inspection found readable headings, paragraphs, citations, the table, and the MISSING marker, with no visible overlap or clipping. The PDF is a QA artifact, not an approved business document.

Timeout/connection/5xx/schema failure paths were covered by deterministic adapter and workflow tests. The HTTP adapter owns finite retries for timeout, connection errors, and 5xx; schema violations fail immediately. This does not prove uptime or recovery under every real network fault. The selected regression is not the whole Agent repository. The project copy has no `.git` directory, so “RAG Core unchanged” records the absence of RAG edits in this sprint rather than a Git diff comparison.

Final freeze suggestion: `document-workflow-agent-v2.0`. No remote tag or publication was created. Core development stops here.
