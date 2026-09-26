# V4 固定评测报告

## 范围与限制

评测使用 `evaluation_dataset.json` 中 7 个完全合成、固定用例，并通过真实 Agent→RAG HTTP 边界运行。它覆盖 Exact ID、跨文档、语义、版本冲突、No Answer、Scope Violation 和术语/缩写。数据集规模很小，结果只能证明当前 Golden Case 和安全规则，不能外推为生产召回率，也没有据此上线 Hybrid。

## RAG 结果

| 指标 | 结果 |
|---|---:|
| Hit@5 | 1.0000 |
| Recall@5 | 1.0000 |
| MRR | 1.0000 |
| Exact Identifier Hit@5 | PASS |
| Current Version Correctness | PASS |
| Citation Membership Correctness | PASS |
| No-answer Rejection | PASS |
| Scope 错误引用 | 0 |
| P95 Latency | 109.513 ms |

No Answer 与 Scope Violation 使用受控 EngineeringItem 检索，未向 Dense 结果强行套用未经校准的拒答阈值。版本冲突用例只允许 `system_design` 当前版本，确认未返回 `design-v1`。

## Agent 结果

| 指标 | 结果 |
|---|---:|
| Impact Recall | 1.0000 |
| Impact Precision | 1.0000 |
| Patch Target Correctness | PASS |
| Evidence Coverage | 1.0000 |
| Unauthorized Apply Count | 0 |
| Duplicate Patch Apply Count | 0 |
| Resume Correctness | PASS |
| RAG Call Count | 9 |
| Workflow Latency | 9878.840 ms |
| Candidate 状态 | ACTIVE |
| 原文未覆盖 | PASS |

已确认影响为 `DES-014 / API-008 / TC-102`，疑似语义影响为 `OPS-006`。Stale Evidence 和 Conflict 由 Agent 专项测试覆盖；发布失败保留旧 ACTIVE 由 RAG Candidate 专项测试覆盖。

## 安全硬指标

- 未经批准写入：0
- 重复 Patch 应用：0
- 过期 Evidence 未阻断：0
- Scope 错误引用：0
- 发布失败导致旧有效版本丢失：0

原始机器结果保存在 `evaluation_results.json`。未来扩大真实授权数据集前，不设置人为的生产 Recall 阈值，也不根据当前小样本声称 Hybrid 更优。
