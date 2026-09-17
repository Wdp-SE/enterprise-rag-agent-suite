# STAR / Failure Stories

## Story 1：Structured Output 看似成功，实际还是字符串

**Situation**：原项目对多个 Provider 使用同一“结构化输出”说法，但 DashScope/Qwen 返回的是
JSON 文本，下游按字典读取可能失败。

**Task**：在不移除 OpenAI/Gemini/IBM 兼容性的前提下，让 Answer Schema 行为真实一致。

**Action**：沿调用链检查 Provider 返回类型，在统一边界兼容 dict、Pydantic、普通 JSON 和
代码块 JSON，再由 Pydantic 校验；为普通字符串保留合理兼容路径。

**Result**：Runtime 15/15、Phase 2 10/10、Phase 3 4/4 Structured Output 有效，相关本地测试
稳定通过。

**Lesson**：接口名称叫 Structured Output 不代表实际对象已经结构化，必须验证运行时类型和
下游契约。

## Story 2：OCR 0.65 阈值删除了正确条款

**Situation**：扫描法规 OCR 需要过滤噪声，最初使用 confidence 0.65 作为简单阈值。

**Task**：既保留有效法规文本，又避免把页边和乱码写入 Corpus。

**Action**：保存低置信 block，人工核验发现 confidence=0.621376 的“1.1 目的”被误删；进一步
比较 0.60/0.50 后，改用 confidence + 中文密度 + 日期/条款结构 + 稳定页边位置的通用规则。

**Result**：已知有效 3/3 保留、已知噪声 3/3 拒绝，规则不依赖特种设备关键词。

**Lesson**：模型 confidence 是信号，不是真值；阈值必须通过具体 false negative/positive
共同校准。

## Story 3：54 页 OCR 跑完，第 37 页仍是空的

**Situation**：Normal OCR 完成后 Quality Gate 发现第 37 页无有效文本，但源 PDF 页面并非空页。

**Task**：恢复该页，又不能重跑所有页面或把场景字段硬编码进生产逻辑。

**Action**：视觉核验确认横置表格，只对显式 orientation-suspected 页比较 90°/270°；独立缓存
每个候选，用字符量、中文比例、结构信号和乱码比例评分。

**Result**：270°候选恢复 94 meaningful chars 和主要表格字段；其他 53 页新增 OCR=0，复验
全部 cache hit。

**Lesson**：质量门禁必须 fail closed；异常恢复应该局部、可追溯且不破坏正常缓存。

## Story 4：版本关系有了，但旧版仍无法检索

**Situation**：Manifest 已记录 2017 被 2026 取代，但明确询问旧版时，默认索引里没有 2017
检索资产。

**Task**：支持历史追溯，同时不让旧版污染默认当前问答。

**Action**：为 2017 建立独立 46 pages / 110 vectors 历史资产；Resolver 根据问题意图和日期
产生 eligible set，默认当前版、明确历史时按需加载。

**Result**：原 5 题版本子集从 0.6 提升到 1.0，8 题 Version OFF/ON Hit@1 从 0.75 到 1.0；
非版本题 Top-5 保持一致。

**Lesson**：Metadata 关系本身不等于可检索能力，治理决策必须和真实索引资产闭环。

## Story 5：Cosine Threshold 在 Held-out 上失败

**Situation**：计划为无答案问题设置 similarity threshold，但旧数据已显示分布重叠。

**Task**：判断是否有足够证据上线 pre-generation Reject，而不是为了功能清单强行给阈值。

**Action**：统计 34 题分布，再冻结 20 题独立 Held-out。诊断阈值 0.70475 会误拒 6/27
Answerable；Held-out Hard Negative Top1 mean=0.720500，高于 Answerable 0.712550。

**Result**：拒绝上线 cosine Reject，pre-generation 保持 Shadow；阶段结论明确为
`POST_ANSWER_ENFORCEMENT_ONLY`。

**Lesson**：不上线一个数据不支持的功能也是工程结果；离线指标不能被选择性解释。

## Story 6：引用被过滤后，事实答案仍然返回

**Situation**：Phase 2 真实 Qwen Smoke 中有两个答案内容看似合理，但声明页不属于本次 Retrieval；
旧流程只是删除 Citation，仍返回事实答案。

**Task**：在不增加 LLM Judge、不改变 Retriever 的前提下建立可靠失败边界。

**Action**：实现 `trusted_qa_post_answer_v1`：Structured Output/Citation validation 后检查确定性
不变量，任何成员失败都 fail closed；对外 N/A，内部保存 original/audit/decision/final。

**Result**：历史失败离线回放 2/2 intercepted；合法答案 2/2、正确 N/A 5/5 preserved，False
Fail-closed=0；真实 4 题 Smoke 为 2 PASS + 2 VALID_ABSTENTION，额外 LLM 调用 0。

**Lesson**：Citation Membership 不能证明语义正确，但确定性成员失败足以成为安全拦截条件；
不要悄悄删引用后继续返回不可追溯答案。
