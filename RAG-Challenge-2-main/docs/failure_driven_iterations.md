# Failure-driven Development Timeline

本项目没有按功能清单堆叠 RAG 技术，而是用真实失败证据决定下一步。以下每项均按
Problem / Evidence / Decision / Change / Validation 记录。

## 1. Qwen Structured Output 只是 JSON 字符串

- **Problem**：DashScope/Qwen 返回的 JSON 文本没有统一解析为 Pydantic Schema，下游可能把
  字符串当结构化对象。
- **Evidence**：Provider 分支调用链与 OpenAI 原生 structured output 行为不一致。
- **Decision**：保持多 Provider 兼容，在公共边界解析 JSON、代码块 JSON 和普通兼容响应。
- **Change**：增加统一 `parse_structured_response()`，使用现有 Answer Schema 校验。
- **Validation**：本地测试覆盖 Qwen JSON、代码块和字符串兼容；Runtime Structured Output
  15/15，Phase 2 为 10/10，Phase 3 为 4/4。

## 2. Rerank relevance score 固定为 0

- **Problem**：DashScope 分支没有正确读取模型评分，排序看似执行、实际不可用。
- **Evidence**：运行时结果的 `relevance_score` 固定为 0。
- **Decision**：修复响应解析和排序，不重写 Reranker。
- **Change**：统一 Provider/Model 配置与 DashScope score 提取。
- **Validation**：真实控制探针得到 0.7/0.1；15 题中 14/15 改变向量初排，Domain Smoke 3/3
  改序。

## 3. IndexFlatIP 未归一化

- **Problem**：未归一化向量的 inner product 不能解释为 cosine similarity。
- **Evidence**：原始 DashScope embedding 范数远离 1，旧 FAISS 分数语义不成立。
- **Decision**：文档和查询向量均 L2 normalize；旧索引禁止沿用。
- **Change**：在 ingestion 和 retrieval 的 embedding 边界归一化，并检测旧索引。
- **Validation**：Runtime 5/5 新索引为 IndexFlatIP，文档范数约 1，15 个查询范数约 1，
  分数位于 [-1,1]。

## 4. Citation 校验会补模型未声明的页码

- **Problem**：没有合法模型引用时，Validator 可能自动补检索页，制造“看起来可追溯”的答案。
- **Evidence**：`_validate_page_references()` 的旧行为允许满足最小页数而补页。
- **Decision**：Citation 只能过滤，不能发明。
- **Change**：空声明保持空；Generic 使用 `(document_id,page_number)` 成员关系。
- **Validation**：独立探针 `[11,999]` 只保留 11，空声明仍为空；15 题无有效 Citation 时未补页。

## 5. Company-only Competition Coupling

- **Problem**：问题不包含 company name 时直接失败；数据库选择、文件名和路由均围绕年报公司。
- **Evidence**：`QuestionsProcessor` 和 `retrieve_by_company_name()` 是唯一正常入口。
- **Decision**：最小增加 Generic/Legacy 双模式，不合并全部 FAISS，不改 BM25。
- **Change**：稳定 DocumentMetadata/document_id；每文档局部 Top-K 后全局 merge；Retriever 在
  QuestionsProcessor 初始化并复用。
- **Validation**：普通无公司名问题可跨 5 文档检索；真实 Generic Smoke 返回答案与复合来源；
  Legacy submission 回归保持通过。

## 6. 扫描 PDF 阻塞当前规范

- **Problem**：TSG 08—2026 共 54 页但只有封面文本层，无法进入当前版本检索。
- **Evidence**：Corpus v0.1 审计记录该文档 54 页、仅 1 页有文本，状态 OCR_REQUIRED。
- **Decision**：实现最小中文 OCR 适配，不对所有 PDF 全局打开 OCR。
- **Change**：页级触发、cache、quality gate 和 fail-closed 构建边界。
- **Validation**：54 页 OCR 结果可离线复用；Corpus v0.1 保持冻结，未伪造扫描正文。

## 7. OCR 0.65 阈值误删有效文本

- **Problem**：单一 confidence threshold 会删除有效法规段落。
- **Evidence**：confidence=0.621376 的有效“1.1 目的”在 0.65 阈值下被过滤；后续 0.60 也会
  丢失有效日期/条款结构。
- **Decision**：不继续拍脑袋降低阈值；结合 confidence、中文密度、日期/条款结构和稳定页边
  位置。
- **Change**：实现通用 hybrid block-retention rule，行业词只留在 validation fixture。
- **Validation**：小型已核验 fixture 上有效 3/3 保留、噪声 3/3 拒绝；不宣称通用 OCR Accuracy。

## 8. 横置表格第 37 页仍为空

- **Problem**：Normal OCR 有 raw blocks，但 retention 后第 37 页为空；源页实际是横置表格。
- **Evidence**：视觉核验和离线 assembly 证明该页非空，90°候选质量低，270°候选恢复 94 个
  meaningful chars。
- **Decision**：只对显式 orientation-suspected 页面做有限旋转恢复。
- **Change**：独立 rotation cache，固定比较 90°/270°，不覆盖 normal cache。
- **Validation**：270°得分 243.521277 并恢复表格字段；二次运行 cache hit，EasyOCR 调用 0；
  其他 53 页未重新 OCR。

## 9. 历史版本没有可检索资产

- **Problem**：Manifest 知道 2017/2026 关系，但明确询问旧版本时没有独立历史 FAISS。
- **Evidence**：Corpus v0.2 的版本题仍有歧义/失败，2017 文档不在默认索引。
- **Decision**：保留旧文档并建立独立 historical retrieval asset，不污染默认当前语料。
- **Change**：2017 版新增 46 pages、110 chunks/vectors；Version Resolver 根据 intent 和日期
  选择 current/historical eligible set。
- **Validation**：原 5 题版本子集从 0.6 到 1.0；8 题 Version OFF/ON Hit@1 从 0.75 到 1.0；
  非版本 29 题 Top-5 保持一致。

## 10. Cosine Reject 分布重叠

- **Problem**：希望用 score threshold 拒绝知识库无答案问题，但两类分数重叠。
- **Evidence**：Answerable Top1 最低 0.4434，Unanswerable 最高 0.6862；阈值 0.70475 会误拒
  6/27 Answerable；Held-out Hard Negative mean 0.720500 高于 Answerable 0.712550。
- **Decision**：不上线 single-score reject；pre-generation 保持 Shadow。
- **Change**：只增加 RetrievalSignalSnapshot、可解释决策和离线评测，不改变回答。
- **Validation**：Phase 1/2 保存了 34/20 题分布、False Reject/Accept/UNCERTAIN 和 coverage；
  最终明确 `POST_ANSWER_ENFORCEMENT_ONLY`。

## 11. 模型声明了未检索 Citation

- **Problem**：模型能生成内容合理但不可追溯的答案；旧流程过滤非法 Citation 后仍返回事实答案。
- **Evidence**：Phase 2 的 10 题真实 Smoke 中出现 2 个 Citation Membership Failure，过滤后
  valid citation=0。
- **Decision**：只对确定性 post-answer invalid states fail closed，不增加第二次 LLM Judge。
- **Change**：`trusted_qa_post_answer_v1` 在 Structured Generation 和既有 Citation Validation
  之后执行；保留原始结果和原因，对外返回 N/A + 空引用。
- **Validation**：保存结果离线回放 2/2 拦截，合法答案 2/2、正确 N/A 5/5 保留，False
  Fail-closed=0；4 题真实 ENFORCE Smoke 2 PASS + 2 VALID_ABSTENTION，额外 LLM 调用 0。

## 总结

这些迭代的共同原则是：先保存失败证据，再做最小改动，写测试并回归；当数据不能支持某个
功能（例如 cosine Reject、semantic entailment、Conflict Resolver）时，选择明确不上线，
而不是为了项目包装补造能力。
