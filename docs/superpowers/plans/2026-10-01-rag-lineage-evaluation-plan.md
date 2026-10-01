# RAG Lineage and Evaluation Foundation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Establish a reproducible Autoware quality baseline and explicit document relationships so unverified Chinese/English pages remain searchable without being misreported as translation drift.

**Architecture:** Keep source snapshots immutable and add a separately hashed relation registry keyed by exact versioned document IDs. Expose relation state in the public API and workbench, and build a frozen, split-locked quality set that measures retrieval, language/version correctness, abstention and image evidence independently.

**Tech Stack:** Python 3.12, FastAPI, pytest, JSONL evaluation fixtures, Streamlit.

**Spec:** `docs/superpowers/specs/2026-10-01-ai-app-engineering-readiness-design.md`

## Global Constraints

- The public snapshot currently contains 1,148 version/language sources, 660 topics/paths and 7,927 chunks; default `latest` combines Documentation `main` with Universe `0.52.0`.
- Of 260 community Chinese pages, 44 are path candidates and 216 have no verified counterpart; path equality alone never verifies translation equivalence.
- Only `verified + translation_of` may trigger bilingual drift findings; localized variants require explicit rules; candidate/unknown relations remain searchable but never prove drift.
- The 74 inventoried figures include only two manually verified OCR records; OCR is a candidate until reviewed against the pinned image.
- Preserve BM25 as baseline; benchmark improvements on frozen development and holdout splits before selecting another strategy.
- Explicit version correctness must remain 100% in the evaluation gate; never label retrieval scores or keyword coverage as answer-confidence probability.
- No automatic approval or writing to public/upstream material; reviewers make final decisions.
- Latency goals are provisional: warm retrieval API P95 ≤2 s, single-turn generation P95 ≤15 s, bounded review P95 30–45 s.
- Never send private company material to the public model; this public workspace uses public or explicitly synthetic evidence.

## Review Focus

- A path-matched but unverified Chinese page must not become a translation-drift alert; Task 1 tests a `candidate` relation.
- A localized variant must not be treated as an incorrect translation when no localization rule is registered; Task 1 tests `localized_variant_of` without a rule.
- A malformed or stale relation registry must fail closed without corrupting normal search; Task 1 tests an invalid manifest hash.
- Composite `latest` must preserve component release identity in benchmark cases and API output; Tasks 2 and 3 test `latest` with distinct component versions.
- Unanswerable cases must be reported separately from retrieval misses and must not be counted as successful answers; Task 3 tests an unanswerable case with irrelevant hits.

---

### Task 1: Versioned document relationship registry

**Files:**
- Create: `versioned-rag-service/src/document_relations.py`
- Create: `versioned-rag-service/public_corpus_autoware/document_relations.json`
- Create: `versioned-rag-service/tests/test_document_relations.py`
- Modify: `versioned-rag-service/src/public_knowledge.py`

**Interfaces:**
- Produces `DocumentRelationIndex.from_corpus(root: Path, manifest: dict) -> DocumentRelationIndex`.
- Produces `DocumentRelationIndex.for_document(document_id: str) -> list[dict]` and `.summary() -> dict`; one source may participate in more than one typed relationship.
- Registry rows use `relation_id`, `relation_type`, `verification_status`, `source_document_id`, `target_document_id`, and `verification_evidence`; a registry-level `corpus_manifest_sha256` binds it to the source snapshot.
- Only relation types `translation_of`, `localized_variant_of`, `references_or_depends_on`, `supersedes`, and `none`, and states `verified`, `candidate`, `unknown` are accepted.

- [ ] **Step 1: Write failing relation validation tests**

```python
def test_candidate_translation_pair_is_not_a_verified_drift_relation(tmp_path):
    import hashlib
    import json

    manifest = {"sources": [
        {"version": "docs-main", "language": "zh", "document_key": "guide/start"},
        {"version": "docs-main", "language": "en", "document_key": "guide/start"},
    ]}
    manifest_path = tmp_path / "corpus_manifest.json"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    digest = hashlib.sha256(manifest_path.read_bytes()).hexdigest()
    registry = {
        "schema_version": 1,
        "corpus_manifest_sha256": digest,
        "relations": [{
            "relation_id": "same-path-start",
            "relation_type": "translation_of",
            "verification_status": "candidate",
            "source_document_id": "docs-main:zh:guide/start",
            "target_document_id": "docs-main:en:guide/start",
            "verification_evidence": "same canonical path only; not reviewed",
        }],
    }
    (tmp_path / "document_relations.json").write_text(json.dumps(registry), encoding="utf-8")
    relations = DocumentRelationIndex.from_corpus(tmp_path, manifest)
    assert relations.for_document("docs-main:zh:guide/start")[0]["verification_status"] == "candidate"
    assert relations.summary()["verified_translation_pairs"] == 0
```

Also cover an unruled localized variant, unknown document IDs, duplicate relation IDs, invalid relation enums and a mismatched corpus hash.

- [ ] **Step 2: Run `python -m pytest tests/test_document_relations.py -q` from `versioned-rag-service/`; confirm the module/import or expected validation behavior fails.**
- [ ] **Step 3: Implement the immutable registry loader and validator.** Do not auto-create verified pairs from matching paths; add only pairs whose equivalence was manually checked and record the evidence basis. Keep unreviewed candidates explicit.
- [ ] **Step 4: Run the focused tests and `python -m pytest tests/test_public_knowledge.py -q`; both must pass.**
- [ ] **Step 5: Commit as `feat: model verified document relationships`.**

### Task 2: Relationship state in API and workbench

**Files:**
- Modify: `versioned-rag-service/src/public_api.py: workspace, documents, search`
- Modify: `demo-ui/public_workbench.py: _source_card, _consistency, _source_coverage_text`
- Test: `versioned-rag-service/tests/test_public_server.py`
- Test: `demo-ui/tests/test_public_official_workbench.py`

**Interfaces:**
- `GET /public/workspace` adds `document_relationships` with counts by relation type/state and `verified_translation_pair_count`.
- Each document/search evidence row adds `document_relationships` (an array, empty when no relationship is recorded); this field is descriptive and does not alter retrieval scope or score.
- The workbench labels `verified`, `candidate`, and `unknown` distinctly. Only a verified translation pair can render a drift state; candidate rows say “对应关系待核验”.

- [ ] **Step 1: Add API and UI tests asserting a candidate path match displays as unverified and yields no drift notice.**
- [ ] **Step 2: Run `python -m pytest tests/test_public_server.py -q` from `versioned-rag-service/` and the named UI tests from `demo-ui/`; confirm the assertions fail because relationship state is absent.**
- [ ] **Step 3: Load the validated registry once with the public index, attach read-only relation metadata to workspace/documents/search responses, and render concise Chinese labels.**
- [ ] **Step 4: Run both focused test commands and the complete package suites.**
- [ ] **Step 5: Commit as `feat: expose verified document relationships`.**

### Task 3: Frozen Autoware quality set and baseline report

**Files:**
- Create: `evaluation/autoware_quality_v1/cases.jsonl`
- Create: `evaluation/autoware_quality_v1/split_lock.json`
- Create: `evaluation/autoware_quality_v1/run_benchmark.py`
- Create: `evaluation/autoware_quality_v1/evaluate_saved_answers.py`
- Create: `evaluation/autoware_quality_v1/test_quality_v1.py`
- Create: `evaluation/autoware_quality_v1/test_answer_evaluation.py`
- Create: `evaluation/autoware_quality_v1/README.md`
- Modify: `demo-ui/public_workbench.py: _benchmark`
- Test: `demo-ui/tests/test_public_official_workbench.py`

**Interfaces:**
- Every case has `case_id`, `family_id`, `split`, `category`, `query`, `version`, `language`, `required_sources`, `required_answer_points`, `expected_image_ids`, `answerable`, `expected_relation_state`, and `expected_component_versions`.
- `category` is one of `single_fact`, `cross_source`, `explicit_version`, `zh_query_en_evidence`, `en_query_zh_evidence`, `translation_relation_state`, `image_evidence`, or `unanswerable_scope`; `expected_component_versions` maps each selected component to its exact version under composite `latest`.
- `expected_relation_state` is one of `verified`, `candidate`, `unknown`, or `none`; synthetic verified-pair tests are labeled and reported separately from public corpus cases.
- Cover the eight spec categories with 80–120 source-grounded cases; keep near-duplicate questions from a document family in the same split. Keep synthetic bilingual-pair cases explicitly marked and separate from public-corpus retrieval metrics.
- CLI: `python evaluation/autoware_quality_v1/run_benchmark.py --policy bm25 --repeats 3 --output evaluation/autoware_quality_v1/results/bm25.json`.
- Report separate per-category required-source Recall@5, complete-source rate, MRR/nDCG, version mismatch count/rate, image evidence hit rate, no-answer false-positive rate, citation membership, and P50/P95 latency. State that this is retrieval coverage, not generated-answer accuracy.
- `evaluate_saved_answers.py` accepts JSONL rows `{case_id, answer, citations:[chunk_id]}` and a separate review JSONL `{case_id, answer_sha256, claims:[{claim_text, supported, supporting_chunk_ids}], covered_required_points:[string]}`; it reports citation precision/recall, supported-claim ratio, required-point completeness and no-answer abstention precision/recall. It never calls a model and refuses semantic-support metrics when the answer hash or human review is missing.

- [ ] **Step 1: Add validator/metric tests using a two-document composite-latest case, one verified bilingual pair, one unverified candidate and one unanswerable query with irrelevant hits. Add answer-evaluation tests for a cited-but-human-marked-unsupported claim and an incomplete but otherwise supported answer.**
- [ ] **Step 2: Run `python -m pytest evaluation/autoware_quality_v1/test_quality_v1.py -q`; confirm failure on missing loader/metrics.**
- [ ] **Step 3: Curate 80–120 cases from pinned sources; record split by family, answer support and exact source IDs. Implement schema validation, corpus/runtime fingerprinting, per-policy execution and stratified metrics. Do not mark an image or translation expectation unless its source evidence is reviewed.**
- [ ] **Step 4: Run the benchmark twice against BM25 and verify stable case/fingerprint hashes and equal non-latency metrics (latency is reported, not expected to be bit-identical); run both named evaluation test files. Do not make model calls in CI.**
- [ ] **Step 5: Render baseline and coverage limitations in the UI, replacing stale V3-as-current wording while preserving historical reports. Run the complete service and UI test suites.**
- [ ] **Step 6: Commit as `test: freeze Autoware quality baseline`.**

