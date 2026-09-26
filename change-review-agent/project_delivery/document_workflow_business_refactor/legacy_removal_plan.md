# Legacy Removal Plan

## Scope and baseline

The target product is **Evidence-driven Document Workflow Agent**: a single
business workflow that drafts and reviews enterprise R&D documents from a
structured DOCX template and evidence retrieved from a fixed external RAG
service. The RAG retrieval core is outside this refactor.

Pre-change baseline:

- Git working tree contains the preceding RAG V3 changes and they must be
  preserved.
- `tests/document_workflow`: 35 passed, 0 failed.
- Repository size excluding `.venv`, `.git`, runtime workspace and bytecode:
  599 files, 193 Python files, 28,779 Python lines.
- Product entry points: `run_document_workflow.py` and the Document Workflow
  tab in `demo-ui/app.py`.

## A. Modules actually used by Document Workflow

- `app/document_workflow/*`: template parsing/rendering, planning, RAG adapter,
  evidence cache/freshness, checkpoint, integrity and runner.
- `app/reliability/budget.py`, `progress.py`, `trace.py`: bounded execution,
  no-progress detection and structured trace.
- `app/research/models.py`: only `Evidence`, `SourceLevel` and text/hash helpers.
- `app/research/evidence_store.py`: only the local deterministic Evidence store.
- `httpx`, `pydantic`, `python-docx`: external runtime dependencies.
- `demo-ui/services/agent_client.py`, `components/workflow_view.py` and the Agent
  tab: current UI adapter and presentation.

The dependency on `app.research` is a boundary violation. The required
Evidence contract and store will be moved into `app.document_workflow` before
the Research package is removed.

## B. Generic modules retained in reduced form

- Reliability primitives that are either used directly or form the small
  supported reliability boundary: budget, errors, progress, retry, timeout and
  trace.
- Package roots and a single CLI entry point for Document Workflow.
- Rendering helper scripts used to inspect generated DOCX artifacts.

Legacy Reliability orchestrators that depend on the generic Tool/Agent stack
will not be retained merely to preserve upstream abstractions.

## C. Modules serving only legacy products

- `app/research/*` after Evidence extraction: Knowledge Research, discovery,
  selection, acquisition, archive, synthesis, Candidate Package and RAG import.
- `app/agent/*`, `app/flow/*`, `app/prompt/*`: general OpenManus/ReAct/Browser
  product paths.
- `app/tool/*`: browser, web search, crawler, shell, generic tools, candidate
  drafting and visualization tools.
- `app/sandbox/*`, `app/daytona/*`: generic sandbox product infrastructure.
- `app/mcp/*`, `protocol/a2a/*`: unused generic protocol entry points.
- Generic OpenManus web UI, examples, travel knowledge and upstream media.
- Research, candidate and sandbox tests and fixtures.
- Research profiles, source policies, MCP/Daytona/model examples and old
  Research documentation/demos.

## D. Files that can be deleted after entry-point migration

- Research CLI and generic OpenManus/MCP/Flow/Sandbox entry points.
- All legacy product modules in section C.
- Tests, fixtures, configuration, docs and dependencies that exclusively
  exercise those removed paths.
- Old V2 intermediate delivery folders after the final flagship template and
  relevant operating knowledge have been consolidated into the new delivery.

No deletion occurs until the Evidence extraction, Facade cut-over and targeted
tests pass.

## E. Code extracted before deletion

1. Stable Evidence identity, version metadata and validation move from
   `app.research.models` to the Document Workflow domain.
2. Deterministic atomic Evidence persistence moves from
   `app.research.evidence_store` to the Document Workflow retrieval boundary.
3. Generic capability enforcement is replaced with a small Document Workflow
   allowlist so the business workflow no longer depends on the legacy global
   Tool policy graph.

No Browser/Search/Candidate abstraction is considered reusable by the final
product.

## F. Affected tests, config, docs and dependencies

- Remove `tests/research`, `tests/research_live`, `tests/sandbox`, candidate and
  research fixtures, plus Reliability tests for deleted generic executors.
- Retain and extend tests for workflow, scope, planning, retrieval, evidence,
  drafting, review, checkpoint/resume, Word rendering, Facade and UI.
- Replace the broad upstream dependency list with the dependencies imported by
  the final product and retained tests.
- Replace Research-first README/delivery documents with one business README,
  architecture, runbook, demo guide, known limitations and final report.
- Remove tracked Research/Browser/Candidate configuration. The ignored local
  `config/config.toml` is not read, modified or deleted because it can contain
  user credentials; it is outside the distributable product.

## Target dependency direction

```text
Streamlit / CLI
    -> DocumentWorkflowFacade
        -> workflow runner
        -> review/finalization service
        -> workflow repository
            -> template, planning, drafting, retrieval domain services
                -> RAG client boundary / drafting backend boundary
                -> filesystem persistence boundary
```

The UI will import only the Facade. Domain and planning code will not import
Streamlit, HTTP clients or concrete LLM SDKs. The deterministic extractive
drafting backend remains the safe default; a bounded generative backend is an
explicit replacement boundary rather than an implicit online call.
