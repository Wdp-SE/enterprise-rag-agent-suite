# Retrieval and Review Quality Iteration V2 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Expand version-aligned official evidence, measure retrieval improvements on a new locked evaluation suite, and make change-review advice structured and reviewable without changing the human approval boundary.

**Architecture:** Keep the public FastAPI/Streamlit interfaces and current BM25 behavior as the baseline. Add provenance-tracked official source coverage, heading-aware chunk metadata and a field-weighted BM25 candidate; add a separate V2 evaluation suite; promote a new retrieval policy only if the new locked evaluation gate passes. Use a separate structured model contract for review advice while keeping ordinary RAG answer generation unchanged.

**Tech Stack:** Python, FastAPI, Streamlit, NumPy, JSON/JSONL, pytest, Git.

**Spec:** `docs/superpowers/specs/2026-09-27-retrieval-review-quality-v2-design.md`

## Global Constraints

- Treat current V1.0 public sources, query set, ground truth, selection lock, and final-selection results as the historical baseline; do not overwrite those evaluation result files.
- Pin every added source to its official Apache DolphinScheduler commit or release, and retain canonical URL, path, language, license/attribution, retrieval timestamp, and SHA-256.
- Add only relevant official documentation and directly related official change records; do not represent hypothetical text as upstream material or ingest the full source repository.
- Never let model output create a confirmed document relation; confirmed relations must come from registered, explicit source links.
- Validate all model evidence IDs against the exact evidence supplied to that request; preserve abstention/fallback behavior and human review.
- Do not write to Apache upstream or public baseline; do not add API keys, secrets, private absolute paths, or local runtime artifacts.
- Leave the unrelated untracked `RAG-Challenge-2-main/` directory untouched and unstaged.
- Work on `codex/retrieval-review-quality-20260927`; `main` remains canonical and changes only after the approved validation gates. Never force-push.

## Review Focus

- A source absent at the pinned 3.4.2 commit must be recorded as unavailable, never copied from 3.4.3 or synthesized; test manifest/source commit consistency.
- Cross-document success requires every expected independent source in Top-5; test joint source recall rather than “any relevant hit”.
- A no-answer or version-conflicting request must not become a confident model answer; test abstention and explicit ambiguity output.
- Prompt-injection text and model citations outside the supplied evidence must not alter the review or be accepted; test evidence-ID membership and fail-closed behavior.
- Model-disabled, malformed-response, and provider-unavailable cases must retain usable retrieval evidence and a pending human decision; test each fallback.

---

### Task 1: Expand pinned official source coverage and rebuild artifacts

**Files:**
- Create: `versioned-rag-service/scripts/sync_pinned_sources.py`
- Create: `versioned-rag-service/public_corpus/source_coverage.json`
- Create: available 3.4.2 source pages under `versioned-rag-service/public_corpus/sources/3.4.2/{en,zh}/`
- Modify: `versioned-rag-service/public_corpus/corpus_manifest.json`
- Modify: `versioned-rag-service/public_corpus/chunks.json`
- Modify: `versioned-rag-service/public_corpus/dense_vectors.npy`
- Modify: `versioned-rag-service/public_corpus/retrieval_policy.json`
- Test: `versioned-rag-service/tests/test_public_knowledge.py`
- Test: `versioned-rag-service/tests/test_sync_pinned_sources.py`

**Interfaces:**
- Consumes: the existing manifest's pinned commits `71eb6412f940afa1f171f1097dc0e99ed61d16e2` (3.4.2) and `a190201acffa03d199d4ca216288734a6513de3d` (3.4.3).
- Produces: `sync_sources(root: Path, fetcher) -> SyncResult`, `raw_source_url(commit: str, path: str) -> str`, and a coverage record distinguishing fetched pages from paths absent at the pinned source commit; a manifest and artifacts accepted by `PublicKnowledgeIndex`.

- [ ] **Step 1: Write failing source-provenance tests.** Test that every manifest path exists, its bytes match the manifest SHA-256, its URL commit matches the version's pinned commit, and coverage records every requested counterpart as present or absent.

```python
def test_raw_source_url_uses_the_pinned_commit():
    assert raw_source_url(
        "71eb6412f940afa1f171f1097dc0e99ed61d16e2",
        "docs/docs/zh/guide/parameter/priority.md",
    ) == (
        "https://raw.githubusercontent.com/apache/dolphinscheduler/"
        "71eb6412f940afa1f171f1097dc0e99ed61d16e2/"
        "docs/docs/zh/guide/parameter/priority.md"
    )
```

- [ ] **Step 2: Run the new test and confirm it fails** because the synchronizer and coverage record do not exist.

Run: `pytest versioned-rag-service/tests/test_sync_pinned_sources.py -q`

- [ ] **Step 3: Implement the pinned-source synchronizer.** Use the current 3.4.3 documentation paths as the allowlist, fetch matching bilingual 3.4.2 files only from the 3.4.2 pinned commit, and record absent paths instead of substituting newer text. Preserve license and NOTICE attribution.

- [ ] **Step 4: Rebuild and validate the corpus.** Run the synchronizer, regenerate chunks/vectors from the manifest, and update manifest/index SHA-256 fields through one reproducible command. Do not change the version range or retrieval default in this task.

Run: `python versioned-rag-service/scripts/sync_pinned_sources.py --rebuild`

- [ ] **Step 5: Run source and public-index tests.** Confirm the new tests and public-corpus integrity tests pass.

Run: `pytest versioned-rag-service/tests/test_sync_pinned_sources.py versioned-rag-service/tests/test_public_knowledge.py -q`

### Task 2: Preserve heading context and add an experimental field-weighted BM25 candidate

**Files:**
- Modify: `versioned-rag-service/src/public_knowledge.py`
- Modify: `versioned-rag-service/tests/test_public_knowledge.py`
- Modify: `versioned-rag-service/public_corpus/chunks.json`
- Modify: `versioned-rag-service/public_corpus/retrieval_policy.json`

**Interfaces:**
- Consumes: pinned Markdown source files and existing `PublicKnowledgeIndex.search(query, ..., policy=...)` interface.
- Produces: `document_title` and inherited `heading_path` chunk metadata; experimental `bm25_fields` search policy; unchanged default policy unless Task 3 accepts promotion.

- [ ] **Step 1: Write a failing heading-path test.** Use nested Markdown headings and assert a child chunk retains its full ancestor path and leaf heading.

```python
def test_parts_keep_inherited_heading_path():
    parts = _parts("# API\n## Workflow\n### Recovery\nDefault: retry")
    assert parts[0] == ("Recovery", ["API", "Workflow", "Recovery"], "Default: retry")
```

- [ ] **Step 2: Run the test and confirm it fails** because chunks currently store only a leaf heading.

Run: `pytest versioned-rag-service/tests/test_public_knowledge.py::test_parts_keep_inherited_heading_path -q`

- [ ] **Step 3: Implement heading-path metadata and fielded scoring.** Keep the current BM25 implementation intact as the comparison baseline. Add a candidate score with separate title, heading-path, and body term frequencies; make weights explicit in code and include those fields in new chunks.

- [ ] **Step 4: Write and run ranking tests.** Assert that an exact title/section match can improve a candidate's rank while ordinary `policy="bm25"` results remain unchanged for the pre-existing fixture.

Run: `pytest versioned-rag-service/tests/test_public_knowledge.py -q`

- [ ] **Step 5: Rebuild chunks and index hashes** with the Task 1 command, then run the public index validation tests again.

### Task 3: Add a separate V2 retrieval evaluation suite

**Files:**
- Create: `evaluation/real_world_retrieval/quality_v2/queries.jsonl`
- Create: `evaluation/real_world_retrieval/quality_v2/ground_truth.jsonl`
- Create: `evaluation/real_world_retrieval/quality_v2/frozen_split.json`
- Create: `evaluation/real_world_retrieval/quality_v2/selection_lock.json`
- Create: `evaluation/real_world_retrieval/quality_v2/run_quality_v2.py`
- Create: `evaluation/real_world_retrieval/quality_v2/test_quality_v2.py`
- Create: `evaluation/real_world_retrieval/quality_v2/results/`

**Interfaces:**
- Consumes: the V2 corpus manifest, `PublicKnowledgeIndex`, and query/ground-truth fields compatible with the existing retrieval benchmark.
- Produces: `complete_source_recall(ranked_source_ids: list[int], required_source_ids: set[int]) -> bool`, 40 newly authored cases, deterministic 20/20 DEV/HOLDOUT assignment, hash-locked inputs, per-policy metrics and ranked evidence IDs written only under `quality_v2/results/`.

- [ ] **Step 1: Write failing split and metric tests.** Assert deterministic query IDs per category, 20 DEV plus 20 HOLDOUT, split disjointness, locked input hashes, and complete-source scoring for two-source queries.

```python
def test_cross_document_metric_requires_both_sources():
    assert complete_source_recall([0], {0, 1}) is False
    assert complete_source_recall([0, 1], {0, 1}) is True
```

- [ ] **Step 2: Run the tests and confirm they fail** because the V2 split and runner do not exist.

Run: `pytest evaluation/real_world_retrieval/quality_v2/test_quality_v2.py -q`

- [ ] **Step 3: Author 40 new questions from the pinned sources and documented 3.4.2→3.4.3 changes.** Include eight cross-document cases, eight version-scope cases, six Chinese cases, six English cases, four mixed-language cases, four hard/ambiguous cases, and four no-answer cases. Record exact expected evidence markers and source identity; label hypothetical scenarios explicitly.

- [ ] **Step 4: Implement the deterministic split and runner.** Use category-stratified SHA-256 assignment, lock the hashes of the query set, ground truth, and corpus manifest, and report Recall@5, MRR, nDCG@5, complete multi-source Top-5 recall, no-answer Top-1 score distribution as a retrieval-only diagnostic, errors, and local warm P95. Do not label nearest-neighbor candidate presence as a false answer.

- [ ] **Step 5: Run DEV candidate comparisons only.** Compare `bm25` and `bm25_fields`; write outputs under `quality_v2/results/`. Do not run the V1 final-selection runner or overwrite any V1 result.

Run: `python evaluation/real_world_retrieval/quality_v2/run_quality_v2.py --split dev --policies bm25,bm25_fields`

- [ ] **Step 6: Apply the promotion gate and then run HOLDOUT once.** Promote `bm25_fields` only if DEV improves complete multi-source Top-5 recall by at least one of the eight cases, overall MRR drops by no more than 0.01, and P95 is no more than twice BM25. After fixing the candidate, run the locked HOLDOUT once; promotion also requires HOLDOUT complete multi-source recall and Recall@5 to be no lower than BM25, MRR to drop by no more than 0.01, and P95 to be no more than twice BM25. Otherwise leave BM25 default and document the result.

Run: `python evaluation/real_world_retrieval/quality_v2/run_quality_v2.py --split holdout --policies bm25,bm25_fields`

### Task 4: Structure model-assisted review advice and validate its evidence

**Files:**
- Modify: `versioned-rag-service/src/answer_generation.py`
- Modify: `versioned-rag-service/src/public_api.py`
- Modify: `versioned-rag-service/tests/test_public_server.py`
- Modify: `versioned-rag-service/tests/test_formal_runtime_contract.py`
- Modify: `change-review-agent/app/public_review.py`
- Modify: `change-review-agent/tests/test_public_review.py`

**Interfaces:**
- Consumes: only current-version evidence chunks already selected by the Agent; generic RAG answers continue using their current answer/citation contract.
- Produces: structured review fields for change assumption, suggested impacts, evidence gaps, and reviewer actions, plus validated cited sources and a pending-human-review status. Confirmed relations remain deterministic and outside model output.

- [ ] **Step 1: Write failing review-response tests.** Cover a valid structured response, an unknown evidence ID, a missing field, malformed JSON, and an unavailable provider; assert the generic answer decoder and prompt contract remain unchanged.

```python
def test_review_advice_rejects_evidence_id_outside_supplied_chunks():
    payload = {
        "change_assumption": "假设变更",
        "suggested_impacts": [{"statement": "需要核对", "reason": "相关证据", "evidence_ids": ["not-supplied"]}],
        "evidence_gaps": [], "reviewer_actions": ["人工核对"],
        "review_status": "PENDING_HUMAN_REVIEW",
        "relevant_sources": [{"document_id": "not-supplied", "page_number": 1}],
    }
    with pytest.raises(ValueError, match="evidence"):
        decode_review_advice(payload, allowed_ids={"chunk-1"})
```

- [ ] **Step 2: Run the focused tests and confirm they fail** because no separate review schema exists.

Run: `pytest versioned-rag-service/tests/test_formal_runtime_contract.py versioned-rag-service/tests/test_public_server.py change-review-agent/tests/test_public_review.py -q`

- [ ] **Step 3: Implement a separate review prompt and decoder.** Keep `StructuredAnswerGenerator.generate()` behavior intact. Validate exact response keys, field types, status, source citation membership, and every suggested-impact evidence ID against supplied chunks. Never accept model-created confirmed relations.

- [ ] **Step 4: Integrate the structured response in `/public/review-advice` and `PublicReviewAgent`.** On missing credentials or provider errors, retain retrieved candidates and return a non-success review-advice status; do not turn fallback evidence into model-confirmed impact.

- [ ] **Step 5: Run the focused service and Agent tests.**

Run: `pytest versioned-rag-service/tests/test_formal_runtime_contract.py versioned-rag-service/tests/test_public_server.py change-review-agent/tests/test_public_review.py -q`

### Task 5: Present structured review findings and update project documentation

**Files:**
- Modify: `demo-ui/public_workbench.py`
- Modify: `demo-ui/tests/test_custom_change_review.py`
- Modify: `demo-ui/tests/test_business_workflow_ui.py`
- Modify: `README.md`
- Modify: `demo-ui/README.md`
- Create: `evaluation/real_world_retrieval/quality_v2/report.md`

**Interfaces:**
- Consumes: the validated structured review response from Task 4 and V2 metrics from Task 3.
- Produces: separate UI sections for assumptions, suggested candidates, evidence gaps, reviewer actions, and human decision; documentation that distinguishes V1 historical selection from current measured behavior.

- [ ] **Step 1: Write failing UI tests** asserting those sections render independently and no generated impact is labeled confirmed.

- [ ] **Step 2: Run the focused UI tests and confirm they fail.**

Run: `pytest demo-ui/tests/test_custom_change_review.py demo-ui/tests/test_business_workflow_ui.py -q`

- [ ] **Step 3: Render structured fields and preserve existing safe fallbacks.** Keep the public-baseline disclaimer and current session-only review decision behavior.

- [ ] **Step 4: Update READMEs and add the V2 report.** State the new corpus count and actual selected policy only after Task 3's gate; retain the V1 selection results as historical evidence and report the V2 split, metrics, and limitations separately.

- [ ] **Step 5: Run focused UI tests and documentation whitespace checks.**

Run: `pytest demo-ui/tests/test_custom_change_review.py demo-ui/tests/test_business_workflow_ui.py -q`

### Task 6: Validate and promote the finished change to `main`

**Files:**
- Validate only the explicit files listed in Tasks 1–5; do not stage unrelated workspace content.

- [ ] **Step 1: Run targeted corpus, retrieval, API, Agent, and UI tests.** Do not run unrelated full-repository tests or a live paid model call.

Run: `pytest versioned-rag-service/tests/test_sync_pinned_sources.py versioned-rag-service/tests/test_public_knowledge.py versioned-rag-service/tests/test_formal_runtime_contract.py versioned-rag-service/tests/test_public_server.py change-review-agent/tests/test_public_review.py demo-ui/tests/test_custom_change_review.py demo-ui/tests/test_business_workflow_ui.py evaluation/real_world_retrieval/quality_v2/test_quality_v2.py -q`

- [ ] **Step 2: Run corpus/hash validation, the finalized V2 evaluation gates, and `git diff --check`.** Confirm the documentation reports the actual expanded source/chunk counts, labels V1 selection results as historical, and does not present old V1 metrics as the new corpus result.

- [ ] **Step 3: Inspect changed paths, staged paths, diff, secret scan, and tracked status.** Stage explicit files; verify `RAG-Challenge-2-main/` remains untracked and untouched.

- [ ] **Step 4: Create one implementation commit** on `codex/retrieval-review-quality-20260927` after all checks pass.

- [ ] **Step 5: Fetch `origin` and verify `origin/main` has not diverged.** If it has moved, stop and reconcile without overwriting remote work.

```powershell
git fetch origin
git merge-base --is-ancestor origin/main codex/retrieval-review-quality-20260927
```

- [ ] **Step 6: Fast-forward local `main` to the validated branch, push normally, and verify remote HEAD.** Never force-push. If push is blocked by credentials or transport, leave the remote untouched and report the exact failure.

```powershell
git switch main
git merge --ff-only codex/retrieval-review-quality-20260927
git push origin main
git ls-remote origin refs/heads/main
```

---

## Self-review

- Every scope item in the approved design maps to Tasks 1–6.
- The new corpus, evaluation suite, review response contract, and UI presentation have separate test cycles.
- Existing V1 selection artifacts are never overwritten; the new runner writes only beneath `quality_v2/`.
- Confirmed relations are deterministic, while model output can only suggest checks tied to supplied evidence.
- No task writes to the public baseline or upstream. The final Git operation is a normal fast-forward and normal push, never a force-push.
