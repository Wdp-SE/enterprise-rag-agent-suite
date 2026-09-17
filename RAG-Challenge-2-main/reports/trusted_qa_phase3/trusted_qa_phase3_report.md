# Trusted QA Phase 3：Deterministic Post-answer Fail-closed Enforcement

## 最终状态

`COMPLETE_POST_ANSWER_ENFORCEMENT_READY`

该状态仅表示已批准的、确定性的 post-answer enforcement 已完成并通过测试；不表示
Production Ready，也不表示全部 hallucination 已被解决。核心功能开发在本阶段后冻结，
下一阶段仅建议进入 RAG Autumn Recruitment Finalization。

## Enforcement 范围

- `OFF`：不写 Trusted QA trace，不改变响应。
- `SHADOW`：记录 pre-generation observation 和 post-answer audit/decision，不改变响应。
- `ENFORCE`：pre-generation 仍为 Shadow；仅在生成、Structured Output 解析和既有
  Citation Membership 校验之后执行确定性 fail-closed。
- `enforcement_scope = POST_ANSWER_ONLY`
- `pre_generation_enforcement = false`
- `post_answer_enforcement = true`
- `policy_version = trusted_qa_post_answer_v1`
- `gate_extra_llm_calls = 0`

`PRE_GENERATION`、`FULL` 及未知 scope 会明确抛出 `NotImplementedError`，不能通过配置
误启用未实现的 enforcement。

## 正式规则

1. Structured Output 无效：`STRUCTURED_OUTPUT_INVALID` → `FAIL_CLOSED`。
2. Generic 实质性答案未声明 Citation：
   `SUBSTANTIVE_ANSWER_WITHOUT_CITATION` → `FAIL_CLOSED`。
3. 声明的任一 Citation 不属于实际 retrieval evidence set（包括 valid/invalid 混合）：
   `CITATION_MEMBERSHIP_INVALID` → `FAIL_CLOSED`。
4. `N/A` 与非空 Citation 并存：
   `ANSWER_CITATION_STATE_CONFLICT` → `FAIL_CLOSED`。
5. `N/A + citations=[]`：`VALID_ABSTENTION`，保持原响应。
6. 实质性答案且所有声明 Citation 均通过既有 membership 校验：`PASS`。

Fail-closed 的对外结果保持现有 Schema：`final_answer = "N/A"`、引用字段为空。内部 trace
保留 original result、AnswerEvidenceAudit、PostAnswerEnforcementDecision 和 final result；
内部 reason code 不写入用户 answer 字段。

## 仍只在 Shadow 的信号

retrieval cosine、top-k 分布、margin、document/page diversity、retrieval agreement、版本
resolution observation 仍只用于 pre-generation Shadow。它们不参与正式 post-answer
enforcement。`UNCERTAIN` 不会预先跳过生成，也不会自动变成 `FAIL_CLOSED`；同样，
pre-generation `ANSWER` 不能绕过生成后的结构或引用失败。

真实 Smoke 中 `tqa-holdout-a06` 的 pre-generation 决策为 `UNCERTAIN`，但其 Structured
Output 与 Citation Membership 均合法，因此 post-answer 为 `PASS`，直接验证了两阶段决策
相互独立。

## Phase 2 保存结果离线回放

回放输入为冻结的 10 题 Phase 2 Answer Smoke 及其人工复核结果；未调用 Answer LLM、
未重新 retrieval，Gate 额外 LLM 调用为 0。

- 已知无效答案：2；拦截：2；Known Invalid Interception Rate = 1.0。
- 历史 Citation Membership Failure：2；拦截：2；Interception Rate = 1.0。
- 已知合法答案：2；保留：2；Preservation Rate = 1.0。
- 正确 N/A：5；保留：5；Preservation Rate = 1.0。
- False Fail-closed Count = 0。
- Structured Output Failure：保存的真实样本为 0；拦截证据仅来自确定性 fixture/unit test，
  明确标记为 `FIXTURE_ONLY`。
- 检索漏召回 N/A：1。结果仍为 N/A，但 Gate 不宣称修复 retrieval miss。

## 真实 Runtime Smoke

在 Unit Tests、离线回放和 Full Regression 通过后，仅执行一次有效的 4 题真实
DashScope/Qwen Smoke：2 个 Answerable、2 个 Hard Negative。首次启动因 FAISS 在 Windows
上无法打开含中文的绝对路径而在任何 Provider 调用前失败，token 为 0；失败记录保留为
`runtime_smoke_failed_path_attempt.json`。改为与既有 Phase 2 相同的项目根相对路径后执行
有效 Smoke；没有重建索引或修改检索逻辑。

- Structured Output：4/4 有效。
- Answerable：2/2 `PASS`，最终答案及合法 Citation 保留。
- Hard Negative：2/2 `VALID_ABSTENTION`，均为 `N/A + citations=[]`。
- 本次新 Citation Membership Failure：0；不据此否定 Phase 2 的两个真实失败。
- Fail-closed：0；False Fail-closed：0。
- Prompt / Completion / Total tokens：8,424 / 968 / 9,392，低于 20K 上限。
- 平均 / 最小 / 最大 latency：2,376.577 / 1,144.218 / 3,693.254 ms。
- Gate 额外 LLM 调用：0。

## Citation 能力边界

Citation Membership 只证明 `(document_id, page_number)` 属于当前 Retriever 实际返回的
证据页面，不证明引用在语义上支持答案。当前实现没有 LLM-as-Judge、NLI、cross-encoder
entailment 或其他 semantic support gate：

- `citation_membership_is_semantic_entailment = false`
- `semantic_entailment_verified = false`

因此 `PASS` 表示通过确定性结构/成员关系不变量，不等价于事实正确或语义蕴含已验证。

## 兼容性与回归

- 新增测试覆盖 PASS、VALID_ABSTENTION、结构错误、零 Citation、全部/部分非法 Citation、
  N/A/Citation 冲突、pre/post 独立、OFF/SHADOW/ENFORCE、无额外 LLM 调用、策略版本、
  original/final audit、Schema 兼容、Generic、Legacy、Version、Candidate v2 与 scope 拒绝。
- Targeted compatibility：146 passed / 0 failed。
- Full regression：220 passed / 0 failed，高于阶段前 201 passed 基线。
- 保留 1 个既有第三方 DashScope Assistants API deprecation warning；未为消除该 warning
  扩大任务范围。
- 未解析 PDF、未重新 Embedding、未重建 FAISS、未修改冻结 Corpus、Version、Retriever、
  Parent Page、Prompt、Structured Output Schema 或 Citation Validator 核心语义。
- Generic 对外字段保持兼容；Legacy submission 不新增强制字段；Candidate v2 未改变。

## 已知限制与结论

1. Post-answer policy 无法恢复 retrieval miss；Phase 2 的 1 个 false abstention 仍存在。
2. 合法 Citation Membership 不代表 semantic entailment，语义完整性仍需人工评测。
3. pre-generation Shadow 没有得到可部署的 hard reject 边界，因此继续禁止 pre-generation
   enforcement。
4. 当前指标来自已保存的 10 题回放、4 题真实 Smoke 和 unit fixtures，不称为 Production
   Accuracy。

项目可以进入 Finalization。秋招版建议立即冻结核心 RAG 功能，不再继续 Confidence v2、
Conflict、Semantic Entailment、GraphRAG、Agent enhancement、OCR optimization、Retrieval
tuning 或 UI 开发。
