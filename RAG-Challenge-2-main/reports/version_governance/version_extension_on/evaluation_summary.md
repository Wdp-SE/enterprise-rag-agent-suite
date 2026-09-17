# Domain Evaluation v0.2

## Corpus

- Frozen source documents: 8
- Default indexed documents: 5
- Source PDF pages: 318
- Indexed pages: 182
- Indexed chunks: 319

## Dataset

- Questions: 8
- version_temporal: 8

## Retrieval

- Hit@1: 1.0
- Hit@3: 1.0
- Hit@5: 1.0
- Recall@1: 0.875
- Recall@3: 0.9375
- Recall@5: 1.0
- MRR: 1.0

## Citation

- Evaluation mode: retrieval_evidence_citation_potential
- Document Citation Accuracy: 0.9
- Page Citation Accuracy: 0.25

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
