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

- Hit@1: 0.75
- Hit@3: 0.75
- Hit@5: 0.75
- Recall@1: 0.625
- Recall@3: 0.625
- Recall@5: 0.625
- MRR: 0.75

## Citation

- Evaluation mode: retrieval_evidence_citation_potential
- Document Citation Accuracy: 0.55
- Page Citation Accuracy: 0.15

## Answer

- Status: NOT_RUN
- Answerable Accuracy: None
- Unanswerable Refusal Rate: None
- Key Point Coverage: None

## Failure distribution

- VERSION_AMBIGUITY: 2

## Run notes

- No confidence threshold or reject policy was selected.
- Citation metrics in this run measure whether retrieved evidence pages hit ground truth; they are not generated-answer citation semantics.
- Documents marked OCR_REQUIRED were retained in the frozen corpus but excluded from the default index.
- Version governance was disabled; historical assets were not loaded.
