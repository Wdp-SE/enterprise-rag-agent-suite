# Agent Full Rerun vs Checkpoint Resume

Each scenario used five warm-ups and 30 measured pairs. Checkpoints were created
by a controlled interruption after the stated number of completed sections.
Full rerun and Resume used identical Scope, template, required output, evidence,
and EXTRACTIVE drafting.

| Completed | Sections skipped | RAG calls | Call reduction | P50 ms full → resume | Time reduction | Effect |
|---:|---:|---:|---:|---:|---:|---|
| 25% | 2 | 8 → 6 | 25.000% | 226.684 → 272.024 | -20.001% | REGRESSION |
| 50% | 4 | 8 → 4 | 50.000% | 228.653 → 232.491 | -1.679% | NEUTRAL |
| 75% | 6 | 8 → 2 | 75.000% | 239.520 → 188.267 | 21.398% | MODERATE |

All Resume paths skipped exactly the completed sections and produced the same
semantic drafts as a full rerun. On this small eight-section template, fixed
costs for template parsing, checkpoint restoration, freshness validation, and
full DOCX rendering dominate at 25% and 50% completion. The time result is
therefore a regression at 25%, neutral at 50%, and moderate only at 75%. The RAG
call and section-work reductions remain exact and are the more portable metric.
