# 跨案例评测报告

## 结论

同一核心流程在 Case A 与 Case B 上均完成 15 项检查。该结果只适用于当前两套固定合成案例，不等同于通用准确率或生产能力。机器可读结果见 cross_case_results.json。

Case A 使用 REQ-023、容量与接口变化、候选 design-v2；Case B 使用 REQ-071、日志留存变化、候选 audit-design-v2。二者的组织、项目、章节、Evidence、Patch、资产组合与 Session 均不同。Case B 不读取 Case A Ground Truth，核心 Domain、Retriever 和 Agent 没有 Case-specific branching。

| 检查 | Case A | Case B |
| --- | --- | --- |
| Requirement Change Detection | PASS | PASS |
| Current Version Selection | PASS | PASS |
| Impact Candidate Generation | PASS | PASS |
| Evidence Scope / Version | PASS | PASS |
| Patch Target | PASS | PASS |
| Human Review Gate | PASS | PASS |
| Conflict Detection | PASS | PASS |
| Idempotency | PASS | PASS |
| Candidate Version | PASS | PASS |
| Safe Activation | PASS | PASS |
| New Version Retrieval | PASS | PASS |
| Baseline Immutable | PASS | PASS |
| Confirmed / Suggested Expected | PASS | PASS |

| 观察项 | Case A | Case B |
| --- | --- | --- |
| Confirmed | API-008、DES-014、TC-102 | DES-031、TC-207 |
| Suggested | OPS-006 | OPS-031 |
| Candidate | design-v2 | audit-design-v2 |
| Conflict / Duplicate Block | 1 / 1 | 1 / 1 |
| 新 Session 初始目录 | 空 | 空 |
| Baseline SHA-256 | 前后一致 | 前后一致 |

全通过只说明同一核心流程在两套结构不同的合成案例中复用，不能写成“适用于所有企业研发场景”或“系统准确率 100%”。
