# Knowledge Research Live Workflow Report

日期：2026-08-28  
最终状态：**COMPLETE**

## 1. 范围与架构边界

Knowledge Research 作为 OpenManus 的独立、可插拔 Workflow，固定阶段为：

`DISCOVER -> SELECT -> ACQUIRE -> EXTRACT -> BUILD_RESULT -> OUTPUT`

`KnowledgeResearchAgent` 使用组合方式持有 `KnowledgeResearchWorkflow`，没有继承或改写
Manus 的 ReAct 循环。BaseAgent、ReActAgent、ToolCallAgent、Manus、PlanningFlow、
WebSearch、BrowserUseTool、ToolCollection 和原 `main.py` 行为均未修改。

Knowledge Research 不依赖 RAG 也可独立输出 ResearchResult、Markdown 和 JSON；
Candidate Package 仍只是可选 Output Adapter。

## 2. 本次 Closure 新增与修改文件

新增：

- `app/research/evidence_budget.py`
- `tests/research_live/test_evidence_budget.py`

修改：

- `app/research/research_synthesis.py`
- `app/research/llm_synthesis_smoke.py`
- `app/research/output_adapters.py`
- `run_research.py`
- `tests/research_live/test_cli_and_llm_smoke.py`
- `tests/research_live/test_research_synthesis_and_result.py`
- `docs/knowledge_research_live_workflow_report.md`

没有修改 Agent Core，没有新增依赖，没有实现全局 BudgetController、Retry、Timeout、
NoProgress、Structured Trace 或 Task Policy。

## 3. 已完成的真实 Deterministic Workflow

- run_id：`kr_20260828T082105547457Z_b40bc521`
- 主题：`特种设备使用单位基本安全管理要求`
- Search candidates：7
- Selected sources：3
- Download：2 success / 1 failure
- EvidenceStore：22 条 Evidence
- ResearchResult：PARTIAL（保留一项 HTTP 403 limitation）
- 运行时间：4.719 秒
- Deterministic LLM tokens：0
- CandidateValidator：`accepted=true`

本次 Closure 没有重新执行 Search、Browser、下载、HTML/PDF 解析、Evidence Extraction、
Candidate Generation 或 RAG Import。

## 4. RAG Candidate Interface v2 联动

正确 RAG 项目路径：

`E:/工作项目/秋招项目/11-项目实战：企业知识库/11-项目实战：企业知识库/RAG-Challenge-2-main`

根据 Closure 前置门结果，Candidate Interface v2 已升级并完成真实联动：

- candidate_id：`cand_special-equipment-validation_4996f87d16f2cd6b`
- document_id：`doc_special-equipment-validation_62ce784eda553678`
- `import_candidate().accepted=true`
- `ingestion_performed=false`
- `approve_candidate()`：未调用
- Embedding / FAISS / 正式 ingestion：未执行

该联动在本次 LLM Closure 中没有重复执行。

## 5. EvidenceBudgetPlanner

`EvidenceBudgetPlanner` 只决定一次 Research synthesis 的输入子集，不修改或删除完整
EvidenceStore。输入为 ResearchProfile 与 Evidence 集合，输出为 SelectedEvidence 与
EvidenceSelectionReport。

确定性选择算法依次考虑：

1. research_topic 与 research_questions 的 CJK n-gram / ASCII token overlap；
2. Evidence content、title、section 的相关度；
3. SourcePolicy level；
4. preferred_source_types；
5. 不同来源的首条代表 Evidence；
6. 跨来源 `content_hash` 去重；
7. 单来源最大预算占比；
8. 单条 Evidence 最大预算占比；
9. token budget 与稳定 evidence_id 排序。

排序不依赖输入顺序、set 遍历顺序、当前时间、UUID 或随机采样。页面导航/页脚等低分
内容通过最低相关度阈值排除。

## 6. Token Estimation 与预算推导

正式预检复用了项目现有 `LLM.count_tokens()`。当前 `qwen-max` 不在 tiktoken 的预设
模型表中，因此项目按既有逻辑使用 `cl100k_base` 作为本地估算 tokenizer。该值属于
estimated tokens，不等于服务端真实 usage。

预算计算：

- max_context_budget：20,000
- 实际固定 Prompt/System/消息格式估算：155
- completion reserve：4,000
- safety margin：1,500
- max_evidence_budget：`20,000 - 155 - 4,000 - 1,500 = 14,345`

Prompt 限制为最多 8 个简洁、逐字摘录式 Finding。Planner 不使用 LLM、Embedding、
Vector DB 或 Reranker。

## 7. 真实 22 → 6 Evidence 结果

- original_evidence_count：22
- selected_evidence_count：6
- original_estimated_tokens：35,313
- selected_estimated_tokens：9,640
- selected_prompt_estimated_tokens：9,795
- max_evidence_budget：14,345
- 预算余量：4,705 Evidence tokens
- 上下文总余量：10,205 tokens

Selected Evidence IDs：

- `ev_209727e632b49e7f0a0b`
- `ev_5fa187b07581ec063b3b`
- `ev_7b1a29801cf2dc9832f3`
- `ev_b4163969297218428865`
- `ev_b6a07b8a9622d75ba7ed`
- `ev_c8878619ef7c6bf1c5c9`

来源覆盖：

- 国家市场监督管理总局页面：5 条
- 江门市人民政府页面：1 条

两条成功获取的来源均保留代表 Evidence；两个页面导航/页脚片段被判定为低相关并排除。
完整 22 条 Evidence 仍保留在原 EvidenceStore 中。

## 8. EvidenceSelectionReport

报告已独立落盘，包含：总数、选择数、原始/选择 token 估算、上下文与 Evidence 预算、
Selected/Excluded IDs、来源分布，以及每条 Evidence 的 selected/excluded 原因。

路径：

`workspace/research_runs/kr_20260828T082105547457Z_b40bc521/outputs/evidence_selection_report.json`

首次预检暴露一条低分导航内容仍被选择，随后仅修改本地 Planner 与 Fixture，将最低相关度
阈值纳入确定性策略并重新生成 SelectionReport；没有重跑真实调研或调用模型。

## 9. 真实 LLMResearchSynthesizer 调用

在 Planner 测试与真实预检通过后，仅执行了一次底层模型 API 请求：

- model：`qwen-max`
- API attempts：1
- prompt_tokens：5,479
- completion_tokens：495
- total_tokens：5,974
- latency_ms：11,500
- finding_count：8

Research 专用 Adapter 对本次调用使用 `LLM.ask` 的未装饰 coroutine，绕过原 OpenManus
六次重试包装；该行为有独立单元测试，Agent Core 未修改。

本地 cl100k_base 的完整 Prompt 估算为 9,795，而服务端 qwen tokenizer 报告真实
prompt usage 为 5,479。两者分别记录，不混写为同一统计口径。

## 10. GroundingValidator

- grounded_finding_count：8
- rejected_finding_count：0
- unknown Evidence IDs：0
- 所有引用均属于 SelectedEvidence：是
- GroundingValidator result：passed

当前验证范围是：

1. Finding 至少关联一个 evidence_id；
2. evidence_id 存在且属于本次 SelectedEvidence；
3. statement 是 cited Evidence 规范化文本中的连续逐字片段。

该验证不能证明完整的语义蕴含、法律解释正确性或事实绝对真实性。指标文件明确保存
`semantic_entailment_verified=false`，没有夸大验证能力。

## 11. Deterministic 与 LLM 产物

原产物保持不变：

- `research_report.md`
- `structured_result.json`

调用前后 SHA256 一致：

- research_report.md：`DA461D88D87ABD9723FDA01403D4D92F05A47F571D70567278EF8A3461E32DD0`
- structured_result.json：`635D96FA43204A41C40F89E62A6C34C0AC4EF3C935E85902E79CFDF5BC2A5D4B`

新增独立产物：

- `research_report_llm.md`
- `structured_result_llm.json`
- `evidence_selection_report.json`
- `llm_synthesis_metrics.json`

全部位于：

`workspace/research_runs/kr_20260828T082105547457Z_b40bc521/outputs/`

## 12. 测试与回归

- EvidenceBudgetPlanner：16 passed
- Live Workflow：55 passed，6 warnings
- Minimal Core：41 passed，3 warnings
- Sandbox：28 passed，1 warning
- Full project：124 passed，5 warnings，0 failed，0 errors，0 skipped
- Knowledge Research import smoke：passed
- `python run_research.py --help`：passed
- `python main.py --help`：passed

警告均为既有 Pydantic V2 配置弃用提示和 pytest-asyncio 默认 fixture loop scope 提示。
没有删除、skip 或降低原测试断言，也没有发现 Knowledge Research 对 Agent Core、Sandbox、
Docker、Browser、Search 或 ToolCollection 引入回归。

## 13. 真实运行暴露的问题

1. Search redirect URL 会在选择阶段隐藏最终官方域名；后获取重分类已有本地修复，但未回写
   本次不可变真实 run。
2. HTML body 内仍可能存在站点 chrome；Planner 的最低相关度过滤能减少其进入 synthesis，
   但更强的通用 main-content extraction 仍值得后续设计。
3. BrowserUseTool 尚缺公开的完整 document/download 返回契约，JS-only 页面仍受限。
4. `cl100k_base` 是 qwen-max 的保守本地估算口径，与服务端 tokenizer usage 存在差异；
   当前通过同时保留 estimated/actual 指标避免混淆。
5. GroundingValidator 是引用成员与抽取式文本校验，不是语义蕴含验证器。

## 14. 完成判定

以下条件全部满足：

- Deterministic Live Workflow 成功；
- Candidate Package 与本地 CandidateValidator 成功；
- RAG Interface v2 import accepted=true 且 ingestion_performed=false；
- EvidenceBudgetPlanner 工作且完整 EvidenceStore 未修改；
- 22 条 Evidence 已稳定筛选为预算内 6 条；
- 唯一一次真实 LLM synthesis 成功；
- GroundingValidator 通过；
- LLM 独立产物与 token/latency 指标已落盘；
- Sandbox、Minimal Core、Live Workflow 与全项目回归全部通过。

因此：**Knowledge Research Live Workflow = COMPLETE**。

下一阶段可以进入 Agent Reliability Enhancement。优先级建议为：阶段级错误分类与超时、
受限 Retry、NoProgress、Structured Trace，随后再考虑 Task Policy；不要把本次局部
EvidenceBudgetPlanner 扩张为未经设计的全局 BudgetController。
