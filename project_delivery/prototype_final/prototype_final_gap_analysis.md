# Prototype Final 差距分析

## 结论

V4 已经完成版本感知 RAG、变更影响分析、局部 Patch、人工审核、冲突与幂等校验、候选版本和安全激活的核心闭环。本轮不重新实现这些能力，只补齐产品入口、执行可解释性、Evidence 上下文预算、统一确定性门禁结果，以及面向面试的评测和文档表达。

## 现状核对

1. **UI 当前展示内容**：已有研发文档目录、业务检索范围、可信问答与原始 Evidence、版本差异、Requirement Diff、已确认关系、疑似影响、Patch 前后对比、人工审核、候选版本和发布结果。旧文档起草流程仍作为第二个主标签出现，V4 变更工作台排在其后。
2. **Scope / Version / Evidence 业务化程度**：RAG 页面已经使用业务范围和历史版本提示；普通检索 Evidence 已展示文档名、版本、章节和页码。变更工作台仍直接暴露 Evidence ID、Anchor、状态枚举等内部名，需要移入技术详情。
3. **Workflow Trace 字段**：现有状态记录 workflow_id、step、status、latency_ms、rag_calls、llm_calls、evidence_count、组织/项目/文档版本、提示版本和 failure_reason。
4. **现有统计能力**：rag_calls、llm_calls、耗时和 Evidence 数量均已存在；V4 主链当前没有 LLM 调用，因此 llm_calls 的真实值为 0。UI 目前仅显示步骤、状态和耗时，没有完整汇总。
5. **Evidence 去重**：已有。EvidenceStore 依据稳定来源、Chunk 和内容哈希生成身份并去重，EvidenceCache 保留任务、字段和查询成员关系。
6. **Evidence 数量或 Token Budget**：字段起草已有 DraftPolicy.max_evidence=3，但没有统一的选择结果、范围/版本过滤统计和可配置 max_evidence_count。V4 变更链也没有把检索、有效、去重、入选数量作为正式结果。当前无可靠 Token Usage，不适合引入精确 Token 预算或费用估算。
7. **确定性校验现状**：已有 Scope 指纹、Evidence 存在性与哈希、Freshness、人工批准、目标版本、Anchor、原文内容与哈希、输出冲突、重复应用、候选结构、Chunk、Embedding、Index、业务验证和安全激活。缺口是没有统一的 PASS/BLOCKED 与 reasons 结果供 Trace 与 UI 复用。
8. **固定 7 条 Evaluation**：覆盖精确标识检索、跨文档检索、语义检索、版本冲突、无答案、Scope 越界和术语类问题；同时汇总当前版本命中、Citation、延迟以及 Agent 的影响识别、Patch 安全、恢复和候选版本行为。
9. **Baseline comparison**：没有。现有版本库具备 V1=500、V2=1000 的真实合成冲突，可以在离线 Evaluation 中对比“无版本约束”与“仅当前有效版本”，无需增加生产 Retriever。
10. **README 统一产品故事**：没有完整收口。当前 README 将 RAG、Agent、V3、V4 分段介绍，缺少统一架构、固定 Demo、Evaluation、设计边界、截图和完整 Quick Start。
11. **三分钟 Demo**：业务素材和操作能力已存在，但没有一份固定、计时明确、从 500→1000 到安全激活与 Evaluation 的完整讲解脚本。
12. **一键启动说明**：已有 demo-ui/start_demo.ps1，但它只启动 Streamlit，不会启动 RAG API，README 也没有把两者整理为一条可复现路径。
13. **旧 V3 是否仍是主要入口**：是。它仍占据第二个主标签，且页面标题和页脚仍强调 Word 模板到整篇草稿，应降为“扩展能力”。
14. **普通用户可见的内部名**：存在，包括 Requirement Diff、Impact Candidate、Patch Before/After、Evidence ID、Anchor、Candidate Version、Workflow Progress 及状态枚举，需要改为业务语言，技术码仅保留在折叠详情和 Trace 中。

## 本轮最小改动范围

- 重排 Streamlit 信息架构，突出版本变化到安全发布的主链，保留旧 V3 为次要入口。
- 增加薄 Evidence Selection 层：范围与版本校验、Freshness、去重、相关性顺序和数量预算；记录四个确定性计数。
- 将既有 Patch 校验收口为统一 Quality Gate 结果，并复用现有状态与失败码映射。
- 以现有状态渲染 Workflow Trace；只读展示，不触发额外 RAG 或 LLM 调用。
- 整理固定评测，补 P50 和仅用于 Evaluation 的真实版本约束对照。
- 重写根 README，并生成架构、Demo、评测、回归和面试材料。

## 明确不实施

- 不增加 Hybrid、BM25、RRF、Reranker、LangGraph、多 Agent、MCP、数据库、消息队列或 React。
- 不改核心检索语义，不扩展审批模型，不做自动代码修改。
- 不实现 Token/费用估算：当前主链没有可靠 Usage 和可维护价格配置。
- 不删除 V3 稳定代码，不修改或提交 OpenManus-rag/runtime/ 与 project_delivery/interview_guide/。
