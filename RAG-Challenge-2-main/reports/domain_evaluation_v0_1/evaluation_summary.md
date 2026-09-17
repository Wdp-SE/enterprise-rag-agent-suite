# RAG Domain Corpus + Evaluation Baseline Report

## 1. 结论

Domain Corpus v0.1、真实解析、真实 DashScope Embedding、全新归一化 FAISS、34 题 Retrieval/Citation Baseline、3 题真实 Qwen Rerank + Structured Answer Smoke 以及 87 项本地回归均已完成。

34 题正式 Answer Evaluation 未执行：3 题 Smoke 已消耗 12,697 个可计量的 Rerank/Answer tokens，按同配置外推约 143,899 tokens，超过约 50K 的停止边界。该停止是资源约束的预期行为，不是运行失败。

本阶段没有增加 Confidence Threshold、自动拒答、Version Resolver、Conflict Resolver、GraphRAG、Agent、UI 或新的检索算法。

## 2. Corpus Audit

| document_id | 文档 | 页数 | 文本页 | 状态 | 解析判定 | 默认索引 |
| --- | --- | ---: | ---: | --- | --- | --- |
| `cn-law-special-equipment-safety-2013` | 中华人民共和国特种设备安全法 | 30 | 30 | ACTIVE | READY | 是 |
| `samr-order-50-2022` | 特种设备事故报告和调查处理规定 | 15 | 15 | ACTIVE | READY | 是 |
| `samr-order-57-2022` | 特种设备安全监督检查办法 | 13 | 13 | ACTIVE | READY | 是 |
| `samr-order-74-2023` | 特种设备使用单位落实使用安全主体责任监督管理规定 | 70 | 70 | ACTIVE | READY | 是 |
| `tsg-08-2017` | 特种设备使用管理规则 TSG 08—2017 | 46 | 46 | SUPERSEDED | READY / VERSION_TEST | 否 |
| `tsg-08-2026` | 特种设备使用管理规则 TSG 08—2026 | 54 | 1 | ACTIVE | OCR_REQUIRED | 否 |
| `tsg-z0007-2023` | 生产单位质量安全总监和质量安全员考试指南 | 49 | 1 | REFERENCE | OCR_REQUIRED | 否 |
| `tsg-z0008-2023` | 使用单位安全总监和安全员考试指南 | 41 | 1 | REFERENCE | OCR_REQUIRED | 否 |

共审计 8 份、318 页 PDF。字节 SHA-256 与可提取文本规范化 Hash 均未发现重复组。3 份扫描型 PDF 只有封面文本层，未伪造正文，也未为此重构 OCR。

TSG 08—2017 与 TSG 08—2026 已显式记录 `SUPERSEDED_BY` 关系；2017 版只保留为版本测试，2026 版是当前目标资料，但正文在通过中文 OCR 前不进入正式索引。

## 3. Domain Corpus v0.1

- Corpus ID：`special-equipment-use-management-public`
- 版本：`0.1`
- 状态：`FROZEN`
- 源文档：8 份，按原始字节复制到 `data/domain_corpus/source_pdfs/`
- 默认可检索文档：4 份 ACTIVE 且可直接提取文本的法律/部门规章
- 版本测试：TSG 08—2017
- OCR 阻塞的当前目标：TSG 08—2026
- 场景仅用于验证通用 RAG，核心 RAG 代码未写入特种设备专用分支。

文档身份、日期、文号、效力、来源、Hash、页数、解析状态和索引决策均固定在 `domain_corpus_manifest.json`；未知值应保留为 null/UNKNOWN，不通过猜测补齐。

## 4. Parsing 与 Ingestion

4 份索引文档通过现有 Docling 链路的 PyPdfium backend 解析，文本 PDF 显式 `do_ocr=False`：

| document_id | pages | empty pages | chunks | index vectors |
| --- | ---: | ---: | ---: | ---: |
| `cn-law-special-equipment-safety-2013` | 30 | 0 | 58 | 58 |
| `samr-order-50-2022` | 15 | 0 | 24 | 24 |
| `samr-order-57-2022` | 13 | 0 | 24 | 24 |
| `samr-order-74-2023` | 70 | 0 | 135 | 135 |
| **合计** | **128** | **0** | **241** | **241** |

使用统一配置 `dashscope / text-embedding-v1` 真实生成 Embedding，并创建全新 `IndexFlatIP` 索引；未复用竞赛旧索引。241 个索引向量与 241 个 chunks 一一对应，全部通过单位范数检查（观测 min=0.99999988、max=1.0、mean=1.0），因此 inner product 可解释为 cosine similarity。Parent Page 与 Citation 均保留稳定 `document_id + page_number`。

Windows 下 Docling Parse v2 与 FAISS 的原生绑定不能可靠处理当前中文绝对路径。解析使用稳定 document_id 的 ASCII staging 文件，FAISS 运行使用仓库相对路径；原始中文文件、Hash 和文档身份未改变。

## 5. Evaluation Dataset

`domain_eval_v0_1.jsonl` 共 34 题：

- Single Document：15
- Cross Document：7
- Unanswerable：7
- Version / Temporal：5

所有可回答题均包含实际 corpus 对应的 `expected_document_ids`、复合 `expected_pages`、参考答案和关键点；不可回答题不声明虚假证据。Ground Truth 未直接采用 LLM 自动生成结果。

## 6. Retrieval Baseline

本轮固定使用 normalized vector retrieval、每文档局部 Top-K 后全局 merge、Parent Page、最终 Top-5；未在测量过程中调 chunk、Top-K、Prompt 或阈值。

| 范围 | Hit@1 | Hit@3 | Hit@5 | Recall@1 | Recall@3 | Recall@5 | MRR |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| Overall（27 个 answerable） | 0.814815 | 0.814815 | 0.814815 | 0.685185 | 0.703704 | 0.759259 | 0.814815 |
| Single Document（15） | 1.0 | 1.0 | 1.0 | 1.0 | 1.0 | 1.0 | 1.0 |
| Cross Document（7） | 1.0 | 1.0 | 1.0 | 0.5 | 0.571429 | 0.785714 | 1.0 |
| Version / Temporal（5） | 0.0 | 0.0 | 0.0 | 0.0 | 0.0 | 0.0 | 0.0 |

Single Document 检索表现稳定。Cross Document 的“至少命中一份”表现好，但多文档证据召回不足。Version / Temporal 全部失败，主要由新版扫描 PDF 未入索引和缺少版本路由造成。

## 7. Citation Baseline

34 题 Retrieval 阶段的 Citation 指标只表示 Top-5 检索页是否命中 Ground Truth，不代表页面语义一定支持最终答案：

- Document Citation Accuracy：0.703704
- Page Citation Accuracy：0.222222
- Document Citation Hit Rate：0.814815
- Page Citation Hit Rate：0.814815

较低的 page-level precision 表明 Top-5 内存在较多同文档但非 Ground Truth 页，不能把“来自 retrieved page”写成“引用语义正确”。

## 8. Answer / Rerank Smoke

仅执行 3 题真实 Provider Smoke：1 个单文档题、1 个跨文档题、1 个不可回答题。完整调用链为：Generic Query → normalized vector retrieval → Parent Page → Qwen rerank → Qwen structured generation → `(document_id, page_number)` Citation validation。

- 3/3 Structured Output 成功解析，无 error。
- 3/3 的 Rerank 后排序相对向量初排发生变化，真实评分不是固定 0。
- 单文档题关键点全部覆盖。
- 跨文档题漏掉“逐级上报每级不超过 2 小时”，因此 rule-based answer pass 为 false。
- 不可回答的“家用电梯价格与品牌”题返回 `N/A`，Citation 为空。
- Smoke Answerable Accuracy：0.5（2 题样本，不是正式指标）。
- Key Point Coverage：0.857143。
- 生成 Citation：document accuracy 0.8、page accuracy 0.6；两个可回答题均至少命中一条正确文档/页面。
- 所有 3 题仍需人工检查 unsupported claim 与语义支持，未用自动 Judge 冒充人工结论。

## 9. Token / Latency 与正式 Answer 停止决策

3 题真实 Smoke 的 Provider usage：

- Input tokens：10,892
- Output tokens：1,805
- Total：12,697
- 平均：4,232 tokens/题
- 单题范围：3,975～4,503 tokens
- 平均端到端延迟：7,645 ms/题

按相同配置外推 34 题：点估计约 143,899 tokens，按本次单题范围外推为 135,150～153,102 tokens，明显超过 50K。因此 `full_answer_evaluation_performed=false`。该统计只包括 Provider 返回的 Rerank/Answer usage；查询 Embedding 响应未提供 token usage，明确排除。

## 10. Unanswerable 与 Score Distribution

7 个不可回答题全部仍返回 5 个向量检索结果，`questions_with_any_retrieval=7/7`。这是无阈值向量检索的正常现象，不等于系统已回答。

- Answerable top-1 cosine：min 0.2223，max 0.8334，mean 0.693659，median 0.7547
- Unanswerable top-1 cosine：min 0.2567，max 0.6862，mean 0.516486，median 0.5340

两类分数明显重叠，不能从本次分布诚实推出一个简单、安全的单阈值。3 题 Smoke 中不可回答题虽正确返回 N/A，但样本过少，不能视为正式拒答率。

## 11. Failure Taxonomy 与实际失败

已实现并测试：`PARSE_FAILURE`、`CHUNKING_MISS`、`RETRIEVAL_MISS`、`RERANK_MISS`、`PARENT_PAGE_MISS`、`CITATION_MISS`、`ANSWER_GENERATION_ERROR`、`UNSUPPORTED_CLAIM`、`UNANSWERABLE_HALLUCINATION`、`VERSION_AMBIGUITY`、`UNKNOWN`。

本轮自动分类出 5 个 Retrieval 失败：

- PARSE_FAILURE：3（均涉及正文未入索引的 TSG 08—2026）
- VERSION_AMBIGUITY：2（明确询问 2017 历史版，但默认索引有意排除了旧版）

这不是为了指标而补数据；相反，它准确暴露了当前 corpus 的 OCR 和版本能力边界。

## 12. 回归测试

- Evaluation：8 passed
- Generic RAG：14 passed
- Candidate v2：34 passed
- Reliable / Legacy Baseline：31 passed
- Full project：87 passed，1 个 DashScope SDK 自身弃用警告

测试未调用真实模型、OCR 或重建索引；在线 Smoke 与 pytest 隔离。

## 13. 当前主要短板与下一阶段

1. 首要阻断是 TSG 08—2026 的中文扫描正文无法进入索引，导致当前有效使用管理规则缺席。
2. Cross Document Hit 高但完整证据 Recall 不足，应在固定 baseline 后再分析检索候选与 rerank，不应边测边改。
3. 2017/2026 历史与当前问题无法自动路由，确实需要 Version Governance。
4. Unanswerable 与 Answerable cosine 有重叠；可信拒答/Confidence Gate 有业务必要性，但阈值不能只靠本轮 top-1 分数拍定。
5. Page Citation precision 偏低，需要后续做证据支持校验，而不是自动补页。

建议顺序：先以最小、独立的中文 OCR 接入补齐 TSG 08—2026，并冻结 Corpus v0.2；再跑同一 Retrieval Dataset 做回归；随后实现 Version Governance；最后结合更多真实 answer/rerank 样本设计 Confidence/Reject。Conflict 目前没有被本轮失败分布证明为首要矛盾，不应提前做复杂实现。

## 14. 本阶段状态

`COMPLETE_WITH_FORMAL_ANSWER_RUN_SKIPPED_BY_APPROVED_BUDGET_BOUNDARY`

Corpus、Ingestion、Retrieval、检索证据 Citation、Failure Analysis、3 题 Answer Smoke 和全量回归已完成。34 题正式 Answer Evaluation 因预计消耗超过用户设定的 50K token 边界而按要求停止；没有编造 Answer 指标。
