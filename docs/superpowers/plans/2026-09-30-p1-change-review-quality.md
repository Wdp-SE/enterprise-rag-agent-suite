# P1 Change Review Quality Work Plan

## Goal and boundaries

Implement the three approved P1 improvements for the public, version-aware change-review workflow: broaden and freeze a realistic offline evaluation set, persist human review events beyond Streamlit session state, and make only evaluation-supported changes to deterministic request planning. Preserve the frozen V4 retrieval artifacts, current BM25 serving policy, evidence allowlist, human-review boundary, and no-writeback behavior. Do not call paid generation APIs during offline evaluation.

The audit store is SQLite with a configurable file path. It records the user-entered change summary and the review report only when a reviewer clicks a decision button. The UI must disclose that the demo has no authenticated reviewer identity and that hosted ephemeral storage may be cleared on restart. This is session-independent demo persistence, not a production audit service.

## Files and responsibilities

- `evaluation/change_review_v5/cases.jsonl`: new manually annotated change-review cases, grouped by case family.
- `evaluation/change_review_v5/run_evaluation.py`: deterministic evaluation of request classification, clause coverage, query budget, required-source recall, version correctness, and no-answer candidate noise against the pinned public corpus.
- `evaluation/change_review_v5/README.md`: freeze/split rules, metric definitions, reproducible commands, and interpretation limits.
- `evaluation/change_review_v5/test_evaluation.py`: evaluator, split integrity, metric, and current planner contract tests.
- `change-review-agent/app/change_request.py`: only targeted deterministic planner fixes justified by DEV failures.
- `change-review-agent/app/review_audit.py`: SQLite append-only review-event repository and serialization boundary.
- `change-review-agent/tests/test_review_audit.py`: persistence, ordering, and data round-trip tests using temporary SQLite files.
- `demo-ui/public_workbench.py`: persist decision callbacks, show audit state/history, and explain identity and hosted-storage limits.
- `demo-ui/tests/test_public_review_audit.py`: UI helper/record integration tests where existing Streamlit test support permits.
- `README.md`: explain V5 metrics and public review audit scope without overstating production readiness.

## Execution tasks

### 1. Establish V5 evaluation baseline

1. Add a new, version-controlled case set with realistic parameter/configuration, API compatibility, workflow recovery, cross-document, version-specific, and unanswerable requests. Bind expected source keys/markers and family IDs; do not edit V4 files.
2. Write evaluator tests first for stable family split, exact change-type checks, clause coverage, query-budget enforcement, expected-source recall, version mismatch, and unanswerable candidate reporting.
3. Run the evaluator against the existing planner and pinned BM25 corpus. Save the baseline report and use DEV failures only to decide whether planner behavior should change.
4. Freeze input/split hashes and document that this offline suite does not call or score the LLM answer generator.

### 2. Improve only demonstrated planner failures

1. Add one regression test per DEV failure before changing production planner code.
2. Make the smallest deterministic change that fixes the failure while retaining the four-query hard bound and original request query.
3. Run planner and V5 DEV tests; then run the frozen V5 HOLDOUT once and save its report without tuning against it.

### 3. Persist human review decisions

1. Test a SQLite repository API for append-only decisions, JSON payload round trips, and retrieval ordered by decision time.
2. Implement the repository using SQLite standard library only; key each event independently so a later return/review action does not erase prior history.
3. Wire approve/reject callbacks to save a compact event containing task/fingerprint, mode, summary, request plan, retrieval trace, evidence IDs, model status, decision, UTC time, and pseudonymous session ID.
4. Show the saved outcome and recent events in the workbench. State clearly that identities are not authenticated and hosted files may disappear on deployment restart.
5. Keep the existing downloadable JSON export and ensure persistence failure is surfaced without falsely claiming it was saved.

### 4. Verify and update product claims

Run the focused planner, audit, and evaluation test suites, then the relevant full component tests available in the current environment. Confirm V4 files are unchanged, the public BM25 default is unchanged, no paid API was called, and the working tree contains no unrelated changes. Update README limitations and commands with measured V5 results.
