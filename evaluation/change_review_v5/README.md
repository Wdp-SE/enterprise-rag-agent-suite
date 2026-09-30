# 变更审查 Agent V5 历史离线评测（DolphinScheduler）

> 这是当前 Autoware 语料启用前冻结的旧版评测，使用 DolphinScheduler 3.4.x 语料。本文结果只用于回顾旧版变更审查规划，不代表当前 Autoware 检索效果或当前在线部署指标。

V5 使用 32 条人工标注的变更审查请求，按 18 个业务场景族切分为 DEV 25 条、HOLDOUT 7 条；同一场景族不会跨集合。题目覆盖参数优先级和传参、API 契约与健康检查、工作流恢复和依赖、版本升级、多资料和截图问题、公开语料无答案问题，以及明确要求查询公司内部资料的越界问题。题目、分组与两个集合的 ID 都由 [`cases.jsonl`](cases.jsonl) 和 [`split_lock.json`](split_lock.json) 固定，runner 每次运行都会校验题库哈希和切分。

运行器只调用本地固定语料索引，不访问模型 API，也不产生模型费用。它度量规则分类、已标注子问题覆盖、每请求最多 4 次检索、最多 5 条候选证据内的必需来源召回、版本错误、无答案候选噪声和本地 warm 检索时间。它不运行或评估生成回答，也不能据此声称答案准确率或幻觉率。

```powershell
python evaluation/change_review_v5/run_evaluation.py --split dev --policy bm25 --output evaluation/change_review_v5/results/dev__bm25.json
python evaluation/change_review_v5/run_evaluation.py --split dev --policy bm25_figure_ocr --output evaluation/change_review_v5/results/dev__bm25_figure_ocr.json
python evaluation/change_review_v5/run_evaluation.py --split holdout --policy bm25 --output evaluation/change_review_v5/results/holdout__bm25.json
python -m pytest -p no:cacheprovider evaluation/change_review_v5/test_evaluation.py -q
```

DEV 在实现定稿前用于检查规则规划和候选选择；HOLDOUT 在 DEV 决策完成后运行一次，只用于最终复核。不要根据 HOLDOUT 继续调参；发生后续修改时应新建 V6 题库和锁文件。命令可以复现检索结果，但 warm 延迟受本机环境影响，不是公网延迟承诺。

## V5 结果

当时的 BM25 是旧版 DolphinScheduler 服务的实际运行策略。DEV 结果见 [`dev__bm25.json`](results/dev__bm25.json)：规则类型分类 100%，标注子问题覆盖 100%，四次查询预算合规 100%，私有范围拦截 2/2 且没有发起 RAG 请求；必需来源 Recall@5 为 96%，完整必需来源率为 95%（20 条可回答题中 19 条找齐来源），版本错误 0。DEV 中 3 条公开但语料不支持的问题都返回了候选，候选噪声率 100%；这不是模型幻觉率，但说明检索命中本身不足以判断答案可答，必须保留证据约束生成和人工审核。

按人工复核 OCR 得到的图片证据候选见 [`dev__bm25_figure_ocr.json`](results/dev__bm25_figure_ocr.json)：图片 Hit@5 为 6/7（85.71%），文字来源 Recall@5 与完整来源率和 BM25 持平，但这里仅有 7 个图片锚点，仍是小样本 DEV 对照。在该历史版本中，为保持当时冻结的正式 BM25 运行策略，OCR 结果只作候选，不默认启用。当前 Autoware 服务采用独立评测选出的图片证据策略，见 [Autoware 检索评测 V3](../autoware_retrieval_v3/README.md)。

锁定 HOLDOUT 报告见 [`holdout__bm25.json`](results/holdout__bm25.json)：分类 100%，子问题覆盖率 85.71%，预算合规 100%，私有范围拦截 2/2、误拦公开问题 0；来源 Recall@5 为 85.71%，4 条可回答题中 3 条找齐全部必需来源，版本错误 0。唯一子问题覆盖未满的样例是单句英文无答案问题；业务问题只需要整句检索，显示题目对“分解覆盖”的标注需在下一版改进。1 条公开无答案题仍返回候选，说明 V5 不解决普通公开问题中的检索噪声。

DEV / HOLDOUT 各只有 25 / 7 条，且是人工构造的公开资料问题；图片样本、私有越界样本和无答案样本都不足以估算生产分布。耗时只计算同一 Python 进程内的索引检索，不包含 HTTP、模型生成、冷启动和公网网络。
