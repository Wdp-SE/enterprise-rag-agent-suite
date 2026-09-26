# Architecture

## Dependency direction

```text
Streamlit / CLI
  → DocumentWorkflowFacade
      → DocumentWorkflow runner
      → ReviewService / Finalization Guard
      → WorkflowRepository
          → TemplateParser / TemplateRenderer
          → SectionTaskPlanner / QueryPlanner
          → EvidenceSufficiencyService / FieldDraftingService
          → RAGTool / HTTPRetrieveClient
          → CheckpointStore / EvidenceStore
```

The UI imports only `DocumentWorkflowFacade`. Domain models have no Streamlit,
HTTP, FAISS or concrete LLM SDK dependency. Retrieval calls only the external
`POST /retrieve` and `GET /documents` contracts. Drafting has an injectable
generative protocol, while the safe default is deterministic extractive
composition. Filesystem persistence is isolated by `WorkflowRepository`,
`CheckpointStore` and `EvidenceStore`.

`WorkflowScope` is immutable once a workflow is created. Its canonical SHA256
fingerprint is stored in the checkpoint and trace. Resume rejects a caller-
supplied scope that differs from the saved scope.
