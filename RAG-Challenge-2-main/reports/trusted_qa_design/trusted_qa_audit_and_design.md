# Trusted QA / Confidence & Reject Gate — Audit & Design

## 1. 阶段结论

状态：`DESIGN_COMPLETE_WITHOUT_GATE_IMPLEMENTATION`

本轮仅审计现有代码并复用已有评测结果做离线分析。没有修改 RAG 业务代码，没有调用
Answer LLM、Rerank、Embedding，没有解析 PDF，也没有重建 FAISS。

核心结论：当前数据不支持部署单一 cosine threshold。Top1 对样本有一定排序能力，
但 Answerable 与 Unanswerable 区间存在实质重叠；若使用当前样本中表现最好的单阈值，
会错误拒绝 6/27 条可回答题，其中包括 5 条已正确完成版本解析的题。Evidence Gate
应采用可解释的分层决策，而不是输出一个混合的 `confidence_score`。

## 2. 分析输入与边界

主分析集：

- `data/evaluation/domain_eval_v0_1.jsonl`
- 34 题：27 Answerable，7 Unanswerable
- 类型：15 single-document、7 cross-document、7 unanswerable、5 version-temporal
- 结果：`reports/version_governance/full_34_on_final/retrieval_results.json`
- 运行模式：归一化向量检索、Parent Page、Version Governance ON、Top-K=5

补充压力集：

- `data/evaluation/version_eval_v0_1.jsonl`
- 8 题，全部 Answerable，没有 Unanswerable 对照
- 结果：`reports/version_governance/version_extension_on/retrieval_results.json`
- 只用于观察版本问题的 score 范围，不参与 Reject 二分类阈值诊断

两个结果集都没有 Domain Rerank score。本轮没有为了补齐字段重新调用 Rerank。
历史 `domain_answer_smoke` 只有 3 题，并且来自早期运行快照，因此只证明信号可以产生，
不与本轮 34+8 题混合校准。

## 3. 当前可信问答调用链

```text
Question
  -> QuestionsProcessor
  -> VersionResolver（Generic + feature flag enabled 时）
  -> VectorRetriever / HybridRetriever
  -> 每文档 local Top-K
  -> global merge
  -> Parent Page composite dedup
  -> optional LLM Rerank
  -> Generic structured generation
  -> (document_id, page_number) citation membership validation
  -> Answer / N/A + validated sources
```

当前没有独立的 Evidence Sufficiency 决策步骤。拒答主要依赖 Generic Prompt 要求模型在
上下文不足时输出 `N/A`。这是一种生成行为，不是已校准、可解释的 Gate。

## 4. Runtime Signal 审计

| Signal | 当前是否存在 | 当前边界 |
|---|---:|---|
| Top1 / Top-K cosine | EXISTING | Retriever 结果的 `distance`；已是 normalized inner product，但批量答案输出不保留 |
| Top1-Top2 / Top1-Top5 margin | DERIVABLE | 当前没有显式字段；可由 Retriever 结果计算 |
| 文档多样性 | DERIVABLE | 可按 Top-K 中唯一 `document_id` 计算 |
| 页面多样性 | DERIVABLE | 必须按 `(document_id, page_number)` 计算；本次固定 Top-5 下全部为 5 |
| Rerank score | EXISTING_WHEN_ENABLED | `relevance_score` 存在于 Hybrid 结果；本次最终 34/8 题结果未启用 |
| Rerank rank change | PARTIAL | Hybrid 内部拥有重排前结果，但常规返回值没有保存 `original_rank` |
| Version intent / resolution | EXISTING | Resolver 可生成 trace；`get_answer_generic()` 可返回，批量输出路径会丢弃该 trace |
| Eligible document count | DERIVABLE | 可由 `VersionResolutionPlan.eligible_document_ids` 得到，当前无统一观测字段 |
| Structured N/A | EXISTING | Generic schema 支持 text/number/boolean/names 的 `N/A` |
| Answer type | EXISTING | 输入 schema 和解析后的 `final_answer` 类型可判断，但未形成统一审计字段 |
| Valid citation count | EXISTING | 可由校验后的 `sources` 数量得到 |
| Citation membership | EXISTING | Generic 使用 `(document_id, page_number)` 与 Retriever 结果校验 |
| Invalid citation count/reason | MISSING | Validator 过滤无效来源，但不返回被过滤数量和原因 |
| Citation semantic entailment | MISSING | membership 不证明引用语义支持答案 |
| Retrieval latency | PARTIAL | Evaluation runner 有记录；常规 QuestionsProcessor 结果未统一输出 |
| Answer token usage | PARTIAL | provider `response_data` 可得，但 QuestionsProcessor 并行时是共享可变状态 |
| Rerank token usage | PARTIAL | 单批调用可得，HybridRetriever 没有统一聚合/传播 |
| Error | EXISTING | 批处理结果包含结构化程度有限的 error string |

Parent Page 返回的 cosine 是触发该页面入选的 chunk score，不是整页重新计算的 score。
未来 Signal Collector 必须保留这个语义，不能把它描述为 page-level similarity。

## 5. 三种 Confidence 必须分离

### 5.1 Retrieval Confidence

描述检索器返回候选的强弱与稳定性，例如 cosine、margin、Top-K 分布、文档与页面分布。
它只能说明“语义上像不像”，不能说明候选是否完整回答了问题。

### 5.2 Evidence Sufficiency

描述候选证据是否覆盖问题所要求的事实、条件、时间和比较范围。这应成为 Reject Gate
的主要决策对象。它需要结合版本决策、证据覆盖和受约束的证据判断，不能只看 cosine。

### 5.3 Answer Confidence

描述生成后的答案是否被证据支持。当前只有 structured output、`N/A` 和 Citation
membership；没有自动 semantic entailment。现阶段不应声称系统已经估计 LLM 的通用
不确定性或输出了概率意义上的答案置信度。

## 6. Answerable vs Unanswerable 分布

以下统计均来自主分析集 34 题。

| Signal | Answerable min / max | Answerable mean / median | Unanswerable min / max | Unanswerable mean / median |
|---|---:|---:|---:|---:|
| Top1 cosine | 0.4434 / 0.8334 | 0.732141 / 0.7560 | 0.4765 / 0.6862 | 0.562943 / 0.5390 |
| Top3 mean | 0.4282 / 0.808633 | 0.705414 / 0.7353 | 0.455633 / 0.6668 | 0.537100 / 0.530567 |
| Top5 mean | 0.4017 / 0.79536 | 0.684872 / 0.71856 | 0.4038 / 0.65818 | 0.518149 / 0.52308 |
| Top1-Top2 margin | 0.0023 / 0.1233 | 0.0310 / 0.0224 | 0.0023 / 0.0701 | 0.0341 / 0.0305 |
| Top1-Top5 margin | 0.0153 / 0.2707 | 0.084444 / 0.0643 | 0.0276 / 0.2551 | 0.083371 / 0.0509 |
| Unique document count | 1 / 4 | 1.814815 / 2 | 1 / 3 | 2.142857 / 2 |
| Unique composite page count | 5 / 5 | 5 / 5 | 5 / 5 | 5 / 5 |

完整 p25、p75 和逐题信号保存在 JSON 产物中。

关键观察：

- Top1 的两类范围重叠区间为 `[0.4765, 0.6862]`。
- 排除 5 条 Domain 版本题后，普通 Answerable 的 Top1 仍与 Unanswerable 在
  `[0.6151, 0.6862]` 重叠。
- Unanswerable 最大 Top1 是 0.6862；有 6 条正确可回答题不高于该值：1 条跨文档题和
  5 条版本题。
- 以“高分更可能可回答”计算，Top1 的样本内 AUC 为 0.894180，但这只表示排序趋势，
  不表示存在无损阈值。
- 样本内诊断阈值 0.70475 可以拒绝 7/7 Unanswerable，但同时错误拒绝 6/27
  Answerable，False Reject Rate 为 22.2222%。该值不得作为部署配置。
- Top1-Top2 margin 的 AUC 为 0.468254，低于 Top1；两类均值也几乎相同，margin
  没有表现出更好的区分度。
- Top1、Top3 mean、Top5 mean 的相关系数为 0.970242～0.992679。把这些高度相关的
  score 简单加权，并不会自然形成可靠的多信号 Gate。
- 固定 Top-K 和 Parent Page 去重使每题都有 5 个唯一 composite pages，因此当前
  `retrieved_page_count` 完全没有区分能力。
- 8 条补充版本题的 Answerable Top1 范围是 0.4579～0.8632，进一步证明低 cosine
  不能直接解释成证据不足。

## 7. Citation 的可信边界

当前 Generic Citation Validator 正确保证：

- Citation 必须来自 Retriever 实际返回的页面；
- 校验键是 `(document_id, page_number)`；
- 模型没有声明合法引用时允许返回空列表；
- `final_answer == "N/A"` 时强制清空 sources；
- 不会自动补充页面。

它不能保证：

- 引用文本蕴含答案中的每个事实；
- 引用覆盖问题要求的全部条件；
- 同页中的其他内容不会被模型错误延伸；
- 多文档比较是否完整覆盖所有对象。

因此未来输出应分别记录 `citation_membership_valid` 与尚未实现的
`semantic_support_verified`，禁止用前者代替后者。

## 8. 推荐的最小 Gate 设计

### 8.1 独立数据结构

不要增加一个模糊的 `confidence_score`。建议分成三个内部对象：

```text
RetrievalSignalSnapshot
  - raw cosine scores and margins
  - document/page diversity
  - optional rerank scores and original ranks
  - version intent/resolution/eligible count

EvidenceSufficiencyDecision
  - decision: ANSWER | REJECT
  - reason_codes[]
  - supporting_sources[]
  - missing_information[]
  - signal_snapshot_ref

AnswerEvidenceAudit
  - answer_kind: SUBSTANTIVE | N/A
  - claimed_citation_count
  - valid_citation_count
  - citation_membership_valid
  - semantic_support_verified: null until a real verifier exists
```

这些对象应为内部 Generic 运行时模型，不修改 Candidate v2 或通用 DocumentMetadata。

### 8.2 未来调用链

```text
Question
  -> Version Resolution
  -> Retrieval / Parent Page / optional Rerank
  -> Signal Collector
  -> Deterministic Preconditions
       no result / no eligible document / unresolved explicit version
       => REJECT with reason
  -> Structured Evidence Sufficiency Judge
       sufficient evidence + explicit retrieved source membership
       => continue
       insufficient / partial / invalid source reference
       => REJECT / N/A + sources=[]
  -> Existing Structured Generation
  -> Existing Citation Membership Validation
  -> Post-answer fail-closed check
       substantive answer with zero valid citations
       => REJECT / N/A + sources=[]
  -> Answer + sources + explainable decision trace
```

Evidence Sufficiency Judge 的职责只限于“给定证据是否足够回答给定问题”，不要求它
预测模型正确率。其结构化输出至少应包括 verdict、依据页面、缺失信息和简短理由；
引用仍必须经过现有 composite Citation Validator。

### 8.3 确定性规则边界

适合直接作为 hard reject 的条件：

- Retriever 返回空集合；
- Version Resolver 对显式版本/明确日期给出不可消解错误，或 eligible document 为 0；
- Evidence Judge 返回 INSUFFICIENT/PARTIAL，或其所有 supporting sources 均未通过
  membership 校验；
- 生成结果为 substantive answer，但经过现有 Validator 后没有任何合法 Citation；
- 生成结果为 `N/A`，此时保持 sources 为空。

不适合直接作为 hard reject 的条件：

- 单独的 Top1 cosine；
- 单独的 Top1-Top2 margin；
- 文档数量多或少；
- Citation membership 已通过；
- `status=ACTIVE` 本身。

## 9. 第一版实施顺序建议

1. 先增加只观测、不改变答案的 `RetrievalSignalSnapshot`，解决批量路径丢失 score、
   version trace、rerank original rank 和 token/latency 的问题。
2. 在 Shadow Mode 运行现有 34 题和版本专项题，Gate 只记录 WOULD_ANSWER / WOULD_REJECT。
3. 为 Unanswerable 增加少量经人工核验、覆盖高语义相似陷阱的样本；当前 7 条不足以
   固化阈值。
4. 实现结构化 Evidence Sufficiency Judge，并复用现有 Citation membership 校验。
5. 仅在离线 Reject Accuracy、Answerable Retention 和分类型回归稳定后启用 fail-closed。
6. Rerank threshold 保持禁用，直到同一 Corpus v0.2 + Version Governance 快照上拥有
   足量 Answerable/Unanswerable rerank score。

## 10. 后续评测指标

至少需要：

- Reject Accuracy / Unanswerable Reject Rate
- False Accept Rate（不可回答却放行）
- False Reject Rate（可回答却拒答）
- Answerable Retention / Coverage
- Selective Accuracy 与 Risk-Coverage 曲线
- 按 single/cross/version/unanswerable 分片的结果
- Citation membership pass rate
- Substantive answer with zero valid citations count
- 人工抽检的 semantic support / unsupported claim
- Gate 增量 latency 与 token usage

Ground-truth 的 `expected_document_hit` 和 `expected_page_hit` 只能用于离线评测，严禁作为
Runtime Gate 输入。

## 11. 建议测试（下一编码阶段）

- 高 cosine 但缺少问题所求事实时拒答；
- 低 cosine 但显式历史版本已解析且证据完整时允许回答；
- Version ambiguity / missing indexed version 返回可解释拒答；
- Boolean schema 保持 `True / False / N/A`；
- `N/A` 始终清空 sources；
- 虚构 `(document_id, page_number)` 被过滤；
- substantive answer 的全部引用被过滤后 fail-closed；
- membership 通过时 `semantic_support_verified` 仍不得自动变成 true；
- Generic、Legacy、Candidate v2、Version Governance 回归不受影响；
- Shadow Mode 不改变现有答案。

## 12. 当前是否可以直接编码 Reject Gate

可以进入下一轮“Signal Instrumentation + Shadow Gate”实施，但不应直接上线 cosine
threshold 型 Reject Gate。当前最关键的数据缺口是：

- 只有 7 条 Unanswerable；
- 最终 34/8 题快照没有 Rerank score；
- 当前没有证据覆盖/语义支持标签；
- 常规 QuestionsProcessor 未完整传播检索与版本 trace；
- Citation Validator 只验证 membership。

因此当前阶段完成的是可信、可复现的审计与设计，而不是已实现 Reject 能力。
