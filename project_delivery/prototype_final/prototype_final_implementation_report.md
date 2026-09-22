# 秋招原型收口实施报告

## 1. 实施目标

本轮在已验证的 V4 业务闭环上完成秋招演示收口，不改变正式业务语义，不引入新框架，也不继续做仓库清理。最终产品仍由两个边界清晰的服务组成：RAG 负责版本可信的研发文档知识服务，Agent 负责证据驱动的文档变更审查。

删除前恢复点为 Git 标签 `backup/pre-prototype-final-20260922`，指向基线提交 `e2860d09bad57c9f0898f6ee5baebf54921b17b1`。

## 2. 统一产品界面

Streamlit 首页统一为“版本可信研发知识与变更审查系统”，并按业务流程组织为七个页签：

1. 项目概览
2. 文档与版本
3. 可信检索与版本差异
4. 变更影响与修改审核
5. 执行轨迹
6. 评测结果
7. 扩展：文档起草

V4 的变更影响审查是主流程，原有文档起草能力作为扩展入口保留。所有主流程标签、状态和说明都使用面向业务用户的中文；内部 ID、原始状态和技术字段收纳在技术详情中。

## 3. Evidence Context Budget

新增确定性的证据选择器，并由配置项 `max_evidence_count` 控制每个字段最多进入起草上下文的证据数，默认值为 5。选择过程依次执行：

- Workflow Scope 校验
- ACTIVE、版本和新鲜度校验
- 稳定去重
- 必需证据优先
- 按检索顺序截断

Trace 会记录 retrieved、valid、deduplicated、selected 四个阶段的数量。必需证据不存在或必需证据数量超过预算时会直接失败，不会静默丢弃。

## 4. Deterministic Quality Gate

Patch 应用前新增纯确定性 Quality Gate。它检查证据存在性、真实 scope、证据新鲜度、基线版本、目标锚点、人工审核状态、重复应用和候选版本校验。阻断原因使用稳定枚举：

- `NO_EVIDENCE`
- `OUT_OF_SCOPE_EVIDENCE`
- `STALE_EVIDENCE`
- `BASE_VERSION_MISMATCH`
- `TARGET_CHANGED`
- `ALREADY_APPLIED`
- `REVIEW_REQUIRED`
- `CANDIDATE_VALIDATION_FAILED`

旧的 `PatchApplyStatus` 和 `failure_reason` 继续保留，避免破坏 V4 已有调用方。Gate 不调用模型，不依赖随机性，也不改变 Patch 的局部修改语义。

## 5. Workflow Trace

执行轨迹页面只投影现有 Session 状态与 Trace，不触发新的 RAG 请求或模型调用。页面展示工作流阶段、证据数量、证据选择过程、Quality Gate 结果、候选版本和人工审核状态，便于演示系统为何继续、为何阻断以及执行到了哪一步。

## 6. 固定评测面板

评测脚本保留 V4 的真实 HTTP 评测，并增加一个明确标记为 evaluation-only 的离线对照：无版本限制的候选检索与 ACTIVE 版本检索使用相同语料和问题进行比较。该对照不接入正式 Runtime，不改变 DENSE_ONLY + SECTION_PATH 主链路。

评测面板直接读取固定 JSON 报告，展示 RAG 命中率、版本正确性、无答案安全性、影响识别、应用安全、恢复能力、Evidence Budget、候选版本状态和离线对照结论。

## 7. 文档与演示材料

本轮补齐了根 README、最终架构说明、演示脚本、实现报告、评测报告、面试讲解要点、回归报告和界面截图。根目录新增 `start_prototype.ps1`，用于在 Windows PowerShell 中启动既有 FastAPI 与 Streamlit 服务。

## 8. 明确未实施的内容

- 未新增 Hybrid/BM25 生产检索路径。
- 未引入 LangGraph、消息队列、数据库或新的前端框架。
- 未把离线对照接入生产运行时。
- 未增加不可靠的 Token/成本展示。当前主流程没有可核验的模型 usage 与统一价格来源，展示估算值会误导用户。
- 未修改 `OpenManus-rag/runtime/`、`project_delivery/interview_guide/` 或用户业务数据。

## 9. 兼容性结论

V4 的 RAG、版本治理、变更影响分析、局部 Patch、人工审核、候选版本发布、Checkpoint/Resume 和幂等保护语义保持不变。本轮新增逻辑集中在确定性选择、确定性校验、只读可视化和交付文档中。
