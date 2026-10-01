# RAG Retrieval and Figure Evidence Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Improve current Autoware RAG only where a frozen bilingual benchmark proves measurable gains, while making image-derived evidence auditable and safely retrievable.

**Architecture:** Use the quality baseline and relation registry from `rag-lineage-evaluation-plan.md` as the gate. Compare the already implemented BM25, faceted RRF, OCR-assisted and hybrid candidates offline; retain the simplest policy that passes all gates. Add OCR evidence only from pinned image bytes, with human-reviewed text and independent hashes. This plan starts after the baseline task in that plan is complete.

**Tech Stack:** Python 3.12, BM25/FAISS retrieval, FastAPI, pytest, JSON/JSONL benchmark artifacts.

**Spec:** `docs/superpowers/specs/2026-10-01-ai-app-engineering-readiness-design.md`

## Global Constraints

- Use `evaluation/autoware_quality_v1` and its corpus/runtime fingerprint as the only promotion basis for the current expanded Autoware snapshot.
- BM25 remains the baseline; change one retrieval factor at a time and compare development plus holdout splits.
- Any adopted policy must not reduce required-source recall, full required-source coverage, citation membership, or no-answer behavior; wrong-version results must remain zero on explicit-version cases.
- The current corpus's default `latest` is Documentation `main` plus Universe `0.52.0`, not one release.
- Only manually approved OCR text bound to pinned source image SHA may become evidence; OCR output alone is not verified evidence.
- A diagram's arrows, colors, spatial relations or implied safety semantics are not inferred from OCR text.
- Warm retrieval API target P95 ≤2 s is a provisional acceptance budget; report local and hosted values separately.
- Human review remains required; no upstream or public corpus writes occur during a review.

## Review Focus

- A Chinese query retrieving an English source is useful when language mode permits it, but strict-language mode must not leak the other language; Task 1 tests both modes.
- Composite `latest` must not mix unselected component versions; Task 1 tests per-component scope membership.
- A query about an unreviewed picture must not cite guessed OCR; Task 2 tests rejected/unreviewed sidecar rows.
- Adding OCR evidence must not evict a unique required text source from Top-K; Task 2 tests source coverage under a full evidence budget.
- A candidate strategy that wins development but regresses holdout or latency must not be selected; Task 3 tests the selection gate.

---

### Task 1: Cross-language and version-scope failure analysis

**Files:**
- Create: `evaluation/autoware_quality_v1/analyze_failures.py`
- Modify: `evaluation/autoware_quality_v1/README.md`
- Test: `evaluation/autoware_quality_v1/test_quality_v1.py`
- Read-only inputs: `versioned-rag-service/src/public_knowledge.py`, `src/public_retrieval_runtime.py`, corpus relation registry and frozen cases.

**Interfaces:**
- `analyze_failures(report: dict, cases: list[dict]) -> dict` groups misses by `category`, language, selected component version, relation state and expected modality, and lists case IDs plus missed source IDs.
- The report must not convert retrieval score to probability or claim answer accuracy.

- [ ] **Step 1: Add tests for a Chinese query with English-only expected evidence, an explicit-version mismatch and an unverified-translation case.**
- [ ] **Step 2: Run `python -m pytest evaluation/autoware_quality_v1/test_quality_v1.py -q`; confirm the failure analyzer is missing.**
- [ ] **Step 3: Implement deterministic failure grouping over frozen case/report rows and include top-5 hit IDs for diagnosis.**
- [ ] **Step 4: Run the tests and produce the BM25 failure report; classify failures before touching retrieval behavior.**
- [ ] **Step 5: Commit as `test: classify Autoware retrieval failures`.**

### Task 2: Image evidence expansion with review provenance

**Files:**
- Modify: `versioned-rag-service/public_corpus_autoware/figure_evidence_reviewed.json`
- Modify: `versioned-rag-service/public_corpus_autoware/figure_evidence_reviewed.lock.json`
- Modify: `versioned-rag-service/public_corpus_autoware/figure_evidence.json` only when inventory corrections are proven
- Modify: `versioned-rag-service/src/public_retrieval_runtime.py: _validated_images, _search_images, _add_image_evidence`
- Test: `versioned-rag-service/tests/test_figure_evidence.py`
- Test: `versioned-rag-service/tests/test_public_retrieval_runtime.py`

**Interfaces:**
- Sidecar evidence continues to carry `figure_id`, `chunk_id`, `version`, `language`, `document_key`, `heading`, `source_url`, `raw_url`, original image `sha256`, reviewed text, review state and timestamp.
- Only `review_status == "approved"` with matching source commit, image SHA and manifest reference is searchable.
- Keep figure selection query-triggered; do not add image processing to ordinary text-only requests.

- [ ] **Step 1: Add one test per failure mode: wrong SHA is excluded, OCR-unreviewed text is excluded, approved relevant image text is returned, and Top-5 preserves distinct required-source documents.**
- [ ] **Step 2: Run the named service tests and confirm the new assertions fail before any implementation/data change.**
- [ ] **Step 3: Select candidate images by image-question cases and local/source availability; compare OCR text against exact pinned images and record human-review notes. Add only verified records and regenerate their lock hashes. If image bytes cannot be accessed or reviewed, record the remaining coverage gap and do not insert speculative OCR.**
- [ ] **Step 4: Implement only the minimal selection/merge fixes required by failing tests; keep the existing strict provenance checks and evidence-source diversity.**
- [ ] **Step 5: Run figure/runtime tests and the complete service suite; run the image subset of the frozen benchmark and record source coverage, wrong-version count and latency.**
- [ ] **Step 6: Commit as `feat: expand reviewed Autoware figure evidence` (or `test: document reviewed figure coverage` if no additional candidate passes review).**

### Task 3: Retrieval candidate promotion gate

**Files:**
- Modify: `evaluation/autoware_quality_v1/run_benchmark.py`
- Modify: `evaluation/autoware_quality_v1/test_quality_v1.py`
- Modify: `versioned-rag-service/public_corpus_autoware/public_retrieval_runtime.json`
- Modify: `versioned-rag-service/config/public_retrieval_runtime.json`
- Modify: `versioned-rag-service/public_corpus_autoware/retrieval_policy.json` only for a passing promotion
- Modify: `versioned-rag-service/src/public_api.py: workspace evaluation status`
- Test: `versioned-rag-service/tests/test_public_retrieval_runtime.py`
- Test: `versioned-rag-service/tests/test_public_server.py`

**Interfaces:**
- Candidate report includes `selected_policy`, a specific pass/fail reason per gate, BM25 baseline, development/holdout metrics, retrieval operation count, P95 and evaluation fingerprint.
- Promotion order is: source-recall/complete-source noninferiority, zero explicit-version errors, no-answer noninferiority, holdout objective gain, and retrieval P95 no more than 20% above BM25; ties select the lower-call/simpler policy. The separate hosted retrieval API target remains warm P95 ≤2 s.

- [ ] **Step 1: Add a test where one candidate wins development but fails holdout, plus a test that zero wrong-version and no-answer noninferiority are mandatory.**
- [ ] **Step 2: Run `python -m pytest evaluation/autoware_quality_v1/test_quality_v1.py -q`; confirm the existing selector either lacks or violates the new gate.**
- [ ] **Step 3: Compare `bm25`, `bm25_faceted_rrf`, `bm25_figure_ocr`, `bm25_faceted_figure_ocr`, and `hybrid` on the frozen set without tuning the holdout.**
- [ ] **Step 4: Implement deterministic policy selection and expose the fingerprinted result. Change the public default only if the frozen gates pass; otherwise retain BM25 and publish the measured reason.**
- [ ] **Step 5: Run benchmark twice, named runtime/server tests and all service tests; verify selected policy and fingerprint agree with the API.**
- [ ] **Step 6: Commit as `feat: gate retrieval policy on holdout quality`.**

