# Retrieval and Review Quality Iteration V2

## Goal

Improve retrieval evidence coverage and make hypothetical change reviews easier to verify, while preserving the public V1.0 behavior, its frozen evaluation record, and the rule that a person makes the final review decision.

## Current baseline

- The public corpus contains 52 provenance-tracked Apache DolphinScheduler sources for versions 3.4.2 and 3.4.3. Each included source is stored with its source URL, repository commit, path, language, license, and SHA-256. The snapshot is a limited topic selection, not the complete upstream documentation set.
- The current retrieval policy is BM25 with the selected Chunk A configuration and Top-5. The frozen retrieval suite has 46 queries, a locked DEV/HOLDOUT split, and a 0/4 complete dual-source Top-5 result.
- The public Agent already accepts a natural-language change description, retrieves current-version evidence, optionally requests citation-constrained model advice, and records an in-session human review decision. It does not write to the public baseline or upstream repository.
- Current limitations include narrow topic coverage, weak multi-source evidence recall, and a free-form review answer that does not consistently expose assumptions, evidence gaps, and reviewer actions as separate fields.

## Design decisions

### Preserve the V1.0 record

Treat the existing 52-source corpus, benchmark queries, ground truth, selection lock, and final-selection results as the V1.0 baseline. Do not rewrite their history or reuse their HOLDOUT queries to tune new behavior.

Create a separately versioned quality-iteration dataset and split. It will contain queries derived from official source material and real, documented version changes, plus clearly labeled hypothetical cases. Each query will identify its version scope, expected evidence source IDs, answerability, and whether complete support requires multiple independent sources. The new HOLDOUT remains locked and is used only after DEV tuning is complete.

### Expand relevant official source coverage

Add complete, version-aligned official documents in the domains already demonstrated by the workbench, such as parameter behavior, workflow/task behavior, API behavior, configuration, and upgrade changes. Include official release notes and directly related official proposals, issues, or pull requests only when they provide evidence needed by a review scenario.

Every added source must have a pinned upstream commit or release, canonical URL, repository path, language, license/attribution, retrieval timestamp, and SHA-256. Do not add synthetic text as if it were upstream material, and do not index the entire source repository indiscriminately. Hypothetical changes belong in evaluation inputs and must be labeled as hypothetical.

### Measure retrieval changes before promotion

Keep the current BM25 ranking as the comparison baseline. Add an offline comparison for narrowly scoped improvements that use existing source metadata, such as document title and inherited heading path. Any chunking or ranking change must be evaluated against the new DEV set and compared with the baseline on the locked new HOLDOUT only after candidate selection.

Report at least Recall@5, MRR, complete multi-source evidence recall, no-answer false-positive behavior, citation-source validity, and local warm P95 latency. Keep retrieval results separate from answer-generation quality. Promote a new default only if the measured evidence-recall gain is repeatable and the HOLDOUT and latency results do not reveal a material regression. Otherwise retain BM25 and document the failure analysis.

### Structure the review advice contract

Keep the natural-language request flow and current human-review boundary. Ask the model for a compact, structured review result with these distinct fields:

- change assumption and scope;
- explicitly confirmed document relations, only when supported by an explicit registered source relation;
- suggested paragraphs or documents to check, clearly marked as candidates;
- evidence IDs and the reason each source is relevant;
- evidence gaps, conflicting sources, or version ambiguity;
- proposed reviewer actions;
- an explicit pending-human-review status.

The server must validate every returned evidence ID against the evidence supplied for that request. A model citation outside that set, an unsupported confirmed relation, malformed output, unavailable model, or insufficient evidence must not be presented as a valid recommendation. The system must abstain or fall back to visible retrieval evidence. No generated recommendation may modify official material, create an upstream change, or approve itself.

### Preserve the public workflow boundary

Review drafts and decisions remain session-only for this iteration. The UI may present the structured fields and evidence gaps, but this design does not add persistent accounts, an approval database, external ticketing, automatic patch application, or a new public baseline.

## Data flow

1. The user submits a natural-language hypothetical change and the current fixed-version scope.
2. The Agent retrieves current-version candidates through the public RAG API.
3. If generation is configured, the review endpoint receives only those candidate evidence chunks and requests a structured review result.
4. The server validates returned evidence references and response structure.
5. The workbench displays candidates, confirmed relations, suggested impacts, evidence gaps, and reviewer actions separately.
6. A human records the session-level reviewed or returned decision. No public source is changed.

## GitHub and release discipline

- `main` is the sole canonical branch for the latest public version.
- Implement this iteration on `codex/retrieval-review-quality` (or a dated equivalent) created from the latest verified `origin/main`; do not develop directly on `main`.
- Keep the V1.0 baseline and the V2 evaluation additions in one reviewable change series. Stage explicit files only; never use `git add .`.
- Before proposing a merge, verify a clean tracked working tree, inspect the staged file list and full diff, run `git diff --cached --check`, targeted tests, corpus/hash checks, and the new DEV/HOLDOUT evaluation gate. No secret or machine-private path may enter Git.
- Push and merge are separate release actions. Do not push or merge until the owner approves the finished diff. After an approved merge, verify that GitHub `main` points to the intended commit. Configure the public Render and Streamlit deployments to follow `main`, then verify their deployed commit identifiers so a feature branch cannot be mistaken for the public latest version.

## Validation

- Added official sources match their pinned SHA-256 and manifest metadata; generated chunks preserve source/version/heading provenance.
- Existing V1.0 corpus and frozen evaluation artifacts remain identifiable and are not silently reused as V2 ground truth.
- The new evaluation split is deterministic, hash-locked, and keeps DEV and HOLDOUT separate.
- Retrieval comparisons report per-category and overall evidence metrics, including multi-source queries and no-answer cases.
- Review API tests cover valid evidence citations, citations outside the provided evidence, insufficient evidence, conflicting/version-ambiguous evidence, malformed model output, and provider-unavailable fallback.
- Agent/UI tests verify the distinction between confirmed document relations and suggested paragraph impacts, show evidence gaps, preserve human review, and never modify the public baseline.
- Run targeted service, Agent, and UI tests plus `git diff --check`; do not run unrelated retrieval experiments or alter the V1.0 final-selection results.

## Out of scope

- Replacing BM25 before new evaluation supports the change.
- Changing the 3.4.2/3.4.3 public version range without a separate decision.
- Automatic document/code writes, upstream PR creation, deployment, persistent approval storage, or changes to Agent authority.
- Broad UI redesign or unrelated cleanup.
