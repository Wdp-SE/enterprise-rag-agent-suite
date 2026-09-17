# Project Pitch

## 30 秒版本

我基于一个公司年报竞赛 RAG 做工程化二次开发。先修复 Qwen Structured Output、Rerank 分数、
向量归一化和引用问题，再把 company-only 路由改成通用多文档检索。之后用公开法规做垂直
验证，补上选择性 OCR、历史版本检索和可信问答。最终同一 34 题 Retrieval Hit@1 从 0.815
提升到 0.926，全项目 220 个测试通过；对没有数据支持的 cosine Reject，我选择不上线。

## 1 分钟版本

这个项目叫“企业文档可信知识库与问答系统”。它不是从零开发，而是基于开源/课程竞赛 RAG
做系统性二次开发。原项目只适合公司年报，并且真实运行后发现 Structured Output、Rerank
score、IndexFlatIP normalization 和 Citation 都有行为问题。

我先建立 Reliable Runtime Baseline，再保留 Legacy 的同时增加 Generic 多文档模式。为了验证
企业文档常见问题，我选公开特种设备法规作为场景，建立固定评测集；扫描版规范促使我实现
选择性 OCR 和横置页恢复，新旧规范促使我增加 Version Governance。Trusted QA 阶段发现
Hard Negative 的 cosine 甚至高于 Answerable，所以 pre-generation 只保留 Shadow；只把结构
和引用成员关系这种确定性失败做 post-answer fail closed。最终回归 220 passed，但我明确不
宣称 Production Ready 或语义引用验证。

## 3 分钟版本

项目起点是一个竞赛获奖 RAG，原链路已经有 PDF、chunk、FAISS、Parent Page、Rerank 和
生成，但围绕 company name 和单公司年报设计。我先做代码审计和真实 Runtime Verification，
发现课程里提到的能力不等于代码真的正确。例如 DashScope 的 JSON 没被解析成 Schema，
Rerank score 固定为 0，IndexFlatIP 两侧没归一化，Citation Validator 还会补模型没声明的页。

第一步是 Reliable Baseline：修复这些缺陷并重建小样本索引。5 份 PDF 共产生 599 页和
1,924 chunks，15 题全部通过真实 Qwen Structured Output，14 题 Rerank 改序。第二步是竞赛
解耦：增加稳定 document_id、Generic/Legacy 双模式和每文档局部 Top-K 后全局合并，Citation
改为复合文档/页身份。

接着我建立公开法规验证 corpus 和 34 题 Retrieval Evaluation。新版规范是扫描 PDF，不能把
空文本当成功，所以我做了 page-level OCR trigger、cache 和 Quality Gate。0.65 confidence 会
误删有效条款，第 37 页还是横置表格，这些失败又驱动 hybrid retention 和有限旋转恢复。
Corpus v0.2 达到 5 文档、182 页、319 vectors。

新旧 TSG 规则同时存在，所以我实现 ACTIVE/SUPERSEDED、版本意图和独立历史资产。最终同一
34 题 Hit@1 从 0.814815 到 0.925926。最后做 Trusted QA：分数分布证明单 cosine threshold
会误拒 6/27 Answerable，Held-out Hard Negative 均值还更高，因此 pre-generation 坚持
Shadow。Phase 2 真实发现两个 Citation Membership Failure，我才上线零额外 LLM 调用的
post-answer fail closed，保存结果回放 2/2 拦截。项目最终 220 tests passed；它是可展示、
可评测的工程原型，不是生产系统。

## 5 分钟版本

### 背景

企业知识库的问题不只是“向量召回后让模型回答”，还包括文档扫描、新旧版本混用、来源追溯、
无答案问题和持续回归。我接手的原项目是公司年报竞赛代码，目标是把它改造成行业通用、行为
可验证的 RAG 基础架构。

### Reliable Baseline

我没有先加新算法，而是验证基础事实。Qwen Structured Output、Rerank score、cosine 语义和
Citation 都存在 bug。修复后文档/查询 embedding 均归一化，旧 FAISS 明确作废并重建；15 题
真实链路保存了 retrieval/rerank/generation 延迟、token 和引用。这个阶段也暴露了高分但漏掉
正确页的问题，说明 similarity 不能直接等同于答案可信。

### Generic 与 Candidate

Generic Mode 去除了问题对 company name 的依赖，同时保留比赛 Legacy Mode。我没有大规模
合并索引，而是复用每文档 FAISS，以局部 Top-K 再全局合并。Agent 接入则走 Candidate v2：
严格 schema、路径逃逸防护、raw-file hash 重算和人工审核。Agent 无权写正式 FAISS。

### Corpus、OCR 与版本

8 份公开资料里只有 4 份可直接入库，扫描文档保持 OCR_REQUIRED，而不是伪造正文。选择性
OCR 的两个关键失败是低置信有效条款被阈值过滤，以及横置第 37 页为空。我用真实 fixture
校准通用 retention，并只对异常页做 90°/270°恢复。新版入库后，又为 2017 旧版建立独立历史
资产，通过 Resolver 控制默认当前版和明确历史版。

### Trusted QA 与取舍

我先分析 34 题，再冻结 20 题 Held-out。Answerable 和 Unanswerable score 重叠，Hard Negative
均值更高，所以没有上线 cosine Reject。Pre-generation 只记录 Shadow observation。真正上线
的是 Phase 2 已观察到的确定性故障：结构无效、答案无引用、引用不属于 Retriever 或 N/A/引用
冲突。失败时对外 N/A，内部保留完整审计，Gate 不增加 LLM 调用。

### 结果和边界

最终同一 34 题 Retrieval Hit@1 为 0.925926，Version 8 题 Hit@1 为 1.0，历史 Citation
Failure 2/2 被拦截，Full regression 220 passed。与此同时我明确保留 Retrieval miss、Citation
不验证 semantic entailment、无 Conflict Resolver 和无生产基础设施这些限制。项目的核心价值
是 failure-driven 和 claim-safe，而不是堆更多 RAG 名词。
