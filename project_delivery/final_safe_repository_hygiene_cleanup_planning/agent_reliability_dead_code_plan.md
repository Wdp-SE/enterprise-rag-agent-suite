# Agent Reliability Dead-Code Removal Plan

## Finding

`app/reliability/retry.py` and `app/reliability/timeout.py` contain implemented policies with dedicated tests, but the formal Evidence-driven Document Workflow does not call any of their classes or functions.

The only production-facing references are re-exports from `app/reliability/__init__.py`. Because Python executes a package `__init__.py` before loading a submodule such as `app.reliability.budget`, those exports also cause both otherwise-unused modules to load as an import side effect. Removing the exports is therefore part of the cleanup, not an optional documentation change.

## Exact future change set

Delete these four tracked files:

- `OpenManus-rag/app/reliability/retry.py`
- `OpenManus-rag/app/reliability/timeout.py`
- `OpenManus-rag/tests/reliability/test_retry.py` (15 exclusive test functions)
- `OpenManus-rag/tests/reliability/test_timeout.py` (11 exclusive test functions)

Edit one tracked file:

- `OpenManus-rag/app/reliability/__init__.py`
  - remove imports of `RetryPolicy`, `RetryRule`, `TimeoutResolver`, and `TimeoutRule`
  - remove those four names from `__all__`

No active configuration or current documentation references the generic `RetryPolicy` / `TimeoutPolicy` implementation. No dependency can be removed solely because these files are removed: `pydantic` and the standard reliability modules remain required elsewhere.

## Required retention

Keep `rag_timeout_seconds` and `rag_retry_limit` in `app/document_workflow/configuration.py`. They are active Document Workflow settings passed to `HTTPRetrieveClient`; they are independent of the unused generic retry/timeout policy modules.

Keep `budget.py`, `errors.py`, `progress.py`, and `trace.py` plus their tests. The formal workflow imports and uses these modules. Do not broaden this change to unused fields within retained modules without a separate audit and approval.

Historical audit/manifests may continue to mention the removed modules as evidence of the earlier repository state. They should not be rewritten as if those files never existed.

## Preconditions and validation

Before a later approved removal, repeat tracked and dynamic-reference scans. After removal, run import/compile checks, the remaining Agent test suite, Agent to RAG integration, Safe Business E2E, UI tests and smoke, secret scan, and `git diff --check`. A failure or new reference stops the removal and restores the affected file from the pre-cleanup recovery point.

This document is a plan only. No Agent source, export, configuration, test, or documentation file was changed in this pass.
