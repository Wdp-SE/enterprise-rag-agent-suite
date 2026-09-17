# Trusted QA Signal Instrumentation + Shadow Gate Report

## 1. 阶段状态

`COMPLETE_NOT_READY_FOR_ENFORCEMENT`

Signal Instrumentation、确定性 Shadow Gate、Policy Ablation、34 题 Domain Shadow、
8 题 Version Stress 和 6 题真实 Post-answer Smoke 均已完成。Shadow Gate 从未修改最终
答案、Citation 或原检索链路。`ENFORCE` 仅保留枚举，任何启用尝试都会明确抛出
`NotImplementedError`。

当前数据仍不支持开启真实 Reject Enforcement。原因不是代码未完成，而是 42 题中没有
触发高确定性 Hard Reject；默认策略将所有 7 条 Unanswerable 留在 `UNCERTAIN`，因此
Reject Precision 尚无法估计。

## 2. Implemented Signal Model

新增独立 `src/trusted_qa/`，没有把 Gate 规则塞入 Retriever、Version Resolver 或
Citation Validator。

`RetrievalSignalSnapshot` 只记录事实：

- retrieved count；
- Top1/2/3、Top-5 cosine、Top1-Top2 margin、Top3/Top5 mean；
- 唯一文档、复合页面 `(document_id, page_number)`；
- dominant-document ratio、Top3 document concentration、相邻页面对数量；
- Version Governance 开关、intent、resolution status、ambiguity、eligible count；
- Citation candidate availability；
- Rerank availability/score/margin；
- Retrieval state validation issues。

Snapshot 不包含 `confidence_score`、`is_good`、`is_bad` 或 `should_reject`。

本次 42 题真实运行中：

- 42/42 返回 5 个 Parent Page；
- 42/42 Retrieval state valid；
- 42/42 有 Citation candidate；
- 41 个 Version resolution 为 `RESOLVED`；
- 1 个为 `AMBIGUOUS`；
- Rerank 42/42 为 `NOT_AVAILABLE`，对应 score 为 `null`。

## 3. Shadow Architecture

```text
Question
  -> Existing Version-aware Retrieval
  -> RetrievalSignalSnapshot
  -> Deterministic Preconditions
  -> EvidenceSufficiencyDecision (SHADOW)
  -> Existing Generation（不跳过）
  -> Existing Citation Validation（不修改）
  -> AnswerEvidenceAudit（SHADOW）
  -> Original Response
```

`QuestionsProcessor` 只把 trace 写入内部、线程安全的观测存储，并通过
`get_trusted_qa_traces()` 显式读取；现有 Answer response 不增加字段。

## 4. Preconditions

已实现的确定性前置条件：

| Condition | Shadow action |
|---|---|
| `NO_RETRIEVAL_RESULT` | REJECT |
| `INVALID_RETRIEVAL_STATE` | REJECT |
| `NO_ELIGIBLE_DOCUMENT` | REJECT |
| `VERSION_RESOLUTION_FAILED` | REJECT |
| `VERSION_AMBIGUITY` | UNCERTAIN |

版本歧义没有直接 REJECT，因为版本压力集中包含一条人工验证的可回答模糊年份题。Gate
只消费 Version Resolver 的既有输出，不重新解析日期，也没有修改 Resolver。

## 5. Soft Signals

Soft policy 使用两个来自前一轮分布分析的 calibration-only 正向提示：

- `top1 >= 0.75`；
- `top3_mean >= 0.70`。

只有两者同时满足才可进入 Shadow `ANSWER`；不满足时进入 `UNCERTAIN`，绝不因 cosine
低而进入 `REJECT`。0.75 接近 Answerable median 0.756，并高于当前 7 条
Unanswerable 的最大值 0.6862。该值只用于 Shadow 观察，不是生产阈值，也不是此前
0.70475 分割值的复制。

`top1 < 0.50` 只产生 `WEAK_RETRIEVAL_SIGNAL + UNCERTAIN`；其余无法进入强正向区域的
结果产生 `AMBIGUOUS_RETRIEVAL_SIGNAL + UNCERTAIN`。

## 6. Policy v0.1 与 Decision State

默认策略版本：`trusted_qa_shadow_v0_1`

支持状态：

- `ANSWER`：没有 hard failure，且进入 calibration-only 强正向区域；
- `REJECT`：只由高确定性 Hard Preconditions 产生；
- `UNCERTAIN`：版本歧义、弱信号或无法安全判定的中间区域。

运行模式：

- `OFF`：不采集/不返回 Shadow decision；
- `SHADOW`：采集并决策，但不改变现有行为；
- `ENFORCE`：接口预留，明确未实现，禁止静默拒答。

## 7. Stable Reason Codes

当前真正实现并可能输出的 pre-generation reason codes：

- `NO_RETRIEVAL_RESULT`
- `INVALID_RETRIEVAL_STATE`
- `NO_ELIGIBLE_DOCUMENT`
- `VERSION_RESOLUTION_FAILED`
- `VERSION_AMBIGUITY`
- `WEAK_RETRIEVAL_SIGNAL`
- `AMBIGUOUS_RETRIEVAL_SIGNAL`

Post-answer audit 另支持：

- `STRUCTURED_OUTPUT_INVALID`
- `ANSWER_IS_NA`
- `ANSWER_WITHOUT_VALID_CITATION`
- `CITATION_MEMBERSHIP_FAILED`

没有预先堆放未实现的 `INSUFFICIENT_EVIDENCE` 或 learned-confidence reason。

## 8. No-extra-LLM Proof

- `src/trusted_qa/` 不导入 `APIProcessor`、DashScope、OpenAI 或任何 LLM client；
- Retrieval-only runner 使用 `VectorRetriever`，没有构造 `HybridRetriever`；
- 42 题结果明确记录 `answer_llm_called=false`、`rerank_called=false`、
  `gate_extra_llm_calls=0`；
- 单元测试验证 OFF/SHADOW 都只调用一次 Retriever 与一次原 Answer generator；
- 6 题真实 Smoke 只有原流程的 6 次 Answer generation，Gate 调用为 0。

## 9. 34-question Domain Shadow Result

默认 `HARD_PLUS_SOFT`：

| Ground Truth | ANSWER | REJECT | UNCERTAIN |
|---|---:|---:|---:|
| Answerable（27） | 16 | 0 | 11 |
| Unanswerable（7） | 0 | 0 | 7 |

Counterfactual metrics：

- Shadow Answerable Acceptance Rate：0.592593
- Shadow Unanswerable Rejection Rate：0.0
- Shadow False Reject：0 / 27，rate 0.0
- Shadow False Accept：0 / 7，rate 0.0
- Shadow Uncertain：18 / 34，rate 0.529412
- Coverage：0.470588
- Potential Selective Accuracy：1.0
- Shadow Reject Precision：`null`（没有 REJECT，不能计算）

`Potential Selective Accuracy=1.0` 只代表当前小样本 Shadow 反事实，且策略使用同一数据
分布确定 calibration-only 正向区域，禁止描述为 Production Accuracy。

## 10. Answerable / Unanswerable 结果解释

可回答题没有被错误 REJECT，但 11/27 被保守地放入 UNCERTAIN。不可回答题没有被错误
ANSWER，但也没有一个触发 Hard Reject；7/7 全部进入 UNCERTAIN。这符合 Phase 1 的
“Reject Precision 优先”方向，却同时说明当前没有证据估计真正的 Reject Precision。

默认策略的 42 题 reason 分布：

- `AMBIGUOUS_RETRIEVAL_SIGNAL`：16
- `WEAK_RETRIEVAL_SIGNAL`：6
- `VERSION_AMBIGUITY`：1

## 11. Version Stress Result

8 条 Version Answerable：

- ANSWER：3
- REJECT：0
- UNCERTAIN：5
- Acceptance Rate：0.375
- False Reject Rate：0.0
- Coverage：0.375

其中明确的模糊年份题由现有 Resolver 标记为 `VERSION_AMBIGUITY`，Shadow Policy 保持
UNCERTAIN，没有重新解释时间，也没有误拒绝其他低 cosine 历史版本题。

## 12. Policy Ablation

| Domain policy | Answerable A/R/U | Unanswerable A/R/U | False Accept | False Reject | Coverage |
|---|---:|---:|---:|---:|---:|
| Hard only | 27/0/0 | 7/0/0 | 7 | 0 | 1.0 |
| Hard + soft | 16/0/11 | 0/0/7 | 0 | 0 | 0.470588 |
| Hard + soft + agreement | 16/0/11 | 0/0/7 | 0 | 0 | 0.470588 |

结论：Hard-only 对当前 7 个无答案问题没有识别能力；Soft signal 可以把它们转入
UNCERTAIN，但还不能安全 REJECT。当前 concentration/page-neighborhood agreement 没有
带来增益，因此不应仅为了增加规则复杂度进入后续 Enforcement。

## 13. Hard Negative Coverage

对原有 7 条 Unanswerable 完成人工语义审计：

- HARD：5
- EASY_OR_MEDIUM：2
- 新增 Hard Negative：0

五条 Hard Negative 分别覆盖：事故年度统计缺失、企业保险具体价格缺失、地方规则缺失、
安全总监薪资缺失、未来版本发布日期缺失。它们都与语料主题高度相关或可检索到邻近
内容，但缺少问题所需事实。已有数量达到阶段最低 5 条，因此没有扩写 Ground Truth。

## 14. AnswerEvidenceAudit 与真实 Answer Smoke

Retrieval-only 42 题的 post-answer 字段均如实为 `NOT_AVAILABLE`。

在预算确认后，额外运行 6 题真实 Qwen Smoke：3 Answerable + 3 Hard Negative，关闭
Rerank，Gate 不增加模型调用。

- 预估：16,266 tokens，保守上限 20,000，停止线 30,000；
- 实际 Answer usage：10,843 prompt + 979 completion = 11,822 tokens；
- Answerable：3/3 返回实质答案，合法 Citation 数分别为 1、2、1；
- Unanswerable：3/3 返回 `N/A`，Citation 均为 0；
- Structured output：6/6 valid；
- Citation membership：6/6 通过；
- 平均端到端 latency：1,690.625 ms；最大 2,458.925 ms。

其中 2 条低分 Answerable 在 pre-generation 被标记 UNCERTAIN，但原 Generation 仍正常
执行并给出带合法 Citation 的答案；3 条 Unanswerable 也先标记 UNCERTAIN，随后原模型
自行返回 `N/A`。这直接证明 Shadow 没有跳过或改写 Generation。

`citation_membership_valid=true` 仍不等于 semantic entailment。Audit 中
`semantic_support_verified` 始终为 `null`，没有伪造语义支持结论。

## 15. Runtime / Regression

- 42 题 Retrieval latency：min 117.411 ms，mean 158.821 ms，median 153.642 ms，
  max 306.397 ms；
- 新增 Trusted QA tests：27 passed；
- Full regression：187 passed / 0 failed；
- 唯一警告：DashScope Assistants API deprecation，与本阶段代码无关；
- 没有 OCR、PDF Parse、文档 Embedding、FAISS rebuild、Search 或 Agent 操作。

## 16. Compatibility

- Generic：答案字段不变，trace 通过独立 accessor 读取；
- Legacy：默认 `trusted_qa_mode=OFF`，SHADOW fixture 也保持响应字段不变；
- Version Resolver：只读消费 plan，没有修改 resolver 或 temporal logic；
- Candidate v2 / DocumentMetadata：没有新增 Trusted QA 字段；
- Citation Validator：原 composite membership 逻辑未修改；
- Parent Page / Rerank / Prompt / Structured Output：均未修改。

## 17. Remaining Limitations

- 只有 7 条 Unanswerable，Reject Precision 仍不可估计；
- 42 题没有自然 Rerank score，不能设计 rerank threshold；
- Soft calibration 来自同一小样本，不具备跨语料泛化证据；
- Agreement signal 的本次 ablation 没有增益；
- Citation 仅验证 membership，没有 semantic entailment；
- 6 题 Answer Smoke 不能替代完整 Answer Evaluation；
- Answer token usage 可记录，Embedding provider 未返回查询 token usage；
- 常规 QuestionsProcessor 的历史 `response_data` 仍是共享状态，未来并行精确 token
  归因需要独立 request trace，但本轮没有扩大改造范围。

## 18. 是否可以进入 Enforce Gate

结论：`NO`。

缺少的关键证据：

1. 至少一组真实触发 Hard Reject 的、人工核验的 runtime case，用于估计 Reject
   Precision，而不是只靠单测；
2. 更多高相似 Hard Negative，以及不同文档场景中的外部验证集；
3. 同一 Corpus/Version 快照上的 Rerank signal（若未来策略准备使用它）；
4. Citation semantic support 或可审计的证据覆盖标签；
5. Shadow policy 在未参与 calibration 的留出集上的结果；
6. 更高的安全 Coverage，避免把多数问题永久停留在 UNCERTAIN。

下一阶段应继续收集 Shadow 证据并设计高精度 deterministic reject case，不应把
UNCERTAIN 偷换成 REJECT，也不应启用 `ENFORCE`。

## 19. 本阶段产物

- `signal_snapshots.json`
- `shadow_decisions.json`
- `shadow_metrics.json`
- `shadow_failure_cases.json`
- `policy_ablation.json`
- `hard_negative_audit.json`
- `answer_smoke_token_estimate.json`
- `answer_smoke_results.json`
- 本报告

本阶段满足 Signal Instrumentation、deterministic Shadow、0 extra Gate LLM、响应兼容、
False Reject/False Accept 量化和 UNCERTAIN 可追溯等成功标准；完成后保持 ENFORCE、
Learned Confidence、Conflict Detection 关闭。
