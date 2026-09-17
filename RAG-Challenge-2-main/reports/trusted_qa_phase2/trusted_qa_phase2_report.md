# Trusted QA Phase 2 Report

## 1. 结论

阶段状态：`COMPLETE`

Enforcement Readiness：`POST_ANSWER_ENFORCEMENT_ONLY`

本阶段没有启用 `ENFORCE`，没有修改最终 Answer/Citation，也没有调整冻结的
`trusted_qa_shadow_v0_1`、Retriever、Embedding、FAISS、Chunk、Top-K、Parent Page、
Version Resolver、Citation Validator 或 Answer Prompt。没有运行 OCR、PDF Parse、
Embedding 建库、FAISS rebuild、Rerank、搜索或 Agent。

当前证据不支持 Pre-generation Reject 上线，但支持在后续单独评审后，对结构错误、
无有效引用和引用成员校验失败实施确定性的 Post-answer fail-closed。单 cosine threshold
仍不具备实施依据。

## 2. Held-out 冻结与 Ground Truth

新增 `data/evaluation/trusted_qa_holdout_v0_1.jsonl`，共 20 题：

- Answerable：10
- Unanswerable：10
- Easy Negative：3
- Hard Negative：7

每题保存 question id/text/type、answerable、expected documents/pages、reference answer、
key points、unanswerable reason、difficulty、negative class、notes 和人工 review status。
所有 Answerable 的事实与页码均从冻结的已解析 Markdown 人工核验；所有 Unanswerable
均通过冻结语料范围和去空白全文缺失项检查确认，没有使用 LLM 生成或审核 Ground Truth。

Hard Negative 覆盖：事故现场到达时限、死亡赔偿固定金额、每单位年度检查次数、日管控
记录保存年限、考核指南合格分、保险最低赔偿限额和使用登记具体收费。这些问题与语料主题
高度相关，但目标数值或条件不在当前 Corpus 中。

留出集在第一次 Gate 运行前冻结：

- SHA-256：`c23c95ca1a97e67520bc2deeee03933f4661414e3991b5118430cdce98798f71`
- `evaluated_before_freeze=false`
- `holdout_contaminated=false`
- 与 Domain 34、Version 8 及 Phase 1 Smoke 6 的 question id/规范化题面精确重合：0
- 未在看到结果后修改或删除题目

语义独立性为人工核验结论；代码只自动防止 ID 和规范化题面的精确复制，不夸大为自动语义
去重。

## 3. Frozen v0.1 Retrieval-only 运行

调用链：

`Frozen Holdout -> Version Resolver -> Existing Vector Retrieval -> Parent Page -> Signal Snapshot -> trusted_qa_shadow_v0_1`

配置与边界：

- 仅生成 20 条 DashScope `text-embedding-v1` 查询向量
- Top-K=5，per-document Top-K=8
- Parent Page=true，Version Governance=true
- Answer LLM=false，Rerank=false，Gate extra LLM calls=0
- Policy 调整=false

结果：

| Ground Truth | 数量 | ANSWER | REJECT | UNCERTAIN | False Accept/Reject | Uncertain Rate | Coverage |
|---|---:|---:|---:|---:|---:|---:|---:|
| Answerable | 10 | 4 | 0 | 6 | False Reject 0/10 | 0.600000 | 0.400000 |
| Easy Negative | 3 | 0 | 0 | 3 | False Accept 0/3 | 1.000000 | 0.000000 |
| Hard Negative | 7 | 3 | 0 | 4 | False Accept 3/7 | 0.571429 | 0.428571 |
| Overall | 20 | 7 | 0 | 13 | False Accept 3/10；False Reject 0/10 | 0.650000 | 0.350000 |

Observed REJECT=0，因此 Observed Reject Precision 为 `null`，证据状态为
`SAMPLE_SIZE_INSUFFICIENT`。按阶段约束，不把 UNCERTAIN 强制转成 REJECT，结论为：

`PRE_GENERATION_HARD_REJECT_EVIDENCE_INSUFFICIENT`

## 4. Retrieval Signal 观察

- Answerable Top1：min 0.5549，max 0.8385，mean 0.712550
- Easy Negative Top1：min 0.4902，max 0.6739，mean 0.571267
- Hard Negative Top1：min 0.6052，max 0.8162，mean 0.720500
- Answerable 预期文档/页命中：9/10；`tqa-holdout-a02` 同时漏文档和漏页
- 平均 Retrieval latency：Answerable 204.619 ms；Easy Negative 167.348 ms；Hard Negative 201.399 ms

Hard Negative 的 Top1 均值高于 Answerable，且高分区间显著重叠。3 条 Hard Negative
因为进入 frozen v0.1 的强分数区域而得到反事实 `ANSWER`。这直接否定了把 cosine 强度
当作 Evidence Sufficiency 的做法，也没有证据支持新增 margin/agreement heuristic。

因此未创建 `trusted_qa_candidate_v0_2`。在查看 Held-out 后据此调规则会污染验证集；如未来
确需 v0.2，只能使用 Calibration/Development Set 和新的明确故障机制进行设计，再使用新
的未见验证集。

## 5. 一次性 10 题 Answer Smoke

选择 5 Answerable + 5 Hard Negative，覆盖 frozen v0.1 的全部 3 个 Hard Negative
反事实误放行案例、两个高分 UNCERTAIN，以及 Answerable 漏召回案例。

运行前基于 Phase 1 的 6 题/11,822 tokens 估算：

- 点估计：19,704
- 1.25 倍保守估计：24,630
- 停止线：30,000

实际只执行一次：

- Prompt tokens：21,095
- Completion tokens：2,088
- Total answer tokens：23,183
- 平均 latency：2,126.254 ms
- 中位 latency：1,694.389 ms
- Structured Output：10/10 valid
- Gate extra LLM calls：0

Embedding 请求的 token usage 不由当前 Provider 响应返回，未编造到上述统计中。

## 6. Pre-generation 与生成结果的真实关系

5 条 Hard Negative 中，Pre-generation 为 3 ANSWER / 2 UNCERTAIN，但 Qwen 最终全部返回
`N/A` 且 citations 为空：

- Correct Abstention：5/5，1.0
- Unsupported Answer：0/5，0.0

这证明当前样本中，强检索信号不代表证据充分；把这 3 条在生成前强制放行也没有价值。
相反，现有 Evidence-aware Generation 能在高相似但不蕴含答案的上下文中正确弃答。

5 条 Answerable 中：

- 2 条返回有合法成员引用的实质答案
- 2 条返回实质答案，但模型声明的引用不属于实际检索复合页，过滤后 citations=0
- 1 条因目标文档/页未进入 Top-5 而返回 N/A，属于 False Abstention

`tqa-holdout-a02` 表明 Post-answer 规则无法修复 Retrieval Recall；本阶段按冻结边界只记录，
不修改检索。

## 7. Post-answer Candidate（Shadow Only）

新增隔离的 `trusted_qa_post_answer_candidate_v0_1`，只读取已有
`AnswerEvidenceAudit`，不修改 Response：

- Structured Output invalid -> `FAIL_CLOSED`
- 实质答案且 valid citation=0 -> `FAIL_CLOSED`
- 任一声明引用未通过 `(document_id, page_number)` membership -> `FAIL_CLOSED`
- 明确 `N/A` 且 citations 为空 -> `VALID_ABSTENTION`
- 结构及引用成员均合法 -> `ALLOW_ANSWER`

10 题真实结果：

- `ALLOW_ANSWER`：2
- `VALID_ABSTENTION`：6（其中 5 个正确 Hard Negative，1 个 Answerable False Abstention）
- `FAIL_CLOSED`：2
- Citation Membership Failure：2/10
- Structured Output Failure：0/10
- Candidate Fail-closed：2/2 均有真实确定性引用不变量支持

2/2 只能报告 Observed Potential Fail-closed Precision=1.0，样本状态仍为
`SAMPLE_SIZE_INSUFFICIENT`，不能表述为稳定生产指标。两个案例均来自 Answerable：一个答案
内容人工核验正确但不可追溯，另一个答案不完整且不可追溯；二者都应按可信问答边界关闭。

Citation Validator 只证明引用页属于 Retriever 返回集合。`membership valid` 从未被当作
semantic entailment；本阶段没有实现 LLM Judge 或 Entailment Model。

## 8. Version Ambiguity

Held-out 没有产生 Version Ambiguity。复用 Phase 1 Version Stress 的真实案例：
`vg-ambiguous-year-001` 的 Resolver issue 为
`TEMPORAL_YEAR_CROSSES_VERSION_BOUNDARY`，Ground Truth 要求解释 2026 年跨越 5 月 1 日版本
切换，而不是拒答。因此该类型必须保留 UNCERTAIN/可回答边界，不能硬拒绝。

只有未来 Resolver 提供明确的“用户要求唯一版本且无法确定、也无法形成边界解释”的 typed
outcome，并有独立样本证据时，才可考虑 Version Ambiguity Hard Reject。当前没有这样的
证据，故本阶段不增加规则。

## 9. Readiness 决策

最终选择：`POST_ANSWER_ENFORCEMENT_ONLY`。

含义是：

1. Pre-generation 继续 SHADOW；保留 UNCERTAIN，不启用 cosine reject。
2. 已有确定性 invalid-state preconditions 保留，但本 Held-out 未观察到真实 REJECT，Reject
   Precision 不可估计。
3. 下一次若经评审实施 Enforcement，只应上线结构/Citation 的 Post-answer fail-closed 和
   `N/A + empty citations` 合法弃答，不应顺带启用 Pre-generation 分数规则。
4. 当前代码仍明确拒绝 `trusted_qa_mode=ENFORCE`；本阶段没有偷偷改变该行为。

## 10. 新问题与限制

1. 一个 Answerable 在 Top-5 漏掉目标文档和页面，导致正确但保守的 N/A。
2. 两个 Answerable 的模型引用了未检索复合页，现有 Validator 正确过滤；说明 Post-answer
   fail-closed 有真实价值，也说明仅靠 Prompt 不能保证引用成员正确。
3. 一个 Answerable 的答案遗漏部分报告字段；Citation fail-closed 恰好拦截，但 Citation
   校验本身不能检测语义完整性。
4. Hard Negative 的 cosine 比 Answerable 更高，Pre-generation score rule 不可用。
5. 实际 candidate fail-closed 只有 2 例，样本仍不足以形成稳定生产统计。
6. 当前没有可安全硬拒绝的 Version Ambiguity 类型样本。

## 11. 测试与回归

新增 14 个 Phase 2 本地测试，覆盖：严格 Held-out Schema、冻结 Hash、精确独立性、Hard/Easy
Negative 约束、分组 Shadow 指标、Post-answer allow/abstain/fail-closed、N/A 与 Citation
矛盾、Citation membership 边界及不修改 Response。

最终 Full Regression：`201 passed / 0 failed`。唯一 warning 为已有 DashScope Assistants API
弃用警告，与本阶段无回退关系。

## 12. 是否可以进入 Finalization

可以，范围为：冻结并展示本阶段证据，明确 Pre-generation 保持 Shadow；如最终评审批准
实际 Enforcement，另起最小实现只接入已经验证的 Post-answer deterministic rules。当前
项目没有启用 ENFORCE，也没有宣称已验证 Citation 语义蕴含。

结构化结论见 `enforcement_readiness.json`，真实运行明细见 `answer_smoke_results.json`，
人工核验见 `answer_smoke_manual_review.json`。
