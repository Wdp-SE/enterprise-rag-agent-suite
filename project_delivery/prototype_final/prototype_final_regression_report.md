# 秋招原型最终回归报告

## 1. 结论

Prototype Final 在冻结 V4 业务语义的前提下通过最终回归。RAG、Agent、UI、真实 HTTP 集成、版本生命周期、离线 Runtime、浏览器 Smoke、依赖检查、Secret Scan 和 Git 差异规范检查均通过。

## 2. 自动化测试

| 检查 | 结果 |
| --- | --- |
| RAG 全量测试 | PASS，47 passed in 4.93s |
| Agent 全量测试 | PASS，103 passed in 2.74s |
| UI 全量测试 | PASS，20 passed in 6.00s |
| Evidence Context Budget 专项 | PASS，包含 Scope/Freshness、稳定去重、必需证据和可配置预算 |
| Deterministic Quality Gate 专项 | PASS，包含审核、证据、Scope、新鲜度、基线、目标变化和幂等 |

Agent 测试环境仍会输出既有的 `pytest-asyncio` 默认 loop scope 弃用提示；它不影响测试结果或 Runtime。

## 3. 业务闭环与可靠性

| 场景 | 结果 |
| --- | --- |
| Safe Business E2E | PASS，synthetic/offline，缺失字段 fail-closed，拒绝时阻断正式输出，审核后生成 Approved DOCX |
| Human Review | PASS，未批准修改不会写入；批准、编辑复核和拒绝路径由 Agent 全量测试覆盖 |
| Checkpoint/Resume | PASS，V3 章节恢复只处理未完成部分；V4 恢复返回 `SKIPPED_ALREADY_APPLIED` |
| Evidence Freshness | PASS，旧版本与内容变化会阻断依赖该证据的输出 |
| Conflict / Idempotency | PASS，基础版本、目标内容、输出存在和重复应用均确定性处理 |
| Candidate / Safe Activation | PASS，候选校验成功后才激活，失败时原 ACTIVE 保持不变 |

## 4. RAG 与 Agent 集成

固定评测在全新的临时版本库上通过真实 HTTP 边界执行：

| 指标 | 结果 |
| --- | ---: |
| 固定 RAG 案例 | 7/7 |
| Hit@5 / Recall@5 / MRR | 1.0 / 1.0 / 1.0 |
| 当前版本正确 / 引用正确 / 无答案拒答 | 全部通过 |
| Scope 违规 | 0 |
| P50 / P95 | 66.852 ms / 77.057 ms |
| 影响 Precision / Recall | 1.0 / 1.0 |
| 未授权写入 / 重复写入 | 0 / 0 |
| RAG 调用数 | 9 |
| Candidate 状态 | ACTIVE |
| 原始 DOCX | SHA-256 前后一致 |
| Evidence Budget | retrieved 5 / valid 5 / deduplicated 5 / selected 5 / max 5 |
| Quality Gate | PASS，`patch_apply_status=APPLIED` |

完整 V4 Business Smoke 也通过：3 个变化项、3 个确认影响、1 个建议影响；当前查询只返回 `design-v2`，显式历史查询返回 `design-v1`。

## 5. RAG 生命周期与离线运行

| 检查 | 结果 |
| --- | --- |
| Versioned RAG E2E | PASS，首次版本、ACTIVE 默认查询、历史显式查询、跨文档范围和版本 Diff 均正确 |
| Incremental Build | PASS，V2 重用 1 个 Embedding，新建 2 个 Embedding |
| Offline Runtime Smoke | PASS，Artifact COMPLETE，DENSE_ONLY + SECTION_PATH |
| 外部生成 | 已禁用，状态为 `GENERATION_DISABLED_BY_DATA_POLICY` |
| 正文日志 | 未输出 |
| 离线版本对照 | 2/2 有效；无版本限制会混入 v1/v2，正式检索只返回 ACTIVE v2 |

## 6. UI 与演示验证

| 检查 | 结果 |
| --- | --- |
| Streamlit Health | HTTP 200，`ok` |
| Streamlit 首页 | HTTP 200 |
| Chrome Smoke | PASS，主标题可见，7 个页签名称与顺序正确 |
| 最终截图 | PASS，PNG 242611 bytes，1440×1050 |
| Trace 只读约束 | PASS，UI 组件测试确认投影已有状态，不触发额外检索 |
| Evaluation 面板 | PASS，读取固定 JSON，展示真实指标与 evaluation-only 对照 |

## 7. 工程检查

| 检查 | 结果 |
| --- | --- |
| RAG compile/import | PASS |
| Agent compile/import | PASS |
| UI compile/import | PASS |
| RAG `pip check` | PASS，No broken requirements found |
| Agent/UI `pip check` | PASS，No broken requirements found |
| Secret Scan | PASS，260 个文本文件、18 个二进制文件跳过、0 potential match |
| `git diff --check` | PASS |

Secret Scan 只扫描 Git 跟踪文件和本轮非忽略文件，不保存命中正文；根据保护要求排除了 `OpenManus-rag/runtime/` 与 `project_delivery/interview_guide/`。

## 8. 数据与目录安全

- 所有新鲜评测、V4 Business Smoke、Versioned E2E 和 Offline Smoke 都使用系统临时目录或合成资料。
- Safe Business 脚本生成的随机输出已经逐项核对后恢复为原有基线，没有作为本轮产品改动提交。
- `OpenManus-rag/runtime/` 未修改、未暂存。
- `project_delivery/interview_guide/` 未修改、未暂存。
- 未运行完整 Performance Benchmark；本轮没有改变检索算法，只运行了固定 HTTP 评测并保留了既有 Benchmark 脚本与报告。

## 9. 最终业务边界

正式 RAG 仍为 DENSE_ONLY + SECTION_PATH 的版本感知研发文档知识服务；正式 Agent 仍为 Evidence 驱动的文档工作流和变更审查。离线版本对照、Trace 和 Evaluation 都没有进入生产路由，也没有新增模型调用、Hybrid Search、LangGraph 或全文重写路径。
