# 企业文档可信知识库与问答系统：二次开发记录

## 1. 原项目架构

原项目是面向公司年报竞赛数据的 RAG 流程：Docling PDF 解析、页面规整、Token 分块、Embedding、每文档独立 FAISS、按公司名检索、可选父页面检索和 LLM rerank，最后通过结构化 Prompt 生成答案及比赛格式页码引用。

## 2. 原项目已有能力

- PDF/OCR/表格解析与中间 JSON、Markdown 产物。
- Token-aware chunking，并保留页码。
- FAISS `IndexFlatIP` 建库、加载和检索。
- Parent Page Retrieval。
- OpenAI、IBM、Gemini、DashScope 模型适配骨架。
- Pydantic Answer Schema、批量问答和比赛引用格式。

## 3. 为什么需要二次开发

原实现以固定年报和竞赛提交为目标。代码审计发现，默认 Qwen 未真正解析结构化输出，DashScope rerank 固定返回零分，FAISS 向量未归一化，引用校验会自动补页，Boolean Schema 不能拒答，provider/model 配置分散，并存在敏感日志风险。必须先修复这些基线问题，再增加知识治理能力。

## 4. Reliable Baseline Repair 方案

本阶段只修现有 RAG 行为，不实现 Candidate Zone、版本管理、知识健康、Confidence Gate、BM25、GraphRAG、Agent 或 UI。

- 共享结构化输出解析：JSON/code fence 清理、可选 JSON repair、Pydantic 校验。
- DashScope rerank 复用结构化解析并返回真实 relevance score。
- 文档和查询 Embedding 均做 L2 normalize，使 `IndexFlatIP` 表达 cosine similarity。
- 载入时拒绝未归一化的旧 FAISS，避免静默使用错误分数。
- Citation 只保留模型声明且存在于检索结果中的页码，不自动补页。
- Boolean 最终答案兼容 `True`、`False` 和 `"N/A"`。
- Answer、Embedding、Rerank 分别显式配置 provider/model，并在调用前校验。
- 删除 API Key、完整响应、原始失败文本等敏感输出。

## 5. 修改文件

- `src/api_requests.py`
- `src/reranking.py`
- `src/ingestion.py`
- `src/retrieval.py`
- `src/questions_processing.py`
- `src/prompts.py`
- `src/pipeline.py`
- `src/provider_config.py`
- `src/vector_utils.py`
- `requirements.txt`
- `requirements-windows.txt`
- `.gitignore`
- `scripts/parse_missing_runtime_pdfs.py`
- `scripts/run_baseline_runtime.py`
- `artifacts/baseline_runtime/`
- `tests/`

## 6. 测试

执行命令：

```powershell
python -m pytest -q -p no:cacheprovider
```

结果：31 passed，1 个 DashScope Assistants API 弃用警告。pytest 测试本身不调用真实外部 API；在线结果由独立 runtime runner 生成。

覆盖范围：

- Qwen JSON 和 code-fenced JSON 解析。
- 普通字符串响应兼容。
- DashScope rerank 结构化分数和排序变化。
- 文档/查询向量单位范数与零向量拒绝。
- 旧未归一化 FAISS 检测。
- Citation 不补页、幻觉页删除、去重。
- Boolean `True`、`False`、`N/A`。
- provider/model 错配在 API 调用前失败。
- API Key 和 Embedding 原文不进入输出或错误日志。

## 7. 实验结果

Reliable Baseline Repair 阶段没有调用在线 LLM。随后执行的 Runtime Baseline Verification 使用真实 DashScope：5 份 PDF、1,924 个 chunk、15 个问题全部完成。15/15 Structured Output 成功解析，14/15 发生真实 rerank 排序变化，简单人工标签精确匹配为 11/15；平均总延迟 7,117.11 ms，真实记录 188,605 个 Answer/Rerank tokens。Embedding token 未由当前响应提供，明确排除在统计外。完整明细见 `artifacts/baseline_runtime/baseline_report.md` 和 `baseline_results.json`。

## 8. 已知问题

- 现有 `data/test_set/databases/vector_dbs` 仍是未归一化旧索引，必须重新构建或显式迁移后才能由新检索器使用；本次验证使用 `artifacts/baseline_runtime/runtime_dataset` 下的新索引。
- Windows 中文仓库路径会触发 Docling Parse v2 原生路径问题；本次通过 ASCII junction 完成验证，尚未消除底层限制。
- EasyOCR 在 Mercia PDF 的空图像裁剪上触发 OpenCV 异常；已提供默认不启用的 `do_ocr=False` 文本 PDF 降级入口。
- 当前 DashScope 账号不支持 `qwen-turbo-latest`，已使用真实可用的 `qwen-turbo`。
- 15 题中 4 题暴露检索 miss、指标粒度错误或 False/N/A 语义边界问题；`temperature=0` 下两次在线运行仍观察到 Boolean 输出差异。
- 尚未实现 Evidence Confidence Gate、企业级元数据、候选区、版本治理、健康检查和回归评测。
- `legacy_company` 仍保留按 `company_name` 的比赛路径；`generic` 已支持无需公司名的跨文档检索。
- 当前 provider/model 校验使用明确的已支持模型名称前缀；接入新的模型系列时需同步扩展规则。

## 9. 后续优化

Competition Decoupling 已完成最小实现。下一步可以接入公开垂直资料并验证通用元数据；Candidate Knowledge Zone、版本治理、知识健康和 Confidence Gate 仍需按后续阶段单独实现。特种设备使用管理公开资料仅作为首个验证场景，不进入核心类名、字段判断或检索分支。

## 10. Runtime Baseline Verification

正式验证产物：

- `artifacts/baseline_runtime/baseline_queries.json`：修正歧义后冻结的 15 题输入。
- `artifacts/baseline_runtime/baseline_results.json`：正式在线运行逐题记录。
- `artifacts/baseline_runtime/baseline_queries_run1.json` 与 `baseline_results_run1.json`：原始首轮审计记录，用于说明测试标签修正和模型输出波动，没有覆盖或美化。
- `artifacts/baseline_runtime/baseline_report.md`：环境、索引、Structured Output、Rerank、Citation、Boolean、Latency、Token、分数分布和已知问题的完整报告。

正式运行不保存完整检索原文，只保存 page、score、文本长度和 SHA-256。对已配置 secret 扫描全部 runtime 文本产物，泄漏文件数为 0。

## 11. Competition Decoupling

本阶段保留默认 `legacy_company` 路由，同时增加 `generic` 路由。Generic 问题不执行公司名抽取，而是对每个独立 FAISS 做局部 Top-K，合并候选后再取全局 Top-K；Parent Page 使用 `(document_id, page_number)` 去重。没有合并索引，也没有修改 BM25。

最小通用元数据字段为 `document_id`、`title`、`document_type`、`source`、`source_url`、`category`、`tags`，并保留 `legacy_company_name`。`document_id` 优先复用显式 ID 或原 `sha1_name`，否则由稳定来源标识生成；加载时拒绝语料内重复 ID。旧分块数据会在内存中补齐元数据、`document_id` 和 `chunk_id`，因此已归一化 FAISS 无需重建。

Generic Structured Output 使用行业无关 Prompt，并通过 `(document_id, page_number)` 校验来源。模型未声明、重复声明或指向未检索页面的来源不会进入最终 `sources`。比赛路径继续使用原 `relevant_pages -> pdf_sha1/page_index` 格式，submission schema 未修改。Generic 禁止 `full_context`，且不会生成比赛 submission。

Retriever 现在在 `QuestionsProcessor` 初始化时构建一次并复用。CLI 提供 `generic` 配置和 `--routing-mode [legacy_company|generic]`，默认仍为 `legacy_company`。

本阶段本地测试结果为 45 passed。真实 DashScope/Qwen Smoke Test 仅复用 Runtime Baseline 的 5 份文档和已归一化索引，运行 2 题：可回答题得到 `Michael J. Maddox` 并通过复合引用校验；无答案月球网点题得到 `N/A` 且来源为空。运行产物见 `artifacts/competition_decoupling/generic_smoke_results.json`。本阶段没有重新解析 PDF、重建 FAISS 或重跑 15 题 Runtime Baseline。

仍保留的比赛代码包括：Legacy 公司路由、公司比较问题重写、比赛 subset/引用/submission 适配、旧年报 Prompt，以及按公司实现的 BM25 路径。这些代码只服务 Legacy Mode；BM25 按本阶段约束未修改。

## 12. Minimal Candidate Ingestion Interface

新增独立的 Candidate Package 文件交接边界。Agent 只能生成
`document.md`、`metadata.json`、`sources.json` 和 `raw_sources/`，再通过
`import_candidate()` 导入 `candidate_knowledge/`。导入会校验通用文档元数据、
候选状态、来源文件、`[source:Sxx]` 引用和重复 `document_id`，不会调用
Embedding、Retriever 或 FAISS。

候选状态保存在独立 `CandidateMetadata` 中，没有向通用
`DocumentMetadata` 加入治理语义。Agent 只能提交 `CANDIDATE`；人工调用
`approve_candidate(candidate_id)` 后状态可改为 `APPROVED`，但仍不会自动正式
入库。接口契约见 `docs/candidate_interface.md`，可导入样例见
`examples/sample_candidate_package/`。

本阶段没有实现 ACTIVE/SUPERSEDED/EXPIRED、版本管理、重复内容检测、冲突
检测、知识健康或 Confidence Gate。`APPROVED` 仅表示完成人工审核边界，为后续
正式 Ingestion 保留扩展点。

本阶段新增 11 个 Candidate 专项测试；与原有 45 个测试合并后，全量结果为
56 passed。测试全程未调用在线模型、解析 PDF 或重建 FAISS。

## 13. Candidate Interface v2 Upgrade

Candidate Source 现在支持两种外部契约：v1 使用
`{"sources": [...]}` 与 `source_url/raw_path`；推荐的 v2 使用数组根节点与
`url/local_file/content_hash/raw_file_hash`。两者在边界层统一为严格的
`NormalizedCandidateSources`，Citation、路径与 Hash 逻辑只使用统一内部字段。

v2 的 `content_hash` 仅校验 SHA-256 格式、转为小写并保存，状态为
`DECLARED_AND_FORMAT_VALIDATED`。由于 Candidate Package 没有独立保存 Agent
Evidence 的规范化文本，RAG 不宣称重新计算或验证了内容 Hash。`raw_file_hash`
则会从 `local_file` 的真实文件字节重新计算并比较，成功状态为
`RECOMPUTED_AND_VERIFIED`。两种 Hash 不要求相等，也不能混用。

路径校验同时拒绝 Windows drive、UNC、POSIX absolute、`..`、separator
normalization 后逃逸、symlink、`raw_sources/` 外路径、缺失文件和非普通文件。
已知 v2 可选来源字段均显式建模，未知字段默认拒绝，避免拼写错误造成契约漂移。

升级后 Candidate 专项测试为 34 passed，Generic 回归为 9 passed，
Legacy/Reliable Baseline 回归为 36 passed，全项目为 79 passed。测试没有调用
真实模型、解析 PDF 或重建 FAISS。

在确认 RAG Candidate Zone 中不存在相同 `candidate_id/document_id` 后，使用真实
OpenManus v2 Candidate 执行了一次且仅一次 `import_candidate()`。结果为
`accepted=true`、`issues=[]`、`ingestion_performed=false`；`content_hash` 状态为
`DECLARED_AND_FORMAT_VALIDATED`，`raw_file_hash` 状态为
`RECOMPUTED_AND_VERIFIED`。落区后仍为 `CANDIDATE`、`requires_review=true`，含
2 个来源和 2 个 raw 文件、0 个 FAISS 文件，没有调用 `approve_candidate()`。
结构化记录见 `artifacts/candidate_interface_v2/import_result.json`。

## 14. Domain Corpus + Evaluation Baseline

将 `data/test_set/pdf_reports` 中 8 份公开资料冻结为 Domain Corpus v0.1。语料仅是
通用企业文档 RAG 的首个垂直验证场景；核心检索、元数据和问答代码未增加特种设备
专用判断。4 份可直接提取文本且当前有效的法律/部门规章进入默认索引；TSG
08—2017 标记为 `SUPERSEDED / VERSION_TEST`；TSG 08—2026 和两份考试指南因
正文缺少可用文本层标记为 `OCR_REQUIRED`，没有伪造解析正文。

真实 ingestion 共得到 128 页、241 chunks 和 241 个全新 DashScope Embedding，
4 个 `IndexFlatIP` 索引均通过单位范数检查。34 题固定评测集包括 15 个单文档题、
7 个跨文档题、7 个不可回答题和 5 个版本/时间题。Normalized Vector Baseline 的
Hit@1/3/5 均为 0.814815，Recall@1/3/5 分别为 0.685185、0.703704、
0.759259，MRR 为 0.814815。Single Document 指标为 1.0；版本题因 OCR 和版本路由
缺失全部失败，形成 3 个 `PARSE_FAILURE` 和 2 个 `VERSION_AMBIGUITY`。

Retrieval Citation 只测检索页命中 Ground Truth，Document/Page Citation Accuracy
分别为 0.703704/0.222222，不宣称语义支持正确。3 题真实 Qwen Smoke 中 Structured
Output 3/3 成功，Rerank 3/3 改变排序，不可回答题返回 `N/A` 且 Citation 为空。
Smoke 消耗 12,697 个 Rerank/Answer tokens；同配置 34 题点估计约 143,899 tokens，
超过约 50K 的停止边界，因此未执行正式全量 Answer Evaluation，也未编造指标。

本阶段新增 8 个 Evaluation 测试，全项目结果为 87 passed。正式产物位于
`reports/domain_evaluation_v0_1/`，语料与索引位于 `data/domain_corpus/`。当前优先
短板是 TSG 08—2026 的中文扫描 OCR，其次是版本路由、跨文档完整召回和基于更多
真实分布设计的 Confidence/Reject；本轮未提前实现这些功能。

## 15. Minimal Chinese OCR 与 Block Retention Calibration

TSG 08—2026 已完成一次完整 OCR：54 个物理页中 1 页使用原生文本，53 页执行
EasyOCR 成功，耗时约 34 分 27 秒。原始页级 cache 与 2,879 个 raw blocks 被完整
保留；后续 calibration 全部读取 cache，EasyOCR invocation 为 0。

统一 confidence threshold 被真实 false-negative 证明不足：0.60 会丢失生效日期句
与正文续句，0.50 又会放入全部已知噪声。新增的通用 hybrid rule 使用 confidence、
中文文本密度、日期/条款结构及稳定页边重复位置；在小型真实 fixture 上达到已知有效
3/3 保留、已知噪声 3/3 拒绝。该结果只代表 calibration fixture，不宣称 OCR Accuracy。

离线重组随后发现第 37 个物理页为空。单页视觉核验确认源页是一张横置的压力管道
基本信息汇总表，含表名、单位字段和多列表头；现有 raw blocks 未可靠识别这些正文，
仅调整 retention 无法恢复。新增通用空页门禁后，OCR Quality 被修正为 FAIL，
`Corpus v0.2 allowed=false`。构建入口已验证会 fail-closed；未执行增量 Embedding、
FAISS、版本子集或 34 题刷新，也未重复 OCR。

该阶段全项目回归为 128 passed。详细分布、策略比较、页面核验和当时的阻断原因见
`reports/domain_evaluation_v0_2/ocr_block_retention_calibration.md`。阻断随后由第 16 节的
Exceptional Page Rotation OCR Recovery 解决。

## 16. Exceptional Page Rotation OCR Recovery + Corpus v0.2

新增外围页级 `RotationOcrProcessor`。它只接受显式 `OCR_ORIENTATION_SUSPECTED`、
normal OCR 已执行、源页 render 非空且 Hybrid Retention 后文本为空/极少的页面。正常
成功页不会触发。独立 rotation cache 由 file/page/rotation/OCR config/rotation config/
retention config 共同标识，不覆盖 normal OCR cache。

物理第 37 页只运行 90°和 270°：90°候选为 13 meaningful chars、中文比例 0、
garbled ratio 0.882353；270°候选为 94 chars、中文比例 0.851064、garbled ratio
0.375，因质量分 243.521277 被确定性选中。表名及多个表格字段信号恢复，第二次运行
两个候选均 cache hit，EasyOCR 为 0；其他 53 页没有重新 OCR。

54 页离线重新 assembly 后 OCR Quality Gate 全部通过。Corpus v0.2 独立生成，4 份旧
ACTIVE 文档在 source hash、provider/model、normalization、chunk config 和 metadata
schema 全部一致后复用 241 vectors；TSG 08—2026 新增 54 pages、78 chunks/vectors。
五个 IndexFlatIP 均通过单位范数及 chunk/vector 数量一致检查。

版本/时间 5 题由 v0.1 全零提升到 Hit@1/3/5=0.6、Recall@1/3/5=0.5、MRR=0.6；
两个历史 2017 版本问题仍为 `VERSION_AMBIGUITY`。完整 34 题 Hit@1/3/5 提升至
0.851852/0.888889/0.925926，MRR 0.87963；`PARSE_FAILURE` 从 3 降为 0。Citation
仍只代表 retrieval-evidence potential，不代表 Answer 语义支持。完整 Answer LLM 未运行。

全项目回归为 143 passed。详细报告见
`reports/domain_evaluation_v0_2/exceptional_page_rotation_corpus_v0_2_report.md`。下一阶段
建议进入 Version Governance；Confidence / Reject 继续暂停，等待独立 score 分布设计。

## 17. Version Governance 与 Version-aware Retrieval

在不修改 Candidate v2 契约、Answer Prompt、Rerank Provider/Prompt 和既有 5 个 FAISS
的前提下，新增独立 VersionMetadata、确定性 Intent Detector、Resolver、Policy 与
Version Trace。Manifest 为 2017/2026 两版配置同一 `TSG_08` version family；旧版
effective_to 由显式 superseded relation 的 2026-05-01 生效边界推导，`is_current` 仅在
运行时计算。

TSG 08—2017 原 PDF 经核验为 46/46 页 Native Text，不使用 OCR。独立历史资产包含
46 pages、110 chunks、110 个全新 `text-embedding-v1` normalized vectors 和单文档
IndexFlatIP；仍保持 `SUPERSEDED`。该资产只在治理开启时显式加载，普通 Generic/OFF
仍扫描原 5 份默认文档。最终 34 题中全部 29 个非版本问题的 Top-5 文档、页码和 cosine
与 v0.2 一致。

原 5 题版本子集 Hit@1/3/5 与 MRR 从 0.6 提升到 1.0，VERSION_AMBIGUITY 从 2 降到
0。独立 8 题 OFF/ON 消融的 Hit@1 从 0.75 提升到 1.0。完整 34 题 Hit@1/3/5 达到
0.925926/0.962963/1.0，MRR 为 0.953704，Page Citation Accuracy 从 0.237037 提升到
0.259259；这些 Citation 指标只代表检索证据页 potential，不代表 Answer 语义准确率。

全项目回归为 160 passed。当前 Corpus 没有独立实施通知检索资产，Resolver 未编码任何
过渡期法律规则。详细实现、消融和限制见
`reports/version_governance/version_governance_report.md`。版本治理阶段完成，可以开始
基于治理后 score distribution 设计 Confidence / Reject；Conflict Detection 仍保持暂停。

## 18. Trusted QA Audit、Signal Instrumentation 与 Shadow Gate

先复用最终 34 题 Domain 结果和 8 题 Version 结果完成离线审计。Answerable Top1 为
0.4434～0.8334，Unanswerable 为 0.4765～0.6862，存在实质重叠；样本内 0.70475
阈值虽然拒绝 7/7 Unanswerable，却误拒 6/27 Answerable。Top1-Top2 margin AUC 仅
0.468254，Top1/Top3/Top5 mean 相关系数为 0.97～0.99，因此不采用单 cosine threshold。
审计与分布产物保存在 `reports/trusted_qa_design/`。

Phase 1 新增独立 `src/trusted_qa/`，将 RetrievalSignalSnapshot、确定性 Preconditions、
EvidenceSufficiencyDecision 和 AnswerEvidenceAudit 与原检索、版本及 Citation 模块分离。
支持 `OFF/SHADOW`；`ENFORCE` 仅预留枚举并明确拒绝启用。Shadow trace 写入内部观测
存储，不改变 Generic/Legacy Answer schema，也不跳过 Generation 或 Citation。

42 题 Retrieval-only Shadow 中，默认 policy 对 27 条 Answerable 给出 16 ANSWER、
11 UNCERTAIN，对 7 条 Unanswerable 全部给出 UNCERTAIN；False Reject/False Accept
均为 0，但没有 REJECT，因此 Reject Precision 不可计算，尚不允许进入 Enforcement。
8 条 Version Stress 为 3 ANSWER、5 UNCERTAIN、0 REJECT。Agreement ablation 没有
超过 soft policy。原 7 条负样本中 5 条经人工审计为 Hard Negative，无需本轮扩写数据集。

预算内的 6 题真实 Qwen Answer Smoke 消耗 11,822 Answer tokens：3 条 Answerable
均返回实质答案和合法 Citation，3 条 Hard Negative 均返回 N/A 且 Citation 为空。
Gate 增加 LLM 调用为 0。新增 27 个测试后，全项目为 187 passed / 0 failed。完整产物与
限制见 `reports/trusted_qa_shadow_v0_1/trusted_qa_signal_instrumentation_shadow_gate_report.md`。

## 19. Trusted QA Phase 2：Held-out Validation 与 Enforcement Evidence

在任何 Gate 运行前冻结独立 `trusted_qa_holdout_v0_1`：20 题中 Answerable/Unanswerable
各 10 条，负样本包含 7 条 Hard Negative 和 3 条 Easy Negative。所有 Ground Truth 均从
Corpus v0.2 已解析文本人工核验；与原 Domain 34、Version 8 和 Phase 1 Smoke 6 的 ID/规范化
题面精确重合为 0。冻结 SHA-256 为
`c23c95ca1a97e67520bc2deeee03933f4661414e3991b5118430cdce98798f71`，未按 Gate 结果
修改或删除题目。

首次且唯一的 frozen `trusted_qa_shadow_v0_1` Retrieval-only 运行中，Answerable 为
4 ANSWER/6 UNCERTAIN/0 REJECT，Easy Negative 为 0 ANSWER/3 UNCERTAIN/0 REJECT，
Hard Negative 为 3 ANSWER/4 UNCERTAIN/0 REJECT。Observed REJECT 为 0，Reject Precision
不可计算；Hard Negative Top1 均值 0.720500 反而高于 Answerable 的 0.712550，因此
Pre-generation 结论为 `PRE_GENERATION_HARD_REJECT_EVIDENCE_INSUFFICIENT`，未创建基于
Held-out 调参的 candidate_v0_2。

预算内只运行一次 5 Answerable + 5 Hard Negative Qwen Smoke：预估上界 24,630，实际
Prompt/Completion/Total tokens 为 21,095/2,088/23,183。5 条 Hard Negative 全部返回
`N/A + empty citations`；10/10 Structured Output 合法。Answerable 中观察到 1 条因检索漏召回
而错误弃答、2 条实质回答的声明 Citation 被成员校验过滤为空。

隔离的 `trusted_qa_post_answer_candidate_v0_1` 仍为 Shadow-only，不修改 Response；它将结构
错误、实质答案无有效引用、引用成员失败映射为 candidate `FAIL_CLOSED`，将
`N/A + empty citations` 映射为合法弃答。真实 Smoke 中观察到 2 个 fail-closed 案例，均有
确定性引用不变量支持，但样本状态仍为 `SAMPLE_SIZE_INSUFFICIENT`。Citation membership
仍不等于 semantic entailment。

最终 Readiness 为 `POST_ANSWER_ENFORCEMENT_ONLY`：Pre-generation 继续 Shadow 并保留
UNCERTAIN；若最终评审批准实际 Enforcement，只应另行最小接入确定性的 Post-answer 规则。
本阶段未启用 ENFORCE。新增 14 个测试后 Full Regression 为 201 passed / 0 failed。完整报告见
`reports/trusted_qa_phase2/trusted_qa_phase2_report.md`。

## 20. Trusted QA Phase 3：Deterministic Post-answer Fail-closed Enforcement

新增 `trusted_qa_post_answer_v1`，仅在既有 Generation、Structured Output 解析和 Citation
Membership 校验之后执行确定性策略。`ENFORCE` 明确限定为 `POST_ANSWER_ONLY`；pre-generation
仍为 Shadow，不跳过生成，cosine、margin、diversity 与 retrieval agreement 均不参与正式
拦截。结构无效、实质答案无引用、任一声明引用成员关系失败、N/A 与引用冲突会 fail closed
为兼容 Schema 的 `N/A + empty citations`；合法 N/A 和合法引用答案保持不变。Gate 增加 LLM
调用为 0，原始生成结果、验证状态、决策与最终结果保留在内部 trace。

Phase 2 保存的 10 题离线回放中，两个真实 Citation Membership Failure 被 2/2 拦截，两个
人工确认合法答案与五个正确 N/A 全部保留，False Fail-closed 为 0；一个 retrieval miss 仍为
已知限制。真实 2 Answerable + 2 Hard Negative ENFORCE Smoke 消耗 9,392 Answer tokens：
2 个合法答案 `PASS`，2 个无答案题 `VALID_ABSTENTION`，无错误拦截。Citation Membership
仍不等于 semantic entailment。

Full Regression 为 220 passed / 0 failed，保留既有第三方 DashScope deprecation warning。
未重复 PDF Parsing、Embedding 或 FAISS 构建。阶段状态为
`COMPLETE_POST_ANSWER_ENFORCEMENT_READY`，只代表批准的确定性 post-answer enforcement
完成；项目不是 Production Ready。核心功能现已冻结，下一阶段仅进入秋招材料 Finalization。
完整证据见 `reports/trusted_qa_phase3/trusted_qa_phase3_report.md`。
