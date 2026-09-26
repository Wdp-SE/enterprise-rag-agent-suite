# Prototype Final 架构

## 产品边界

产品只解决“研发资料版本可信”和“需求变化后的文档修改审查”两个连续问题。RAG 管资料与证据，Agent 管变化、修改和写入安全，UI 只展示真实状态。

## 组件图

    ┌─────────────────────────────────────────────────────────────┐
    │ Streamlit：概览 / 版本 / 检索 / 变更审核 / Trace / Evaluation │
    └───────────────┬───────────────────────────────┬─────────────┘
                    │                               │
                    ▼                               ▼
    ┌────────────────────────────┐      ┌──────────────────────────┐
    │ Version-aware RAG          │ HTTP │ Change Review Agent      │
    │ Structure / Version Store  │◄────►│ Diff / Impact            │
    │ Scope / Dense Retrieval    │      │ Evidence Selection       │
    │ Evidence / Citation / Diff │      │ Local Patch              │
    │ Candidate Build/Activation │      │ Quality Gate             │
    └───────────────┬────────────┘      │ Human Review             │
                    │                   │ Conflict / Idempotency    │
                    │                   │ Checkpoint / Resume       │
                    │                   └────────────┬─────────────┘
                    │                                │
                    └──────────► Candidate Version ◄─┘
                                      │
                                      ▼
                              Validation / Activation

## 关键数据流

1. 文档进入结构处理与版本目录，形成当前有效版本和历史版本。
2. 检索请求携带不可变业务 Scope；默认 active_only。
3. RAG 返回版本、章节、页码和 Chunk 完整的 Evidence。
4. 需求 Diff 产生变更项；已登记 TraceLink 与语义建议分开建模。
5. Evidence Selection 执行 Scope、版本、Freshness、去重和数量预算。
6. PatchCandidate 只引用入选且可追溯的 Evidence。
7. Quality Gate 复用现有审核、冲突、Freshness 和幂等状态。
8. 已批准 Patch 写入 Candidate DOCX，不覆盖原文档。
9. RAG 服务对 Candidate 做结构、Chunk、Embedding、Index 和业务校验。
10. 只有校验通过才激活新版本；失败保留旧有效版本。

## 共享接口

- Agent 通过 HTTPRetrieveClient 调用 RAG API。
- Evidence 是两个模块的可审计契约。
- QualityGateResult 是 Patch 应用与候选校验的统一只读结果。
- Trace 和 UI 读取工作流状态，不触发额外 RAG/LLM 调用。
- Baseline Comparison 只属于 Evaluation Harness。

## 明确没有使用

LangGraph、Multi-Agent、MCP、GraphRAG、Hybrid、BM25、RRF、Reranker、PostgreSQL、Redis、消息队列、Kubernetes 和 React。
