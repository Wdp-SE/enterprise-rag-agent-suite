# V4 变更影响审核闭环实施计划

## 实施约束

- 分支：`feature/change-impact-review`
- 方式：每项生产行为先写失败测试，再写最小实现，再运行相关回归。
- 提交：M1–M5 独立小提交；任何失败均停在当前里程碑修复。
- 不改：冻结 Dense/Trusted QA 语义、现有 Document Workflow 语义、清理候选和受保护本地文件。

## M1：企业适配与 EngineeringItem

新增 RAG `src/engineering_change/`：

1. 测试两套 `OrganizationProfile`：编号正则、文档类型映射、章节别名、版本状态映射。
2. 实现 `OrganizationProfile` 严格模型和配置加载。
3. 测试并实现 `IdentifierExtractor`，只向核心层输出统一 `external_identifier`。
4. 测试并实现 `EngineeringItem` 与从结构化 section 输入建立 item 的 adapter。
5. 生成完全合成的公司 A 六份 DOCX 与公司 B 最小解析夹具。
6. 运行 M1 测试和 RAG 全回归，提交 M1。

## M2：Diff、Trace 与影响发现

1. 先测 EngineeringItem 的 ADDED/MODIFIED/REMOVED/UNCHANGED 和内容哈希。
2. 实现 Item Diff，不做复杂语义 Diff。
3. 先测 `EXPLICIT+CONFIRMED` 与 `SEMANTIC+SUGGESTED` 不可混淆。
4. 实现 TraceLink、ImpactCandidate 和影响服务。
5. 实现 Scope → Exact ID → Dense baseline suggestion → Confirmed Trace Expansion 的顺序。
6. 将工程接口接入现有 FastAPI，并扩展 Agent 现有 HTTP 客户端协议，不复制 HTTP 层。
7. 运行 M2 单测、API 测试、RAG 与 Agent 回归，提交 M2。

## M3：Patch、Review、Conflict、Idempotency

1. 先测 `PatchCandidate(REPLACE_PARAGRAPH)` 只定位唯一段落。
2. 先测 PENDING/REJECTED/EDIT 未复核均不得 apply。
3. 实现单审核人 Patch Review；EDIT 后进入 `EDITED_RECONFIRM_REQUIRED`。
4. 先测 base version、anchor、原文、hash 任一变化返回 CONFLICT。
5. 先测幂等键重复执行为 SKIP，候选文档内容只修改一次。
6. 复用 Evidence 与 Freshness；过期 Evidence 只阻断依赖 Patch。
7. 扩展现有原子 CheckpointStore payload 能力，测试中断恢复不重复应用。
8. 实现 `ChangeImpactWorkflow` 与 facade；输出轻量结构化 trace。
9. 运行 M3、Agent 全回归与 Safe Business 相关测试，提交 M3。

## M4：Candidate Version 与安全激活

1. 先测原 DOCX 永不覆盖，candidate 输出独立路径。
2. 先测 candidate 经 DOCX/structure/chunk/embedding/index/business validation 后才激活。
3. 使用现有 `VersionLifecycleService.ingest_version(activate=False)` 构建。
4. 所有校验通过后使用现有 `activate_version()` 原子切换。
5. 先测任一步失败时旧 ACTIVE 继续有效，失败原因可读。
6. 测试默认查询命中新版本，显式 historical scope 仍命中旧版本。
7. 增加真实 Agent ↔ RAG HTTP 集成与 V4 端到端测试，提交 M4。

## M5：UI、评测与交付

1. 先写 Streamlit 测试，覆盖工作台标题、流程阶段、Confirmed/Suggested 分区、Patch 审核和发布状态。
2. 新增独立页签，保留现有 RAG 和文档工作流页签行为。
3. 固定 RAG 评测集：Exact ID、跨文档、语义、版本冲突、No Answer、Scope、术语。
4. 固定 Agent 评测集：影响、Patch 目标、Evidence、未授权写入、过期阻断、冲突、恢复、重复应用、调用数和耗时。
5. 生成架构、领域模型、企业适配、影响分析、Patch 审核、评测、回归、演示和最终报告。
6. 执行 V3 全回归、V4 A–O、pip check、compile/import、Secret Scan、Streamlit Smoke、HTTP Integration 和 `git diff --check`。
7. 提交 M5 并停止新增功能。

