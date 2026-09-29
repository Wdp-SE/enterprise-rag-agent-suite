+# RAG Multi-Source Image Evidence Implementation Plan

> For agentic workers: REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox syntax for tracking.

**Goal:** Improve cross-document evidence retrieval for the public DolphinScheduler RAG and add a small, human-verified image OCR evidence set, promoting a candidate only if an independent V4 evaluation supports it.

**Tech Stack:** Python 3.11, existing NumPy/custom BM25, FastAPI, Streamlit AppTest, pytest, existing pinned-image audit script and Tesseract for offline OCR only.

**Spec:** [RAG multi-source and image evidence design](../specs/2026-09-29-rag-multisource-image-evidence-design.md)

## Global Constraints

- Preserve the V3 test cases, annotations, selection/holdout locks, results, reports, runtime policy, corpus chunks/vector artifacts, and their hashes. Do not rerun its consumed HOLDOUT.
- Do not edit versioned-rag-service/src/public_knowledge.py: the V3 release binds its hash. Implement new behavior in a separate runtime adapter and prove that the original hash and V3 validation remain intact.
- Keep public_corpus/retrieval_policy.json defaulting to BM25. Put new runtime selection config and image OCR sidecar in separate files.
- Never download images, run OCR, or call a vision/paid model during a user request. Only approved OCR from fixed-commit images may be indexed.
- Apply version/language scope before any candidate ranking or fusion. The public request schema must not let a caller choose an experimental retrieval policy.
- Image OCR must be visibly labeled as derived evidence and retain immutable source, version, chapter, commit, image hash, and raw image URL.
- Keep human review as the final decision boundary. OCR text or an image description is never presented as author-written Markdown.
- Preserve the existing untracked RAG-Challenge-2-main/ directory.
- Merge normally, without force, then verify the Render API and Streamlit public site.

## Review Focus

- A requested version never returns text or image evidence from another version. Cover in runtime tests.
- Pending, rejected, empty, invalid, or hash-mismatched OCR is never searchable. Cover in sidecar and runtime tests.
- Repeated facets deduplicate a source chunk without losing contributing facet IDs. Cover in fusion tests.
- Single-fact queries use one BM25 call and preserve current ordering. Cover in fusion/runtime tests.
- No-answer metrics measure retrieved candidates, not generated-answer hallucinations. Cover in V4 metric tests.
- A policy supplied by an HTTP client is rejected; runtime policy comes only from server configuration. Cover in API tests.

---

### Task 1: Build the reviewed image evidence sidecar

**Files:**
- Modify versioned-rag-service/scripts/figure_evidence.py
- Create versioned-rag-service/public_corpus/figure_evidence_reviewed.json
- Modify versioned-rag-service/tests/test_figure_evidence.py

**Interface:** build_reviewed_figure_chunks(rows, manifest) -> list[dict]. A returned row has schema_version, chunk_id, figure_id, version, language, document_key, heading, commit, sha256, source_url, raw_url, content, modality="image_ocr", review_status="approved", and review metadata.

- [ ] **Step 1: Write failing tests for approval and provenance validation.**

Add tests for each of these cases:

Define _figure_row(**overrides) to return a schema_version=1 inventory row with figure_id="fig-task", asset_path="docs/img/task.png", one 3.4.3 zh reference to guide/task.md and heading "任务配置", a verified validation object, text_extracted OCR object, approved review fields, and the pinned raw URL. Define _manifest() with that exact source key, version, language, commit, and document path so the builder must validate against real manifest metadata.

    def test_reviewed_builder_accepts_only_pinned_approved_ocr():
        approved = _figure_row(
            validation={"status": "verified", "sha256": "a" * 64},
            ocr={"status": "text_extracted", "text": "MAX_RETRY=3"},
            review_status="approved",
            reviewed_sha256="a" * 64,
        )
        pending = _figure_row(review_status="pending")
        bad_hash = _figure_row(review_status="approved", reviewed_sha256="b" * 64)
        chunks = build_reviewed_figure_chunks([approved, pending, bad_hash], _manifest())
        assert len(chunks) == 1
        assert chunks[0]["modality"] == "image_ocr"
        assert chunks[0]["raw_url"].endswith("/docs/img/task.png")

Also assert that rejected/unverified rows, empty OCR, unsupported schema versions, invalid raw URLs, and commit/version mismatches produce no searchable row or a fail-closed validation error. Never treat Markdown alt text as OCR.

- [ ] **Step 2: Run the focused tests and confirm they fail.**

From the repository root run:

    python -m pytest -p no:cacheprovider versioned-rag-service/tests/test_figure_evidence.py -q

Expected: the approval builder tests fail because the approved sidecar interface is not implemented.

- [ ] **Step 3: Expand the fixed image sample and implement the builder.**

The audit currently selects six images and enforces a maximum of 20. Add a deterministic, stratified list of up to 20 existing manifest images covering UI screenshots, parameter/status tables, and diagrams with readable labels. Keep fixed-commit URL construction, MIME/signature agreement, full decode, byte/pixel caps, SHA-256, and explicit failure states. Do not exceed the script’s current --max-images limit.

Builder validation must check that the image is verified, OCR is non-empty, review_status and OCR index review status are approved, the reviewed hash equals the verified image hash, and version/language/document reference/commit/raw URL match the fixed corpus inventory. Construct a stable image chunk ID from version, document, figure ID, and reference identity. Store only metadata and OCR text in Git; do not store downloaded binaries.

- [ ] **Step 4: Create and manually check the pilot sidecar.**

Run the audit against the fixed sample with no more than 20 images. Inspect each retrieved image and correct OCR against the pixels before marking it approved. Do not approve diagrams when OCR cannot represent the relevant relationship. If fewer than 20 valid images remain, keep the real count and label image evaluation as a limited pilot.

- [ ] **Step 5: Run the sidecar regression tests.**

Run:

    python -m pytest -p no:cacheprovider versioned-rag-service/tests/test_figure_evidence.py -q

Expected: approved rows retain all provenance, and every invalid or unreviewed row is excluded.

### Task 2: Add a separate frozen V4 evaluation

**Files:**
- Create evaluation/real_world_retrieval/quality_v4/cases.jsonl
- Create evaluation/real_world_retrieval/quality_v4/frozen_split.json
- Create evaluation/real_world_retrieval/quality_v4/selection_lock.json
- Create evaluation/real_world_retrieval/quality_v4/run_quality_v4.py
- Create evaluation/real_world_retrieval/quality_v4/test_quality_v4.py
- Create evaluation/real_world_retrieval/quality_v4/README.md
- Create evaluation/real_world_retrieval/quality_v4/report.md

**Interfaces:**
- split_cases(cases, seed) -> {"dev": [query_id], "holdout": [query_id]}
- compute_metrics(cases, ranked_hits) -> metrics grouped by category and overall
- runner policies: bm25, bm25_faceted_rrf, bm25_figure_ocr, bm25_faceted_figure_ocr, hybrid

**Dataset:** Target 104 human-checked questions: 16 single-source, 16 cross-document, 16 cross-version, 24 image-only, 16 text-plus-image, and 16 no-answer/confusable. Image-only questions cover visible screenshot text, visible table/config values, and readable labels. Do not claim OCR understands arrow direction or complex visual relationships. A question must name required source/version and answer evidence markers; image cases additionally include figure ID, image hash, and region/page. If pinned corpus and approved images cannot support this count, use the feasible count and mark the evaluation pilot rather than inventing cases or results.

- [ ] **Step 1: Write failing split, source, and version integrity tests.**

Add a deterministic split test with two questions per family and same-image cases. Assert each family and figure occurs in exactly one partition. Add tests that reject a required source absent from the pinned manifest/approved sidecar and count any wrong-version result as a hard leak.

    cases = [
        {"query_id": "q1", "family_id": "parameter-a", "figure_id": "fig-a"},
        {"query_id": "q2", "family_id": "parameter-a", "figure_id": "fig-a"},
        {"query_id": "q3", "family_id": "recovery-b", "figure_id": None},
        {"query_id": "q4", "family_id": "recovery-b", "figure_id": None},
    ]
    split = split_cases(cases, seed="v4-test")
    assert not (set(split["dev"]) & set(split["holdout"]))
    assert set(split["dev"]) | set(split["holdout"]) == {row["query_id"] for row in cases}
    for family in {row["family_id"] for row in cases}:
        family_ids = {row["query_id"] for row in cases if row["family_id"] == family}
        assert family_ids <= set(split["dev"]) or family_ids <= set(split["holdout"])

- [ ] **Step 2: Run the new V4 tests and confirm they fail.**

Run:

    python -m pytest -p no:cacheprovider evaluation/real_world_retrieval/quality_v4/test_quality_v4.py -q

Expected: the split/metric implementation is missing.

- [ ] **Step 3: Implement the dataset validator, lock, metrics, and CLI.**

Source Recall@20 is the fraction of required sources appearing in the first 20 fused results; complete source Hit@5 requires every required source in the first five. Also report anchor recall, cross-document completeness, both-sides cross-version completeness, image Hit@5, version-mismatch count, MRR/nDCG, no-answer non-empty candidate rate, answerable zero-result rate, retrieval-call count, and warm local P50/P95. Keep no-answer metrics explicitly at the retrieval-candidate level: this runner does not measure model answers, hallucination, or model abstention.

The CLI accepts --freeze, --split dev|holdout, --policy POLICY_NAME, and --lock-selection. Freezing records corpus manifest, source/chunk hashes, reviewed sidecar, cases, split, runner and candidate code hashes. --freeze writes the immutable input lock and --split dev writes the baseline report. The runner refuses HOLDOUT until selection_lock.json contains the locked candidate and parameters. Add tests that reject HOLDOUT before selection is locked, reject any hash change after locking, and reject a second HOLDOUT execution for the same lock; store a one-time execution marker in the V4 directory.

- [ ] **Step 4: Run V4 unit tests and freeze inputs before any candidate comparison.**

Run:

    python -m pytest -p no:cacheprovider evaluation/real_world_retrieval/quality_v4/test_quality_v4.py -q
    python evaluation/real_world_retrieval/quality_v4/run_quality_v4.py --freeze
    python evaluation/real_world_retrieval/quality_v4/run_quality_v4.py --split dev --policy bm25

Expected: deterministic split, valid markers, one frozen input manifest, and a BM25 DEV baseline; no HOLDOUT result is written.

### Task 3: Implement bounded facet splitting and RRF separately

**Files:**
- Create versioned-rag-service/src/retrieval_fusion.py
- Create versioned-rag-service/tests/test_retrieval_fusion.py

**Interfaces:**
- split_query_facets(query: str, max_facets: int = 4) -> list[str]
- fuse_ranked_hits(rankings: list[list[dict]], top_k: int = 20, rrf_k: int = 60) -> list[dict]

- [ ] **Step 1: Add failing unit tests.**

    def test_single_fact_is_left_unchanged():
        query = "3.4.3 的 missed_fire_policy 默认值是什么？"
        assert split_query_facets(query) == [query]

    def test_explicit_multi_clause_query_is_bounded():
        result = split_query_facets("参数优先级是什么；失败恢复如何配置；下游节点参数如何传递")
        assert result == ["参数优先级是什么", "失败恢复如何配置", "下游节点参数如何传递"]

    def test_rrf_deduplicates_and_keeps_facet_trace():
        first = {"chunk_id": "v343:a:1", "version": "3.4.3"}
        second = {"chunk_id": "v343:b:2", "version": "3.4.3"}
        result = fuse_ranked_hits([[first, second], [first]], top_k=5)
        assert [hit["chunk_id"] for hit in result].count("v343:a:1") == 1
        assert result[0]["retrieved_by"] == [0, 1]

- [ ] **Step 2: Run the fusion tests and confirm they fail because the module does not exist.**

Run:

    python -m pytest -p no:cacheprovider versioned-rag-service/tests/test_retrieval_fusion.py -q

- [ ] **Step 3: Implement deterministic, safe splitting and reciprocal-rank fusion.**

Split only explicit list/conjunction boundaries, preserve the original query if fewer than two non-empty clauses remain, cap at four facets and 4000 characters. RRF must deduplicate by chunk_id, retain original per-facet rank/score in trace metadata, and use chunk_id for stable ties. Do not cap results per document.

For each occurrence, add 1/(rrf_k + rank); union facet IDs for duplicate chunk IDs, then sort by descending fused score and ascending chunk_id. With one facet, return its rows in original order without recomputing scores.

- [ ] **Step 4: Verify fusion compatibility.**

Run the focused tests. Assert one facet preserves baseline order and results; test duplicate hits, empty rankings, stable tie order, maximum facet count, whitespace, and oversized input.

### Task 4: Add the runtime adapter and approved image retrieval

**Files:**
- Create versioned-rag-service/src/public_retrieval_runtime.py
- Create versioned-rag-service/config/public_retrieval_runtime.json
- Create versioned-rag-service/tests/test_public_retrieval_runtime.py
- Modify versioned-rag-service/src/public_server.py
- Modify versioned-rag-service/src/public_api.py
- Modify versioned-rag-service/tests/test_public_server.py
- Modify evaluation/real_world_retrieval/quality_v4/run_quality_v4.py

**Runtime interface:** PublicRetrievalRuntime(base_index, config_path=None, sidecar_path=None) provides search(query, *, top_k=5, version="current", language="zh_preferred", policy=None) -> list[dict]. The optional policy argument is internal to tests/evaluation only; HTTP SearchRequest must not expose it. The adapter exposes manifest, root, chunks, and policy metadata expected by public_api.py and public_server.py. It delegates BM25 to the immutable base index.

**Runtime config:** separate schema-versioned JSON with default_policy="bm25", an enumerated allowed_policies list, and bounded candidate settings. It does not edit the V3 corpus retrieval_policy.json. The current hybrid is the existing BM25 plus 512-dimensional character-hash dense baseline, not a neural semantic model.

- [ ] **Step 1: Add failing adapter and API tests.**

Cover:
- Config default runs the same BM25 results as PublicKnowledgeIndex.
- Invalid schema, unknown default, or default omitted from allowlist fails closed.
- Image search for version 3.4.3 returns no 3.4.2 rows.
- Pending OCR, wrong SHA, or unknown figure is absent.
- Duplicate facet hits occur once and carry retrieved_by trace.
- HTTP requests containing a policy field return 422.

Define pytest fixtures that create base_index using PublicKnowledgeIndex() and runtime using PublicRetrievalRuntime(base_index, config_path=tmp_path / "runtime.json", sidecar_path=tmp_path / "figures.json"). The fixtures write valid schema-versioned JSON. Create the HTTP client inside TestClient(create_app(index=PublicKnowledgeIndex())).

    def test_runtime_default_is_byte_compatible_bm25(base_index, runtime):
        question = "参数优先级是什么？"
        assert runtime.search(question) == base_index.search(question)

    def test_http_client_cannot_select_runtime_policy(client):
        response = client.post("/public/search", json={
            "query": "参数优先级是什么？", "policy": "hybrid",
        })
        assert response.status_code == 422

- [ ] **Step 2: Run tests first and confirm the runtime adapter is missing.**

Run:

    python -m pytest -p no:cacheprovider versioned-rag-service/tests/test_public_retrieval_runtime.py versioned-rag-service/tests/test_public_server.py -q

- [ ] **Step 3: Implement the adapter, config validation, and multi-source ranking.**

Use base_index.search(..., policy="bm25") for baseline; call it per safe facet for bm25_faceted_rrf; score approved figure OCR only from the validated sidecar for bm25_figure_ocr; combine text and image candidates by rank for the two combined candidates. Apply exact version and language scopes to both modalities before fusion. Stable figure citations include modality="image_ocr", figure_id, version, document_key, heading, commit, sha256, raw_url, and source_url. Keep original chunk fields and evidence IDs.

At service startup load the server config and sidecar once. A malformed file or integrity mismatch must fail startup rather than silently fall back to unsafe image rows. The default file remains BM25 unless a strategy has passed V4.

- [ ] **Step 4: Connect the adapter without invalidating V3 release evidence.**

In public_server.create_app, wrap the passed or default PublicKnowledgeIndex with PublicRetrievalRuntime. Preserve the base index as the source for the historical V3 lock check. Public /health, /public/workspace, /public/search, and /public/query report the runtime policy. Only report V3 as applicable when default runtime remains BM25 and its existing lock is valid. Add tests proving version filtering, public policy reporting, answer evidence IDs, and V3 hashes are unchanged.

- [ ] **Step 5: Compare the candidate retrieval policies on DEV.**

Run:

    python evaluation/real_world_retrieval/quality_v4/run_quality_v4.py --split dev --policy bm25_faceted_rrf
    python evaluation/real_world_retrieval/quality_v4/run_quality_v4.py --split dev --policy bm25_figure_ocr
    python evaluation/real_world_retrieval/quality_v4/run_quality_v4.py --split dev --policy bm25_faceted_figure_ocr
    python evaluation/real_world_retrieval/quality_v4/run_quality_v4.py --split dev --policy hybrid

Compare group quality, evidence anchors, request fanout, and local latency against BM25.

### Task 5: Render image evidence distinctly in the Streamlit workbench

**Files:**
- Modify demo-ui/public_workbench.py
- Modify demo-ui/tests/test_public_official_workbench.py
- Modify demo-ui/README.md

- [ ] **Step 1: Add a failing AppTest using the existing RAG navigation and evidence button.**

Use _mock_client(monkeypatch), patch PublicKnowledgeClient.search to return one approved image_ocr row, then drive the existing app controls:

    app = AppTest.from_file(APP, default_timeout=40).run()
    next(button for button in app.button if button.label == "版本化知识检索").click().run()
    next(button for button in app.button if button.label == "仅查看检索原文").click().run()
    assert not app.exception
    visible = "\n".join(row.value for row in app.markdown)
    assert "图片 OCR 文字" in visible
    assert "OCR 提取，需对照原图" in visible
    assert "3.4.3" in visible and "任务配置" in visible
    assert "查看原图" in visible

The mocked row includes approved status, modality, fixed raw_url, sha256, commit, source version, heading, and OCR text. Also test that a malformed URL or missing approval status is not rendered as a trusted image citation.

- [ ] **Step 2: Run the UI test and verify it fails before changing the UI.**

From demo-ui:

    python -m pytest -p no:cacheprovider tests/test_public_official_workbench.py -k image -q

- [ ] **Step 3: Add a modality-specific citation card.**

Render OCR separately from Markdown body text. Escape OCR content, label it as OCR-derived and human-verified, show the version/section and immutable image URL, and retain the referring official source. A missing or invalid provenance field must not create a clickable source link.

- [ ] **Step 4: Verify the image card and existing public RAG UI.**

From demo-ui:

    python -m pytest -p no:cacheprovider tests/test_public_official_workbench.py -k image -q
    python -m pytest -p no:cacheprovider tests/test_public_official_workbench.py -q

Update README to state that only the reviewed figure subset is searchable.

### Task 6: Select on DEV, lock once, and validate the winner on HOLDOUT

**Files:**
- Modify evaluation/real_world_retrieval/quality_v4/run_quality_v4.py
- Modify evaluation/real_world_retrieval/quality_v4/test_quality_v4.py
- Update evaluation/real_world_retrieval/quality_v4/selection_lock.json
- Update evaluation/real_world_retrieval/quality_v4/report.md
- Update README.md
- Update demo-ui/README.md
- Update versioned-rag-service/README.md

- [ ] **Step 1: Add failing promotion gate tests before implementation.**

promotion_gate(baseline, candidate, budgets) -> bool must reject a candidate if version mismatch count is nonzero, text-only anchor recall drops, no-answer non-empty candidate rate worsens beyond the predeclared tolerance, the target group does not improve, or measured P95 exceeds the deployment budget.

    baseline = {"version_mismatch_count": 0, "text_anchor_recall": 0.90,
                "no_answer_candidate_rate": 0.10, "cross_doc_complete_at_5": 0.50,
                "warm_p95_ms": 30}
    leaked = {**baseline, "version_mismatch_count": 1}
    assert not promotion_gate(baseline, leaked, budgets={"warm_p95_ms": 100})

- [ ] **Step 2: Run the gate tests and confirm promotion_gate is missing.**

Run:

    python -m pytest -p no:cacheprovider evaluation/real_world_retrieval/quality_v4/test_quality_v4.py -q

- [ ] **Step 3: Choose a single candidate using only DEV and write the lock.**

Declare target group, quality non-inferiority limits, no-answer candidate tolerance, fanout and P95 budgets before seeing HOLDOUT. The lock records exact case, split, corpus, sidecar, implementation and runtime config hashes, selected policy, and parameters. If no candidate passes DEV, the selected policy remains BM25.

- [ ] **Step 4: Run HOLDOUT exactly once after the lock is committed to the evaluation workflow.**

Run:

    python evaluation/real_world_retrieval/quality_v4/run_quality_v4.py --lock-selection
    python evaluation/real_world_retrieval/quality_v4/run_quality_v4.py --split holdout

Expected: the runner rejects changed inputs and a second HOLDOUT execution. If the selected candidate fails a promotion gate, keep BM25; do not try another candidate on this HOLDOUT.

- [ ] **Step 5: Publish only hash-matched evaluation results and honest interpretation.**

Update evaluation and project docs. If workspace/UI expose V4 metrics, show them only when the serving corpus, policy, code, and sidecar match the V4 lock. Keep the V3 record labeled as its historical baseline. Never label retrieval metrics as answer accuracy or hallucination rate.

### Task 7: Run regressions, merge to main, and verify public deployment

**Files and checks:**
- versioned-rag-service/tests/
- demo-ui/tests/
- evaluation/real_world_retrieval/quality_v4/

- [ ] **Step 1: Run all relevant tests on the feature branch.**

From the repository root:

    python -m pytest -p no:cacheprovider versioned-rag-service/tests -q
    python -m pytest -p no:cacheprovider evaluation/real_world_retrieval/quality_v4 -q

From demo-ui:

    python -m pytest -p no:cacheprovider tests -q

Use the repository’s configured Python environment if the global interpreter lacks Streamlit. Do not mark the UI checks passed if the suite cannot run.

- [ ] **Step 2: Verify frozen assets, working tree, and review diff.**

Run from the root:

    git diff --check main...HEAD
    git status --short --branch

Recompute the V3 source/artifact hashes and require exact equality with the committed V3 lock. Stage only files belonging to this task; leave RAG-Challenge-2-main/ untouched.

- [ ] **Step 3: Merge and push without force.**

Fetch origin/main. If it is unchanged and all checks pass, switch to main, fast-forward from origin/main, merge codex/rag-multisource-image-evidence normally, and push main. If origin/main advanced, integrate it into the feature branch, rerun affected tests, then perform the normal merge.

- [ ] **Step 4: Verify both public deployments after automatic deploy.**

Check Render /health and /public/workspace for ready status, actual policy, pinned corpus, and matching evaluation metadata. Check Streamlit HTTP status, hard refresh, then run search-only probes for one single-source question, one cross-document query, one version-scoped query, and one approved image OCR question. Verify source/version/image provenance in the UI and API. Do not call the paid answer-generation endpoint.

- [ ] **Step 5: Roll back if a release gate fails.**

Restore the previous main commit and BM25 runtime config if there is a version leak, unapproved OCR, broken image citation, material text-only regression, failed health check, or stale/unavailable public UI.
