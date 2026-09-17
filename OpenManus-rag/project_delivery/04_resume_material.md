# 简历材料

## 1. 项目名称

**Reliable OpenManus Agent — 公开资料调研、证据构建与可靠任务执行扩展**

## 2. 一句话描述

基于 OpenManus 构建配置驱动的 Knowledge Research Workflow，将 Search/Browser 原生能力组织为 Raw Source、Evidence、ResearchResult 与多输出适配链，并补充可组合的错误、重试、超时、预算、进度、轨迹和任务策略组件。

## 3. 简历精简版（三条）

- 在不修改 OpenManus BaseAgent/ReAct/ToolCall 核心语义的前提下，设计阶段式公开资料调研 Workflow，实现结构化搜索、来源分级、HTML/文本 PDF 归档与 Evidence-first 研究结果生成。
- 构建稳定 ID、双 SHA256、引用校验、原子发布和 RAG Candidate Adapter；真实任务形成 22 条可追溯 Evidence，CandidateValidator 与外部 RAG `import_candidate()` 均通过，且未执行正式 ingestion。
- 实现操作级 Error/Retry/Timeout、BudgetLedger、NoProgress、Structured Trace 与 TaskPolicy 组件；完成 Windows Docker SDK 兼容修复，最终全项目 `361 passed`。

## 4. 简历标准版（四条）

- 审计 OpenManus Agent/Tool/Sandbox 调用链，采用独立入口和组合式架构新增 `DISCOVER → SELECT → ACQUIRE → EXTRACT → BUILD_RESULT → OUTPUT` Workflow，保持原 Agent Core 可逆、可回归。
- 设计通用 `ResearchProfile`、`Evidence`、`SourcePolicy`、`EvidenceStore` 和 `RawSourceArchive`；分离 Evidence `content_hash` 与原始文件 `raw_file_hash`，实现稳定 Evidence/Candidate/Document/Sxx ID 和路径安全校验。
- 通过 Markdown、JSON、Candidate Package 三种 Adapter 解耦研究结果与 RAG；真实调研获得 7 个搜索候选、3 个入选来源、2 个成功下载、22 条 Evidence，RAG 导入 `accepted=true` 且 `ingestion_performed=false`。
- 针对 20K 上下文预检实现确定性 EvidenceBudgetPlanner，将 22 条 Evidence 从估算 35,313 tokens 筛至 6 条/9,640 tokens；真实 `qwen-max` synthesis 使用 5,974 tokens、11.5s，8/8 findings 通过引用集合 grounding。

## 5. 详细项目描述

项目基于 OpenManus 二次开发，目标不是重新实现 Agent 框架，而是建立一条可验证的智能任务执行样板。系统直接复用原有 WebSearch、Browser、ToolCollection、Sandbox 和 MCP，在 Research 层保留结构化 SearchResult，并用配置化 SourcePolicy 做限量选源。原始 HTML/PDF 先由 RawSourceArchive 保存，再按 section/page 提取 Evidence，所有专业 finding 必须关联 Evidence ID。

ResearchResult 不依赖 RAG，可直接输出 Markdown 和 JSON；CandidatePackageAdapter 复用 KnowledgeDraftTool/Builder/Validator 生成候选知识包。系统固定 Candidate 状态为 `CANDIDATE`，禁止 approve、Embedding 与 FAISS 写入。为了在 20K 上下文约束下完成真实 LLM synthesis，新增无需第二次模型调用的确定性 EvidenceBudgetPlanner，同时保存完整 EvidenceStore 与 selection report。

可靠性方面，项目用独立组件表达 ExecutionError、RetryDecision、TimeoutPolicy、BudgetReservation、ProgressSignal、NoProgressDecision、PolicyDecision 和 StructuredTrace。BudgetLedger 是权威状态，Trace 只做 best-effort 投影；TaskPolicy 当前以 observer 方式接入 Research Workflow，避免在未验证前改写原 Agent 行为。最终通过 361 项全项目测试和 Docker container smoke。

## 6. 技术栈

- Python 3.12、asyncio、Pydantic、pytest
- OpenManus Agent Core、ToolCollection、MCP
- Web Search、Browser automation、HTTP acquisition
- HTML parsing、文本 PDF parsing
- Docker SDK / Docker Sandbox
- TOML 配置、JSON/Markdown 数据契约
- SHA256、稳定 ID、原子目录发布
- DashScope `qwen-max`（真实 synthesis 验证）
- 外部 RAG Candidate Interface v2

## 7. 可量化结果

| 指标 | 结果 |
|---|---:|
| 全项目测试 | 361 passed |
| Minimal Core tests | 41 passed |
| Sandbox tests | 28 passed |
| 真实搜索候选 / 入选来源 | 7 / 3 |
| 下载成功 / 失败 | 2 / 1 |
| Evidence | 22 |
| EvidenceBudgetPlanner | 22 → 6 |
| 估算 Evidence tokens | 35,313 → 9,640 |
| LLM prompt / completion / total | 5,479 / 495 / 5,974 |
| LLM latency | 11,500 ms |
| Grounded findings | 8 / 8 |
| Candidate validator | accepted=true |
| RAG import | accepted=true, ingestion=false |

不要把 `361 tests` 写成 `361% coverage`，也不要把 8/8 ID-level grounding 描述成语义正确率 100%。

## 8. 60 秒项目介绍

这个项目是在 OpenManus 上做的一次可逆二次开发。OpenManus 本身已经有 ReAct、Tool Calling、Search、Browser、Sandbox 和 MCP，我没有把这些包装成自己的成果，而是解决“这些工具怎么形成可靠交付”的问题。我新增了一条固定阶段的 Knowledge Research Workflow：结构化搜索后按策略选源，归档原始 HTML/PDF，再提取带定位、双 hash 的 Evidence，最后生成独立 ResearchResult，以及 Markdown、JSON 和 RAG Candidate 三种输出。

真实任务里系统从 7 个候选选出 3 个来源，成功下载 2 个并形成 22 条 Evidence。由于全量输入超过 20K 预检，我实现确定性 EvidenceBudgetPlanner，将输入筛到 6 条、估算 9,640 tokens，再调用一次 qwen-max，实际使用 5,974 tokens，8 个 finding 都引用了合法 Evidence。另一个重点是 Reliability Phase 1A–1D，包括错误、重试、超时、预算、进度、轨迹和任务策略，但保持为组合式组件，没有改写 Agent Core。最终全项目 361 项测试通过。

## 9. 20 秒项目介绍

我基于 OpenManus 新增了一条 Evidence-first 的公开资料调研 Workflow，复用原生 Search/Browser，把原始资料转成可追溯 Evidence、ResearchResult 和多种输出，同时补充操作级可靠性组件。真实任务完成 22 条 Evidence、一次受预算约束的 LLM synthesis 和 RAG 候选导入验证，最终全项目 361 项测试通过，并保持原 Agent Core 语义不变。

## 10. 建议使用的关键词

`Agent Workflow`、`Evidence-first`、`structured output`、`deterministic planning`、`source traceability`、`reliability engineering`、`budget ledger`、`idempotency`、`Docker Sandbox`、`RAG interface`、`LLM grounding boundary`。

避免使用未经验证的词：`生产级`、`零幻觉`、`全局容错`、`语义正确率 100%`、`大规模爬虫`、`全行业知识库`。
