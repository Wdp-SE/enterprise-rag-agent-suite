# Autoware V7：中文研发资料检索策略对照

本实验只评估 `docs-main` 中文资料的证据召回和排序，不修改产品检索默认值，也不调用付费模型 API。

## 评测范围

- 语料：Autoware `docs-main` 中文社区译本，1,905 个检索分片。
- 题目：26 条新写问题；DEV 13 条，HOLDOUT 13 条。每组各有 11 条可回答题、2 条不可由公开语料回答的边界题；HOLDOUT 含跨来源问题。
- 必需来源：DEV 12 个来源标签，HOLDOUT 13 个来源标签。验证时确认题目和来源均不与旧评测精确复用，且来源家族没有跨 split。
- 向量模型：`BAAI/bge-small-zh-v1.5`，固定 revision `7999e1d3359715c523056ef9478215996d62a620`，本机离线缓存；查询采用模型卡建议的检索前缀，分片向量归一化。
- 图表/OCR、LLM 答案生成、引用蕴含、拒答判断和 Agent 变更审查均不在本轮测量范围。
- 本轮对照的是文本 BM25 分量；线上配置目前为 `bm25_figure_ocr`，额外合并已审核的图像 OCR 证据。图像支路保持原样，但它没有纳入本次 V7 评分。

题目与来源由同一评测者基于语料编写，属于新建的单人策划集，不是独立盲测。26 题不能代表所有研发团队问题分布。

## 方法

| 策略 | 实验方式 |
| --- | --- |
| `bm25_global` | 当前 BM25 排名方式，之后硬过滤到 `docs-main` + 中文。BM25 统计沿用完整索引。 |
| `bm25_fields_global` | 增加标题/章节字段权重，检验结构字段是否改善前排排序。 |
| `bge_body` / `bge_context` | BGE 对正文或“标题+文档路径+章节+正文”做稠密召回。 |
| `rrf_context_20/50/100` | BM25 与上下文向量分别召回指定候选数，再用 RRF 合并。 |
| `bm25_bge_body_rerank_top100` | BM25 先召回 100 个候选，再按 BGE 正文向量相似度重排。 |
| `bm25_bge_context_rerank_top100` | 同上，重排表示增加标题和章节上下文。 |

这里的 BGE 重排是双编码器余弦相似度重排，不是 Cross-Encoder。Cross-Encoder 权重没有在本机缓存，因此没有下载，也没有声称已测试。候选策略只在 DEV 对比；一个预注册候选与 BM25 在分组隔离的 HOLDOUT 上比较一次。

## 结果

指标只统计答案可回答题。`Recall@K` 按必需来源标签命中数计算；`完整@K` 表示单题的全部必需来源都出现在前 K 个分片中；MRR 看第一个必需来源的位置。这里 K 是最终排序分片数，不是独立文档数。

| 策略 / split | Recall@5 | 完整@5 | MRR@5 | Recall@10 | 完整@10 | Recall@20 | 完整@20 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| BM25 / DEV | 91.7% | 90.9% | 0.697 | 91.7% | 90.9% | 91.7% | 90.9% |
| BM25 → BGE 正文重排 top-100 / DEV | 91.7% | 90.9% | 0.795 | 91.7% | 90.9% | **100%** | **100%** |
| RRF 上下文 / DEV | 91.7% | 90.9% | **0.841** | 91.7% | 90.9% | 91.7% | 90.9% |
| BGE 正文直召回 / DEV | 91.7% | 90.9% | 0.795 | 91.7% | 90.9% | **100%** | **100%** |
| BM25 / HOLDOUT | **92.3%** | **90.9%** | **0.909** | **100%** | **100%** | **100%** | **100%** |
| BM25 → BGE 正文重排 top-100 / HOLDOUT | 69.2% | 72.7% | 0.712 | 92.3% | 90.9% | 92.3% | 90.9% |

DEV 上 BM25 top-100 候选池覆盖全部 12 个必需来源；但这不保证重排后资料仍留在前 5/10/20。HOLDOUT 清楚显示了这个风险：选中的 BGE 重排把定位启动配置的必需来源从第 1 位移到第 9 位，并把一个跨来源题的第二份必需资料移出前 20。它降低了前排质量，且没有超过 BM25 的最终完整覆盖。

## 决策

**本轮不把 BGE / RRF / BGE 重排接入线上，线上现有 `bm25_figure_ocr` 默认配置不变。** 在这一组 HOLDOUT 上，文本 BM25 前 10 已覆盖全部必需来源；增加一个未校准的重排器反而变差。不要因为 DEV 上个别指标上升就上线候选方法。

本轮也不能得出“BM25 已满足生产级准确性”的结论。基于当前小样本，合适的工程方向是：

1. 保持 BM25 可回退基线；继续收集真实研发提问及人工确认的必需来源，优先扩充多来源、参数/接口变更和不可回答问题。
2. 如要试 Cross-Encoder，固定模型 revision 后只在 DEV 调参，再用新的、独立策划的留出集确认；对版本和语言继续先硬过滤。
3. 检索召回、证据相关性、答案逐句蕴含和拒答能力分别评测。用证据不足/来源冲突作为交给人工的硬门槛；不能把 embedding 相似度直接展示成概率置信度。
4. 检查中文社区译本的翻译准确度、版本对应和图片/表格内容。召回正确的文件仍可能包含错误或过期文字。
5. 对最终上下文 K 值做答案级盲评。当前检索-only 测试不能证明 top-20 生成的答案一定比 top-10 更真实。

## 复现

在仓库根目录执行：

```powershell
python -m pytest -p no:cacheprovider evaluation/autoware_accuracy_v7/test_quality_first_retrieval.py -q
python -m evaluation.autoware_accuracy_v7.run_benchmark dev
python -m evaluation.autoware_accuracy_v7.run_benchmark holdout
```

HOLDOUT 受 `selection_lock.json` 与 `results/holdout-execution.json` 保护，只能运行一次。模型与语料嵌入缓存在 `results/`；报告保存 DEV/HOLDOUT 逐题前 20 命中、hash 与指标。

## 相关方法参考

- Anthropic 对高召回候选池、重排和上下文增强的工程实践说明：[Contextual Retrieval](https://www.anthropic.com/engineering/contextual-retrieval)。本文实验测试的是轻量元数据拼接和本地双编码器，不等同于其 LLM contextualization 或 Cross-Encoder。
- Corrective RAG 强调检索质量评估与纠错流程：[CRAG](https://arxiv.org/abs/2401.15884)。
- RAGChecker 将检索与生成拆开做细粒度诊断：[RAGChecker](https://arxiv.org/abs/2408.08067)。
