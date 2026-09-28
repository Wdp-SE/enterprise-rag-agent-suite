# V3 扩充语料检索评测

本评测针对固定提交的 Apache DolphinScheduler 3.4.2/3.4.3 官方资料。语料为 **132 份来源、1322 个片段**；题库为 72 条全新业务问题，按 9 类场景各 8 条组织。每类有 4 个双题场景家族，确定性哈希分配整个家族，DEV/HOLDOUT 各 36 条，避免同一家族跨切分。题目和人工标注保存在 `cases.jsonl`，来源 ID 使用 `version|language|document_key`。

## 冻结与计分

`selection_lock.json` 固定题库、切分、评测脚本、语料 manifest、索引片段、向量与检索策略的 SHA-256。每个可回答问题的证据锚点在冻结前逐一验证：必须同时出现在 manifest 所列原文和对应索引片段。未回答问题的来源集为空。冻结后修改任一输入会使 runner 拒绝运行。

指标按**独立来源**计算。来源 Hit@5 只要求至少命中一份必需来源；来源 Recall@5 是命中的必需来源数除以全部必需来源数；完整命中要求每份必需来源都在 Top-5 中。片段证据锚点召回要求锚点文字实际出现在返回的对应片段。MRR 按独立来源排名计分。重复命中同一来源的多个片段不会虚增来源指标。

无答案题只列 Top-1 分数分布，**不等同于拒答准确率**。检索指标也不证明生成答案的事实正确性或引用对每项主张的支持。warm 搜索耗时仅是本机内存索引的检索，不含进程启动、HTTP、模型调用、Render 冷启动。

索引基于固定 Markdown 文本；图片二进制及图片内文字未采集、未 OCR。图片引用的路径或替代文字可作为文本出现，但不能当成识别了图片内容。

## 已完成的一次性评测

DEV 上比较 BM25 与三种来源多样化候选后，选择 BM25。来源多样化提高了一题的多来源完整命中，却降低返回片段中的原文锚点覆盖，因此没有晋级。选择、DEV 结果哈希和候选代码指纹保存在 `candidate_selection.json`。

仅对锁定的 BM25 运行了一次 HOLDOUT，开封记录位于 `holdout_execution.json`，结果位于 `results/holdout__bm25.json`。两组各 36 题、其中 32 题可回答。DEV→HOLDOUT 的来源 Hit@5 为 0.9688→0.8750，宏来源 Recall@5 为 0.9531→0.8594，完整来源为 30/32→27/32，多来源完整命中为 6/8→4/8，返回片段锚点为 44/48→37/49。详情和失败题见 `report.md`。

以下命令只读取现有记录；可先运行只读单元测试检查冻结输入、DEV 结果哈希与 HOLDOUT 记录是否一致：

```powershell
python -m unittest discover -s evaluation/real_world_retrieval/quality_v3 -p test_quality_v3.py
Get-Content evaluation/real_world_retrieval/quality_v3/candidate_selection.json
Get-Content evaluation/real_world_retrieval/quality_v3/holdout_execution.json
Get-Content evaluation/real_world_retrieval/quality_v3/results/holdout__bm25.json
```

不要在这个冻结目录执行 `run_quality_v3.py --split dev`：它会覆盖 `results/dev__bm25.json`，新耗时将改变 `candidate_selection.json` 锁定的结果哈希。若要重新实验，使用独立工作树或新评测版本，并将输出写到独立路径；不要覆盖 V3 的已冻结结果。

runner 会拒绝再次打开 V3 HOLDOUT。不能根据 HOLDOUT 结果继续调参；若要改动策略、题目或语料，应建立新评测版本和新切分。题目及标注位于仓库，故这是固定的一次性离线验证，不能称为对开发者完全盲测。无答案分数不能代表拒答率，检索指标也不能直接代表生成答案的幻觉率。
