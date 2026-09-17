# Resume Material

## 项目名称

企业文档可信知识库与问答系统（Trusted Enterprise Document RAG System）

## 一行项目简介

基于开源/课程竞赛 RAG 进行工程化二次开发，构建支持通用多文档检索、可信引用、候选知识
审核边界、扫描文档 OCR、版本治理和确定性可信问答的 evaluation-driven 原型。

## 推荐简历 Bullet

1. 审计并修复 Qwen Structured Output、DashScope Rerank、IndexFlatIP 向量归一化和虚假引用
   补页等基线缺陷，完成 5 份 PDF、599 页、1,924 chunks 的真实运行验证；15/15 结构化输出
   成功，14/15 问题在真实 Rerank 后发生改序。
2. 将 company-only 年报检索解耦为 Generic/Legacy 双模式，采用稳定 `document_id`、每文档
   局部 Top-K 后全局合并、Parent Page 和复合 Citation；在同一 34 题 Retrieval Evaluation
   上，随 Domain Corpus/OCR/Version Governance 迭代将 Hit@1 从 0.815 提升至 0.926。
3. 设计 Candidate v2 人工审核边界、选择性中文 OCR 与历史版本独立索引，并基于 Held-out
   数据拒绝上线无依据的 cosine Reject；最终实现零额外 LLM 调用的 post-answer fail-closed，
   历史 Citation Failure 2/2 拦截，全项目 220 tests passed。

## 更保守的三条版本

1. 基于既有 RAG 原型完成可靠性修复和通用多文档解耦，保留 Legacy 兼容，并用真实
   DashScope/Qwen、归一化 FAISS 与 Parent Page 链路验证行为。
2. 建立 34 题 Domain、8 题 Version、20 题 Trusted QA Held-out 评测资产；用失败样本驱动
   OCR、历史版本检索和 Citation fail-closed，而不是堆叠 GraphRAG 或无证据阈值。
3. 实现 Agent Candidate Package v2 的路径/hash/引用校验和人工审批边界，保证 Agent 不能
   直接操作正式 FAISS；最终回归 220 passed / 0 failed。

## 技术栈

Python 3.11、Pydantic v2、DashScope/Qwen、OpenAI-compatible provider abstraction、FAISS
IndexFlatIP、NumPy、Docling、EasyOCR、PyPDFium2、pytest、JSONL evaluation datasets。

## 可量化证据

- Runtime Baseline：5 PDFs、599 pages、1,924 chunks。
- Corpus v0.2：5 indexed docs、182 pages、319 normalized vectors。
- 同一 34 题 Retrieval：Hit@1 0.814815 → 0.925926；最终 Hit@5 1.0、MRR 0.953704。
- Version 8 题 OFF/ON Hit@1：0.75 → 1.0。
- Trusted QA：20 题冻结 Held-out；历史 Citation Failure 2/2 intercepted；False
  Fail-closed 0；真实 ENFORCE Smoke 4/4 Structured Output。
- Full regression：220 passed / 0 failed。

## 可被追问的技术点

- 为什么 `IndexFlatIP + L2 normalize` 才能解释为 cosine。
- 为什么每文档局部 Top-K 再全局合并，而没有合并所有 FAISS。
- Parent Page 的召回/上下文权衡及其 score 语义。
- Citation Membership 与 semantic entailment 的边界。
- Candidate v2 中 `content_hash` 与 `raw_file_hash` 的不同验证强度。
- OCR 为什么 fail closed、为什么单阈值失败、横置页如何恢复。
- ACTIVE/SUPERSEDED 与 current/historical 检索资产。
- 为什么 Hard Negative 分数更高后仍拒绝上线 cosine threshold。
- pre-generation Shadow 与 post-answer Enforcement 的职责分离。

## 不允许写的 Claim

- 从零自研整个 RAG。
- 应用于真实特种设备生产环境。
- 企业级/生产级系统、Production Ready。
- 准确率提升到 92.6%（0.925926 是 Retrieval Hit@1，不是 Accuracy）。
- 零幻觉、语义引用验证、通用置信度、自动法律解释。
- 完整自动知识治理或 Agent 自动发布正式知识。

## 项目描述边界

正确表述：

> 选取特种设备使用管理相关公开资料作为首个垂直场景进行验证。

不要表述：

> 为特种设备企业设计并上线行业知识库。
