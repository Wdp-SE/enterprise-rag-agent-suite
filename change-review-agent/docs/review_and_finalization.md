# Review and finalization

The product implements one reviewer, not an enterprise approval platform.
Each section has PENDING, APPROVED or REJECTED review state and records the
reviewer, timestamp, comment, pre-review draft hash, approved content hash and
field edits.

Draft DOCX is downloadable after workflow execution. `approved.docx` is
created only when every required section is APPROVED and the finalization
guard confirms:

- template identity is unchanged;
- every field is resolved by Evidence or an explicit human edit;
- every referenced Evidence belongs to the SectionTask;
- versioned Evidence is FRESH;
- approved content hashes still match current section drafts.

The workflow never approves itself. A rejected section blocks formal output.
