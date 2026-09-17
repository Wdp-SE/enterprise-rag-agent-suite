# Exceptional Page Rotation OCR Recovery + Corpus v0.2 Report

## 1. 阶段结论

本阶段状态：**COMPLETE**。

物理第 37 页通过最小旋转恢复，完整 OCR Quality Gate 随后通过；Corpus v0.2 已独立构建，旧 v0.1 未覆盖。仅为新增的 TSG 08—2026 生成了 78 个 Embedding 和单文档 FAISS。版本子集与全部 34 题 Retrieval/Citation 已真实刷新，没有执行 Answer LLM、Rerank 调参、Confidence Gate 或 Version Resolver。

## 2. Rotation Trigger 与原始失败证据

触发条件全部满足：Native Text 不足、normal OCR 已执行、源页 render 非空、Hybrid Retention 后有效字符为 0，且页面被显式标记为 `OCR_ORIENTATION_SUSPECTED`。

Normal OCR page 37 有 26 个 raw blocks，但 Hybrid Retention 后保留 0 个。视觉核验确认源页不是空页，而是横置的“压力管道基本信息汇总表”。Rotation Recovery 没有覆盖 normal cache，也没有扫描其他 53 页。

## 3. 90° / 270° 比较

| Rotation | Raw blocks | Retained blocks | Meaningful chars | Chinese ratio | Garbled ratio | Score | Result |
|---:|---:|---:|---:|---:|---:|---:|---|
| 90° | 51 | 6 | 13 | 0.000000 | 0.882353 | 19.352941 | FAIL |
| 270° | 56 | 35 | 94 | 0.851064 | 0.375000 | 243.521277 | SELECTED / PASS |

候选评分只使用有效字符数、保留 block 数、中文比例、通用结构信号与 garbled ratio。生产模块不包含表名、行业名或字段名；同分时固定优先 90°。

## 4. Page 37 恢复质量

选择方向：270°；状态：`OCR_ROTATION_RECOVERED`；物理页码保持 37。

完整恢复表名，并恢复或按表格布局拆分恢复以下字段信号：使用单位、管道名称、使用登记编号、途经区域、设计压力、工作压力、公称直径、公称厚度、管道材质、管道级别、介质。验证字段只存在于场景 validation runner，不参与 production orientation selection。

## 5. Cache 行为与 OCR 调用

独立 cache identity 包含 source file SHA-256、physical page number、rotation degree、OCR config SHA-256、rotation config SHA-256 与 retention config SHA-256。90°和 270°结果分别保存，raw blocks、retained blocks 与 assembled text 均保留。

- Cache 生成运行：2 次 EasyOCR，分别对应 page 37 的 90°与 270°。
- 当前复验运行：两个候选均 cache hit，EasyOCR 0 次。
- 同次第二遍复验：两个候选均 cache hit，EasyOCR 0 次。
- 其他 53 页新增 OCR：0 次。
- Normal page 37 cache：SHA-256 前后一致。

## 6. Full OCR Quality Gate

使用已有 normal cache + Hybrid Retention + page 37 rotation cache 离线重新 assembly。结果：

- 54/54 physical pages 有有效处理结果。
- Page 37 不再为空。
- 标题、文号、发布日期、生效日期、主体责任、使用登记、至少 5 个条款编号和 page 37 表格信息均通过。
- Native page unchanged、known-valid 3/3、known-noise 3/3、无 replacement character、无已知 header/footer/watermark 污染。
- Offline full reassembly OCR invocation：0。
- OCR Quality Gate：**PASS**。

## 7. Corpus v0.2 与 Artifact Reuse

Corpus v0.2 位于 `data/domain_corpus_v0_2/`，没有覆盖 v0.1。TSG 08—2026 为 `ACTIVE / OCR_SUCCEEDED / included_in_default_index=true`；TSG 08—2017 继续保持 `SUPERSEDED / VERSION_TEST`，未加入默认 ACTIVE index。

4 份旧 ACTIVE 文档仅在以下条件全部相等时复用：file SHA-256、DashScope `text-embedding-v1`、L2 normalization、chunk size 300、overlap 50、`generic-document-v1-compatible` metadata schema。结果为 4/4 `ALL_REUSE_CONDITIONS_MATCH`，复用 241 个 embeddings。

TSG 08—2026 新建 54 pages、78 chunks、78 embeddings 和独立 FAISS。第一次增量请求被本地网络沙箱拒绝，没有生成索引；授权后的重试只处理 1 份新报告并成功。没有重新 embedding 未变化文档。

## 8. Ingestion Statistics

| Metric | v0.1 | v0.2 | Delta |
|---|---|---|---|
| Indexed documents | 4 | 5 | +1 |
| Indexed pages | 128 | 182 | +54 |
| Chunks / vectors | 241 | 319 | +78 |

5 个 per-document FAISS 均通过 chunk/vector 数量一致、1536 维和单位范数检查；因此 IndexFlatIP 分数仍可解释为 normalized cosine similarity。

## 9. Version / Temporal 子集

| Metric | v0.1 | v0.2 |
|---|---:|---:|
| Hit@1 / Hit@3 / Hit@5 | 0 / 0 / 0 | 0.6 / 0.6 / 0.6 |
| Recall@1 / Recall@3 / Recall@5 | 0 / 0 / 0 | 0.5 / 0.5 / 0.5 |
| MRR | 0 | 0.6 |
| Document Citation Accuracy | 0 | 0.52 |
| Page Citation Accuracy | 0 | 0.12 |
| Document/Page Citation Hit Rate | 0 / 0 | 0.6 / 0.6 |

5 题中 3 题随新版 TSG 入库恢复；两个明确查询 2017 历史版本的问题仍失败。这说明原失败同时包含 OCR corpus 缺失和版本路由缺失，不能全部归因于 OCR。

## 10. Full 34-question Retrieval / Citation

34 题中 27 题为可回答题，7 题为不可回答题。以下为当前原参数 Retrieval 结果：

| Metric | v0.1 | v0.2 | Delta |
|---|---:|---:|---:|
| Hit@1 | 0.814815 | 0.851852 | +0.037037 |
| Hit@3 | 0.814815 | 0.888889 | +0.074074 |
| Hit@5 | 0.814815 | 0.925926 | +0.111111 |
| Recall@1 | 0.685185 | 0.722222 | +0.037037 |
| Recall@3 | 0.703704 | 0.759259 | +0.055555 |
| Recall@5 | 0.759259 | 0.851852 | +0.092593 |
| MRR | 0.814815 | 0.879630 | +0.064815 |
| Document Citation Accuracy | 0.703704 | 0.725926 | +0.022222 |
| Page Citation Accuracy | 0.222222 | 0.237037 | +0.014815 |
| Document Citation Hit Rate | 0.814815 | 0.925926 | +0.111111 |
| Page Citation Hit Rate | 0.814815 | 0.925926 | +0.111111 |

Citation 指标是 retrieval-evidence citation potential，即检索页是否命中 Ground Truth；不是 Answer 生成后的语义引用准确率。未运行完整 Answer LLM。

## 11. Failure Taxonomy 变化

- v0.1：`PARSE_FAILURE=3`，`VERSION_AMBIGUITY=2`。
- v0.2：`VERSION_AMBIGUITY=2`。

3 个 `PARSE_FAILURE` 已随 TSG 08—2026 OCR/索引完成而消失；两个历史版本失败保留，未通过修改 Top-K、Citation 或测试标签掩盖。

## 12. 测试与边界

- Rotation/OCR 专项：56 passed。
- Full project regression：143 passed，1 个 DashScope Assistants API deprecation warning。
- 新增覆盖：严格 trigger、90/270 candidates、deterministic selection/tie-break、cache hit/invalidation、page mapping、Hybrid Retention 复用、failed recovery、其他页不 OCR、离线 recovered-page replacement、Quality FAIL build fail-closed、production rule 无场景硬编码。
- 未改：Retriever、Top-K、Chunk Size、Rerank、Parent Page、Citation Validator、Confidence/Reject、Version Resolver。

## 13. 下一阶段建议

建议进入 Version Governance / Version-aware Retrieval：两个剩余失败已有明确、可复现证据，问题不再是 OCR。Confidence / Reject 继续暂停；本阶段没有基于 score 分布重新设计阈值，也不应顺带实现拒答策略。

最终状态：`PAGE_37_ROTATION_RECOVERY=PASS`，`OCR_QUALITY=PASS`，`CORPUS_V0_2=BUILT_AND_INDEXED`，`RETRIEVAL_CITATION_REFRESH=COMPLETE`，`ANSWER_LLM_FULL_RUN=NOT_RUN`。
