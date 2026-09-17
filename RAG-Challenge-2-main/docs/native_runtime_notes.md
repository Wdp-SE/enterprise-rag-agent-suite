# Windows Native Runtime Notes

## Observed incident

During earlier long embedding/index workflows on Windows, the Python process
could terminate with a native access-violation dialog after substantial work.
The failure occurred below normal Python exception handling when heavyweight
PyTorch and FAISS native runtimes shared lifecycle pressure. The precise upstream
native defect was not proven, so this project records the observed boundary and
the mitigation that was actually validated rather than claiming a universal
root cause.

The engineering sprint also reproduced a separate FAISS 1.9 issue: native
`read_index` could not open an absolute path containing non-ASCII directory
components even though the file existed and its hash was correct.

## Frozen runtime policy

- Torch intra-op threads: 1.
- Torch inter-op threads: 1 where the process permits setting it.
- MKLDNN: disabled.
- `OMP_NUM_THREADS=1` and `MKL_NUM_THREADS=1` in the embedding worker.
- Hugging Face and Transformers: local-files-only/offline.
- Every embedding batch: finite, expected-dimension, and unit-norm checks.
- PyTorch/Transformers: spawned worker process only.
- FAISS: service/index process only.
- `KMP_DUPLICATE_LIB_OK=TRUE`: explicitly rejected, not used as a workaround.

FAISS indexes are loaded by reading bytes through Python's Unicode-safe file API
and calling `faiss.deserialize_index`. This preserves the exact frozen index,
avoids process-wide working-directory changes, and works under a Unicode project
path.

## Long jobs and recovery

Long artifact work must run outside request handlers. The build lifecycle uses
`PENDING`, `BUILDING`, `FAILED`, and `COMPLETE`; records input fingerprints and
checkpoint file hashes; and permits resume only after partial validation. A
failed batch remains `FAILED` and cannot be loaded by the query runtime. Only a
fully validated checkpoint can transition to `COMPLETE`.

The original embedding-enrichment builder already persists batch progress. The
formal `ArtifactBuildLifecycle` supplies the common fail-closed state contract
for future explicit build/rebuild commands. Query startup never starts such a
job and never silently repairs the corpus.

## Operational diagnostics

Use compact error codes and counts. Do not log document bodies, questions,
prompts, credentials, raw model payloads, or irrelevant native-library noise.
If a worker fails, the parent reports a bounded code and can be restarted without
reloading or rebuilding FAISS.

