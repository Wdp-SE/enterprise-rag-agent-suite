# Final Safe Repository Hygiene Cleanup Plan

## Decision

This pass is planning-only. It rechecked every one of the 607 original `SAFE_TO_REMOVE` files and did not delete or modify any candidate, runtime file, test, configuration, user data, recovery point, or prior engineering report.

Recheck result:

| Classification | Files | Planned treatment |
|---|---:|---|
| `CONFIRMED_SAFE_TO_REMOVE` | 606 | Eligible for a later, explicitly approved deletion pass |
| `RETAINED_AFTER_RECHECK` | 0 | Keep |
| `REVIEW_REQUIRED_AFTER_RECHECK` | 1 | Excluded from deletion until a separate ownership decision |

The output manifest contains exactly 607 entries and is bound to the source manifest by SHA-256 `f4d0bf4d67b332424bf1d1b44dd842d8bcf2411bf781fd5364713fa74a203650`.

## What was rechecked

Each entry records existence, Git state, artifact class, file size, exact references from tracked runtime/test/benchmark/demo/entrypoint/config/docs files, protected-data intersection, Git metadata status, and final-report status. The recheck also inspected formal runtime dynamic-load surfaces; none load a candidate path.

The 607 files break down as follows:

| Artifact class | Files | Git state | Recheck outcome |
|---|---:|---|---|
| Python / pytest cache | 324 | ignored | confirmed safe |
| Historical upstream OpenManus logs | 257 | ignored | confirmed safe |
| RAG rendered-page temporary artifacts | 14 | ignored | confirmed safe |
| Retired Knowledge Research Phase 1B outputs | 5 | ignored | confirmed safe |
| Historical local run transcript | 1 | ignored | confirmed safe |
| Nested upstream OpenManus GitHub metadata | 5 | tracked | confirmed safe |
| `OpenManus-rag/CODE_OF_CONDUCT.md` | 1 | tracked | review required after recheck |

The candidates total 8,745,426 bytes. The logs are January 2026 upstream OpenManus execution logs and contain no current Document Workflow, `rd_v2`, `SECTION_PATH`, ACTIVE/SUPERSEDED, or template workflow markers. The RAG images are reproducible render outputs; the protected source corpus is not in this manifest. Cache files are reproducible from source and tests. The five nested `.github` files are tied to the original `FoundationAgents/OpenManus` repository and are not root-level GitHub configuration for this monorepo.

## Recheck exception

`OpenManus-rag/CODE_OF_CONDUCT.md` was downgraded to `REVIEW_REQUIRED_AFTER_RECHECK`. It does not affect runtime, tests, benchmarks, demo, CLI, or API behavior, but it is repository-governance content and may still be useful for a public project. Its enforcement contact belongs to the upstream project, so the safe decision is to exclude it from deletion until the repository owner chooses whether to replace it with a project-owned policy or remove it.

## Protected scope

No confirmed candidate is inside `.git`, current RAG corpus or development documents, Agent runtime/workspace, current Document Workflow code/tests, either planning/report directory, or a recovery-point namespace. The original 79 `LIKELY_REMOVABLE` and 338 `REVIEW_REQUIRED` entries were read only for count validation and were not reclassified or added to this plan.

## Later deletion-pass contract

A future deletion pass should proceed only after explicit approval and must:

1. Require the source manifest SHA-256 above and this recheck manifest to match the files on disk.
2. Create a local Git recovery commit plus a backup tag or branch before deletion.
3. Delete only entries classified `CONFIRMED_SAFE_TO_REMOVE`; currently that is 606 files.
4. Exclude the one `REVIEW_REQUIRED_AFTER_RECHECK` file and every original `LIKELY_REMOVABLE` / `REVIEW_REQUIRED` entry.
5. Re-run the dependency/reference guard immediately before removal; any changed or newly referenced file is retained automatically.
6. Handle Agent retry/timeout dead code as a separate, explicit change set described in `agent_reliability_dead_code_plan.md`.
7. Stop after cleanup and verification; do not add features.

## Required post-cleanup verification

- Import and compile checks for RAG, Agent, and UI.
- Complete RAG regression, including lifecycle, ingestion, DENSE_ONLY + SECTION_PATH retrieval, trusted QA, citations, version diff, artifact validation, and FastAPI contracts.
- Agent core regression after removing the exclusive retry/timeout tests.
- Agent to RAG HTTP integration and Safe Business E2E.
- Streamlit UI tests and browser smoke.
- Benchmark contract/smoke checks without changing accepted baselines.
- Secret scan and `git diff --check`.
- Final report with actual deleted count, any retained exceptions, final directory structure, and all results.

## Current repository state

No candidate was deleted in this planning pass. Existing untracked runtime documents and the prior residual-audit outputs remain untouched. The only new artifacts are this plan, its 607-entry recheck manifest, and the Agent dead-code plan.
