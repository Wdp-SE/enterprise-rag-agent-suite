# Candidate Knowledge Zone

Only packages accepted by `src.candidate_knowledge.import_candidate()` belong here.
Hash-aware Candidate Contract v2 is recommended; legacy v1 packages remain
supported through the normalization boundary.
An imported package remains `CANDIDATE` until a human explicitly calls
`approve_candidate(candidate_id)`. Approval changes metadata to `APPROVED` but
does not run Embedding, write FAISS, or publish the document to the formal
knowledge base.
