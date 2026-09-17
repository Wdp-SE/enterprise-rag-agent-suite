# Workflow and SectionTask lifecycle

WorkflowState starts PENDING, changes to RUNNING before section processing, and ends COMPLETE only when every required section is COMPLETE and output integrity passes. It ends PARTIAL when a deliverable draft has missing or incomplete required sections; the safe E2E is PARTIAL because throughput is MISSING. An integrity/rendering failure moves to FAILED and saves a checkpoint. A process interruption may leave RUNNING at the last safe checkpoint for resume.

Each planned SectionTask has a stable task and section ID, PENDING/RUNNING/COMPLETE/PARTIAL/NO_PROGRESS/FAILED vocabulary, timestamps, attempt count, queries, Evidence IDs, missing fields, stop reason, and typed error fields. Current recoverable RAG errors produce PARTIAL with a missing marker and `RAG_ERROR` stop reason; NO_PROGRESS is a business stop when Evidence growth stalls. Budget and timeout are hard resource boundaries. Later independent sections may continue after a recoverable section failure.

Finalization compares every planned task with exactly one SectionDraft, checks the fields and missing state, verifies cited Evidence IDs against EvidenceCache, verifies the original template hash, and enforces human review. Saving a DOCX alone does not set COMPLETE. Unknown IDs produce `EVIDENCE_MEMBERSHIP_INVALID` and block finalization.
