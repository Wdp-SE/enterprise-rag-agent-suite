# Autoware 检索策略评测 V3

本轮评测对应公网候选语料：Autoware Universe 0.51.0/0.52.0 固定快照，13 份不同英文资料、26 条版本化来源和 562 个文本片段。它覆盖 Planning 概览、Start/Goal/Freespace Planner、Intersection Velocity Planner 及部分规划验证组件，是精选子集，不是整个 Autoware 知识库。

评测比较 `bm25`、`bm25_faceted_rrf`、`bm25_figure_ocr` 与 `bm25_faceted_figure_ocr`，只评估 Top-5 检索候选，不调用模型；结果不代表生成答案准确率、幻觉率、真实用户分布或公网延迟。题集 `cases.jsonl` 共 43 道，DEV 32 道、HOLDOUT 11 道，按 `split_lock.json` 冻结。此前 V1/V2 暴露过的题只留在 DEV；HOLDOUT 使用新增问题表述，并含图片专属线索、跨模块问题和领域内无答案问题。

## 结果与策略选择

| 切分 | 策略 | 必需来源 Recall@5 | 完整来源率@5 | 图片证据命中@5 | 错版本 | 无答案仍返回候选 |
| --- | --- | ---: | ---: | ---: | ---: | ---: |
| DEV（32） | BM25 | 100% | 100% | 0/4 | 0 | 4/4 |
| DEV（32） | BM25 + 复核图中文字 | 100% | 100% | 3/4 | 0 | 4/4 |
| HOLDOUT（11） | BM25 | 91.67% | 90% | 0/2 | 0 | 1/1 |
| HOLDOUT（11） | BM25 + 复核图中文字 | 91.67% | 90% | 2/2 | 0 | 1/1 |

选用 `bm25_figure_ocr`：在这组题集里，它的必需来源覆盖、完整来源率和错版本数不劣于 BM25，并补回图片文字证据；分面策略没有再提高覆盖。图片文字只有在至少匹配两个不同词、且不会挤掉 Top-5 中其他唯一来源时才作为候选加入。DEV 图片命中不是满分，说明当前两张经审核图中文字的查询表达仍有召回边界。

HOLDOUT 有一道跨资料题 `freespace_validation_holdout_41` 没有召回 Freespace Planner 来源，另外两个必需来源命中；其余必需来源 Recall 为 91.67%、完整来源率为 90%。该失败案例应作为后续新版本评测的诊断输入，不能回头改写本轮 HOLDOUT 再报告同一组结果。

DEV 和 HOLDOUT 的无答案问题仍都返回候选（4/4、1/1），因此项目没有证明可靠拒答能力。当前指标只说明已标注必需来源能否进入 Top-5，不说明答案事实是否正确。warm P95 是本机进程内检索微基准，不包含模型、网络、冷启动或 Streamlit 页面耗时。

## 复现

在仓库根目录运行：

```powershell
python evaluation/autoware_retrieval_v3/run_benchmark.py --repeats 10
```

评测输出写入 `results/benchmark.json`。报告绑定语料、索引、图像侧车、运行策略配置、检索实现、题集、切分锁和 runner 的指纹；服务端另校验冻结报告 SHA 与晋级条件。只有报告、当前 runtime、语料及全部输入指纹匹配时，`/public/workspace` 才会显示“已验证”。更改题集、索引或策略后应建立新评测版本并重新冻结，不得覆盖这轮结果。
