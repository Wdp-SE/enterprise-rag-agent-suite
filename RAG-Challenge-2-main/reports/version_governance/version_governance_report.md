# RAG Version Governance + Version-aware Retrieval Report

## 1. Status

`COMPLETE`

本阶段实现了确定性的文档版本治理和版本感知检索，没有实现 Conflict、Confidence、
Reject Gate、LLM Query Planner、Answer Prompt 改造或新的排序算法。Corpus v0.2 原报告
保持不变；新增资产以 `Corpus v0.2 + Historical Retrieval Asset` 独立保存。

## 2. Data-plane blocker resolution

冻结 Manifest 中的 `tsg-08-2017` 原 PDF SHA-256 与实际文件一致。PDF 共 46 页，
46/46 页存在 Native Text，共提取到 33,850 个文本字符，Manifest 状态为
`READY / NOT_REQUIRED / SUPERSEDED`。没有运行 OCR。

Docling 第一次启动因 Unicode 虚拟环境路径下的 native resources 定位失败，在打开 PDF
前终止且没有生成解析结果。使用 ASCII junction 暴露同一安装包资源后，唯一一次实际
Docling PDF 转换完成；后处理最初错误假设 `content` 为字典，随后直接复用已落盘的原始
Docling export 恢复，没有第二次解析 PDF。

历史资产结果：

- document_id: `tsg-08-2017`
- pages: 46
- chunks: 110
- vectors: 110
- vector dimension: 1536
- embedding: `dashscope / text-embedding-v1`
- normalization: unit L2 norm verified
- FAISS: `IndexFlatIP`
- status: `SUPERSEDED`
- version_family: `TSG_08`
- OCR performed: false

一次 sandbox embedding 尝试被网络权限在连接前阻断；获得网络授权后只执行了一次真实
DashScope embedding，成功生成索引。没有重新 embedding 现有 5 份文档。

## 3. Version metadata and effective interval

新增独立 `VersionMetadata`，没有修改 Candidate v2 使用的 `DocumentMetadata` 契约。
字段包括 document identity、version family、version、status、publish date、
effective_from/effective_to、supersedes 和 superseded_by。

状态复用 Manifest 已有的 `ACTIVE / SUPERSEDED / REFERENCE`。`is_current` 根据指定
as-of date 运行时计算，不持久化。旧版本 `effective_to=2026-05-01` 来自 Manifest 中
`tsg-08-2017 -> tsg-08-2026` 的显式关系，采用半开区间 `[from, to)`，并在 metadata
中记录推导来源；没有进行法律解释。

## 4. Intent, resolver and policy

Intent Detector 纯规则运行，支持 `CURRENT / HISTORICAL / EXPLICIT_VERSION /
TEMPORAL_DATE / UNSPECIFIED`，同时保留 explicit_versions、matched_document_ids、
query period、date precision、signals 和 temporal ambiguity。Document number、version、
title 与 version family 均来自 Manifest；核心 versioning 模块不含场景版本硬编码。

Resolver 在向量检索前生成 eligible document_ids。Policy 以资格过滤为主，只对明确匹配
的版本使用固定 `+0.02` PREFER signal。原始 cosine 保存在 `distance/original_score`，
另行记录 version_action、version_adjustment 和 final_pre_rerank_score。Rerank prompt、
provider 和融合公式未改变；有治理 signal 时仅使用 final_pre_rerank_score 作为既有向量
分量输入。

裸年份不会全局切换所有版本族。只有问题先通过 Manifest 标题、文号或版本匹配到
version family 后，Temporal Policy 才改变该 family 的候选资格。这保证诸如“2026 年
全国统一最低月薪”不会引入历史 TSG 文档。

## 5. Retrieval integration and compatibility

调用链为：

`Question -> Intent Detector -> Resolver -> eligible document_ids -> per-document Top-K ->
Version Policy -> global merge -> Parent Page -> optional existing Rerank -> Citation`

`HybridRetriever.retrieve()` 已最小补齐 document_ids/version_plan 透传。Retriever 的
metadata projection 补充 document_number、publish_date、effective_date、version_family、
version 和 status。Parent Page 继续按 `(document_id, page)` 去重；Citation 仍只按
`(document_id, physical page_number)` 校验，版本字段只是可选来源附加信息。

历史 JSON/FAISS 位于独立 `historical_retrieval_assets`，仅在 Version Governance ON 时
显式加载。OFF 或普通 Generic Retriever 仍只扫描原 5 份目录。最终 34 题比较中，全部
29 个非版本问题（含 7 个 unanswerable）的 Top-5 document/page/cosine 结果与 v0.2
逐项一致。

## 6. Version behavior verification

- 当前/无版本问题：只使用默认 ACTIVE corpus，2017 不进入候选。
- 明确 2017：历史文档进入 eligible set 并标记 PREFER。
- 明确 2026：当前文档进入 eligible set，旧版不参与。
- 2025 年：2017 历史版本优先。
- 2026 年 6 月及 2026-05-01 边界：2026 版本优先，旧版边界为 exclusive。
- 仅“2026 年”：同时保留两个时间区间，记录
  `TEMPORAL_YEAR_CROSSES_VERSION_BOUNDARY`。
- 明确双版本比较：2017 和 2026 同时进入 eligible set。

## 7. Original version subset before/after

| Metric | v0.2 Before | Governance ON |
|---|---:|---:|
| Hit@1 | 0.600000 | 1.000000 |
| Hit@3 | 0.600000 | 1.000000 |
| Hit@5 | 0.600000 | 1.000000 |
| Recall@1 | 0.500000 | 0.900000 |
| Recall@3 | 0.500000 | 1.000000 |
| Recall@5 | 0.500000 | 1.000000 |
| MRR | 0.600000 | 1.000000 |
| Document Citation Accuracy | 0.520000 | 0.960000 |
| Page Citation Accuracy | 0.120000 | 0.240000 |
| VERSION_AMBIGUITY | 2 | 0 |

其中 version-001 的 Top1 为 2017 版物理页20；version-005 的 2017 版物理页12进入
Top2。指标是 Retrieval/Citation Potential，不是 Answer LLM 准确率。

## 8. Version extension OFF vs ON

独立 `version_eval_v0_1.jsonl` 共 8 题，覆盖 CURRENT、EXPLICIT OLD/NEW、TEMPORAL
PAST/CURRENT、DUAL VERSION、AMBIGUOUS YEAR 和 NORMAL UNSPECIFIED。

| Metric | OFF | ON |
|---|---:|---:|
| Hit@1 | 0.750000 | 1.000000 |
| Hit@3 | 0.750000 | 1.000000 |
| Hit@5 | 0.750000 | 1.000000 |
| Recall@1 | 0.625000 | 0.875000 |
| Recall@3 | 0.625000 | 0.937500 |
| Recall@5 | 0.625000 | 1.000000 |
| MRR | 0.750000 | 1.000000 |
| Document Citation Accuracy | 0.550000 | 0.900000 |
| Page Citation Accuracy | 0.150000 | 0.250000 |
| Classified version failures | 2 | 0 |

## 9. Full 34-question impact

| Metric | v0.2 Before | Governance ON Final |
|---|---:|---:|
| Hit@1 | 0.851852 | 0.925926 |
| Hit@3 | 0.888889 | 0.962963 |
| Hit@5 | 0.925926 | 1.000000 |
| Recall@1 | 0.722222 | 0.796296 |
| Recall@3 | 0.759259 | 0.851852 |
| Recall@5 | 0.851852 | 0.944444 |
| MRR | 0.879630 | 0.953704 |
| Document Citation Accuracy | 0.725926 | 0.807407 |
| Page Citation Accuracy | 0.237037 | 0.259259 |
| VERSION_AMBIGUITY | 2 | 0 |

最终权威输出目录为 `reports/version_governance/full_34_on_final`。较早的
`full_34_on` 是发现“裸年份错误启用版本族”前的中间审计产物，不作为最终结果。

## 10. Failure taxonomy and trace

新增分类：`WRONG_ACTIVE_VERSION / WRONG_HISTORICAL_VERSION /
TEMPORAL_FILTER_MISS / VERSION_METADATA_MISSING / DATASET_SOURCE_MISSING`，并保留
`VERSION_AMBIGUITY`。每题报告记录 intent、query period、explicit versions、候选文档、
status、version family、action、adjustment、index availability 和 issues。

## 11. Transition notice boundary

Corpus 当前没有独立实施通知的 document_id/chunk/FAISS；只有 TSG 08—2026 正文的
施行条款及 Manifest relation note。本阶段没有新增通知、没有把 2026 过渡期政策写入
Resolver，也没有声称完成“规则 + 独立通知”双文档检索。未来此类题若要求缺失来源，应
标记 `DATASET_SOURCE_MISSING`。

## 12. Regression and next stage

- Full pytest: `160 passed`, 0 failed
- Warning: DashScope Assistants API dependency deprecation warning，与本阶段逻辑无关
- OCR: not run
- Answer LLM: not run
- Rerank online evaluation: not run
- Existing FAISS rebuild: 0
- Existing Answer Prompt changes: 0

新旧版本差异目前应记录为 `VERSION_DIFFERENCE`，不能自动称为知识冲突。Conflict
Detection 仍可作为后续治理能力，但不是修复当前版本检索的必要条件。

版本候选空间已经具备确定性治理和真实历史检索能力，可以进入下一阶段的
Confidence / Reject / Trusted QA 设计。阈值仍必须依据治理后的 answerable 与
unanswerable score 分布重新校准，本阶段没有选择任何阈值。
