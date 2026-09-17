# 5～8 分钟 Demo Guide

## Demo 目标

用已有 artifact 证明三件事：系统能做通用多文档和版本检索；答案可追溯；确定性非法回答
会 fail closed。Demo 不现场重跑 54 页 OCR、Embedding、FAISS 或完整评测。

## 演示前检查（30 秒）

```powershell
.venv\Scripts\python.exe main.py --help
.venv\Scripts\python.exe -m pytest -q
```

预期最终基线：220 passed / 0 failed；可能显示 1 个既有 DashScope Assistants deprecation
warning。若时间有限，只展示已保存的 `reports/trusted_qa_phase3/regression_result.json`。

## Demo 1：普通法规问题与当前版本（1 分钟）

问题示例：

> 压力容器安全员在安全档案、日常巡查、定期检验和事故处置方面承担哪些职责？

展示已有结果：`reports/trusted_qa_phase3/runtime_smoke_results.json` 中
`tqa-holdout-a09`。

讲解点：

- 问题没有 company name，走 Generic Mode。
- Version Resolver 默认选择当前 eligible 文档。
- 输出包含 Answer 和 `(document_id,page_number)` 校验后的 sources。
- pre-generation 观察与 post-answer validity 是两个独立阶段。

## Demo 2：历史版本检索（1 分钟）

打开：

- `reports/version_governance/version_extension_on/retrieval_results.json`
- `reports/version_governance/version_governance_report.md`

选一个明确询问 2017 版的问题，展示命中 `tsg-08-2017` 独立历史资产；再说明默认问题选择
2026 ACTIVE 文档。强调旧文档没有删除，也没有与当前索引混成无差别语料。

## Demo 3：Hard Negative 正确弃答（1 分钟）

问题示例：

> 《每日锅炉安全检查记录》依法至少需要保存多少年？

展示 Phase 3 Smoke 的 `tqa-holdout-n04`：

- 检索结果与主题高度相似；pre-generation 是 `UNCERTAIN`。
- 当前语料没有最低保存年限。
- 模型输出 `N/A`、Citation 为空。
- Post-answer action 为 `VALID_ABSTENTION`，不是错误。

## Demo 4：确定性 Fail-closed（1～2 分钟）

离线运行：

```powershell
.venv\Scripts\python.exe scripts\run_trusted_qa_phase3_replay.py
```

该命令只读 Phase 2 保存输出，不调用 Answer LLM。展示：

- `post_answer_enforcement_metrics.json`：历史 Citation Failure 2/2 intercepted。
- `post_answer_enforcement_replay.json`：original result、audit、decision、final result。
- 非法事实答案最终变成 `N/A + sources=[]`，内部仍保留原始生成结果。

强调：Gate 额外 LLM 调用为 0；Citation Membership 不是 semantic entailment。

## Demo 5：OCR 与横置页证据（1 分钟）

只展示离线证据：

- `reports/domain_evaluation_v0_2/ocr_smoke_validation.json`：0.65 误删有效块。
- `reports/domain_evaluation_v0_2/page_37_rotation_validation.json`：90°/270°比较。
- `reports/domain_evaluation_v0_2/exceptional_page_rotation_corpus_v0_2_report.md`：最终质量门禁。

讲解 270°候选恢复横置表格、第 37 页不再为空；rotation cache 命中后新增 OCR 调用为 0，
其他 53 页没有重跑。

## 收尾（30 秒）

```text
同一 34 题 Retrieval Hit@1：0.815 → 0.926
Full regression：220 passed / 0 failed
Pre-generation：Shadow only
Post-generation：deterministic enforcement
Production Ready：No claim
```

## 现场失败备用方案

- Provider/网络不可用：完全使用已保存 JSON/Markdown artifact。
- 中文绝对路径导致 FAISS 读取失败：使用仓库根相对路径；不要现场重建索引。
- OCR 环境慢：展示 cache 和报告，不运行 EasyOCR。
- 时间不足：只演示 Demo 1、3、4。

## 不要现场做

- 不运行完整 34/42/20 题 Answer Evaluation。
- 不重新解析 PDF、OCR、Embedding 或 FAISS。
- 不反复调用模型以复现随机 Citation Failure。
- 不把公开法规验证描述成真实企业生产系统。
