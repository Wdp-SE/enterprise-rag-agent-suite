# 企业研发文档知识服务

本项目为企业研发文档提供可审计的知识检索与可信问答能力。业务边界固定为研发文档，不包含竞赛问答、候选知识包或其他旁路工作流。

## 正式检索策略

唯一正式检索策略为 DENSE_ONLY + SECTION_PATH：

- 使用冻结且经过哈希校验的分块、向量和 FAISS 索引。
- 查询向量与文档向量均进行归一化，按余弦相似度排序。
- section_path 进入向量表示；上下文扩展只补充同文档、同版本、同章节的锚点与邻近分块。
- 检索范围可按 project_id、document_type、document_id、version_id 过滤。
- 运行时拒绝启用了 BM25、混合融合或重排器的资产策略。

## 正式能力

- ingestion：接收规范化 SectionSnapshot 与经审计的预计算向量。
- document lifecycle：维护文档、版本、章节和活动索引。
- version governance：一个文档只有一个 ACTIVE 版本，历史版本为 SUPERSEDED。
- incremental update：按规范化内容哈希复用未变化章节的向量。
- scope retrieval：在检索计算前限定项目、类型、文档或版本范围。
- version diff：输出章节级 ADDED、REMOVED、MODIFIED、UNCHANGED 差异。
- trusted QA：结构化输出校验、引用成员校验和失败关闭。
- citation：引用仅允许使用本次证据中的 document_id 与 page_number。
- artifact validation：启动前校验状态、哈希、数量、维度和归一化。

## 公开合成 Demo 安装与启动

新克隆仓库在本目录使用 Python 3.12；公开路径加载已跟踪的轻量资产，不需要 `data/rd_v2_corpus/` 内的本机资料或真实 API Key：

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements-render.txt
$env:APP_ENV = 'public_demo'
$env:RD_V2_PROJECT_ROOT = (Get-Location).Path
$env:RD_V2_ARTIFACT_ROOT = (Resolve-Path 'public_demo_artifacts\rd-v2-public-demo-v1').Path
$env:RD_V2_ALLOW_EXTERNAL_GENERATION = 'false'
$env:RD_V4_VERSION_STORE_ROOT = Join-Path $env:TEMP 'rag-agent-public-candidates'
New-Item -ItemType Directory -Path $env:RD_V4_VERSION_STORE_ROOT -Force | Out-Null
.\.venv\Scripts\python.exe main.py validate-artifacts
.\.venv\Scripts\python.exe main.py serve --host 127.0.0.1 --port 8765
```

服务地址为 http://127.0.0.1:8765，接口文档为 http://127.0.0.1:8765/docs。仓库根目录的 `start_prototype.ps1` 可同时启动 RAG 与 Streamlit 工作台。公开资料默认禁用在线生成：`/retrieve` 可用，`/query` 返回生成被数据策略禁用。只有确认资料允许发送给在线模型后，才另行配置密钥并显式开启生成。

`.env.example` 保留为其他本地运行配置示例；其中的 `data/rd_v2_corpus` 路径不属于公开克隆所需资产。

## 文档版本写入

正式写入边界是规范化章节 JSON、原始文件字节和预计算向量映射：

    .venv\Scripts\python.exe main.py ingest-version ^
      --store-root runtime\version_store ^
      --document-id REQ-001 ^
      --project-id project-a ^
      --document-type requirement ^
      --title 需求规格说明 ^
      --version-id REQ-001_2.0 ^
      --version-label 2.0 ^
      --source-file input\requirements.docx ^
      --sections-json input\requirements.sections.json ^
      --embedding-map input\embeddings.json

项目不宣称支持任意格式文档的通用解析。上游必须先完成格式识别、文本规范化和章节切分。

## API

- GET /health：运行时与资产状态。
- GET /artifacts/status：冻结资产与检索策略。
- POST /retrieve：返回原始检索证据。
- POST /query：可信回答、引用和安全 trace。
- GET /documents：文档目录。
- GET /documents/{document_id}/versions：版本目录。
- GET /documents/{document_id}/diff：版本差异。

## 目录

- src：正式运行代码。
- scripts：资产校验、运行时 Smoke、范围基准和版本 E2E。
- tests：正式业务回归测试。
- docs：架构、检索、版本治理和限制。
- public_demo_artifacts/rd-v2-public-demo-v1：仓库已跟踪的合成资料与轻量检索资产。
- data/rd_v2_corpus：本机资料与冻结资产，公开克隆不包含私有原文。
- data/synthetic_versioned_corpus：可公开的版本生命周期测试数据。
- reports/v3_versioned_e2e_run：版本能力验证证据。

## 验证

在本目录运行正式测试和只读公开 Demo Smoke：

```powershell
.\.venv\Scripts\python.exe -m pip install "pytest>=8,<9"
.\.venv\Scripts\python.exe -m pytest tests -q
.\.venv\Scripts\python.exe scripts\public_demo_smoke.py --base-url http://127.0.0.1:8765
git diff --check
```

更完整的本地版本 E2E 与离线运行检查见项目脚本，但可能需要额外的本机资产；公开演示启动不依赖这些资产。更多边界见 [已知限制](docs/known_limitations.md)。
