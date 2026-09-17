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

- Hit@1: 0.851852
- Hit@3: 0.888889
- Hit@5: 0.925926
- Recall@1: 0.722222
- Recall@3: 0.759259
- Recall@5: 0.851852
- MRR: 0.87963

## Citation

- Evaluation mode: retrieval_evidence_citation_potential
- Document Citation Accuracy: 0.725926
- Page Citation Accuracy: 0.237037

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
