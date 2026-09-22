# 秋招原型最终评测报告

## 1. 评测边界

评测通过本地 HTTP 调用真实 RAG 服务和 Agent 工作流，使用临时版本库，避免污染正式业务数据。离线基线仅用于 Evaluation 页面展示，不进入正式 Runtime。

## 2. RAG 评测

固定评测集共 7 个案例，覆盖项目背景、系统范围、非功能需求、版本正确性、引用完整性、无答案拒答和 Scope 约束。

| 指标 | 结果 |
| --- | ---: |
| 案例数 | 7 |
| Hit@5 | 1.0000 |
| Recall@5 | 1.0000 |
| MRR | 1.0000 |
| 当前版本正确率 | 1.0000 |
| Citation 完整率 | 1.0000 |
| 无答案安全率 | 1.0000 |
| Scope 违规数 | 0 |
| 检索延迟 P50 | 66.852 ms |
| 检索延迟 P95 | 77.057 ms |

这些数据来自最终干净临时版本库上的真实 HTTP 运行。机器可读结果以 `project_delivery/v4_change_impact_review/evaluation_results.json` 为准；时延变化不代表本轮修改了检索语义。

## 3. 变更影响识别

| 指标 | 结果 |
| --- | ---: |
| 影响识别 Precision | 1.0000 |
| 影响识别 Recall | 1.0000 |
| 未授权应用次数 | 0 |
| 重复应用次数 | 0 |
| 原始 ACTIVE 文档保持不变 | 是 |
| 候选版本状态 | ACTIVE |

## 4. Evidence Context Budget

一次完整工作流中，证据统计为：retrieved 5、valid 5、deduplicated 5、selected 5，预算上限为 5。选择器保留了关键需求证据，并将实际选择过程写入 Trace。

## 5. Quality Gate 与恢复能力

- 未完成人工审核时，Patch 被 `REVIEW_REQUIRED` 阻断。
- 缺少证据、越界证据、过期证据、基线不匹配、目标变化和重复应用均有确定性阻断原因。
- 候选版本只有在构建、校验和激活成功后才报告 PASS。
- Checkpoint/Resume 评测通过。
- 单次真实工作流耗时为 33238.263 ms，共发起 9 次 RAG 调用。

## 6. 离线版本基线

对照包含 2 个真实问题。无版本限制的候选检索同时返回 v1 与 v2，而正式版本感知检索只返回 ACTIVE 的 v2。该结果说明版本治理减少了旧版本证据混入，但它不被包装成生产 A/B 实验，也不改变正式 DENSE_ONLY + SECTION_PATH 路径。

## 7. 可复现入口

- 评测脚本：`demo-ui/scripts/run_v4_evaluation.py`
- 机器可读结果：`project_delivery/v4_change_impact_review/evaluation_results.json`
- Evaluation 页面：启动 UI 后进入“评测结果”页签
- 一键启动：仓库根目录执行 `./start_prototype.ps1`
