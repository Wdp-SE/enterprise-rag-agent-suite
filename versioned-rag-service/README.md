# Autoware 版本化研发知识 RAG 服务

公网 Render 服务仍使用 `src.public_server:app` 入口及 `public_corpus_autoware` 固定资产。当前语料包含 Autoware 官方 Documentation 的英文 `main` 和 `1.9.0` 快照、Tomato ROS 社区中文译本，以及 Universe Planning 的 `0.51.0` / `0.52.0` 快照，总计 1,148 条版本/语言来源、660 个资料主题/路径和 7,927 个文本片段。默认 `latest` 是 Documentation `main` + Universe `0.52.0` 的组合范围，不是单一产品发行版。260 页中文译文中 44 页路径匹配到当前官方英文快照；其余 216 页未能核实对应英文版本。服务不会实时追踪上游。扩充后当前策略为 BM25 基线，旧 43 题 V3 指标已与语料指纹解绑，新的双语质量评测尚待完成。KEP 仅启发变更提案/评审流程，不是 RAG 语料或兼容性声明。当前语料、图片审核记录和评测状态见 [语料目录](public_corpus_autoware/README.md)、[来源清单](public_corpus_autoware/corpus_manifest.json)、[图片证据说明](public_corpus_autoware/FIGURE_EVIDENCE.md)和[双语评测说明](../evaluation/autoware_bilingual_v1/README.md)。旧 DolphinScheduler 语料和 V1-V4 指标是历史记录，不代表公网当前结果。

对外职责是版本化资料检索、引用溯源和可选的引用约束生成。下文关于 `DENSE_ONLY + SECTION_PATH` 的说明属于保留的合成企业资料 Runtime 与测试路径，不等同于当前公开语料使用的 BM25 + 审核图片文字策略。

## 当前公开服务

- `GET /public/workspace` 返回固定 Autoware 语料的版本、来源和片段数，以及与当前语料、检索代码、OCR 侧车、配置和冻结问题集指纹匹配的评测状态。
- `POST /public/search` 按版本、语言和问题检索官方片段及少量人工复核图中文字。省略版本时取清单中的 `current_version`；未知版本不会悄悄退回到其他版本。
- `POST /public/query` 返回检索证据，并在后端显式开启且模型服务可用时尝试带引用回答；模型不可用或引用校验失败时保留证据并关闭不可靠的回答。
- `POST /public/review-advice` 基于本次指定的证据片段提供受引用约束的变更审查建议，不能直接修改语料或上游项目。
- `GET /health` 区分生成已关闭、缺少密钥、无效供应商和“已配置但未经实时验证”；它不是对供应商计费余额或下一次请求成功率的保证。

应用不设固定会话生成次数上限，也不自动无限重试。供应商余额、限流、服务故障、网络超时或无效/截断响应仍会导致单次调用失败。生成接口返回不含密钥的请求编号、供应商/模型、结束原因、用量和耗时等安全诊断，便于定位失败；不要把密钥放在 Streamlit Secrets 或日志中。当前两条图片派生证据保留原图 SHA、版本、提交和原始图片 URL，不会在请求时下载图片或调用视觉模型。服务启动时会核对审核 OCR sidecar 和独立的 `figure_evidence_reviewed.lock.json`；只改 OCR 文本但保留原图 SHA 的内容也会导致启动失败。

## 历史 DolphinScheduler 评测

仓库保留了旧 DolphinScheduler 语料的 V1-V4 评测记录，供历史实验复查；它们与当前 Autoware 公网语料、当前检索策略和在线服务指纹无关。当前公开检索结论见 [Autoware 检索评测 V3](../evaluation/autoware_retrieval_v3/README.md)。

---

## 历史合成资料 Runtime（回归测试用）

本项目为企业研发文档提供可审计的知识检索与可信问答能力。业务边界固定为研发文档，不包含竞赛问答、候选知识包或其他旁路工作流。

### 历史检索策略（不用于当前公开服务）

该历史 Runtime 的正式检索策略为 DENSE_ONLY + SECTION_PATH：

- 使用冻结且经过哈希校验的分块、向量和 FAISS 索引。
- 查询向量与文档向量均进行归一化，按余弦相似度排序。
- section_path 进入向量表示；上下文扩展只补充同文档、同版本、同章节的锚点与邻近分块。
- 检索范围可按 project_id、document_type、document_id、version_id 过滤。
- 运行时拒绝启用了 BM25、混合融合或重排器的资产策略。

### 历史 Runtime 保留能力

- ingestion：接收规范化 SectionSnapshot 与经审计的预计算向量。
- document lifecycle：维护文档、版本、章节和活动索引。
- version governance：一个文档只有一个 ACTIVE 版本，历史版本为 SUPERSEDED。
- incremental update：按规范化内容哈希复用未变化章节的向量。
- scope retrieval：在检索计算前限定项目、类型、文档或版本范围。
- version diff：输出章节级 ADDED、REMOVED、MODIFIED、UNCHANGED 差异。
- trusted QA：结构化输出校验、引用成员校验和失败关闭。
- citation：引用仅允许使用本次证据中的 document_id 与 page_number。
- artifact validation：启动前校验状态、哈希、数量、维度和归一化。

### 历史合成 Runtime 本地验证

以下命令仅用于历史合成 Runtime 的本地回归验证，不是当前公网服务的部署步骤。项目 Python 版本说明见根目录 [README](../README.md)：本地 clean-clone 已在 Python 3.11 验证，Render 配置为 Python 3.12.8。此历史路径加载已跟踪的轻量资产，不需要 `data/rd_v2_corpus/` 内的本机资料或真实 API Key：

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

这一节的历史 Runtime 服务地址为 http://127.0.0.1:8765，接口文档为 http://127.0.0.1:8765/docs；`/retrieve` 与 `/query` 是历史合成资料接口，不是上文的 `/public/*` 公开知识接口。仓库根目录的 `start_prototype.ps1` 会启动当前公开 RAG 与 Streamlit 工作台；不加 `-EnableGeneration` 时只提供检索证据。确认公开资料允许发送给在线模型后，再于后端配置密钥并显式开启生成。

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
