# Final Retrieval Selection

The selected policy is the existing **BM25 + chunk A + Top-5, without a document cap**. No deployed retrieval file or original Apache source was changed. The experiment is reproducible from [experiment_config.json](experiment_config.json), [frozen_split.json](frozen_split.json), [selection_lock.json](selection_lock.json), [results.json](results.json), and [failure_analysis.json](failure_analysis.json).

## 1. What was compared

The 46 question texts are unchanged from the existing query set. Before this experiment was frozen, a prior audit corrected the cross-document source mapping: ds-034 no longer carries an incorrectly assigned second source, and the intended second-source assignments align with ds-035 through ds-038. Each corrected heading and literal evidence marker was verified in its cited pinned-corpus section. The corrected query and ground-truth files are frozen at the SHA-256 values below; the runner rejects input bytes that do not match those hashes. The labels were not changed during the comparison stages. Their SHA-256 values are `a32fbae207371997cb751c1c1554c7eb04989fb6072050ba84284a56f4db0b21` and `9c5415fa7aaf8d247dc4bb679ca54c8df308f2f4e98b04eaa736a82e6645e323`. A deterministic within-category ID hash split reserved 23 queries for DEV and 23 for HOLDOUT. Only DEV selected the chunk, retriever, hybrid weight, Top-K and diversity policy; the locked BM25 decision was evaluated on HOLDOUT once. Four cross-document questions and three no-answer questions are reported separately.

All comparisons used the same pinned 52-source corpus, each query's version filter, and all languages. A relevant hit must contain the **frozen literal evidence marker**, as well as matching document, version, locale and heading. This prevents a different fragment under the right heading from being scored as evidence. Duplicate chunks from one relevant source add no extra nDCG gain. Hit@K, MRR and nDCG use answerable questions only. Timings are warm local in-process retrieval, including E5 query inference but excluding model load, corpus/index build, HTTP and answer generation.

## 2. Chunking conclusion

BM25 and Top-5 were fixed for this DEV-only comparison. The index-size column is the UTF-8 chunk JSON size; B and C were constructed in memory and never replaced the deployed index.

| Chunk | Max content chars | Overlap | Title in search text | Heading | Chunks | Chunk JSON bytes | DEV Hit@1 | Hit@3 | Hit@5 | MRR | nDCG@5 | Dual-source@5 | P50/P95 ms |
| --- | ---: | ---: | --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| A: current | 1250 | 0 | No; document key present | Yes | 659 | 852,544 | .3636 | .6818 | .8182 | .5295 | .6013 | 0/2 | .85/1.28 |
| B: finer | 650 | 0 | No; document key present | Yes | 1,028 | 1,039,023 | .3636 | .6364 | .6818 | .4886 | .5374 | 0/2 | 1.00/3.43 |
| C: section-aware | 900 | 100 within heading | Yes | Yes | 890 | 1,628,590 | .3636 | .5909 | .7273 | .5015 | .5510 | 0/2 | .97/2.27 |

**A wins:** it has the highest DEV Hit@5/MRR with fewer chunks and the smallest chunk index. Its offline BM25 Top-5 rankings matched the deployed index on every DEV query. All 47 frozen source markers remained present in A/B/C, so B/C were not penalized by lost source text.

## 3. Retriever conclusion and unified comparison

The neural run used real CPU inference with `intfloat/multilingual-e5-small` pinned to revision `ada7b62be30f82b0bc5da131b0477721c8fc14e9`: `query:`/`passage:` prefixes, 512-token truncation, masked mean pooling and normalized 384-dimensional vectors. Hybrid used weighted RRF (50 candidates per branch, rank constant 60); the weight shown is BM25's share. Only chunk A was used. Unanswerable rejection is retrieval-level zero-candidate rejection; the system returned five candidates for the DEV no-answer query. Retriever-only strategy rows do not score generated answers; the separate three-probe generation check is reported below.

| Cohort | Strategy | Chunk | Hit@1 | Hit@3 | Hit@5 | MRR | nDCG@5 | Dual-source@5 | No-answer rejection | P50/P95 ms |
| --- | --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| DEV: 22 answerable | BM25 | A | .3636 | .6818 | .8182 | .5295 | .6013 | 0/2 | 0/1 | .83/1.36 |
| DEV: 22 answerable | Neural Dense E5 | A | .2727 | .5909 | .7273 | .4508 | .5115 | 0/2 | 0/1 | 17.90/21.94 |
| DEV: 22 answerable | Hybrid, BM25 .25 | A | .3182 | .6818 | .7273 | .4962 | .5465 | 0/2 | 0/1 | 22.51/25.27 |
| DEV: 22 answerable | Hybrid, BM25 .50 | A | .3182 | .7727 | .7727 | .5227 | .5760 | 0/2 | 0/1 | 20.56/25.45 |
| DEV: 22 answerable | Hybrid, BM25 .75 | A | .3636 | .7727 | .8182 | .5470 | .6087 | 0/2 | 0/1 | 19.53/22.31 |
| HOLDOUT: 21 answerable | **Locked BM25** | **A** | **.4286** | **.7143** | **.7619** | **.5833** | **.6177** | **0/2** | **0/2** | **.98/1.55** |

Hybrid .75 ties BM25 on DEV Hit@1 and Hit@5 and raises MRR by only .0175. It also requires about 471 MB of model weights, a 1.01 MB embedding matrix, and 168.66 seconds to load/build the 659-passage E5 index in this CPU run, while DEV P95 rises from about 1.4 to 22.3 ms. E5 alone is lower on the main DEV quality measures. This is not a stable, deployment-worthy gain. HOLDOUT was **not** used to retune or compare rejected alternatives.

## 4. Top-K conclusion

Only the leading BM25 retriever was tested at K=3/5/8 on DEV. Hit@returned-K was 15/22, **18/22**, and 18/22 respectively; complete cross-document coverage remained 0/2 at all three values. K=3 loses three answerable queries, while K=8 adds candidates without recovering another answerable query or required second source. **Keep Top-5.** This implementation has no separate candidate-pool/final-K stage, so the optional 10→5 pool trial did not apply.

## 5. Cross-document conclusion

Final locked BM25 still retrieves **both required sources in Top-5 for 0/4**. All eight labeled source sections and markers exist in the index and are eligible after version filtering; no scope/filter excluded them. Exact marker-bearing chunk ranks are:

| Query | Cohort | Source A rank | Source B rank | Same-document crowding in Top-5 | Main failure |
| --- | --- | ---: | ---: | --- | --- |
| ds-035 | HOLDOUT | 344 | 298 | Yes | Both source fragments rank far below five. |
| ds-036 | HOLDOUT | 2 | 47 | Yes | One source reaches Top-5; second is beyond it. |
| ds-037 | DEV | 10 | 82 | No | Both relevant fragments miss Top-5 despite top-ranked related documents. |
| ds-038 | DEV | 71 | 40 | Yes | Related documents appear, but labeled fragments rank much lower. |

The single DEV diversity trial (`max_chunks_per_document=2`) **did not recover a dual-source query** and lowered Hit@5 from .8182 to .7273 and MRR from .5295 to .5030. It was rejected. Crowding exists for three questions, but it is not the sole cause: one question has no crowding, and several required fragments rank 40–344. A simple cap or K=8 cannot solve this without harming broader retrieval.

## 6. No-answer conclusion

The retriever has no zero-candidate abstention on these three frozen no-answer probes: retrieval-level rejection **0/3** (DEV 0/1, HOLDOUT 0/2), with 15 returned evidence candidates. A separate, budget-limited live check sent each original probe once through the existing public query generation path. All three returned HTTP 200 with ABSTAINED, zero citations, and five retrieval candidates: **observed generation abstention 3/3; observed false generated answers 0/3**. No answer text or secret was stored. This is one model run, not a calibrated reliability estimate; candidates must still be presented as material to verify, not proof of an answer.

## 7. Latency and complexity

Locked BM25 HOLDOUT P50/P95 is **.98/1.55 ms** in this warm local process. Neural Dense DEV P95 is 21.94 ms; the best hybrid weight's DEV P95 is 22.31 ms. Runs are small and hardware-sensitive; they are not HTTP, cold-start or public-cloud latency promises. The current prebuilt 512-dimensional lexical-hash vector file is an existing 1.35 MB artifact even though BM25 is selected. E5 weights remained only in the OS temporary cache and were not added to the repository or public deployment.

## 8. Final Retrieval Policy

Keep the existing deployed configuration: **current chunk A (1250 chars, heading/paragraph, zero overlap), BM25, version scope applied before ranking, Top-5, no document cap, no neural model, no Hybrid, no Rerank**. The experiment makes **no production policy change**, so a new browser smoke is not required by this experiment's test rule.

## 9. Why this policy

It has the strongest practical DEV quality/size/latency balance, and the locked HOLDOUT confirms useful single-source retrieval without encouraging a parameter change. A small Hybrid MRR gain does not compensate for model weight, index-build and latency costs, and neither alternative fixes the two-source challenge. The preference for the simpler strategy was decided before opening HOLDOUT.

## 10. Remaining limits and freeze decision

The split is a **retrospective, query-level** holdout: earlier project reports evaluated all 46 questions, and near-duplicate source topics can occur across DEV/HOLDOUT. The 21 answerable HOLDOUT questions and category subsets are too small for broad accuracy claims. Confusable/HARD and cross-document questions remain weak; a reranker could later be tested for cases already in the candidate set (HOLDOUT Hit@5 .7619 versus Hit@1 .4286), but cannot retrieve a required source absent from its input pool. Do not implement one in this round. Freeze retrieval after the focused regression/integrity checks; retain these limitations in public and interview claims.

HOLDOUT category breakdown (answerable questions only; `hard` is the existing confusable-question group):

| Group | n | Hit@1 | Hit@5 | MRR |
| --- | ---: | ---: | ---: | ---: |
| Chinese | 5 | .6000 | 1.0000 | .8000 |
| English | 3 | .3333 | .6667 | .4167 |
| Mixed | 3 | .3333 | 1.0000 | .6667 |
| Exact-term | 3 | 1.0000 | 1.0000 | 1.0000 |
| Version | 3 | .3333 | .6667 | .5000 |
| Cross-document | 2 | .0000 | .5000 | .2500 |
| Confusable (`hard`) | 2 | .0000 | .0000 | .0000 |

Final verification: RAG 68 passed; Agent 107 passed; UI 58 passed; retrieval/evaluation 12 passed; 162 Python files compiled; key imports and both environments' pip check passed. The 52/52 source hashes, three frozen-input hashes, manifest hash and two prebuilt-index hashes match. Secret scan: 413 text files, 0 findings after excluding substring matches inside ordinary upstream words; tracked git diff --check and whitespace checks on 18 new text files passed. Because the production retrieval policy did not change, no additional browser smoke was run. No commit, push or merge was made by this experiment.
