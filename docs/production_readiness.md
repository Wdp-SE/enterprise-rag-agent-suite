# Production readiness and public demo verification

## Current public prototype

The active product profile is `edge_ai_device`: a Chinese-only, pinned Seeed Studio Wiki snapshot for reComputer Industrial / Jetson engineering material. The workbench supports public-source retrieval, device/software scope filters, and human-reviewed change-impact candidates. It does not connect to private tickets, BOMs, lab measurements, or approval systems, and it does not write back to upstream sources.

- `/health` and `/public/workspace` expose separate source-corpus, retrieval-configuration, evaluation, and build fingerprints. The public workspace rejects an unexpected corpus/profile/language rather than silently serving it.
- The Streamlit “系统说明” page reports the frontend and RAG revisions separately.
- API responses include `X-Request-ID`; safe diagnostics record route, status, stage, provider/model label and timing without logging raw queries, prompts, response bodies, or credentials.
- Explicit requests for private company test results and approvals are rejected before retrieval or generation. The release smoke verifies this with a fixed no-model-call probe.
- The public workbench is unauthenticated and uses public material. Its session review history is not a durable enterprise audit trail.

## Read-only post-deploy smoke

After both hosted services have deployed the intended GitHub `main` commit, copy the frontend SHA from **系统说明 → 运行版本与资料指纹** and run this command from the repository root:

```powershell
python versioned-rag-service/scripts/public_release_smoke.py `
  --ui-url https://enterprise-rag-agent-suite-bfmkgsimdisxcewgco7ydk.streamlit.app/ `
  --ui-revision <40-character-frontend-sha> `
  --api-url https://version-aware-rag-public-demo.onrender.com `
  --expected-sha <40-character-github-main-sha>
```

The smoke checks UI availability, matching frontend/API/Git revisions, matching source/config/evaluation fingerprints, the `edge_ai_device` Chinese workspace, two public retrieval probes against the current snapshot, and a private-information refusal. It does not call a model for these probes. Reported service timings are remote request timings, not a long-term availability or latency guarantee.

Exit code 0 means those checks passed at that moment. Unknown Git metadata, mismatched revisions, stale evaluation fingerprints, an unexpected corpus, or a failed scope probe must remain a failure; do not describe the site as updated when the check fails.

## Current evaluation evidence and limits

The current BM25 default is selected using a frozen 22-query Chinese retrieval set split by source family into DEV and HOLDOUT. BM25 and faceted RRF produced the same required-source recall and complete-source-set rates on both splits, with no wrong-scope results, so RRF is not enabled by default. One out-of-corpus question in each 11-query split still returned retrieval candidates; candidate retrieval is not a correct answer and this remains an abstention-quality gap.

The 12-scenario change-review set measures deterministic change classification, required-source coverage, scope-gap detection, and the human-review boundary. It does not score final LLM recommendations, impact-candidate precision, answer factuality, or hallucination rate. The data set is small and bounded to the pinned Seeed source collection; it does not establish generalization or production performance. Image references in the corpus are not OCR-indexed.

The detailed current reports and their fingerprints are in [`edge_ai_retrieval_v2`](../evaluation/edge_ai_retrieval_v2/README.md) and [`edge_ai_change_review_v2`](../evaluation/edge_ai_change_review_v2/README.md). Historical evaluation results are indexed in [`evaluation/archive`](../evaluation/archive/README.md) and are not current product metrics.

## Future private deployment work

Before indexing private engineering material, the design still needs authenticated identity and role mapping, tenant isolation, ACL filtering before retrieval, durable and encrypted audit storage, retention/deletion rules, approved model routing and regional policy, abuse/cost limits, operational alerting, and legal/security approval. The public prototype does not implement or claim these controls.
