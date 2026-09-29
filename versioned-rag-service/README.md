# Apache DolphinScheduler 版本化研发知识 RAG 服务

公网 Demo 使用 `src.public_server:app` 入口和固定提交的 Apache DolphinScheduler 3.4.2 / 3.4.3 官方资料快照。当前语料为 132 份来源、1322 个检索片段，语料清单声明 3.4.3 为当前默认版本；服务不会自动追踪上游发布。当前默认 BM25 已通过 V4 文字检索 HOLDOUT 基线核验；经审核的截图 OCR 有 30 条派生证据，但合并排序候选因原文锚点召回下降 9.4 个百分点而未晋级，线上继续使用 BM25。V1/V2/V3 结果分别按旧语料或旧评测快照解读。来源、许可证与评测见仓库根目录 [README](../README.md)、[语料清单](public_corpus/corpus_manifest.json)、[V2 历史报告](../evaluation/real_world_retrieval/quality_v2/report.md)、[V3 评测](../evaluation/real_world_retrieval/quality_v3/README.md)和 [V4 评测](../evaluation/real_world_retrieval/quality_v4/README.md)。

本服务由仓库根目录的 `render.yaml` 部署；对外职责是版本化资料检索、引用溯源和可选的引用约束生成。下文关于 `DENSE_ONLY + SECTION_PATH` 的说明属于保留的历史企业合成资料 Runtime 与测试路径，不等同于当前公开语料使用的 BM25 策略。

## 当前公开服务

- `GET /public/workspace` 返回固定语料清单的版本、来源和片段数，以及运行默认策略和扩充语料的评测状态。
- `POST /public/search` 按版本、语言和问题检索官方片段。省略版本时取清单中的 `current_version`；未知版本不会悄悄退回到 3.4.3。
- `POST /public/query` 返回检索证据，并在后端显式开启且模型服务可用时尝试带引用回答；模型不可用或引用校验失败时保留证据并关闭不可靠的回答。
- `POST /public/review-advice` 基于本次指定的证据片段提供受引用约束的变更审查建议，不能直接修改语料或上游项目。
- `GET /health` 区分生成已关闭、缺少密钥、无效供应商和“已配置但未经实时验证”；它不是对供应商计费余额或下一次请求成功率的保证。

应用不设固定会话生成次数上限，也不自动无限重试。供应商余额、限流、服务故障、网络超时或无效/截断响应仍会导致单次调用失败。生成接口返回不含密钥的请求编号、供应商/模型、结束原因、用量和耗时等安全诊断，便于定位失败；不要把密钥放在 Streamlit Secrets 或日志中。固定来源截图 OCR 已在离线候选中审核并纳入独立检索实验；由于直接融合挤压了原文锚点召回，当前公共服务默认 BM25 不使用图片候选。OCR 证据保留原图 SHA、版本、提交和原始图片 URL，不会在请求时下载图片或调用视觉/付费模型。服务启动时还会把整份审核 OCR sidecar 与独立的 `figure_evidence_reviewed.lock.json` 摘要逐字节核对；只改 OCR 文本但保留图片 SHA 的内容也会导致启动失败。

扩充语料的 V3 评测冻结了 72 道新业务题，按场景家族分成 DEV/HOLDOUT 各 36 道。DEV 比较后锁定 BM25；一次性 HOLDOUT 的 32 道可回答题中，27 道找齐全部必需来源，8 道多来源题仅 4 道找齐，返回片段找到 37/49 个证据锚点。检索指标区分“至少命中一份来源”“所需来源完整覆盖”及“返回片段含有证据锚点”，不把来源命中率当作答案准确率或幻觉率。评测 runner、锁文件和结果见 [V3 目录](../evaluation/real_world_retrieval/quality_v3/README.md)；可从仓库根目录用只读测试核对冻结输入与已保存结果的哈希：

```powershell
python -m unittest discover -s evaluation/real_world_retrieval/quality_v3 -p test_quality_v3.py
```

不要在当前冻结目录重跑 `run_quality_v3.py --split dev`：它会覆盖已锁定的 DEV 结果文件并改变其哈希。重新实验请使用独立工作树或新评测版本、独立输出路径。V3 的 HOLDOUT 已开封并留有一次性执行锁，不能反复运行并据结果调参。当前运行默认策略仍为 BM25，具体冻结结论与失败题见 [V3 报告](../evaluation/real_world_retrieval/quality_v3/report.md)。

V4 继续在同一 132 份来源、1322 个文字片段上评测跨资料、跨版本、截图 OCR、图文联合和无答案问题，共 104 条并按资料/题族隔离 DEV 与 HOLDOUT。OCR 候选图片 Hit@5 为 100%，但原文锚点召回比同题集 BM25 低 9.4 个百分点，超过 5 个百分点的退化上限，因此候选未晋级。线上仍为 BM25，工作台公开 V4 BM25 当前基线和候选未晋级原因。V4 的 nDCG 实现会重复计入同一来源的多个片段，报告已将其排除；详细数字、失败门槛和下一轮方向见 [V4 报告](../evaluation/real_world_retrieval/quality_v4/report.md)。

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
