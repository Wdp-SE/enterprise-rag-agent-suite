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

## 安装与启动

在本目录执行：

    .venv\Scripts\python.exe -m pip install -r requirements.txt
    copy .env.example .env
    .venv\Scripts\python.exe main.py validate-artifacts
    .venv\Scripts\python.exe main.py serve --host 127.0.0.1 --port 8765

服务地址为 http://127.0.0.1:8765，接口文档为 http://127.0.0.1:8765/docs。

默认 RD_V2_ALLOW_EXTERNAL_GENERATION=false，此时 /retrieve 可用，/query 返回生成被数据策略禁用。只有确认文档允许发送给在线模型后，才配置 DASHSCOPE_API_KEY 并显式开启生成。

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
- data/rd_v2_corpus：本地正式语料与冻结资产，不应提交私有原文。
- data/synthetic_versioned_corpus：可公开的版本生命周期测试数据。
- reports/v3_versioned_e2e_run：版本能力验证证据。

## 验证

    .venv\Scripts\python.exe -m pytest -q
    .venv\Scripts\python.exe scripts\run_v3_versioned_e2e.py
    .venv\Scripts\python.exe scripts\run_rd_v2_offline_runtime_smoke.py
    git diff --check

更多边界见 docs/known_limitations.md。
