# V4 最终实施报告

## 交付结果

V4 已完成“Requirement Version Change → Changed EngineeringItem → Confirmed/Suggested Impact → Evidence → PatchCandidate → Human Review → Conflict Check → Apply → Candidate Version → Validate → Safe Activation → 查询新版本”的受控闭环。开发位于 `feature/change-impact-review`，以小步里程碑提交；V3 正式 RAG、Agent 与 UI 能力继续通过全量回归。

## 新增能力

### RAG

- 轻量 `OrganizationProfile`、公司 A/B 配置夹具与 `IdentifierExtractor`。
- DOCX Heading/Paragraph/Table/Section Path 解析，并标记复杂内容人工检查。
- 统一 `EngineeringItem`、Item 版本 Diff、`TraceLink` 和影响发现。
- Scope → Exact Identifier → 既有 Dense → Confirmed Trace 的检索顺序。
- Candidate Version 构建、DOCX/结构/Chunk/Embedding/Index/业务完整性校验和显式安全激活。
- Candidate 文档目录、文本检索与 FastAPI 端点。

### Agent

- `ChangeImpactTaskState / ImpactCandidate / PatchCandidate / ReviewRecord`。
- APPROVE/EDIT/REJECT 单审核人流程，EDIT 后要求再次确认。
- `REPLACE_PARAGRAPH`、版本/Anchor/原文/哈希冲突检查。
- Evidence Freshness、Scope Fingerprint、Checkpoint/Resume 和幂等 SKIP。
- Candidate 构建与激活编排、结构化 Trace、实际 RAG Call 计数。

### UI 与交付

- 第三个 Streamlit 页签“工程变更审核工作台”。
- 展示 Diff、Confirmed/Suggested Impact、Evidence、Patch Before/After、Review、Conflict、Candidate、Activation 和 Workflow Progress。
- 六份完全合成 DOCX、固定 Evaluation Dataset、真实 HTTP Smoke/评测脚本和十项交付文档。

## 最大化复用

RAG 复用了 Document/DocumentVersion、Section Diff、Version Governance、Incremental Update、Embedding Cache、Scope、Dense、Artifact Validation 和 FastAPI。Agent 复用了唯一 HTTPRetrieveClient、Evidence/Freshness、CheckpointStore、单审核人思想、Pydantic 与 DOCX 处理。没有复制第二套 RAG Client、Evidence、Checkpoint、Review、Version 或 HTTP Layer。

## 企业差异处理

编号规则、文档类型名称、章节别名和版本状态外置到 OrganizationProfile。核心层只消费规范化 external_identifier、item_type 和 Section Path，不包含公司分支。第二 Profile 验证 `PRD-PAY`、`CASE-PAY` 等编号与不同章节别名可被同一 Parser/Domain/Retriever 处理；它没有第二套 UI、数据库、Pipeline 或 Workflow。

`organization_id` 与 `project_id` 用于业务归属、Scope 和来源展示。当前没有租户注册、数据库 schema 隔离、ACL/RBAC、企业管理员或权限策略，因此不是多租户系统。

## Patch 安全设计

Patch 只修改一个指定段落，并保存 base_version、Anchor、原文与哈希、Evidence、Scope 指纹和 Review。应用前重新读取当前目标版本并校验 Evidence；任何版本、Anchor、原文、哈希或 Scope 不一致都 fail-closed。幂等键和 Checkpoint 的 applied_keys 保证 Resume/重复请求不会二次应用。

原始 DOCX 复制为不可变任务输入，Patch 只写 Candidate。Candidate 先以非 ACTIVE 状态完成全部验证，随后单独激活；失败时旧 ACTIVE 不变。成功后旧版本保留为 Historical，可显式查询。

## 主动延期

- LangGraph：现有工作流仍清晰、可恢复且测试充分，引入会扩大编排迁移风险，没有真实必要。
- BM25/Hybrid/RRF：固定数据没有暴露需要替换 Dense 的召回缺口，未做无评测升级。
- PostgreSQL Checkpointer：当前单机文件 Checkpoint 未形成瓶颈。
- React、OpenTelemetry/Langfuse、数据库、权限、多租户、多级审批、Connector、图数据库、Multi-Agent、更多 Office 格式：均超出首版闭环。

## 验证结论

- RAG 47 passed，Agent 97 passed，UI 16 passed。
- 固定 7 Case：Hit@5/Recall@5/MRR 为 1.0；P95 109.513 ms。
- Agent Golden Case：Impact Precision/Recall 为 1.0，RAG Call Count 9。
- 未批准写入、重复应用、未阻断过期 Evidence、Scope 错误引用、发布失败丢失 ACTIVE 均为 0。
- Offline Runtime、Versioned E2E、真实 HTTP、Streamlit、pip、compile/import、Secret Scan 与 diff check 全部通过。

这些数字来自小型完全合成数据，用于证明业务闭环和安全门禁，不代表生产效果承诺。

## 当前明确边界

首版只可靠修改普通 DOCX 段落。图片、流程图、复杂公式和复杂表格只提示人工检查；没有自动冲突合并。单审核人、单机 Checkpoint 和本地候选版本库适合演示与工程验证；并发多实例、长期任务与企业权限需要未来真实需求。Citation/Evidence 证明来源可追溯，不自动证明建议事实正确。

## 里程碑提交

- `19d814b`：V4 只读影响分析
- `3aeb5c4`：M1 OrganizationProfile / EngineeringItem / 合成数据
- `f6a6b98`：M2 Diff / Retrieval / Impact
- `af701d7`：M3 Patch / Review / Conflict / Resume
- `9bba844`：M4 Candidate Version / Safe Activation
- M5：UI / Evaluation / Delivery（本轮最终提交）

达到停止条件后不再增加框架、Retriever、Agent、Connector、数据库、公司 Demo 或文件格式。
