# Known limitations

- Single reviewer only; no identity system, SSO, RBAC, multi-party approval or
  workflow designer.
- Retrieval Scope is business filtering, not access control.
- DOCX support is intentionally bounded to headings, outline levels, paragraphs,
  simple tables and placeholders. Complex content controls, tracked changes,
  nested tables and arbitrary Word layouts are outside the supported contract.
- Run formatting is preserved for the supported replacement path, but exact
  visual fidelity across every Word feature is not claimed.
- EXTRACTIVE drafting composes Evidence text and does not provide editorial
  fluency equal to an LLM. GENERATIVE requires an explicitly supplied safe or
  local backend.
- Evidence grounding and citation integrity reduce unsupported output but do
  not prove semantic correctness or zero hallucination.
- Filesystem persistence is suitable for a local portfolio/demo deployment;
  production database, distributed locking, HA and QPS are not claimed.
