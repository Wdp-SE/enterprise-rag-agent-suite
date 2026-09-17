# Domain Evaluation v0.2

## Corpus

- Frozen source documents: 8
- Default indexed documents: 5
- Source PDF pages: 318
- Indexed pages: 182
- Indexed chunks: 319

## Dataset

- Questions: 34
- cross_document: 7
- single_document: 15
- unanswerable: 7
- version_temporal: 5

## Retrieval

- Hit@1: 0.925926
- Hit@3: 0.962963
- Hit@5: 1.0
- Recall@1: 0.796296
- Recall@3: 0.851852
- Recall@5: 0.944444
- MRR: 0.953704

## Citation

- Evaluation mode: retrieval_evidence_citation_potential
- Document Citation Accuracy: 0.807407
- Page Citation Accuracy: 0.259259

## Answer

- Status: NOT_RUN
- Answerable Accuracy: None
- Unanswerable Refusal Rate: None
- Key Point Coverage: None

## Failure distribution

- No classified failures

## Run notes

- No confidence threshold or reject policy was selected.
- Citation metrics in this run measure whether retrieved evidence pages hit ground truth; they are not generated-answer citation semantics.
- Documents marked OCR_REQUIRED were retained in the frozen corpus but excluded from the default index.
- Version governance used deterministic manifest eligibility and traceable pre-rerank adjustments.
