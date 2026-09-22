# V4 演示脚本

## 启动

打开两个 PowerShell 窗口。在仓库根目录先启动 RAG：

```powershell
cd RAG-Challenge-2-main
$env:RD_V2_PROJECT_ROOT = (Get-Location).Path
$env:RD_V2_ARTIFACT_ROOT = (Resolve-Path 'data\rd_v2_corpus\retrieval_artifacts\rd-v2-retrieval-final-v1.0-safe-integration').Path
$env:RD_V2_ALLOW_EXTERNAL_GENERATION = 'false'
$env:RD_V4_VERSION_STORE_ROOT = (Join-Path $env:TEMP 'rag-agent-v4-demo-store')
.venv\Scripts\python.exe -m uvicorn src.rd_v2_api:app --host 127.0.0.1 --port 8765
```

再启动 UI：

```powershell
cd demo-ui
$env:DEMO_RAG_BASE_URL = 'http://127.0.0.1:8765'
..\OpenManus-rag\.venv\Scripts\python.exe -m streamlit run app.py --server.address 127.0.0.1 --server.port 8502
```

浏览器打开 `http://127.0.0.1:8502`，选择“工程变更审核工作台”。

## 5 分钟演示顺序

1. 说明页面使用 `demo_company_a / PAYMENT` 和完全合成资料，不是多租户系统。
2. 点击“载入变更分析”，展示 REQ-023 的 500→1000、200 MB/s、同步→异步变化。
3. 展示“已确认关系”里的设计/API/测试，再展示单独标记的“疑似影响”运维项。
4. 展开 Evidence，说明 Citation 代表来源可追溯，不自动证明建议正确。
5. 展示 DES-014 的 Before/After，强调只替换指定段落，不重写全文。
6. 先说明未经批准不可应用；选择批准。若选择编辑，需再次确认。
7. 点击应用，展示 Conflict/Validation 状态和 Candidate 文件；重复应用会显示 SKIP。
8. 点击安全发布，展示 Candidate 的结构、Chunk、Embedding、Index、业务完整性校验。
9. 展示 `design-v2` 成为 ACTIVE，`design-v1` 仍可历史查询，原 DOCX 未覆盖。
10. 展示 Workflow Progress、RAG Call 数、每步耗时和失败原因字段。

## 自动化业务 Smoke

在一个干净的 V4 临时版本库上运行：

```powershell
cd demo-ui
$env:DEMO_RAG_BASE_URL = 'http://127.0.0.1:8765'
$env:DEMO_RUNTIME_ROOT = (Join-Path $env:TEMP 'rag-agent-v4-ui-smoke')
..\OpenManus-rag\.venv\Scripts\python.exe scripts\run_v4_business_smoke.py
```

固定评测运行：

```powershell
..\OpenManus-rag\.venv\Scripts\python.exe scripts\run_v4_evaluation.py
```

演示失败时先确认 RAG `/health` 可访问、`RD_V4_VERSION_STORE_ROOT` 已设置，并使用新的空临时目录；不要删除用户本地业务数据。
