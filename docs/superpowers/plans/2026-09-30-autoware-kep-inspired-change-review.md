# Autoware KEP-Inspired Change Review Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `executing-plans` to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the public demo's active DolphinScheduler corpus with a pinned Autoware engineering corpus, incorporate proposal-review structure inspired by KEP into the existing evidence-grounded Agent, then publish and verify the result on GitHub `main` and the public demo.

**Architecture:** Keep one product and preserve the current RAG HTTP boundary. Build a small allowlisted corpus from official Autoware Universe release tags, select the active corpus through a manifest-backed runtime setting, and keep historical DolphinScheduler data only as an inactive reproducibility snapshot. Extend the existing natural-language review path with optional, honest proposal context and human decision states; every Agent impact remains bound to evidence returned by the same RAG service.

**Tech Stack:** Python 3.12, FastAPI, Streamlit, BM25 public retrieval, Pydantic, SQLite demo audit, pytest, GitHub, Render, Streamlit Community Cloud.

**Spec:** `docs/superpowers/specs/2026-09-30-autoware-kep-inspired-review-design.md`

## Global Constraints

- Use the official `autowarefoundation/autoware_universe` releases `0.51.0` and `0.52.0`, then record each resolved commit in the source manifest. The official release list includes both versions and identifies 0.52.0 as latest at planning time: [release history](https://github.com/autowarefoundation/autoware_universe/releases).
- Use an allowlist of planning/module design docs, README/specification files, parameter/config YAML, release notes, and related tests; do not clone the entire repository into the served corpus.
- The public RAG manifest and default results must contain no Kubernetes KEP material. KEP concepts may be described as workflow inspiration only.
- Resolve the default version from the active manifest's `current_version`; never hard-code a guessed “latest” version.
- Preserve the user's original natural-language change request. Missing proposal information must be marked as missing, not inferred as fact.
- Keep the existing maximum of 4 Agent-to-RAG queries and 5 evidence chunks unless an evaluation-backed change is explicitly approved.
- Keep evidence membership validation, human review, no upstream writeback, and no automatic approval.
- Offline evaluation must not call paid generation APIs or use model output as ground truth.
- Before editing, record the initial tracked diff and untracked inventory. The existing P1 query-planning, private-scope guard, and anonymous SQLite audit work is user-authorized from the preceding task and overlaps this release; inspect it, run its tests, and include only those related, verified changes needed by the Autoware release. Preserve unrelated data and experiments. Never assume `git add <path>` excludes unrelated hunks in an overlapping file: stage reviewed hunks with `git add -p` (or an equivalent reviewed index patch), then inspect the complete staged diff.
- Implement on a release branch based on the current `main` checkout while preserving its existing working-tree changes. Do not reset, stash, overwrite, or delete the existing user work. Keep task commits reviewable and do not push until the full diff and test suite have been reviewed.
- Publish only after local RAG, Agent, UI, and new-corpus evaluation checks pass; report deployment failure rather than claiming success.

## Review Focus

- An omitted optional proposal field keeps the raw request searchable and is shown as “待补充”; it does not block RAG or create a made-up fact. Test in Task 3.
- A selected old Autoware version returns only that version's evidence; the default uses the manifest's current version. Test in Tasks 1 and 2.
- A malformed source URL, commit, repository, or hash is rejected before indexing or citation. Test in Tasks 1 and 2.
- If RAG or generation is unavailable, retrieved evidence (when available) and the exact failure/gap remain visible; the Agent never fabricates grounded impacts. Test in Tasks 3 and 5.
- A `deferred` review decision survives migration of an existing SQLite database and remains distinct from `reviewed` and `rejected`. Test in Task 4.

---

### Task 1: Curate and pin the Autoware corpus

**Files:**
- Create: `versioned-rag-service/config/autoware_source_selection.json`
- Create: `versioned-rag-service/config/autoware_retrieval_policy.json`
- Create: `versioned-rag-service/scripts/sync_autoware_sources.py`
- Modify: `versioned-rag-service/scripts/figure_evidence.py`
- Create: `versioned-rag-service/scripts/build_reviewed_figure_sidecar.py`
- Create: `versioned-rag-service/public_corpus_autoware/corpus_manifest.json`
- Create: `versioned-rag-service/public_corpus_autoware/retrieval_policy.json`
- Create: `versioned-rag-service/public_corpus_autoware/figure_evidence.json`
- Create: `versioned-rag-service/public_corpus_autoware/figure_evidence_reviewed.json`
- Create: `versioned-rag-service/public_corpus_autoware/figure_evidence_reviewed.lock.json`
- Create: `versioned-rag-service/public_corpus_autoware/LICENSE` and `NOTICE`
- Create: `versioned-rag-service/public_corpus_autoware/sources/<version>/<allowlisted-path>`
- Test: `versioned-rag-service/tests/test_autoware_source_sync.py`
- Test: `versioned-rag-service/tests/test_figure_evidence.py`

**Interfaces:**
- `load_source_selection(path: Path) -> list[dict]` validates a checked-in allowlist of source path, document key, type, and locale.
- Each allowlist row has `document_path`, `document_key`, `source_type`, `language`, and `locale`; `build_pinned_sources(checkouts: dict[str, dict], selection: list[dict], output_root: Path) -> dict` copies only listed UTF-8 files and returns a manifest with repository, release, resolved commit, license, path, URL, and hashes.
- Each manifest source row includes `repository`, `version`, `commit`, `document_key`, `source_type`, `language`, `locale`, `document_path`, `local_path`, `source_url`, `license`, and `sha256`; `source_url` uses the exact 40-character commit rather than a mutable branch/tag. The manifest includes `workspace`, `repository`, `baseline_version`, `current_version`, `available_versions`, `languages`, a version-to-commit `commits` map, and `sources`.
- `build_pinned_sources` accepts exactly `{ "0.51.0": {"root": Path, "commit": str}, "0.52.0": {"root": Path, "commit": str} }`; it rejects missing/extra releases, symbolic/unfull commit values, duplicate source identity, paths escaping the checkout, absent files, invalid UTF-8, and a repository license other than Apache-2.0.
- `_write_manifest_source(output_root: Path, version: str, commit: str, item: dict, content: bytes) -> dict` writes one unchanged file and returns its row; `_manifest_from_sources(sources: list[dict], *, current_version: str, baseline_version: str) -> dict` returns the complete versioned manifest.
- `main(argv: Sequence[str] | None = None) -> int` accepts `--baseline-checkout`, `--current-checkout`, `--root`, and required `--rebuild`; it verifies exact tag names `0.51.0`/`0.52.0`, reads full commit SHAs from those checkouts, and never fetches network content itself.
- The checked-in `autoware_retrieval_policy.json` starts with BM25 selected, no benchmark claim, no router/reranker, and `frozen_selection_evidence.query_count = 0`; `main` copies this config to the corpus before `build_index` updates the manifest and artifact hashes.
- `scan_inventory(root: Path) -> dict` and `build_reviewed_figure_chunks(rows: list[dict], manifest: dict) -> list[dict]` use repository and commit values from the manifest; they keep source-image text separate from authored Markdown and accept only SHA-bound, manually approved OCR.
- `build_reviewed_figure_sidecar(root: Path) -> dict` writes the approved OCR chunks and manifest/sidecar integrity lock from `figure_evidence.json`; it rejects unapproved, unverifiable, wrong-repository, wrong-commit, or hash-mismatched entries.
- Tests create local fixture checkouts as `{version: {"root": Path, "commit": str}}`; these contain tiny text files and never require network access.
- The sync CLI takes local checkouts of the two official tags so the corpus builder is deterministic and does not download files during RAG service startup.

- [ ] **Step 1: Write source allowlist and integrity tests first**

```python
def test_autoware_manifest_has_two_pinned_releases_and_verified_sources(tmp_path):
    import json

    selection_path = tmp_path / "selection.json"
    selection_path.write_text(json.dumps([{
        "document_path": "planning/validator/README.md",
        "document_key": "planning/validator",
        "source_type": "official_documentation",
        "language": "en",
        "locale": "en-US",
    }]), encoding="utf-8")
    checkouts = {}
    for version, commit in (("0.51.0", "a" * 40), ("0.52.0", "b" * 40)):
        root = tmp_path / "checkout" / version
        (root / "planning/validator").mkdir(parents=True)
        (root / "LICENSE").write_text("Apache License Version 2.0", encoding="utf-8")
        (root / "planning/validator/README.md").write_text(
            "# Planning Validator\nInvalid trajectory handling\n", encoding="utf-8"
        )
        checkouts[version] = {"root": root, "commit": commit}
    selection = load_source_selection(selection_path)
    manifest = build_pinned_sources(checkouts, selection, tmp_path / "corpus")
    assert manifest["workspace"] == "Autoware"
    assert {manifest["baseline_version"], manifest["current_version"]} == {"0.51.0", "0.52.0"}
    assert all(row["repository"] == "autowarefoundation/autoware_universe" for row in manifest["sources"])
    assert all((tmp_path / "corpus" / row["local_path"]).is_file() for row in manifest["sources"])
    assert all(row["license"] == "Apache-2.0" and len(row["sha256"]) == 64 for row in manifest["sources"])
    assert not any("kubernetes" in row["source_url"].casefold() or "kep" in row["document_key"].casefold() for row in manifest["sources"])
```

- [ ] **Step 2: Run the test and verify the missing sync contract fails**

Run: `python -m pytest versioned-rag-service/tests/test_autoware_source_sync.py -q`

Expected: FAIL because the allowlist loader and pinned-source builder do not exist yet.

- [ ] **Step 3: Inspect and freeze only suitable official sources**

Use the two release refs from the official [Autoware Universe release list](https://github.com/autowarefoundation/autoware_universe/releases). Select a compact planning scope with, at minimum, a planner module design, planning-validator behavior/parameters, matching YAML, one release/change record per release, and related test/spec material where present. Verify the repository's `LICENSE` and exact file paths at both refs; exclude generated binaries, maps, models, unrelated code, and all KEP sources. Record exact tag commit SHAs, not branch names, in the manifest.

The checked-in allowlist has this shape (the actual file must include all selected docs, config, tests, and release records for both releases):

```json
[
  {"document_path":"planning/behavior_path_planner/autoware_behavior_path_start_planner_module/README.md","document_key":"planning/start_planner","source_type":"official_documentation","language":"en","locale":"en-US"}
]
```

For the selected Markdown sources, inspect the actual image references and run the corpus-generic inventory scanner. From those, choose at most eight planning/validator figures whose embedded labels or values matter to a plausible change-review question; fetch only those pinned image URLs during offline corpus preparation, run local Tesseract OCR, visually review each candidate, and approve only legible text. Keep each OCR item bound to source version, exact commit, Markdown reference/heading, image SHA, raw image URL, OCR engine, and reviewer note. Do not infer image text from alt text and do not add empty or unreviewed OCR chunks to search. Add a temp-corpus test that builds an inventory for two manifests with different repository/commit values, then verifies a matching approved OCR row is emitted and a SHA or commit mismatch is rejected.

- [ ] **Step 4: Implement the allowlist-only sync builder and CLI**

Use `git show TAG:PATH` or a local shallow checkout for allowlisted text files. Reject paths outside the repository, non-UTF-8 text, duplicate `(version, document_key, locale)` rows, unknown tags, missing files, changed license, and unpinned refs. Copy raw bytes unchanged and hash those bytes. Derive `available_versions` and `languages` from manifest rows. Keep the existing `versioned-rag-service/public_corpus` DolphinScheduler snapshot intact as an inactive historical asset.

```python
def build_pinned_sources(checkouts, selection, output_root):
    sources = []
    for version in ("0.51.0", "0.52.0"):
        root = checkouts[version]["root"].resolve()
        commit = checkouts[version]["commit"]
        if len(commit) != 40 or any(char not in "0123456789abcdef" for char in commit):
            raise ValueError("source checkout must be pinned to a full commit SHA")
        for item in selection:
            source_path = (root / item["document_path"]).resolve()
            if root not in source_path.parents or not source_path.is_file():
                raise ValueError("source path is outside the checkout or missing")
            content = source_path.read_bytes()
            content.decode("utf-8")
            # Copy the exact bytes under sources/{version}/{document_path} and hash them.
            sources.append(_write_manifest_source(output_root, version, commit, item, content))
    return _manifest_from_sources(sources, current_version="0.52.0", baseline_version="0.51.0")
```

`_write_manifest_source` and `_manifest_from_sources` are private helpers in the same new script; each validates uniqueness and emits the concrete fields listed in `build_pinned_sources`.

- [ ] **Step 5: Generate the checked-in source manifest and test the real pinned files**

Use the following PowerShell commands to create two detached source worktrees, sync the corpus, and inspect selected figure evidence. The sync script verifies exact tags and full commit SHAs, copies allowlisted sources, builds BM25 chunks/vectors, and writes empty hash-bound sidecars. The figure inventory script then fetches only explicitly selected images from those pinned commits and runs local Tesseract; visually inspect every extracted image before marking reviewed text approved, then build the reviewed sidecar and lock:

```powershell
$autowareClone = Join-Path $env:TEMP "autoware-universe-corpus-source"
$autoware051 = Join-Path $env:TEMP "autoware-universe-0.51.0"
$autoware052 = Join-Path $env:TEMP "autoware-universe-0.52.0"
git clone --filter=blob:none --no-checkout https://github.com/autowarefoundation/autoware_universe.git $autowareClone
git -C $autowareClone fetch --depth=1 origin refs/tags/0.51.0:refs/tags/0.51.0 refs/tags/0.52.0:refs/tags/0.52.0
git -C $autowareClone worktree add --detach $autoware051 0.51.0
git -C $autowareClone worktree add --detach $autoware052 0.52.0
python versioned-rag-service/scripts/sync_autoware_sources.py --baseline-checkout $autoware051 --current-checkout $autoware052 --root versioned-rag-service/public_corpus_autoware --rebuild
python versioned-rag-service/scripts/figure_evidence.py --root versioned-rag-service/public_corpus_autoware --fetch-selected --max-images 8 --review-dir (Join-Path $env:TEMP "autoware-figure-review")
python versioned-rag-service/scripts/build_reviewed_figure_sidecar.py --root versioned-rag-service/public_corpus_autoware
python -m pytest versioned-rag-service/tests/test_autoware_source_sync.py -q
python -m pytest versioned-rag-service/tests/test_figure_evidence.py -q
```

- [ ] **Step 6: Commit only Task 1 paths**

```powershell
git add versioned-rag-service/config/autoware_source_selection.json versioned-rag-service/config/autoware_retrieval_policy.json versioned-rag-service/scripts/sync_autoware_sources.py versioned-rag-service/scripts/build_reviewed_figure_sidecar.py versioned-rag-service/public_corpus_autoware versioned-rag-service/tests/test_autoware_source_sync.py
git add -p versioned-rag-service/scripts/figure_evidence.py versioned-rag-service/tests/test_figure_evidence.py
git diff --cached --check
git commit -m "feat: add pinned Autoware public corpus"
```

### Task 2: Serve the selected corpus through the existing RAG contract

**Files:**
- Modify: `versioned-rag-service/src/public_knowledge.py`
- Modify: `versioned-rag-service/src/public_retrieval_runtime.py`
- Modify: `versioned-rag-service/src/public_server.py`
- Modify: `versioned-rag-service/src/public_api.py`
- Modify: `versioned-rag-service/src/figure_sidecar_integrity.py`
- Verify: `versioned-rag-service/scripts/figure_evidence.py`
- Verify: `versioned-rag-service/scripts/build_reviewed_figure_sidecar.py`
- Test: `versioned-rag-service/tests/test_public_knowledge.py`
- Test: `versioned-rag-service/tests/test_public_retrieval_runtime.py`
- Test: `versioned-rag-service/tests/test_public_server.py`
- Test: `versioned-rag-service/tests/test_public_autoware_profile.py`

**Interfaces:**
- `PublicKnowledgeIndex(root: Path = ACTIVE_ROOT)` loads the active corpus manifest; `ACTIVE_ROOT` defaults to `public_corpus_autoware` and remains injectable in tests.
- Existing `/public/workspace`, `/public/documents`, `/public/document`, `/public/search`, `/public/query`, and `/public/review-advice` remain backwards compatible; only `/public/review-advice` gains an optional version request field.
- Workspace metadata is read from the manifest (`workspace`, `repository`, `baseline_version`, `current_version`, `available_versions`, counts); release tags and commit SHAs are exposed without an Apache-specific constant.
- `/public/workspace.languages` is the sorted set of source `language` codes from the active manifest; the Streamlit language filter exposes only languages that exist in that corpus plus `all`.
- `ReviewAdviceRequest` keeps `change_summary` and `evidence_chunk_ids` and adds optional `version: str = "current"`; the endpoint resolves `current` to the manifest current version and accepts an explicit version only if declared by that manifest. Every supplied evidence row must match the resolved version. Older clients continue to use current evidence.
- `make_autoware_index_fixture(root: Path) -> Path` writes two tiny versioned Markdown sources plus a valid manifest, then calls `build_index(root)` to produce test chunks and vectors.
- `_load_and_validate_manifest(path: Path) -> dict` verifies schema, the active version pair, source repository/path/tag/license/hash, and that all indexed source paths remain beneath the corpus root; it rejects KEP and undeclared repository rows.
- Approved image rows include `repository` in addition to version/commit/chunk/source URL so the existing Agent source allowlist can validate them exactly like Markdown evidence.

- [ ] **Step 1: Add generic manifest/runtime regression tests**

```python
def test_active_workspace_and_search_use_autoware_manifest(tmp_path):
    corpus_root = make_autoware_index_fixture(tmp_path / "public_corpus_autoware")
    index = PublicKnowledgeIndex(corpus_root)
    assert index.manifest["workspace"] == "Autoware"
    assert index.manifest["current_version"] == "0.52.0"
    hits = index.search("planning validator invalid trajectory handling", version="current", language="en")
    assert hits and all(hit["repository"] == "autowarefoundation/autoware_universe" for hit in hits)
    assert all(hit["version"] == "0.52.0" for hit in hits)
    assert index.manifest["languages"] == ["en"]
```

Add explicit historical-version and source-integrity tests. The parameterized corruption test changes one manifest field at a time and requires construction to fail before a query can return evidence:

```python
def test_explicit_baseline_search_returns_only_baseline_sources(tmp_path):
    root = make_autoware_index_fixture(tmp_path / "corpus")
    index = PublicKnowledgeIndex(root)
    hits = index.search("planning validator", version="0.51.0", language="en")
    assert hits and {row["version"] for row in hits} == {"0.51.0"}


@pytest.mark.parametrize("field,value", [
    ("repository", "attacker/other"),
    ("source_url", "https://example.com/fake"),
    ("commit", "main"),
    ("sha256", "0" * 64),
])
def test_manifest_rejects_untrusted_source_identity(tmp_path, field, value):
    root = make_autoware_index_fixture(tmp_path / "corpus")
    manifest_path = root / "corpus_manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["sources"][0][field] = value
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    with pytest.raises(ValueError):
        PublicKnowledgeIndex(root)


def test_review_advice_accepts_declared_historical_evidence_only_for_its_version(tmp_path):
    root = make_autoware_index_fixture(tmp_path / "corpus")
    index = PublicKnowledgeIndex(root)
    old_hit = index.search("planner", version="0.51.0", language="en", top_k=1)[0]
    with TestClient(create_app(index=index)) as client:
        valid = client.post("/public/review-advice", json={
            "change_summary": "Review planner change",
            "evidence_chunk_ids": [old_hit["chunk_id"]], "version": "0.51.0",
        })
        mismatch = client.post("/public/review-advice", json={
            "change_summary": "Review planner change",
            "evidence_chunk_ids": [old_hit["chunk_id"]], "version": "0.52.0",
        })
    assert valid.status_code == 200
    assert valid.json()["status"] == "GENERATION_NOT_CONFIGURED"
    assert mismatch.status_code == 422
```

- [ ] **Step 2: Run focused tests and confirm the current implementation is corpus-specific**

Run: `python -m pytest versioned-rag-service/tests/test_public_autoware_profile.py -q`

Expected: FAIL because `PublicKnowledgeIndex` defaults to the DolphinScheduler folder and the server advertises an Apache-only workspace.

- [ ] **Step 3: Generalize the active corpus root and workspace metadata**

Change the default root to `public_corpus_autoware`, while keeping an explicit constructor root for legacy tests and experiments. Build chunks, dense vectors and runtime policy from the new manifest; use the SHA-reviewed Autoware figure sidecar, or a valid empty sidecar if the audit finds no relevant legible image text. The service must reject hash/commit/source mismatches as before. Change API title and `/health` workspace/version to read the manifest; derive `/public/workspace.languages` and `available_versions` from validated manifest rows. Preserve endpoint responses and loosen no validated citation rules.

```python
class PublicKnowledgeIndex:
    def __init__(self, root: Path = ACTIVE_ROOT):
        self.root = Path(root)
        self.manifest = _load_and_validate_manifest(self.root / "corpus_manifest.json")
        self.chunks = json.loads((self.root / "chunks.json").read_text(encoding="utf-8"))
        self.matrix = np.load(self.root / "dense_vectors.npy", allow_pickle=False)
        if len(self.chunks) != len(self.matrix):
            raise ValueError("public corpus index size mismatch")
```

In `public_api.py`, keep review evidence explicit and version-aware:

```python
class ReviewAdviceRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    change_summary: str = Field(min_length=1, max_length=4000)
    evidence_chunk_ids: list[str] = Field(min_length=1, max_length=5)
    version: str = Field(default="current", min_length=1, max_length=32)


resolved_version = (
    index.manifest["current_version"] if payload.version == "current" else payload.version
)
if resolved_version not in index.manifest["available_versions"]:
    raise HTTPException(status_code=422, detail="INVALID_REVIEW_VERSION")
if any(row is None or row["version"] != resolved_version for row in evidence):
    raise HTTPException(status_code=422, detail="INVALID_REVIEW_EVIDENCE")
```

The system prompt for this endpoint uses workspace and resolved-version values from the validated manifest; it must not name Apache or another fixed project.

- [ ] **Step 4: Make image sidecar and release validation profile-neutral**

Allow a corpus with no approved image evidence by generating a valid empty inventory/sidecar/lock tied to the Autoware manifest hash. Keep strict validation for any image evidence that is present. Validate OCR image hashes, source markdown path, exact commit URL, repo, language, version, image SHA, and review status before adding a derived chunk. Publish historical DolphinScheduler V3/V4 metrics only when their corpus fingerprint matches; otherwise return no stale metric instead of relabeling it as Autoware.

```python
def _validated_retrieval_release(index):
    release = _load_release_metadata(index.root)
    if release is None or release.get("corpus_sha256") != _sha256(index.root / "corpus_manifest.json"):
        return None
    return release
```

- [ ] **Step 5: Verify version filters, artifact hashes, endpoint behavior, and old asset immutability**

Run: `python -m pytest versioned-rag-service/tests/test_public_autoware_profile.py versioned-rag-service/tests/test_public_knowledge.py versioned-rag-service/tests/test_public_retrieval_runtime.py versioned-rag-service/tests/test_public_server.py -q`.

Expected: new profile tests pass; historical snapshot hash and old result files remain unchanged; `/public/search` returns only the requested version.

- [ ] **Step 6: Commit only Task 2 paths**

```powershell
git add versioned-rag-service/src/public_knowledge.py versioned-rag-service/src/public_retrieval_runtime.py versioned-rag-service/src/public_server.py versioned-rag-service/src/public_api.py versioned-rag-service/src/figure_sidecar_integrity.py versioned-rag-service/tests/test_public_knowledge.py versioned-rag-service/tests/test_public_retrieval_runtime.py versioned-rag-service/tests/test_public_server.py versioned-rag-service/tests/test_public_autoware_profile.py versioned-rag-service/public_corpus_autoware
git diff --cached --check
git commit -m "feat: serve versioned Autoware knowledge"
```

### Task 3: Add KEP-inspired proposal context to the existing Agent

**Files:**
- Modify: `change-review-agent/app/change_request.py`
- Modify: `change-review-agent/app/public_review.py`
- Modify: `demo-ui/services/public_knowledge_client.py`
- Modify: `change-review-agent/tests/test_change_request.py`
- Modify: `change-review-agent/tests/test_public_review.py`

**Interfaces:**
- `build_request_plan(summary, *, change_type=None, impact_scope=None, objective="", constraints="", validation_plan="", target_version="") -> dict` returns the existing bounded query plan plus a `proposal_context` with raw summary, resolved type, scope, target version, supplied fields and `missing_context` labels.
- `PublicReviewAgent.analyze_request(summary, *, change_type=None, impact_scope=None, target_version="current", objective="", constraints="", validation_plan="") -> dict` resolves `current` from the workspace, checks explicit versions against `available_versions`, uses the resolved version for every search and generation-evidence check, includes proposal context in the evidence-constrained prompt, and returns explicit workflow status.
- `PublicKnowledgeClient.review_advice(change_summary: str, evidence_chunk_ids: list[str], *, version: str = "current") -> dict` forwards the version to the backwards-compatible RAG endpoint.
- The workspace's manifest repository is the source allowlist: a hit is eligible only when its repo/version is declared by the current workspace; no Apache hostname assumption remains.
- `proposal_context` keys are `original_summary`, `change_type`, `impact_scope`, `target_version`, `change_goal`, `constraints`, `validation_plan`, and `missing_context`.
- The existing query and evidence bounds remain hard limits; every cited `chunk_id` must be present in the current request's validated RAG candidates. The exact RAG/generation failure state remains separate from “no relevant source found.”

- [ ] **Step 1: Write failing proposal-context and non-fabrication tests**

```python
from app.change_request import build_request_plan
from app.public_review import PublicReviewAgent


def test_missing_proposal_context_is_reported_without_changing_original_query():
    plan = build_request_plan("Change the trajectory validation threshold", target_version="0.52.0")
    assert plan["proposal_context"]["original_summary"] == "Change the trajectory validation threshold"
    assert plan["proposal_context"]["target_version"] == "0.52.0"
    assert {"change_goal", "constraints", "validation_plan"} <= set(plan["proposal_context"]["missing_context"])
    assert plan["queries"][0]["query"].startswith("Change the trajectory validation threshold")
    assert len(plan["queries"]) <= 4


def test_autoware_chinese_terms_expand_search_without_rewriting_request():
    raw = "修改起步规划器的轨迹校验行为"
    plan = build_request_plan(raw)
    assert raw in plan["queries"][0]["query"]
    expanded = plan["queries"][0]["search_query"].casefold()
    assert "start planner" in expanded and "trajectory validation" in expanded


class VersionGateway:
    def __init__(self):
        self.search_versions = []
        self.generation_version = None

    def workspace(self):
        return {"repository": "autowarefoundation/autoware_universe",
                "current_version": "0.52.0", "available_versions": ["0.51.0", "0.52.0"]}

    def search(self, query, *, version, language, top_k=5):
        self.search_versions.append(version)
        return {"results": [{"chunk_id": "aw-051", "document_key": "planning/design",
                             "heading": "Planner design", "repository": self.workspace()["repository"],
                             "version": version,
                             "source_url": f"https://github.com/autowarefoundation/autoware_universe/blob/{version}/planning/design.md",
                             "retrieval_score": 1.0, "content": "Planner behavior and validation."}]}

    def review_advice(self, change_summary, evidence_chunk_ids, *, version):
        self.generation_version = version
        return {"status": "GENERATION_NOT_CONFIGURED", "answer": "N/A", "sources": []}


def test_agent_uses_explicit_historical_version_for_search_and_generation():
    gateway = VersionGateway()
    result = PublicReviewAgent(gateway).analyze_request(
        "Change planner validation behavior", target_version="0.51.0",
    )
    assert gateway.search_versions and set(gateway.search_versions) == {"0.51.0"}
    assert gateway.generation_version == "0.51.0"
    assert result["proposal_context"]["target_version"] == "0.51.0"
    assert {row["version"] for row in result["retrieved_results"]} == {"0.51.0"}


class OutageGateway(VersionGateway):
    def search(self, query, *, version, language, top_k=5):
        if self.search_versions:
            self.search_versions.append(version)
            raise RuntimeError("RAG unavailable")
        return super().search(query, version=version, language=language, top_k=top_k)

    def review_advice(self, change_summary, evidence_chunk_ids, *, version):
        self.generation_version = version
        raise RuntimeError("model unavailable")


def test_outages_keep_successful_evidence_and_do_not_create_impacts():
    gateway = OutageGateway()
    result = PublicReviewAgent(gateway).analyze_request(
        "Change planner validation behavior. Check interface compatibility.",
        target_version="0.51.0",
    )
    assert [row["chunk_id"] for row in result["retrieved_results"]] == ["aw-051"]
    assert any(row["status"] == "search_unavailable" for row in result["retrieval_trace"]["queries"])
    assert result["review_advice"]["status"] == "GENERATION_PROVIDER_UNAVAILABLE"
    assert result["impacts"] == []
```

- [ ] **Step 2: Run the tests before implementation**

Run: `python -m pytest change-review-agent/tests/test_change_request.py change-review-agent/tests/test_public_review.py -q`.

Expected: FAIL because proposal context fields are not part of the current planner/result contract.

- [ ] **Step 3: Add validated optional context and explicit statuses**

Accept only bounded strings; preserve the original text; fill `target_version` from the active workspace when omitted. Keep unprovided goal/constraint/test-plan values empty and list them as missing. Add `proposal_status` values `DRAFT`, `ANALYZED_PENDING_REVIEW`, and `OUT_OF_SCOPE`; the final human decision remains separate from Agent analysis. Fold only provided context into the first query and model prompt without increasing the hard query/evidence limits. Replace stale DolphinScheduler query aliases with a small allowlisted Autoware glossary (`起步规划器` → `start planner`, `行为路径` → `behavior path`, `轨迹校验` → `trajectory validation`, `验证器` → `validator`); retain the user's original query in the trace and add aliases only to the actual search string.

```python
proposal_context = {
    "original_summary": summary,
    "change_type": resolved_type,
    "impact_scope": normalized_scope,
    "target_version": target_version,
    "change_goal": objective.strip(),
    "constraints": constraints.strip(),
    "validation_plan": validation_plan.strip(),
}
proposal_context["missing_context"] = [
    label for key, label in (
        ("change_goal", "变更目标"),
        ("constraints", "约束与兼容性"),
        ("validation_plan", "验证计划"),
    ) if not proposal_context[key]
]
```

- [ ] **Step 4: Replace Apache-only hit validation with manifest-bound validation**

Validate repository and version against the workspace metadata and validate chunk IDs against the candidates returned by this analysis. Search with the selected version, and pass the same version alongside those exact candidate IDs to generation. Keep explicit-private-company scope rejection before RAG/model calls. If the service or generation provider fails, preserve RAG evidence and precise failure state; never manufacture an impact candidate.

```python
workspace = self.gateway.workspace()
allowed_repository = workspace["repository"]
resolved_version = workspace["current_version"] if target_version == "current" else target_version
if resolved_version not in workspace["available_versions"]:
    raise ValueError("目标版本不在当前公开语料清单中")
rows = [
    row for row in search_result.get("results", [])
    if row.get("repository") == allowed_repository
    and row.get("version") == resolved_version
    and row.get("chunk_id")
    and str(row.get("source_url", "")).startswith(
        f"https://github.com/{allowed_repository}/blob/"
    )
]
```

Call `self.gateway.search(search_query, version=resolved_version, language="all", top_k=5)` and `self.gateway.review_advice(summary_and_context, candidate_ids, version=resolved_version)`; the generator endpoint independently verifies that those exact IDs belong to the declared version. The out-of-scope message must name the active manifest workspace and public-only boundary instead of Apache. The `OutageGateway` test above verifies the first valid hit survives later search and generation failures.

- [ ] **Step 5: Run planner, gateway, citation-membership, and outage regressions**

Run: `python -m pytest change-review-agent/tests/test_change_request.py change-review-agent/tests/test_public_review.py -q`.

Expected: all existing query-budget, private-scope and evidence-membership tests remain valid with Autoware hits and version IDs.

- [ ] **Step 6: Commit only Task 3 paths**

```powershell
git add -p change-review-agent/app/change_request.py change-review-agent/app/public_review.py change-review-agent/tests/test_public_review.py
git add change-review-agent/tests/test_change_request.py
git diff --cached --check
git commit -m "feat: structure evidence-grounded change proposals"
```

### Task 4: Present proposal and human decision lifecycle in the workbench

**Files:**
- Modify: `demo-ui/public_workbench.py`
- Modify: `demo-ui/services/review_audit.py`
- Modify: `demo-ui/tests/test_public_official_workbench.py`
- Modify: `demo-ui/tests/test_review_audit.py`
- Modify: `demo-ui/README.md`

**Interfaces:**
- `_analyze_change_request` forwards the selected version and optional objective, constraints and validation plan without losing the original request.
- Review actions persist `reviewed`, `rejected`, or `deferred`; `SQLiteReviewAudit.list_recent` returns all three distinctly.
- UI states distinguish draft, analysis awaiting review, reviewed, rejected, and deferred. “Reviewed” is not approval to write or release a document.
- The audit test helper `_create_legacy_review_database(path, decision)` creates the exact pre-migration `review_events` schema and one valid seeded row. `_review_report(decision)` returns the report fields currently required by `SQLiteReviewAudit.record`, with `public_baseline_written=False`.
- `_analyze_change_request(client, summary, change_type, impact_scope, *, target_version="current", objective="", constraints="", validation_plan="") -> dict` passes the selected version and optional context to the Agent endpoint.
- `_review_version_selector(workspace: dict) -> tuple[list[str], int]` returns manifest-declared versions and the index of `current_version`, so Streamlit's selectbox defaults to the latest indexed version.

- [ ] **Step 1: Write failing UI and database migration tests**

```python
import json
import sqlite3
import pytest


def _create_legacy_review_database(path, decision):
    with sqlite3.connect(path) as connection:
        connection.execute("""
            CREATE TABLE review_events (
                event_id TEXT PRIMARY KEY, task_id TEXT NOT NULL, session_id TEXT NOT NULL,
                decision TEXT NOT NULL CHECK (decision IN ('reviewed', 'rejected')),
                decided_at_utc TEXT NOT NULL, request_fingerprint TEXT,
                report_json TEXT NOT NULL, persisted_at_utc TEXT NOT NULL
            )
        """)
        connection.execute(
            "INSERT INTO review_events VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            ("event-old", "task-old", "session-1", decision, "2026-09-30T00:00:00+00:00",
             "fingerprint-old", json.dumps({"task_id": "task-old", "human_decision": decision}),
             "2026-09-30T00:00:00+00:00"),
        )


def _review_report(decision):
    return {
        "task_id": "task-new", "human_decision": decision,
        "decided_at_utc": "2026-09-30T00:01:00+00:00",
        "public_baseline_written": False,
    }


def test_review_audit_migrates_existing_events_and_records_deferred(tmp_path):
    db_path = tmp_path / "review.sqlite3"
    _create_legacy_review_database(db_path, decision="reviewed")
    repository = SQLiteReviewAudit(db_path)
    event = repository.record(_review_report("deferred"), session_id="session-1")
    rows = repository.list_recent(session_id="session-1")
    assert {row["human_decision"] for row in rows} == {"reviewed", "deferred"}
    assert event["public_baseline_written"] is False
    SQLiteReviewAudit(db_path)  # migration must be idempotent
    assert len(SQLiteReviewAudit(db_path).list_recent(session_id="session-1")) == 2
    with pytest.raises(ValueError):
        repository.record(_review_report("approved"), session_id="session-1")


def test_review_version_selector_defaults_to_manifest_current_version():
    options, default_index = _review_version_selector({
        "baseline_version": "0.51.0", "current_version": "0.52.0",
        "available_versions": ["0.51.0", "0.52.0"],
    })
    assert options == ["0.51.0", "0.52.0"]
    assert options[default_index] == "0.52.0"


def test_analyze_change_request_forwards_explicit_version(monkeypatch):
    from types import SimpleNamespace
    import sys

    captured = {}
    class FakeAgent:
        def __init__(self, _client):
            pass
        def analyze_request(self, summary, **kwargs):
            captured.update(summary=summary, **kwargs)
            return {"request_summary": summary}

    monkeypatch.setitem(sys.modules, "app.public_review", SimpleNamespace(PublicReviewAgent=FakeAgent))
    result = _analyze_change_request(object(), "Update planner", target_version="0.51.0")
    assert result["request_summary"] == "Update planner"
    assert captured["target_version"] == "0.51.0"
```

- [ ] **Step 2: Run the new tests and verify they fail for missing deferred support**

Run: `python -m pytest demo-ui/tests/test_review_audit.py demo-ui/tests/test_public_official_workbench.py -q`.

Expected: FAIL because the SQLite constraint and UI actions currently support only `reviewed` and `rejected`, and the form has no proposal fields.

- [ ] **Step 3: Migrate the append-only audit decision constraint safely**

Add a transactional, idempotent table migration that copies existing events unchanged into a table permitting `reviewed`, `rejected`, and `deferred`. Test migration twice, data preservation, and invalid-decision rejection.

```sql
CREATE TABLE review_events_new (
  event_id TEXT PRIMARY KEY, task_id TEXT NOT NULL, session_id TEXT NOT NULL,
  decision TEXT NOT NULL CHECK (decision IN ('reviewed', 'rejected', 'deferred')),
  decided_at_utc TEXT NOT NULL, request_fingerprint TEXT,
  report_json TEXT NOT NULL, persisted_at_utc TEXT NOT NULL
);
INSERT INTO review_events_new SELECT * FROM review_events;
DROP TABLE review_events;
ALTER TABLE review_events_new RENAME TO review_events;
```

Execute this sequence inside one SQLite transaction and recreate the session/time index before committing.

- [ ] **Step 4: Add a concise optional proposal section and status presentation**

Retitle public workspace copy for Autoware, add an explicit version selector populated from `available_versions` with `current_version` selected by default, and show the corpus's actual language(s), not a fixed Chinese/English claim. Use example questions about indexed Autoware planner/validator material and expose only supported language-filter choices. Add a collapsed “提案补充信息” with optional goal, constraints/compatibility, and validation plan fields. Selecting a historical version is explicit and the Agent's search and generation must use that same version. After analysis show the proposal context and missing-field reminders separately from retrieval evidence gaps, then display evidence-backed impact candidates. Add “暂缓本次审查” beside the existing human decisions; keep no-writeback language visible and retain the JSON export.

Use the tested helper as the only source for selector options and default:

```python
def _review_version_selector(workspace: dict) -> tuple[list[str], int]:
    versions = [str(version) for version in workspace["available_versions"]]
    current = str(workspace["current_version"])
    if not versions or current not in versions:
        raise ValueError("知识空间当前版本不在可检索版本列表中")
    return versions, versions.index(current)


versions, default_index = _review_version_selector(workspace)
target_version = st.selectbox("资料版本", options=versions, index=default_index)
```

The submit callback must forward the collected fields explicitly:

```python
result = _analyze_change_request(
    client, summary, selected_type, impact_scope,
    target_version=target_version,
    objective=objective, constraints=constraints, validation_plan=validation_plan,
)
```

- [ ] **Step 5: Verify Streamlit flow and audit isolation**

Run: `python -m pytest demo-ui/tests/test_review_audit.py demo-ui/tests/test_public_official_workbench.py demo-ui/tests/test_public_ui_profile.py -q`.

Expected: the existing RAG link/citation flow still works, each decision is distinct and persisted, and missing optional fields do not block analysis.

- [ ] **Step 6: Commit only reviewed Task 4 hunks and new files**

```powershell
git add -p demo-ui/public_workbench.py demo-ui/README.md
git add demo-ui/services/review_audit.py demo-ui/tests/test_review_audit.py
git add -p demo-ui/tests/test_public_official_workbench.py
git diff --cached --check
git commit -m "feat: add proposal review lifecycle to workbench"
```

### Task 5: Freeze an Autoware review benchmark and align product documentation

**Files:**
- Create: `evaluation/autoware_change_review_v1/cases.jsonl`
- Create: `evaluation/autoware_change_review_v1/run_evaluation.py`
- Create: `evaluation/autoware_change_review_v1/test_evaluation.py`
- Create: `evaluation/autoware_change_review_v1/README.md`
- Modify: `README.md`
- Modify: `versioned-rag-service/README.md`

**Interfaces:**
- `evaluate_cases(cases: list[dict], search_fn: Callable[[dict, str], list[dict]], plan_fn: Callable[[str], dict], *, policy: str) -> dict` reports query-plan term coverage, document completeness/recall@5, figure recall@5, wrong-version positive hits, no-answer positive-result rate, and observed P95 retrieval latency; it does not call an LLM. `select_policy(dev_reports: dict[str, dict], baseline: str = "bm25") -> str` picks the least complex candidate that passes the frozen DEV gates, otherwise returns BM25. The CLI accepts `--policy bm25|bm25_figure_ocr|bm25_faceted_figure_ocr|all|selected-and-bm25`; `all` evaluates every candidate on DEV and persists the selected policy with its reason, while `selected-and-bm25` runs the frozen selected policy and baseline on HOLDOUT.
- Each case includes a stable `id`, split, request, expected target version, required document keys, optional required figure IDs, required query terms, and an `unanswerable` flag. Required source keys, figure IDs, and versions must resolve against the checked-in corpus/manifest before evaluation.
- `search_fn` uses `PublicKnowledgeIndex.search` for `bm25`, and `PublicRetrievalRuntime.search` for `bm25_figure_ocr` or `bm25_faceted_figure_ocr`; `plan_fn` is `build_request_plan`. Tests use deterministic search fixtures. Candidate order is BM25, BM25 plus reviewed figure OCR, then faceted BM25 plus reviewed figure OCR.

- [ ] **Step 1: Write evaluator tests before the evaluator**

```python
from evaluation.autoware_change_review_v1.run_evaluation import evaluate_cases

cases = [
    {"id": "cross-a", "version": "0.52.0", "request": "planning design config", "required_query_terms": ["planning", "config"], "required_document_keys": ["design", "config"], "unanswerable": False},
    {"id": "single-b", "version": "0.52.0", "request": "validator behavior", "required_query_terms": ["validator"], "required_document_keys": ["validator"], "unanswerable": False},
    {"id": "old-c", "version": "0.51.0", "request": "legacy planner setting", "required_query_terms": ["planner"], "required_document_keys": ["legacy"], "unanswerable": False},
    {"id": "none-d", "version": "0.52.0", "request": "unknown proprietary feature", "required_query_terms": ["proprietary"], "required_document_keys": [], "unanswerable": True},
]
fixture_hits = {
    "cross-a": [{"chunk_id": "a1", "document_key": "design", "version": "0.52.0", "retrieval_score": 1.0}],
    "single-b": [{"chunk_id": "b1", "document_key": "validator", "version": "0.52.0", "retrieval_score": 1.0}],
    "old-c": [{"chunk_id": "c1", "document_key": "legacy", "version": "0.52.0", "retrieval_score": 1.0}],
    "none-d": [{"chunk_id": "d1", "document_key": "validator", "version": "0.52.0", "retrieval_score": 0.2}],
}


def fixture_search(case, policy):
    return fixture_hits[case["id"]]


def fixture_plan(request):
    return {"queries": [{"query": request}]}


def test_evaluator_reports_source_completeness_version_errors_and_unanswerables():
    report = evaluate_cases(cases, fixture_search, fixture_plan, policy="bm25")
    assert report["case_count"] == 4
    assert report["required_source_complete_at_5"] == 1 / 3
    assert report["required_source_recall_at_5"] == 0.5
    assert report["wrong_version_hit_count"] == 1
    assert report["no_answer_result_case_count"] == 1
    assert report["no_answer_result_rate"] == 1.0
    assert report["query_plan_term_coverage"] == 1.0


def test_image_only_case_counts_only_the_required_versioned_figure():
    case = {"id": "image-a", "version": "0.52.0", "request": "planner diagram label",
            "required_query_terms": ["planner"], "required_document_keys": [],
            "required_figure_ids": ["figure-planner-a"], "unanswerable": False}
    def image_search(_case, _policy):
        return [{"chunk_id": "ocr-a", "figure_id": "figure-planner-a", "version": "0.52.0",
                 "document_key": "planning/start_planner", "retrieval_score": 1.0}]
    report = evaluate_cases([case], image_search, fixture_plan, policy="bm25_figure_ocr")
    assert report["figure_source_recall_at_5"] == 1.0


def test_policy_selection_keeps_simplest_strategy_passing_all_dev_gates():
    reports = {
        "bm25": {"required_source_complete_at_5": 0.7, "required_source_recall_at_5": 0.8,
                 "figure_source_recall_at_5": 0.0, "wrong_version_hit_count": 0,
                 "no_answer_result_rate": 0.1},
        "bm25_figure_ocr": {"required_source_complete_at_5": 0.7, "required_source_recall_at_5": 0.8,
                            "figure_source_recall_at_5": 0.5, "wrong_version_hit_count": 0,
                            "no_answer_result_rate": 0.1},
        "bm25_faceted_figure_ocr": {"required_source_complete_at_5": 0.8, "required_source_recall_at_5": 0.9,
                                    "figure_source_recall_at_5": 1.0, "wrong_version_hit_count": 1,
                                    "no_answer_result_rate": 0.1},
    }
    assert select_policy(reports) == "bm25_figure_ocr"
```

- [ ] **Step 2: Run tests and confirm the evaluator contract is absent**

Run: `python -m pytest evaluation/autoware_change_review_v1/test_evaluation.py -q`.

Expected: FAIL because no Autoware frozen benchmark exists.

- [ ] **Step 3: Add a version- and source-pinned benchmark**

Create cases for parameter/config, planning behavior, validator/interface, cross-document change impact, old-version trap, Chinese-to-English glossary retrieval, image-only figure facts, and unanswerable requests. Include Chinese questions tied to a verified OCR figure, for example `修改起步规划器的轨迹校验行为` bound to `planning/start_planner` and one `required_figure_id`. Split by case family into DEV and HOLDOUT before tuning; bind each answerable case to manifest document/figure anchors and expected version. Compute the manifest, case, and split hashes. Implement `evaluate_cases` with deterministic sorting. Query-plan coverage is the fraction of `required_query_terms` found in planned queries; document recall counts a required key only when a positive-score hit has both that key and the expected version; completeness is the fraction of answerable cases with all required documents in the first five hits; figure recall counts required figure IDs only at the expected version; wrong-version counts and no-answer rates consider positive-score hits only. Measure P95 locally but do not treat that value as a hosted latency claim.

```python
import math
import time
from collections.abc import Callable


def evaluate_cases(
    cases: list[dict],
    search_fn: Callable[[dict, str], list[dict]],
    plan_fn: Callable[[str], dict],
    *, policy: str,
) -> dict:
    required_total = 0
    required_found = 0
    complete_cases = 0
    answerable_cases = 0
    wrong_version_hits = 0
    no_answer_result_cases = 0
    unanswerable_cases = 0
    figure_total = 0
    figures_found = 0
    query_terms_total = 0
    query_terms_found = 0
    incomplete_case_ids = []
    latencies_ms = []
    ordered_cases = sorted(cases, key=lambda case: case["id"])
    for case in ordered_cases:
        planned = plan_fn(case["request"])
        planned_text = " ".join(
            str(query.get("search_query") or query.get("query") or "")
            for query in planned.get("queries", [])
        ).casefold()
        terms = case.get("required_query_terms", [])
        query_terms_total += len(terms)
        query_terms_found += sum(term.casefold() in planned_text for term in terms)
        started = time.perf_counter()
        hits = search_fn(case, policy)[:5]
        latencies_ms.append((time.perf_counter() - started) * 1000)
        positive_hits = [
            hit for hit in hits
            if isinstance(hit.get("retrieval_score"), (int, float)) and hit["retrieval_score"] > 0
        ]
        expected_version = case["version"]
        wrong_version_hits += sum(hit.get("version") != expected_version for hit in positive_hits)
        required_keys = set(case.get("required_document_keys", []))
        required_figures = set(case.get("required_figure_ids", []))
        figure_total += len(required_figures)
        figure_hits = {
            hit.get("figure_id") for hit in positive_hits
            if hit.get("version") == expected_version and hit.get("figure_id") in required_figures
        }
        figures_found += len(figure_hits)
        if case.get("unanswerable"):
            unanswerable_cases += 1
            no_answer_result_cases += bool(positive_hits)
            continue
        answerable_cases += 1
        required_total += len(required_keys)
        found_keys = {
            hit.get("document_key") for hit in positive_hits
            if hit.get("version") == expected_version and hit.get("document_key") in required_keys
        }
        required_found += len(found_keys)
        if required_keys <= found_keys:
            complete_cases += 1
        else:
            incomplete_case_ids.append(case["id"])
    latency_order = sorted(latencies_ms)
    p95_index = max(0, math.ceil(0.95 * len(latency_order)) - 1)
    return {
        "policy": policy,
        "case_count": len(ordered_cases),
        "query_plan_term_coverage": query_terms_found / query_terms_total if query_terms_total else 1.0,
        "required_source_complete_at_5": complete_cases / answerable_cases if answerable_cases else 1.0,
        "required_source_recall_at_5": required_found / required_total if required_total else 1.0,
        "figure_source_recall_at_5": figures_found / figure_total if figure_total else 1.0,
        "wrong_version_hit_count": wrong_version_hits,
        "no_answer_result_case_count": no_answer_result_cases,
        "no_answer_result_rate": no_answer_result_cases / unanswerable_cases if unanswerable_cases else 0.0,
        "retrieval_p95_ms": latency_order[p95_index] if latency_order else 0.0,
        "incomplete_case_ids": incomplete_case_ids,
    }
```

- [ ] **Step 4: Compare the retrieval candidates on DEV, select once, and open HOLDOUT once**

Run all three candidates on DEV. A candidate passes only if it has zero wrong-version positive hits, no-answer positive-result rate no worse than BM25, required-source recall/completeness no lower than BM25, and strictly higher figure-source recall than BM25. Pick the first passing candidate in the stated complexity order; if none passes, keep BM25. Persist each DEV report and the selected policy/reason in the evaluation output. Then run the selected policy and BM25 on HOLDOUT exactly once for comparison; do not tune after opening HOLDOUT. Validate evidence membership in the Agent unit tests from Task 3. Do not call the paid LLM. Report offline corpus metrics, not online answer accuracy or hallucination rate.

```powershell
python evaluation/autoware_change_review_v1/run_evaluation.py --split dev --policy all
python evaluation/autoware_change_review_v1/run_evaluation.py --split holdout --policy selected-and-bm25
```

- [ ] **Step 5: Rewrite project descriptions around one Autoware-backed product**

Describe KEP as process inspiration only, cite Autoware source licenses and pinned tags, explain how the same workflow could use a future company-domain public corpus, and state that there is no private company connector, no KEP corpus, and no automatic writeback. Preserve DolphinScheduler historic metrics only as labeled historical evaluation, never as Autoware performance.

- [ ] **Step 6: Run evaluator and docs integrity tests**

Run: `python -m pytest evaluation/autoware_change_review_v1/test_evaluation.py versioned-rag-service/tests/test_autoware_source_sync.py -q`.

Expected: stable hashes and metrics reproduce from checked-in corpus/cases; all claimed corpus results point to the new Autoware report.

- [ ] **Step 7: Commit only Task 5 paths**

```powershell
git add evaluation/autoware_change_review_v1
git add -p README.md versioned-rag-service/README.md
git diff --cached --check
git commit -m "test: benchmark Autoware change review"
```

### Task 6: Full verification, merge to `main`, and public deployment

**Files:**
- Verify: `versioned-rag-service/tests/`
- Verify: `change-review-agent/tests/`
- Verify: `demo-ui/tests/`
- Verify: `evaluation/autoware_change_review_v1/`
- Verify: `render.yaml` and Streamlit app configuration without exposing secrets

- [ ] **Step 1: Run complete component test suites**

Run:

```powershell
python -m pytest versioned-rag-service/tests -q
python -m pytest change-review-agent/tests -q
python -m pytest demo-ui/tests -q
python -m pytest evaluation/autoware_change_review_v1 -q
```

Expected: all pass; record any environment-only skip precisely. Do not call out-of-scope tests “passed” if dependencies or external services are unavailable.

- [ ] **Step 2: Run local RAG + Agent + UI smoke test**

Start the public RAG and Streamlit workbench with generation disabled first. Verify `/health`, `GET /public/workspace`, a current-version Autoware search, an explicit historical-version search, and a natural-language change review that shows only evidence IDs returned by RAG. Verify private-company requests stop before public retrieval and that reviewed/rejected/deferred do not write corpus files. If model generation is configured locally, run one evidence-bound suggestion separately; no secret values in command output.

- [ ] **Step 3: Check only task paths are staged for release**

Inspect the initial diff recorded before implementation, `git status --short`, `git diff --name-only`, and each staged file. Include the verified P1 changes already authorized in this conversation where they overlap or are required for the release; leave unrelated existing changes untouched. Review and stage content hunks (not just paths) in overlapping files. Confirm no unrelated file, secret, local database, cache, `.env`, or generated temporary artifact is staged. Create branch `codex/autoware-kep-review` from the reviewed current `main` state without resetting the dirty working tree; commit only the reviewed change set.

- [ ] **Step 4: Integrate the tested task commits into `main` and push**

Verify `origin/main` immediately before integration; merge/rebase the task branch only if it can be done without dropping the previously reviewed local `main` commits. Ensure a fast-forward or clean merge, resolve no unrelated dirty state by deletion, then push the final commit to GitHub `main`. Do not force-push.

- [ ] **Step 5: Wait for and verify Render RAG deployment**

Confirm the RAG service deployed the pushed `main` commit. Call `/health` and `/public/workspace`; require `workspace=Autoware`, expected baseline/current versions, and ready status. Run a live public search and a live `/public/review-advice` request using IDs from that search. Do not print API credentials.

- [ ] **Step 6: Verify Streamlit public demo**

Open `https://enterprise-rag-agent-suite-bfmkgsimdisxcewgco7ydk.streamlit.app/`, confirm the new Autoware workspace is displayed, perform a live query and a natural-language review, and check the Agent cites the live RAG evidence. If auto-deployment does not update, use the authenticated deployment dashboard only if the connected app remains clearly identifiable; otherwise report the exact manual action needed.

- [ ] **Step 7: Report final commit, public URLs, and observed verification**

Provide the GitHub `main` commit, public Streamlit link, RAG health/workspace verification, test summary, and any remaining hosted-storage/model-service limitation. Do not claim the online change review passed unless it completed with valid RAG citations.

## Source Notes

- The [Autoware Universe repository](https://github.com/autowarefoundation/autoware_universe) publishes its component documentation and identifies an Apache-2.0 license. Its planning documentation includes module roles, interfaces, and configurable parameters; examples include [Planning Validator](https://autowarefoundation.github.io/autoware_universe/main/planning/planning_validator/autoware_planning_validator/) and [Start Planner design](https://github.com/autowarefoundation/autoware_universe/blob/main/planning/behavior_path_planner/autoware_behavior_path_start_planner_module/README.md).
- The official release history lists `0.51.0` and `0.52.0`; source contents, exact tag commit SHAs, and license files still must be verified at implementation time before indexing.

## Self-Review

- The plan covers every spec acceptance item: pinned active Autoware corpus, manifest-driven current version, no KEP indexed, preserved source-bounded Agent, optional proposal context, human review including defer, independent offline evaluation, and verified public release.
- Every planned new module has an interface and a test-first sequence; exact versions are resolved to full commit SHAs before any corpus files are accepted.
- Runtime contracts stay backward compatible; historical Apache artifacts remain unchanged and cannot be presented as Autoware metrics.
- Review focus is assigned: optional/missing fields (Task 3), old-version selection and untrusted source metadata (Tasks 1–2), outage and citation membership (Tasks 3 and 6), review-state persistence migration (Task 4).
- Staging instructions account for authorized pre-existing changes in overlapping files and explicitly protect unrelated dirty/untracked assets.
- No implementation, main push, or hosted deployment is described as already completed; all are gated on the listed tests and live checks.
