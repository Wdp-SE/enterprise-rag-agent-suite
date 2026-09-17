# Interview Q&A

以下答案按口述长度编写。数字均来自仓库 artifact，不应脱离口径使用。

## 1. 为什么选择 RAG？

企业知识通常在文档里持续更新，直接微调成本高且难追溯。RAG 可以把答案约束在可更新的
外部证据上，并返回来源，更适合制度、规范和技术资料。

## 2. 这是从零开发的吗？

不是。我基于开源/课程竞赛 RAG 做系统性二次开发。原项目有 PDF、FAISS、Parent Page、
Rerank 和生成雏形；我的工作重点是可靠性修复、通用解耦、Candidate、OCR、版本治理、评测
和 Trusted QA。

## 3. 原项目最核心的问题是什么？

它围绕“问题里必须有公司名、每家公司一个年报索引”的竞赛假设。除此之外还有 Qwen
Structured Output 未解析、Rerank 分数错误、向量未归一化和 Citation 自动补页等行为缺陷。

## 4. 你为什么先做 Reliable Baseline？

如果分数和结构化输出本身不可信，后续阈值、评测和治理结论都没有意义。我先让基础链路
行为正确、可运行、可测试，再增加业务能力。

## 5. 为什么选择 FAISS IndexFlatIP？

当前数据规模小，Flat index 能做精确近邻检索，便于建立可解释基线。配合 L2 normalization，
inner product 等于 cosine similarity，不需要先引入近似索引的召回误差。

## 6. 为什么文档向量和查询向量都必须归一化？

只归一化一侧或两侧都不归一化，inner product 会受向量长度影响，不能解释为 cosine。修复后
两侧范数都接近 1，IndexFlatIP 分数才有统一语义。

## 7. 修复归一化后为什么必须重建旧 FAISS？

FAISS 保存的是已经写入的向量。改查询代码不会改变旧文档向量，因此旧索引仍是不同分数
空间，必须用归一化后的文档 embedding 重建。

## 8. Generic Retrieval 怎么做？

不再从问题抽公司名选唯一数据库，而是对 eligible 文档分别取局部 Top-K，再全局 merge 和
Top-K。这样问题没有 company name 也能跨文档检索，同时没有全量汇总所有 chunks。

## 9. 为什么没有把所有 FAISS 合并？

最小改造优先复用已有每文档资产，也方便版本资产独立加载和文档级过滤。当前规模下局部
Top-K 的成本可控；更大规模才需要重新评估统一/分层索引。

## 10. Parent Page 的价值是什么？

Chunk 适合精确召回，整页更适合提供完整上下文。系统用 chunk score 触发 Parent Page，减少
条款被切断的问题；但该 score 仍是 chunk score，不是整页重新算的相似度。

## 11. Rerank 解决什么问题？

向量相似度适合快速召回，LLM Rerank 对问题和候选内容做更细粒度相关性排序。我的修复重点
是确保 DashScope 真实 score 被读取；Runtime 15 题中 14 题发生改序，但不夸大为普遍提升准确率。

## 12. Structured Output 怎么兼容不同 Provider？

OpenAI 可以返回原生结构对象，DashScope 常返回 JSON 字符串。公共解析边界兼容 dict、Pydantic
对象、普通 JSON 和代码块 JSON，最后统一由同一个 Pydantic Answer Schema 校验。

## 13. Boolean 为什么需要 N/A？

True/False 会迫使模型在证据不足时猜测。Schema 使用 `Union[bool, Literal['N/A']]`，让知识库
无依据时能够明确弃答，同时不破坏原有 Boolean 数据模型。

## 14. Citation 是怎么校验的？

Generic Mode 用 `(document_id,page_number)` 对模型声明和本次 Retriever 返回页面做成员关系
校验。不同文档的相同页码不会混淆，无效引用被识别，模型未声明时不会自动补页。

## 15. Citation 校验能证明答案正确吗？

不能。它只证明引用来自检索集合，不证明页面语义蕴含答案。Semantic support 仍是明确未实现
边界，面试中不能把 membership 说成事实验证。

## 16. 为什么需要 Candidate Zone？

Agent 自动采集的内容可能来源不稳、字段错误或路径不安全，不应直接污染正式知识库。
Candidate Zone 把机器生成、人工审核和正式 ingestion 分开。

## 17. Agent 和 RAG 怎么联动？

Agent 生成包含 document.md、metadata.json、sources.json 和 raw_sources 的 Candidate Package；
RAG 只执行 import validation。Agent 不能调用 Embedding 或写 FAISS，人工显式 approve 后也
只是改变状态，正式 ingestion 仍是未来独立步骤。

## 18. Candidate v2 的两个 hash 有何区别？

`raw_file_hash` 可以读取本地原始文件字节重算并比对；`content_hash` 对应 Agent 的规范化证据
文本，但 RAG 包里没有独立规范化对象，所以只能校验 SHA-256 格式并保存，不能声称重算验证。

## 19. 为什么 OCR 不全局开启？

Native Text PDF 没必要付出 OCR 成本，还可能引入噪声。系统先判断文本是否足够，只有符合
条件的扫描页才 OCR，并用 cache 和 Quality Gate 控制成本与错误传播。

## 20. OCR confidence 出了什么问题？

0.65 阈值把 confidence=0.621376 的有效“1.1 目的”过滤了；统一降低阈值又会放进噪声。所以
最终结合中文密度、日期/条款结构和稳定页边位置，而不是只看单分数。

## 21. 横置表格页怎么恢复？

第 37 页 normal OCR 后仍为空，视觉证据显示它是横置表格。只对该显式异常页比较 90°和
270°，270°候选质量更好并恢复字段；独立 cache 保证不重跑其他页面。

## 22. Version Governance 怎么工作？

Manifest 定义 version family、版本日期和 ACTIVE/SUPERSEDED 关系。Resolver 识别当前、历史或
日期意图，产生 eligible document set；默认使用当前版本，明确询问旧版时加载独立历史资产。

## 23. 为什么不直接删除旧版本？

企业用户可能追溯历史制度，旧版本也用于审计和时间问题。删除会丢失历史语义，所以保留
SUPERSEDED 文档，但默认检索不把它与 ACTIVE 混用。

## 24. 版本治理的真实效果是什么？

同一 34 题 Retrieval Hit@1 从 v0.1 的 0.814815 提升到最终 0.925926；8 题 Version OFF/ON
Hit@1 从 0.75 到 1.0。这是检索指标，不是最终 Answer Accuracy。

## 25. 为什么不能用 cosine threshold 直接 Reject？

Answerable Top1 最低 0.4434，而 Unanswerable 最高 0.6862。样本阈值 0.70475 会误拒 6/27
Answerable；Held-out Hard Negative 平均分还高于 Answerable，所以没有稳定边界。

## 26. 什么是 Hard Negative？

它与语料主题高度相关、检索分数也可能很高，但问题要求的具体事实不在文档中，例如法规要求
记录却没有给出保存年限。它比“问天气”更能检验 Evidence Sufficiency。

## 27. 为什么 Pre-generation 只做 Shadow？

现有数据没有可部署的 hard reject 规则。Shadow 能保存信号、决策和失败分布，但不提前跳过
生成，避免无依据阈值伤害可回答问题。

## 28. Post-answer Enforcement 为什么可以上线？

它不猜答案置信度，只检查确定性不变量：结构是否合法、事实答案是否有引用、声明引用是否都
属于本次 evidence、N/A 是否与引用矛盾。Phase 2 已真实观察到两个引用失败。

## 29. Fail-closed 后返回什么？

对外保持原 Schema，返回 `N/A` 和空 Citation；内部 trace 保留 original result、validation、
reason code、decision 和 final result，不把策略细节泄漏到用户答案。

## 30. Trusted QA 是否增加额外 LLM 成本？

Post-answer Gate 是确定性代码，额外 LLM 调用为 0。正常回答仍需要原来的 Generation；
pre-generation Shadow 只读取已有 Retrieval 信号。

## 31. 为什么不做 Conflict Detection？

当前没有经标注的真实冲突数据，也没有明确业务裁决规则。Version Governance 只处理已知新旧
关系；贸然用 LLM 判冲突会扩大 Claim，秋招版本选择不实现。

## 32. 为什么不做 GraphRAG？

主要问题是数据质量、版本混用、引用和评测，不是关系图推理。加入 GraphRAG 会扩大复杂度，
但没有证据证明能解决当前失败。

## 33. 如何控制 Token 成本？

使用每文档局部 Top-K、全局 Top-K 和 Parent Page 控制上下文；大规模 Answer Evaluation 在
预计超过预算时停止；Gate 不增加 LLM 调用，Demo 优先回放 artifact。

## 34. 如何保证回归？

每个模块先增加最小 pytest，再跑相关测试和 Full regression。最终覆盖 Generic、Legacy、
Candidate、OCR、Version、Trusted QA 等 220 个测试，并保存阶段报告和冻结数据 hash。

## 35. 当前最大的限制是什么？

Retrieval miss 仍可能导致错误 N/A，Citation Membership 不验证 semantic entailment，而且没有
生产级 auth、异步、分布式和监控。因此定位是可信问答工程原型，不是 Production Ready。

## 36. 如果继续做，优先做什么？

只有真实面试反馈或岗位需求暴露缺口后再推进。生产方向会先做权限/租户、异步 ingestion、
可观测性和更大独立评测；语义验证需要专门标注数据，不会直接加一个 LLM Judge 冒充真值。

## 37. 你自己最重要的贡献是什么？

不是单个算法，而是把“能跑的竞赛原型”变成“行为可验证、失败可解释、Claim 有边界”的通用
RAG：先修基线，再做数据接入和版本，最后只上线有真实证据支持的确定性 Trusted QA 规则。
