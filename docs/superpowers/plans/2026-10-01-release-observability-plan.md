# Release Provenance and Public Demo Observability Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let maintainers and interview reviewers verify exactly which application, corpus and retrieval configuration are live, and diagnose request failures without logging secrets or unnecessary user content.

**Architecture:** Derive source revision from the checked-out Git commit when available and report `unknown` if it cannot be verified. Fingerprint the public corpus and policy independently, propagate a request ID through the API/UI, and provide a read-only deployment smoke that compares the deployed values with an explicitly supplied expected SHA. This plan consumes the evaluation fingerprint created by `rag-lineage-evaluation-plan.md` and depends on that plan for its final release gate.

**Tech Stack:** Python 3.12, FastAPI middleware, Git subprocess with timeout, Streamlit, pytest, HTTPX.

**Spec:** `docs/superpowers/specs/2026-10-01-ai-app-engineering-readiness-design.md`

## Global Constraints

- Build identity must be verified from the deployed checkout or controlled build manifest; never invent a revision from a local branch name or an unvalidated environment variable.
- If deployed Git metadata is unavailable, report `unknown` and fail the release comparison rather than showing a misleading SHA.
- Report separate app revision, corpus manifest/chunk fingerprint, retrieval-policy fingerprint and evaluation dataset fingerprint.
- Request telemetry may include request ID, revision, model/prompt version, policy, hit count, stage duration, status, token usage and safe failure code; never log API keys, full prompts or unnecessary raw user content.
- Public examples contain only public or clearly labeled synthetic data; no private materials are sent to a public model.
- No fixed session generation cap is introduced; supplier rate limits and costs remain external, with bounded timeout, request size and retries.
- P2 private-deployment requirements include authenticated identity, tenant isolation, pre-retrieval ACL, durable audit and retention rules; this plan documents and tests the integration boundary but does not claim to deliver enterprise SSO without an identity-provider decision.
- Deployment smoke validates live UI and RAG API against a caller-provided SHA before saying a release is current.

## Review Focus

- Missing Git metadata must display `unknown`, never a stale or fabricated SHA; Task 1 tests the fallback.
- UI and RAG API revisions that differ must fail release smoke even if both health checks pass; Task 2 tests mismatch.
- User text and credentials must not appear in structured logs; Task 3 tests a canary secret and prompt string.
- A failing model call after successful retrieval must retain evidence and log only a safe stage/status; Task 3 tests this path.
- Public hosted latency and local warm latency must be reported separately; Task 2 tests separate fields/labels.

---

### Task 1: Verified build and corpus identity endpoints

**Files:**
- Create: `versioned-rag-service/src/build_identity.py`
- Create: `demo-ui/build_identity.py`
- Create: `docs/production_readiness.md`
- Modify: `versioned-rag-service/src/public_server.py: health`
- Modify: `versioned-rag-service/src/public_api.py: workspace`
- Modify: `demo-ui/public_workbench.py: _home, _about`
- Test: `versioned-rag-service/tests/test_public_server.py`
- Test: `demo-ui/tests/test_public_official_workbench.py`

**Interfaces:**
- `git_revision(root: Path, *, timeout_seconds: float = 1.0) -> str | None` runs `git rev-parse --verify HEAD` with a timeout and returns a full 40-character SHA only on successful validation.
- `corpus_fingerprint(root: Path) -> dict` returns SHA-256 values for `corpus_manifest.json`, `chunks.json`, and active retrieval config; no source text is returned.
- Health/workspace includes `build_revision`, `corpus_fingerprint`, `retrieval_config_fingerprint`, and `evaluation_fingerprint`; unknown values are explicit.

- [ ] **Step 1: Add tests for valid Git SHA, absent Git metadata, command timeout, corpus hash changes and unknown revision.**
- [ ] **Step 2: Run `python -m pytest tests/test_public_server.py -q` from `versioned-rag-service/` and named UI tests from `demo-ui/`; confirm current API lacks verified identity fields.**
- [ ] **Step 3: Implement bounded Git revision detection and content fingerprints; surface fields in health/workspace and a compact “运行版本” UI area.**
- [ ] **Step 4: Run focused tests and complete service/UI suites; compare API and UI revisions locally.**
- [ ] **Step 5: Commit as `feat: expose verified deployment identity`.**

### Task 2: Live deployment smoke gate

**Files:**
- Create: `versioned-rag-service/scripts/public_release_smoke.py`
- Create: `versioned-rag-service/tests/test_public_release_smoke.py`
- Modify: `docs/production_readiness.md`
- Modify: `demo-ui/README.md`
- Modify: `versioned-rag-service/README.md`

**Interfaces:**
- CLI: `python versioned-rag-service/scripts/public_release_smoke.py --ui-url <url> --ui-revision <40-hex-sha> --api-url <url> --expected-sha <40-hex-sha>`.
- The script checks that the UI URL responds, validates the user-copied revision shown in the UI, requires the API revision to equal `--expected-sha`, compares corpus/policy fingerprints, then checks one Chinese query, one English query, one explicit version and one no-answer case. It does not pretend to scrape Streamlit's live rendered app state from its initial HTML.
- Exit code is `0` only when all checks pass; output excludes secrets and labels remote latency separately from local measurements.

- [ ] **Step 1: Add HTTPX tests for matching SHA, UI/API mismatch, unknown SHA, unhealthy API, wrong-version result and no-answer endpoint behavior.**
- [ ] **Step 2: Run `python -m pytest tests/test_public_release_smoke.py -q`; confirm the CLI is absent.**
- [ ] **Step 3: Implement the smoke CLI with bounded HTTP timeouts and sanitized output.**
- [ ] **Step 4: Run focused tests plus the service suite and document the exact post-deploy command and private-deployment boundary in both service/UI READMEs and `docs/production_readiness.md`.**
- [ ] **Step 5: Commit as `feat: verify deployed public release`.**

### Task 3: Safe request tracing and failure-stage metrics

**Files:**
- Create: `versioned-rag-service/src/request_observability.py`
- Modify: `versioned-rag-service/src/public_server.py`
- Modify: `versioned-rag-service/src/public_api.py: query, search, review_advice`
- Modify: `change-review-agent/app/public_review.py: retrieval_trace`
- Test: `versioned-rag-service/tests/test_public_server.py`
- Create: `versioned-rag-service/tests/test_public_api_generation.py`
- Test: `change-review-agent/tests/test_public_review.py`

**Interfaces:**
- Middleware accepts a valid incoming `X-Request-ID` or creates a UUID, returns it in the response header and request context.
- Structured event fields are `request_id`, `build_revision`, `operation`, `retrieval_policy`, `hit_count`, `stage`, `duration_ms`, `status`, `provider`, `model`, `token_usage`, and `safe_error_code`.
- Logs exclude raw question, prompt, API key and response body; detailed generation diagnostics remain available to the caller under the existing safe response contract.

- [ ] **Step 1: Add tests that send a canary secret and unique prompt phrase, then assert neither appears in captured logs; assert request ID propagation and generation-failure stage.**
- [ ] **Step 2: Run named service/agent tests and observe failures for missing request context or log events.**
- [ ] **Step 3: Implement request context and structured safe events; add no logging of raw request content.**
- [ ] **Step 4: Run focused tests and full service/agent suites; run `git diff --check`.**
- [ ] **Step 5: Commit as `feat: add privacy-safe request observability`.**

