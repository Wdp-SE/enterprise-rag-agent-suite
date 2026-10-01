# Autoware RAG 与变更审查 Agent：V2 策略评测

本报告针对仓库当前锁定的 Autoware 双语公开语料和 `bm25_figure_ocr` 服务策略。评测结果只有在题集、语料索引、关系表、复核图片 OCR、运行代码和服务配置指纹全部匹配时，才由 `/public/workspace` 报告为当前成绩。修改报告内容后，API 会因报告 SHA-256 不匹配而隐藏这组成绩。

## 结论

- **RAG 默认策略保持 BM25 + 已审核图片 OCR。** 90 道文本题按来源主题族切为 DEV/HOLDOUT，各 45 道。当前 HOLDOUT 的必需来源召回@5 为 40.0%，完整必需来源@5 为 30.0%，来源召回@20 为 58.0%，MRR@5 为 0.2596，nDCG@5 为 0.3079，错版本数为 0，本地检索 P95 为 52.80 ms。
- **Hybrid + 图片 OCR 候选不晋级。** HOLDOUT 来源召回@5 为 38.0%，完整来源率为 30.0%，来源召回@20 为 50.0%，MRR@5 为 0.2196，nDCG@5 为 0.2737，本地 P95 为 55.85 ms。两个跨语言方向中，英文问中文证据从 10% 降至 0%；中文问英文证据从 10% 升至 20%。它未满足预先锁定的无方向回退门槛，因此服务继续使用 BM25 + OCR。
- **Agent 采用双语分路检索，并将覆盖不足显式交给人工。** 28 道 HOLDOUT 变更任务上，双语检索的“RAG 来源锚点召回”是 63.6%，仅中文检索为 27.3%；完整来源锚点率分别为 56.5% 和 26.1%。双语模式平均 6 次检索，本机 P95 为 341 ms；仅中文约 3 次、本机 P95 为 171 ms。双语耗时约翻倍，且因审查门禁要求覆盖中英文，完整审查率为 71.4%，低于仅中文模式的 85.7%。高风险流程选择多找证据并暴露未完成项，而不把较快的单语检索误说成完整审查。

## RAG 明细

主题集包括单事实、跨资料、显式版本、中英跨语、翻译关系状态和范围外/无答案案例。图片问题位于单独的 6 题回归探针中，不混进 90 道文本题或策略晋级分母；它们只针对两张已经核验并绑定 SHA-256 的图片。

| 切分 / 策略 | 题数 | 来源召回@5 | 完整来源@5 | 来源召回@20 | MRR@5 | nDCG@5 | 错版本 | 本地 P95 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| DEV / BM25 | 45 | 30.0% | 25.0% | 40.0% | 0.2594 | 0.2852 | 0 | 41.85 ms |
| DEV / BM25 + OCR（当前） | 45 | 30.0% | 25.0% | 40.0% | 0.2594 | 0.2852 | 0 | 41.09 ms |
| DEV / Hybrid + OCR（实验） | 45 | 32.0% | 27.5% | 50.0% | 0.2704 | 0.2980 | 0 | 46.53 ms |
| HOLDOUT / BM25 | 45 | 40.0% | 30.0% | 58.0% | 0.2596 | 0.3079 | 0 | 52.78 ms |
| HOLDOUT / BM25 + OCR（当前） | 45 | 40.0% | 30.0% | 58.0% | 0.2596 | 0.3079 | 0 | 52.80 ms |
| HOLDOUT / Hybrid + OCR（实验） | 45 | 38.0% | 30.0% | 50.0% | 0.2196 | 0.2737 | 0 | 55.85 ms |

当前图片回归探针：BM25 命中 0/6；BM25 + 已审核图片 OCR 命中 6/6；Hybrid + 图片 OCR 也命中 6/6。这个数字证明被审阅的两张图片在这 6 个固定问题上可检索，不代表对任意研发图表都具备视觉理解能力。

本次无答案题的非空候选比例为 100%。这是“检索层仍会返回候选”的噪声提示，不能解释为模型误答率、答案错误率或幻觉率。答案准确率尚无人工复核标签，保持未评估。

## Agent 明细与边界

Agent workflow 实验直接调用项目当前变更分类、检查清单和 RAG 搜索路径，不调用 LLM。用例的必需来源锚点迁自 RAG 评测，不是人工确认的真实影响范围。因此，以下数值只比较多语言检索对锚点覆盖与流程门禁的影响，**不是 Agent 影响分析准确率**：影响候选正确率、漏报率、误报率、检查项完整率和最终建议质量都未评估。

| HOLDOUT 模式 | 任务数 | 来源锚点召回 | 完整锚点率 | 检查覆盖率 | 语言覆盖率 | 完整检索审查率 | 平均检索调用 | 本机 P95 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 中文单语 | 28 | 27.3% | 26.1% | 86.2% | 85.7% | 85.7% | 3.0 | 171 ms |
| 中英双语 | 28 | 63.6% | 56.5% | 81.6% | 91.1% | 71.4% | 6.0 | 341 ms |

双语配置明显增加来源召回，但也增加检索调用和延迟，并可能因“必须覆盖要求语言、否则状态不完整”的严格门禁而更频繁地要求人工补查。对于版本变更审查，这种取舍优先避免漏掉另一语言资料；如业务时延预算不允许，可在后续用经人工确认的任务标签评估可选语言策略，但不得把单语结果包装成双语检查完成。

## 指标解释与限制

- 来源召回@K：可回答问题所需来源中，有多少至少进入前 K 个结果；完整来源@K：所需来源是否全部进入前 K。它们衡量“找没找到资料”，不衡量答案中的每句话是否正确。
- 本地 P95 是当前固定环境下本地检索流程的耗时，不包括公网网络、Render/Streamlit 冷启动或模型生成，不能当作线上 SLA。
- 0 个错版本只说明这批固定问题没有观察到错版本命中，不证明所有版本组合绝无错误。
- 6 个图片回归问题集中在两张人工核验图片，样本不足以推断一般 OCR 或图片问答表现。
- Agent 的 `required_impact_sources` 来自相关证据锚点，并非人工确认的影响真值；没有保存并经人审的模型答案，所以不能给出 Agent 准确率或幻觉率。
- 线上服务没有被切换到 Hybrid 实验策略。浏览器请求不能选择候选策略。

## 复现

在仓库根目录执行，命令只运行本地检索和 Agent 工作流，不调用模型 API：

```powershell
python -m pytest evaluation/autoware_accuracy_v2 -q
python evaluation/autoware_accuracy_v2/run_rag_benchmark.py --split dev --policies bm25,bm25_figure_ocr,hybrid_figure_ocr --repeats 3 --output evaluation/autoware_accuracy_v2/results/dev-policy-comparison.json
python evaluation/autoware_accuracy_v2/run_rag_benchmark.py --split holdout --selection-lock evaluation/autoware_accuracy_v2/selection_lock.json --output evaluation/autoware_accuracy_v2/results/holdout-selected.json
python evaluation/autoware_accuracy_v2/run_agent_workflow.py --split dev --language-mode bilingual --output evaluation/autoware_accuracy_v2/results/agent-dev-bilingual.jsonl
python evaluation/autoware_accuracy_v2/run_agent_workflow.py --split holdout --language-mode bilingual --output evaluation/autoware_accuracy_v2/results/agent-holdout-bilingual.jsonl
```

HOLDOUT 已用于本次一次性比较，不可据此继续调参并宣称独立验证。任何重新选择都应创建新的评测版本和新留出集。
