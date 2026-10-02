# Edge AI change-review evaluation v2

This offline evaluation checks the deterministic change planner and whether its planned queries retrieve the annotated source documents from the pinned Chinese edge-device corpus. It does not call a paid model API and does not claim that an LLM's final impact recommendations are correct.

The 12 change scenarios are grouped into source families and split before scoring: six DEV and six HOLDOUT. HOLDOUT cases are not for query-template tuning. The runner also reports change-type classification, required-source coverage, expected-scope-gap detection, and the manual-review boundary. Evidence coverage is a proxy for workflow readiness, not impact-candidate precision.

Run from the repository root:

```powershell
python evaluation/edge_ai_change_review_v2/run_evaluation.py --freeze-lock
python evaluation/edge_ai_change_review_v2/run_evaluation.py --split dev --output evaluation/edge_ai_change_review_v2/dev_report.json
python evaluation/edge_ai_change_review_v2/run_evaluation.py --split holdout --output evaluation/edge_ai_change_review_v2/holdout_report.json
```

The lock binds case ids, family splits, corpus/index/config fingerprints, planner/profile/runtime source hashes, and the retrieval evaluation inputs. It cannot be overwritten. To deliberately revise cases or code, create a new evaluation version rather than replacing this baseline.

The report includes per-case traces so misses can be reviewed. Human review is explicitly `not_scored`: a reviewer must judge whether suggested impacted documents are useful, whether recommendations are supported by evidence, and whether the gap is appropriately stated. Planning and retrieval latency are reported as context, not treated as the optimization objective.
