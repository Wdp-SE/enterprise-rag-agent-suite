# Four interview stories

## 1. From Knowledge Research to Document Workflow

The old Agent could search, acquire sources, and assemble candidate packages, but a template-driven R&D plan needed a narrower deliverable: fill fixed Word sections with traceable facts and leave unsupported fields visibly missing. I preserved the research code and added a separate Document Workflow policy that allows template read, RAG query, and draft write while denying browser/search in this business flow. The result is a reviewable DOCX rather than an open-ended research answer.

## 2. Fixed workflow with local decisions

The template supplies a stable section list and the deliverable needs uniform checks. I kept section order, budgets, and finalization deterministic. Within a section, QueryPlanner tries a few bounded variants and NoProgressDetector observes Evidence growth. This makes an interruption and a missing field explicit state, rather than an opaque Agent transcript. The safe E2E completed four cited fields and marked throughput MISSING instead of fabricating capacity data.

## 3. Why raw `/retrieve` at the boundary

If RAG generated an answer and the Agent generated the document again, source provenance and the boundary between retrieval and drafting would be harder to verify. The frozen RAG service exposes chunk ID, document/section path, page, text, hash, rank, and score through `/retrieve` without generation. The Agent caches those chunks as stable Evidence IDs and cites only IDs present in its cache. RAG remains DENSE_ONLY + SECTION_PATH and the Agent does not open FAISS.

## 4. Checkpoint/resume plus fail-closed finalization

The prototype lost section progress on process exit and considered DOCX saving sufficient. I introduced an atomic, versioned WorkflowState checkpoint with section drafts and EvidenceCache snapshot. Resume verifies template/config compatibility and references, then skips COMPLETE sections. In a recovery smoke I interrupted after three completed sections, resumed the remaining work, and preserved the original cited IDs. Before rendering, OutputIntegrityValidator compares required sections, missing status, Evidence citations, template hash, and human review. A fabricated `E999` ID blocks finalization. The selected regressions passed, while real enterprise outage/load behavior remains a known limit.
