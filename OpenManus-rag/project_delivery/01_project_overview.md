# 项目总览

## 1. 项目定位

本项目的长期定位是“基于 OpenManus 的可靠智能任务执行 Agent”。它不是一个专门为 RAG 找资料的单用途脚本，也不是特种设备行业生产系统。Knowledge Research 是第一条新增业务 Workflow，用来证明 OpenManus 的通用工具能力可以被组织成一条可验证、可追溯、可离线测试的公开资料调研链路。

第一版垂直验证选择“特种设备使用单位基本安全管理要求”，原因是该主题具有公开权威来源、法规型事实、来源等级与更新时效等典型约束。领域名称和问题均放在 `ResearchProfile` 配置中；更换为能源、制造、金融、电信、交通、AI 技术或软件工程调研时，不需要改核心模型和流程代码。

## 2. 解决的问题

通用 Agent 的 Search/Browser 能力并不自动等于可靠的知识调研。真实交付还需要解决以下问题：

1. 搜索结果如何保留为结构化对象，而不是先压成 Memory 字符串再反向解析；
2. 来源如何依据可配置策略分级、排序和限量；
3. 原始 HTML/PDF 如何完整归档，并和可用于推理的 Evidence 严格分离；
4. 专业结论如何只从 Evidence 生成并保留可追溯引用；
5. Markdown、JSON 和 RAG Candidate Package 如何共用同一 ResearchResult；
6. LLM 上下文不足时，如何用确定性 EvidenceBudgetPlanner 控制输入而不删除知识资产；
7. 任务执行如何逐步具备错误、重试、超时、预算、进度、轨迹与策略治理能力。

## 3. 已完成能力

### 3.1 Knowledge Research Minimal Core

- `ResearchProfile` 与配置加载；
- `Evidence` 数据模型与稳定 Evidence ID；
- 分离的 `content_hash` / `raw_file_hash`；
- 配置化 `SourcePolicy`；
- 可去重、可持久化的 `EvidenceStore`；
- 路径逃逸与 symlink 防护的 `RawSourceArchive`；
- 稳定 candidate/document/source ID；
- `KnowledgeDraftTool`、`CandidateBuilder`、`CandidateValidator`；
- 原子发布与相同输入 `REUSED` 语义。

### 3.2 Knowledge Research Live Workflow

- 独立 `KnowledgeResearchAgent` 外观与固定阶段 Workflow；
- 复用现有 `WebSearch` 的结构化 Search Adapter；
- SourcePolicy classification/ranking/selection；
- HTTP 获取与 Browser fallback；
- HTML 和文本 PDF 提取；
- `ResearchResult`、Markdown/JSON/Candidate 三种输出；
- 确定性与真实 LLM 两种 ResearchSynthesizer；
- EvidenceBudgetPlanner 与 EvidenceSelectionReport；
- Finding 引用集合的 GroundingValidator；
- RAG Candidate Interface v2 联动验证。

### 3.3 Agent Reliability Enhancement Phase 1A–1D

- Phase 1A：结构化错误、重试策略、超时解析、执行结果与结构化轨迹；
- Phase 1B：`ReliableOperationExecutor` 的最小 Workflow 集成；
- Phase 1C：预算账本、操作预留/结算、进度信号和 NoProgress 判定；
- Phase 1D：TaskPolicy、PolicyDecision 与 Workflow Controller；
- 所有能力均以组合方式引入，没有改写 BaseAgent/ReActAgent/ToolCallAgent 核心循环。

## 4. 真实验证结果

真实运行 `kr_20260828T082105547457Z_b40bc521` 的结果：

| 指标 | 结果 |
|---|---:|
| Search candidates | 7 |
| Selected sources | 3 |
| Download success / failure | 2 / 1 |
| Evidence | 22 |
| EvidenceBudgetPlanner | 22 → 6 |
| Evidence token estimate | 35,313 → 9,640 |
| LLM model | qwen-max |
| Prompt / completion / total tokens | 5,479 / 495 / 5,974 |
| LLM latency | 11,500 ms |
| Findings | 8 |
| Grounded findings | 8 |
| CandidateValidator | accepted=true |
| RAG import_candidate() | accepted=true |
| RAG ingestion | false |

真实运行有一个来源下载失败，Workflow 将结果标记为部分完成并保留限制说明，没有用模型常识补齐缺失事实。

## 5. 设计原则

### Evidence-first

Search snippet 只是发现线索，不能成为正式事实基础。原始来源先被归档，随后由确定性解析器生成可定位 Evidence；ResearchResult 的重要 finding 必须关联 Evidence ID。

### RAG 是 Adapter

Research Workflow 即使没有 RAG 也能输出 Markdown 和结构化 JSON。Candidate Package 只是第三种输出，复用相同 Evidence、稳定 ID、引用和校验逻辑。

### 可逆、可插拔

原 `main.py` 默认行为不变，Research 使用独立 `run_research.py`。禁用新增 Workflow 后，原 OpenManus 仍可运行。可靠性能力也通过独立组件和集成层引入。

### 确定性边界优先

Stable ID、hash、选源、证据预算、目录发布和契约校验都由确定性代码完成。LLM 只位于可注入的 Synthesizer 中，不散落在下载、存储、策略或 Candidate 构建模块。

## 6. 能力边界

- 不自动 APPROVE Candidate；
- 不执行 RAG 正式 ingestion、Embedding 或 FAISS 写入；
- 不支持扫描 PDF OCR；
- 不做大规模爬取、GraphRAG、Multi-Agent 或长期 Memory；
- Reliability 当前不是所有 Agent/Tool 的全局强制控制面；
- GroundingValidator 验证引用集合，不进行语义蕴含证明；
- 首个真实样本规模有限，不能据此宣称生产级行业覆盖。

## 7. 项目价值

该项目展示的重点不是“调用了一个搜索工具”，而是将一个开放式 Agent 任务拆为可观测的数据契约和可验证的阶段：每一份事实有原始文件、hash 和定位信息；每一个输出可回到 Evidence；每一个 Candidate 可由外部 RAG Validator 独立拒绝或接受；每一类可靠性能力都有明确权威状态和测试边界。这使系统更容易复盘、调试和继续演进。
