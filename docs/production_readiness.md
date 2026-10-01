# Production readiness and public demo verification

## Implemented for the public demo

- The public RAG service reports a verified Git revision only when Git metadata is present and the deployed checkout is clean. Otherwise it reports `unknown`.
- `/health` and `/public/workspace` expose separate SHA-256 fingerprints for the public corpus, active retrieval configuration, and frozen evaluation inputs. They return hashes only, never corpus contents.
- The Streamlit “系统说明” page shows the frontend SHA separately from the RAG backend SHA and the three fingerprints.
- Each API response carries `X-Request-ID`. Generation diagnostics use the same ID. Logs include a route template, status, safe stage, hit count when available, elapsed time, provider/model labels, and exception type; they do not include raw queries, full prompts, response bodies, or credentials.
- Explicit requests for private company Jira/approval information are returned as `OUT_OF_SCOPE` before retrieval and generation. The release smoke checks this with a read-only query that cannot trigger a model call.
- The public workbench remains an unauthenticated demonstration against public materials. Request IDs and local/session review records are not a durable enterprise audit system.

## Read-only post-deploy smoke

After the changes are merged and both hosted services have deployed, copy the full frontend SHA from **系统说明 → 运行版本与资料指纹** and the intended GitHub `main` SHA. Run from the repository root:

```powershell
python versioned-rag-service/scripts/public_release_smoke.py `
  --ui-url https://enterprise-rag-agent-suite-bfmkgsimdisxcewgco7ydk.streamlit.app/ `
  --ui-revision <40-character-frontend-sha> `
  --api-url https://version-aware-rag-public-demo.onrender.com `
  --expected-sha <40-character-github-main-sha>
```

The command confirms the Streamlit page responds, the copied frontend revision and API revision match the expected commit, `/health` and `/public/workspace` agree on asset fingerprints, Chinese and English public queries return evidence, explicit `0.52.0` results contain no other version, and the internal Jira probe is refused before generation. It reports hosted request timings as **remote latency**. It does not call an LLM for smoke tests and does not scrape rendered Streamlit state from HTML.

Exit code 0 means those checks passed for the instant they ran; it is not a long-running availability guarantee. If the app has no Git metadata, an unknown revision, different UI/API commits, or a stale hosted deploy, the command fails closed. Do not relabel a failed or unknown check as current.

## Current performance evidence and limits

Current retrieval policy is `bm25_figure_ocr`, selected by [Autoware retrieval quality V1](../evaluation/autoware_quality_v1/README.md). On the fixed local corpus, HOLDOUT required-source Recall@5 and complete-source rate remain unchanged from BM25; image-focused evidence is 2/3 versus 0/3; wrong-version hits are zero; warm retrieval P95 is approximately 6.9% above BM25 and below the provisional 20% gate. The suite contains 82 manually curated queries (DEV 51 / HOLDOUT 31) grouped by source family.

These values are offline retrieval metrics, not answer correctness, hallucination rate, real-user generalization, or hosted latency. Only two image OCR records have been reviewed. The Agent planning set has 28 fixed Chinese/English cases and met its rule-contract assertions; its HOLDOUT was inspected during the current fix and is not an unbiased validation set. See [its evaluation notes](../evaluation/autoware_agent_query_planning_v1/README.md).

## Future private deployment work

Before sending private engineering documents to this design, production work remains: authenticated identity and role mapping, tenant isolation, ACL filtering before retrieval, encrypted and durable audit storage, retention/deletion rules, approved model routing and regional policy, abuse/cost limits, operational alerting, and legal/security approval. The public demo does not implement or claim these controls.
