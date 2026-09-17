# OCR Block Retention Calibration Report

- Raw blocks: 2879
- 0.50-0.60 blocks: 233
- OCR invocation count: 0
- Offline quality gate: PASS
- Corpus v0.2 allowed: True
- Empty reassembled pages: []
- Visually confirmed content-loss pages: []

## Confidence distribution

`{">=0.90": 920, "0.80-0.90": 316, "0.70-0.80": 300, "0.60-0.70": 242, "0.575-0.60": 57, "0.55-0.575": 68, "0.525-0.55": 61, "0.50-0.525": 47, "0.45-0.50": 92, "<0.45": 776}`

## Strategy comparison

- A_GLOBAL_0.60: valid 1/3; noise rejected 3/3
- B_GLOBAL_0.50_COMPARISON_ONLY: valid 3/3; noise rejected 0/3
- C_HYBRID_RECOMMENDED: valid 3/3; noise rejected 3/3

## Selected rule

The selected deterministic rule excludes stable repeated page-margin text and numeric footers, keeps >=0.60 blocks, and conditionally keeps 0.50-0.60 blocks with a generic date, clause/chapter structure, or sufficiently dense Chinese body text. Unknown low-confidence blocks are dropped.

No scenario name, document number, domain phrase, concrete date, OCR rerun, renderer, LLM, Embedding, FAISS, Agent, or Search is part of the core rule.

These are calibration-fixture metrics, not character-level OCR accuracy.

## Fail-closed page completeness check

No visually confirmed content-loss page was recorded.