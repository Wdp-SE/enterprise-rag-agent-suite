# Quality V4 — 多资料与截图证据检索评测

V4 在当前固定的 132 份官方资料、1,322 个文本片段上，增加跨资料、跨版本、截图 OCR、图文联合与无答案候选诊断。评测只衡量检索证据，不衡量模型回答准确率、拒答率或幻觉率。

## 冻结范围

题库共 104 条：单资料 16、跨资料 16、跨版本 16、仅图片 OCR 24、文本加图片 16、无答案 16。图片题覆盖 12 张经固定提交校验并人工目视复核的 3.4.3 截图；8 张也进入图文联合组。相同问题族和同一 figure_id 被锁在同一个 DEV/HOLDOUT 切分，避免相似题或同一张图跨集合泄漏。每条图片标注保存图像 SHA-256 与可见区域描述。OCR 只代表已读出的截图文字和值，不表达流程图箭头、复杂拓扑或图片中未读出的信息。

评测冻结清单为 `input_lock.json` 和 `frozen_split.json`。选型及 HOLDOUT 的一次性执行记录分别保存为 `selection_lock.json`、`holdout_execution.json`；固定 BM25 对照只补跑一次并记录在 `baseline_execution.json` 与 `results/holdout__bm25_baseline.json`。不得覆盖已经生成的 DEV 或 HOLDOUT 文件；若要调策略，应创建 V5 或新的独立评测目录。选定候选的 HOLDOUT 已打开，只能按报告解释，不能据此继续挑参。

## 指标

- `source_recall_at_20`：必需来源进入前 20 的比例。
- `complete_source_at_5`：前 5 同时含有全部必需文字来源的比例；跨资料、跨版本另分组统计。
- `anchor_recall_at_5`：前 5 中包含的原文证据锚点比例。
- `image_hit_at_5` / `image_recall_at_5`：必需截图是否出现在前 5。
- `version_mismatch_count`：请求版本范围内出现错误版本的次数，目标为 0。
- `no_answer_nonempty_candidate_rate`：无答案题仍返回检索候选的比例。它是候选噪声诊断，不是模型幻觉率。
- `retrieval_call_count` 与本地 warm P50/P95：记录策略扇出与进程内检索成本，不含公网冷启动和模型调用。

## 运行

评测代码先校验所有锚点与固定资料、OCR sidecar 的哈希，再按固定 seed 切分。输入已冻结，本目录禁止重新执行 `--freeze`。候选开发集命令示例：

```powershell
python evaluation/real_world_retrieval/quality_v4/run_quality_v4.py --split dev --policy bm25
python evaluation/real_world_retrieval/quality_v4/run_quality_v4.py --split dev --policy bm25_figure_ocr
```

所有五种策略的 DEV 结果见 `results/dev__*.json`，解释和晋级门槛见 [report.md](report.md)。候选 `bm25_figure_ocr` 未达到原文锚点召回非劣化门槛，因此服务默认仍为 BM25；下一轮若采用“文字与图片分通道”的新方案，必须使用 V5/独立题集重新选型。V4 冻结 runner 的 nDCG 对同一来源的多个片段存在重复计数缺陷，不能用于策略比较；下一版修正后再报告该指标。

评测流程限制：冻结 runner 的 `--lock-selection` 会校验 DEV 结果指纹，但不会自动计算或把晋级阈值写入选择锁。当前候选与 BM25 的 DEV 对比按配对门槛复核为通过；不过 V4 锁没有保存阈值和门槛明细，不能把这次复核表述为代码强制的、可复演的 DEV 晋级门禁。候选已完成唯一一次 HOLDOUT，结果未通过原文锚点非劣化检查，线上仍保留 BM25。新的检索策略必须放到 V5 或独立评测目录，在打开 HOLDOUT 前由 runner 强制执行并哈希绑定 DEV 门槛、结果与选择记录；不要修改这份已冻结的 V4 runner 或结果来补记流程。
