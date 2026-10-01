# Autoware multilingual retrieval quality v1

This frozen offline benchmark compares retrieval policies on the current public Autoware snapshot. It is a repeatable engineering selection set, not a claim about production traffic or answer accuracy.

## Scope and question set

The corpus combines official English Autoware Documentation snapshots, a community Chinese translation snapshot whose translation relationships are mostly unverified, and Autoware Universe Planning releases. `latest` means Documentation `main` plus Universe `0.52.0`; it is a composite scope, not one product release. The benchmark contains 82 questions across 24 source families: 51 DEV and 31 HOLDOUT, with each family kept on one side of the split.

The categories are 46 single-fact, 6 cross-source, 7 explicit-version, 7 cross-language, 4 translation-relationship-state, 6 image-evidence, and 6 out-of-scope/no-answer questions. There are 43 carried-over V3 retrieval regressions, 10 bilingual smoke cases, and 29 manually curated source-grounded cases. Twenty-eight questions currently have explicit answer points; the rest assess source retrieval only. This distinction prevents source-hit scores from being presented as answer-quality scores.

Question split and source IDs are frozen in `cases.jsonl` and `split_lock.json`. The case validator checks the exact snapshot IDs, selected component versions, and family separation before it runs a policy.

## Policy selection

BM25 remains the textual retrieval baseline. The selected runtime policy is `bm25_figure_ocr`: it adds only manually reviewed OCR records bound to the exact figure bytes, source document, and commit. It does not replace BM25 with the existing character-hash Dense baseline. The hybrid candidate failed the non-inferiority gates for required-source recall and complete-source rate on both splits. Faceted BM25 did not improve the image objective; faceted BM25 plus OCR passed, but used more retrieval operations than the simpler selected policy.

| Split / policy | Questions | Required-source Recall@5 | Complete sources@5 | MRR@5 | Image evidence | Wrong-version hits | Local search P95 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| DEV / BM25 | 51 | 83.02% | 81.25% | 0.7812 | 0/3 | 0 | 44.861 ms |
| DEV / BM25 + reviewed figure text | 51 | 83.02% | 81.25% | 0.7812 | 2/3 | 0 | 42.978 ms |
| HOLDOUT / BM25 | 31 | 91.43% | 89.29% | 0.7319 | 0/3 | 0 | 46.687 ms |
| HOLDOUT / BM25 + reviewed figure text | 31 | 91.43% | 89.29% | 0.7319 | 2/3 | 0 | 49.893 ms |

The selected policy therefore improves HOLDOUT image evidence from 0/3 to 2/3 while preserving textual source coverage, ranking metrics, and zero wrong-version hits. Its local retrieval P95 is 6.9% above BM25 on HOLDOUT, within the provisional 20% gate. The faceted OCR policy reaches the same coverage but performs 2.129 retrieval operations per query on average, compared with 2 for the selected policy.

All six out-of-scope questions (three per split) still return retrieval candidates under both policies. This is a retrieval-noise signal, not a false answer or hallucination rate; generation must be evaluated separately for evidence sufficiency and abstention. Only two image OCR records are currently approved; 2/3 is the evidence hit rate for three image-focused benchmark questions, not general image-understanding accuracy. The missing image evidence remains an explicit data and review gap.

## Failure analysis

`results/failure_analysis_bm25.json` and `results/failure_analysis_selected.json` classify the frozen run by category, query language, selected component version, relationship state, and expected modality. Under BM25, 18 of 82 cases miss at least one required source/image or include a wrong-version hit; under the selected policy, this falls to 14. The selected-policy failures include 7 cross-language cases (four English queries missing Chinese sources and three Chinese queries missing English sources), four translation-state cases missing a Chinese counterpart, one cross-source case missing the Chinese launch guide, and two image questions missing their expected figure evidence. No wrong-version hit occurred.

This points to two distinct next steps. Cross-language recall needs a new controlled candidate (for example, a small reviewed bilingual terminology map or query-expansion experiment) and a separately frozen comparison; current RRF/character-hash hybrid results do not justify promotion. Image gaps require access to the exact pinned figure bytes and human review before adding OCR records; no guessed image text is indexed. Relationship `candidate` or `unknown` means the system must avoid a drift conclusion even when one side is not retrieved. The relationship registry is a provenance hint, not a substitute for source evidence.

The six no-answer probes returned candidates under both policies. This remains an explicit answerability/abstention evaluation gap. No-answer candidate rate is retained as a noise diagnostic; it is never labelled false-answer rate.

## Metric definitions and limits

- **Required-source Recall@5:** fraction of annotated required documents present in the top five document-level results.
- **Complete sources@5:** fraction of answerable questions with every required source in the top five.
- **MRR@5 / nDCG@5:** document-level ranking metrics; duplicate chunks from one document count only at their best rank.
- **Wrong-version hits:** returned documents whose version conflicts with the question's selected component version. Composite `latest` checks Documentation and Universe against their separate expected versions.
- **Image evidence:** required reviewed `figure_id` values found in the top five. Unreviewed images and general visual content are not counted as recognized evidence.
- **No-answer candidates:** reports whether retrieval returned anything for a no-answer probe. This is not an answer-level false-positive measure.
- **Latency:** local process timing over three calls per question. It excludes HTTP/network time, model generation, cold starts, and hosted service contention.

These results do not establish generated-answer correctness, citation entailment, hallucination rate, or production latency. `evaluate_saved_answers.py` computes answer metrics only when a saved answer and its matching human review are supplied. It checks the exact answer hash and never calls an LLM judge. Since only 28 of the 82 cases currently include required answer points, end-to-end answer evaluation needs more human annotations before it can support broad claims.

## Reproduce

From the repository root, run:

```powershell
python evaluation/autoware_quality_v1/run_benchmark.py --repeats 3 --output evaluation/autoware_quality_v1/results/benchmark.json
python -m pytest evaluation/autoware_quality_v1/test_quality_v1.py evaluation/autoware_quality_v1/test_answer_evaluation.py -q
```

The benchmark is offline and makes no model calls. It selects a candidate only when DEV and HOLDOUT source recall/completeness are non-inferior, version mismatches remain zero, no-answer candidate rate does not worsen, P95 remains within 20%, and HOLDOUT shows an objective gain. Otherwise BM25 remains selected. Any corpus, relation, policy, index, reviewed-image, question, or retrieval-code change invalidates the report fingerprint and requires a new run.
