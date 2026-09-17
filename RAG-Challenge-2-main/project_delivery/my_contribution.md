# My Contribution

## Original Project

原始开源/课程竞赛项目已经提供：

- PDF/年报处理主链路；
- Chunk、Embedding、FAISS 和基础 Retrieval；
- Parent Document/Page Retrieval；
- LLM Rerank 与 Structured Prompt 的初始实现；
- company name 路由、多公司比较和竞赛 submission 格式；
- OpenAI、Gemini、IBM、DashScope 等 Provider 分支雏形。

这些能力不是本人从零开发。项目叙述必须保留原作者和原许可证信息。

## My Secondary Development

### 1. Reliable Baseline Repair

- 审计真实调用链，而非根据课程标题推断功能。
- 修复 Qwen JSON/Pydantic Structured Output、DashScope Rerank score、Embedding normalization、
  Citation 自动补页和 Boolean N/A。
- 统一 Answer/Embedding/Rerank provider-model 组合并删除敏感日志。
- 重建小样本 FAISS，完成 5 PDF / 599 pages / 1,924 chunks / 15 题真实验证。

### 2. Competition Decoupling

- 增加 Generic/Legacy 双模式，Generic 问题不依赖 company name。
- 设计稳定通用 DocumentMetadata 和 document_id 传播。
- 实现每文档局部 Top-K → 全局 merge → Top-K，保留独立 FAISS。
- 复用 Retriever 生命周期，使用复合文档/页 Citation。

### 3. Candidate Interface v2

- 定义 Agent Candidate Package、严格 schema、v1/v2 detection 和 normalization。
- 实现跨平台路径逃逸/symlink/绝对路径防护、alias conflict 与 raw file hash 重算。
- 明确 content_hash 只做声明格式校验，不伪称完整性重算。
- 固化 Agent → Candidate → Human Review 边界，禁止自动 Embedding/FAISS/正式发布。

### 4. Domain Corpus and Evaluation

- 审计 8 份公开资料并冻结 manifest，不伪造扫描正文或业务数据。
- 建立 34 题 Domain、8 题 Version 和 20 题独立 Trusted QA Held-out。
- 输出 Retrieval、Citation、Answer Smoke、token、latency、failure taxonomy 和回归证据。
- 对超过 token 边界的完整 Answer Evaluation 主动停止，不生成虚假数字。

### 5. Selective Chinese OCR

- 增加 page-level OCR trigger、cache、质量门禁和 block retention。
- 用 0.65/0.60 threshold false negative 证据替代拍脑袋规则。
- 对横置第 37 页实现有限 90°/270° recovery，保持 normal cache 和其他页面不变。

### 6. Version Governance

- 定义版本 family、ACTIVE/SUPERSEDED、时间意图、eligible document 和 version trace。
- 建立 2017 独立历史资产，默认当前查询和明确历史查询分开。
- 在同一 34 题上将 Retrieval Hit@1 从 0.815 推进到 0.926，同时保持非版本题回归。

### 7. Trusted QA

- 分离 Retrieval Confidence、Evidence Sufficiency 与 Answer validity。
- 用真实 score overlap 和 Held-out Hard Negative 证明 cosine threshold 不可上线。
- pre-generation 保持 Shadow；post-answer 只对确定性结构/Citation invalid state fail closed。
- 保存 original/audit/decision/final trace，额外 Gate LLM 调用为 0。

### 8. Testing and Documentation

- 最终 Full regression 220 passed / 0 failed。
- 持续维护架构、阶段报告、真实 artifact、Claim Matrix、Demo 和 Known Limitations。

## 面试中的推荐说法

> 我不是从零写了一个 RAG，而是接手一个竞赛型原型，先做代码和运行时审计，再用真实失败
> 驱动最小二次开发。我的重点是把它从 company-only 年报问答改成可评测的通用多文档原型，
> 并补上数据接入、OCR、版本选择、引用边界和确定性 fail-closed。

## 不属于本人 Claim 的内容

- 原竞赛获奖成绩和原始比赛方案设计；
- 真实特种设备企业知识库建设；
- 企业生产部署、业务收益或生产 SLA；
- 从零训练 Embedding/Rerank/LLM；
- 未实现的 Conflict、GraphRAG、semantic entailment 和全自动治理。
