# Evidence-Grounded Change Review Agent Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make change-impact reviews easier to trust and read by evaluating query planning, preserving evidence lineage and separating confirmed engineering links from semantic suggestions.

**Architecture:** Keep the deterministic bounded request planner, call the public RAG service for each planned query, and validate all returned advice against the evidence IDs actually retrieved. Render the result as review candidates, supporting evidence and missing checks; never imply an automated approval or probability confidence. Relation-state rendering consumes the API contract from `rag-lineage-evaluation-plan.md`; final end-to-end evaluation runs with the policy selected by `rag-retrieval-figure-plan.md`.

**Tech Stack:** Python 3.12, Pydantic, FastAPI client, pytest, Streamlit.

**Spec:** `docs/superpowers/specs/2026-10-01-ai-app-engineering-readiness-design.md`

## Global Constraints

- The primary workflow is change impact review; direct knowledge Q&A remains secondary.
- The planner stays bounded at no more than four RAG queries and total timeout/context boundaries remain enforced server-side.
- Every candidate must cite an evidence ID from the current request's retrieved set or be marked unsupported/omitted.
- Explicit source relationships and validated document pairs are distinct from semantic suggestions; similarity alone never becomes a confirmed TraceLink.
- Evidence insufficiency, version ambiguity and unverified language relationships remain visible as gaps requiring a human reviewer.
- No numeric confidence probability is shown unless separately calibrated; retrieval score and evidence keyword coverage are not confidence.
- Review decisions remain human-controlled; the public demo does not modify upstream sources.
- Private data, ACL, identity and durable enterprise audit remain future private-deployment work; do not imply those exist in the public demo.
- Provisional latency targets: single-turn P95 ≤15 s and bounded review P95 30–45 s, measured independently from cold start.

## Review Focus

- An unknown change type must use the general plan and stay under four queries; Task 1 tests fallback and query bounds.
- A model-advice citation outside retrieved evidence must be rejected; Task 2 tests citation membership.
- A no-answer or provider failure must retain retrieved evidence and expose the specific failure stage; Task 2 tests both outcomes.
- A semantic candidate must not be displayed with the visual treatment of a confirmed relationship; Task 3 tests distinct labels.
- An unverified Chinese/English counterpart must remain a “needs verification” gap rather than a drift conclusion; Tasks 2 and 3 test relation propagation.

---

### Task 1: Change-review evaluation for planner quality

**Files:**
- Modify: `evaluation/agent_query_decomposition/cases.jsonl`
- Modify: `evaluation/agent_query_decomposition/run_evaluation.py`
- Create: `evaluation/agent_query_decomposition/test_evaluation.py`
- Modify: `evaluation/change_review_v5/cases.jsonl`
- Modify: `evaluation/change_review_v5/split_lock.json`
- Modify: `evaluation/change_review_v5/run_evaluation.py`
- Test: `evaluation/change_review_v5/test_evaluation.py`

**Interfaces:**
- Query-planning cases record `case_id`, `family_id`, `summary`, expected `change_type`, required clauses, scope and expected relation state.
- Change-review cases additionally carry version, language, required source IDs, expected image IDs and answerability.
- Metrics report change-type accuracy, query clause coverage, query-budget compliance, candidate source recall/complete recall, version errors, image coverage, no-answer candidate rate, API-call count and latency separately.

- [ ] **Step 1: Add cases/tests for parameter, interface, workflow and unknown/general changes; include an unanswerable and unverified-translation scenario.**
- [ ] **Step 2: Run `python -m pytest evaluation/agent_query_decomposition/test_evaluation.py evaluation/change_review_v5/test_evaluation.py -q`; confirm coverage/validator assertions fail.**
- [ ] **Step 3: Extend the frozen set to 60–80 cases grouped by document family, split without family leakage, and report metrics by category without using generated-model self-ratings as correctness labels.**
- [ ] **Step 4: Implement exact case validation and metrics; preserve the four-query hard cap.**
- [ ] **Step 5: Run both evaluation commands and repeat to verify hashes/metrics are stable; record known dataset limitations.**
- [ ] **Step 6: Commit as `test: expand change-review evaluation`.**

### Task 2: Enforce evidence-grounded review response contract

**Files:**
- Modify: `change-review-agent/app/public_review.py: _normalize_review_advice, PublicReviewAgent.analyze_request`
- Modify: `change-review-agent/app/change_request.py: build_request_plan`
- Test: `change-review-agent/tests/test_public_review.py`
- Test: `change-review-agent/tests/test_change_request.py`
- Test: `versioned-rag-service/tests/test_public_server.py`

**Interfaces:**
- Review result includes `stage_status` values `OK`, `EMPTY`, `FAILED`, `SKIPPED`, or `OUT_OF_SCOPE` for planning/retrieval/generation; each `evidence_gaps` item includes `gap_type` (`NO_REQUIRED_SOURCE`, `UNVERIFIED_TRANSLATION`, `VERSION_AMBIGUITY`, `IMAGE_NOT_REVIEWED`, `OUT_OF_SCOPE`, or `RETRIEVAL_FAILED`), `missing_source_type`, nullable `expected_version`, `suggested_query`, and readable `description`.
- Any model-proposed `evidence_chunk_id` not present in the current evidence allowlist is removed and recorded as `INVALID_CITATION`; empty support returns an evidence-limited result, not fabricated advice.
- Existing outputs remain backward-compatible for `status`, `sources`, `review_status`, `retrieval_trace` and human decision handling.

- [ ] **Step 1: Add failing tests for an invented citation, a provider timeout after successful retrieval, and no retrieved evidence.**
- [ ] **Step 2: Run `python -m pytest tests/test_public_review.py tests/test_change_request.py -q` from `change-review-agent/`; verify expected failures.**
- [ ] **Step 3: Implement structured gap types and stage status, filter citations against the current allowlist, and preserve evidence on generation failure.**
- [ ] **Step 4: Run focused tests and all `change-review-agent/tests`; run the service tests for response compatibility.**
- [ ] **Step 5: Commit as `feat: enforce evidence-grounded review output`.**

### Task 3: Review-first result layout in Streamlit

**Files:**
- Modify: `demo-ui/public_workbench.py: _impact_panel, _review_evidence_panel, _review_advice_panel, _retrieval_trace_panel, _review_panel`
- Test: `demo-ui/tests/test_public_official_workbench.py`
- Test: `demo-ui/tests/test_business_workflow_ui.py`
- Test: `demo-ui/tests/test_review_audit.py`

**Interfaces:**
- Default review view renders in order: change summary/scope; impact candidates with relationship status; evidence and version; missing checks; reviewer decision. Request IDs, model and latency remain inside a technical-details expander.
- Labels distinguish `CONFIRMED`, `SUGGESTED`, `UNVERIFIED`, and `MISSING_EVIDENCE`; no probability-style confidence badge is added.

- [ ] **Step 1: Add Streamlit AppTest cases for confirmed vs suggested relations, structured gaps and collapsed technical details.**
- [ ] **Step 2: Run `python -m pytest tests/test_public_official_workbench.py tests/test_business_workflow_ui.py tests/test_review_audit.py -q` from `demo-ui/`; verify failing presentation assertions.**
- [ ] **Step 3: Reorder existing result components and simplify copy without hiding evidence, version or human-review actions.**
- [ ] **Step 4: Run focused UI tests and the complete `demo-ui/tests` suite.**
- [ ] **Step 5: Commit as `feat: clarify evidence and review priorities`.**

