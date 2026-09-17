# R&D V2 Demo Guide

## Data boundary first

Do not place the real R&D corpus, normalized PDFs, chunks, screenshots, query
text, or generated answers in GitHub or a public demo. The local corpus and its
reports are Git-ignored. Use only public, simulated, or explicitly approved
documents for a shareable answer-generation demonstration.

The commands below validate the private frozen runtime locally. External
generation remains disabled by default.

## One-time formalization and verification

From the repository root:

```powershell
.venv\Scripts\python.exe scripts\build_rd_v2_final_artifact_manifest.py verify
.venv\Scripts\python.exe scripts\run_rd_v2_offline_runtime_smoke.py
```

If the formal metadata namespace has not yet been created, use the explicit
metadata-only build once:

```powershell
.venv\Scripts\python.exe scripts\build_rd_v2_final_artifact_manifest.py build
```

This command binds existing frozen files by hash. It does not parse, chunk,
embed, build FAISS, evaluate HOLDOUT, or call an online model. It refuses to
overwrite a completed namespace. `--resume` is only for a validated failed or
interrupted metadata build.

## Start the API

The embedding snapshot is discovered from the standard Hugging Face cache at
the exact frozen revision. It can instead be set explicitly:

```powershell
$env:RD_V2_EMBEDDING_MODEL_SNAPSHOT = 'C:\path\to\the\frozen\snapshot'
.venv\Scripts\python.exe -m uvicorn src.rd_v2_api:app --host 127.0.0.1 --port 8000
```

Check the service and artifact contract:

```powershell
Invoke-RestMethod http://127.0.0.1:8000/health
Invoke-RestMethod http://127.0.0.1:8000/artifacts/status
```

Run an offline retrieval request:

```powershell
$payload = @{ question = '本地演示问题' } | ConvertTo-Json
Invoke-RestMethod -Method Post -Uri http://127.0.0.1:8000/query `
  -ContentType 'application/json' -Body $payload
```

With the private corpus and default data policy, the expected answer is `N/A`,
sources are empty, and status is `GENERATION_DISABLED_BY_DATA_POLICY`; the safe
trace demonstrates frozen Dense retrieval without exposing document text.

## Answer-generation demo

Do not enable external generation for the private artifact namespace unless the
data owner has explicitly authorized transmission to that provider. For an
interview/public demo, build a separate public or simulated corpus namespace and
point `RD_V2_ARTIFACT_ROOT` at it. Provider/model and its secret must then be set
through environment variables; never edit keys into source, manifests, reports,
or shell transcripts.

The current sprint deliberately did not perform an online end-to-end smoke on
the private R&D corpus because no external-transmission authorization was
provided.

