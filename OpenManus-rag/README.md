# 基于 RAG 的企业研发文档起草与审核工作流 Agent

> Evidence-driven Document Workflow Agent

本项目只解决一个业务问题：用户选择项目、文档和版本范围，上传结构化
Word 模板，系统在限定 RAG Scope 内收集 Evidence，生成证据约束草稿，
经单审核人逐章节审核后输出正式文档。它不是网页研究、知识采集、通用
聊天或万能办公 Agent。

## 业务流程

```text
WorkflowScope
  → DOCX Template Parse
  → SectionTask / FieldTask
  → bounded RetrievalQuery
  → RAG POST /retrieve
  → Evidence Sufficiency
  → EXTRACTIVE / controlled GENERATIVE FieldDraft
  → Draft DOCX + Citation Appendix
  → Section Edit / Approve / Reject
  → Finalization Guard
  → approved.docx
```

Checkpoint 保存 Scope fingerprint、任务、草稿、审核和 Evidence。Resume
会校验 Scope 不变；文档版本变化时将 STALE Evidence 保留为审计记录，
只重新执行受影响 Section。

## 核心边界

- UI/CLI 只调用 `DocumentWorkflowFacade`。
- `HTTPRetrieveClient` 是唯一 RAG HTTP 边界；不直接访问 FAISS。
- `FieldDraftingService` 是唯一 Drafting 边界；默认 `EXTRACTIVE`。
- `WorkflowRepository` 与 `CheckpointStore` 是本地持久化边界。
- `ReviewService` 只实现 Single-reviewer MVP，不是 OA 审批系统。
- AI 不得自动批准章节；全部必要章节 APPROVED 后才能生成正式 Word。

## Word 模板范围

支持 Heading/标题 1–3、Outline Level 1–3、段落、简单表格，以及
`{{字段名}}` 或 `【待填写】` 占位符。替换跨 Run 占位符时保留未受影响
Run 的字体属性。文档末尾生成“引用来源”附录，列出文档、版本、状态、
章节、页码和 Evidence ID。

旗舰模板：
`project_delivery/document_workflow_business_refactor/demo/requirement_change_impact_template.docx`

## 快速验证

要求 Python 3.12：

```powershell
python -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements.txt
.venv\Scripts\python.exe -m pytest tests -q
.venv\Scripts\python.exe scripts\run_business_e2e.py
```

安全 E2E 完全离线，使用合成 Evidence，覆盖多 Evidence 草稿、MISSING、
编辑、批准、驳回、正式输出门禁和引用附录。

## CLI

```powershell
.venv\Scripts\python.exe run_document_workflow.py `
  --runtime-root runtime `
  --rag-url http://127.0.0.1:8765 `
  run `
  --template project_delivery\document_workflow_business_refactor\demo\requirement_change_impact_template.docx `
  --scope '{"project_ids":["DEMO-RD"],"active_only":true}'

.venv\Scripts\python.exe run_document_workflow.py --runtime-root runtime list
```

配置变量见 `config/document_workflow.example.env`。

## 数据安全

`GENERATIVE` 只允许 synthetic、public、approved-redacted 或明确配置的
本地模型。真实未经授权企业资料不得发送公网模型。`EXTRACTIVE` 是默认
模式；无 Evidence 返回 MISSING，证据不足返回 INSUFFICIENT_EVIDENCE，
未知或陈旧 Evidence 会阻止正式输出。

## 项目演进

项目早期基于 OpenManus 探索过 Knowledge Research，随后按企业研发文档
业务收敛为当前单一工作流。旧产品功能不再属于运行时；演进记录保留在
Git 历史中。

## 文档

- `docs/architecture.md`
- `docs/review_and_finalization.md`
- `docs/evidence_freshness.md`
- `docs/runbook.md`
- `docs/known_limitations.md`
- `project_delivery/document_workflow_business_refactor/legacy_removal_plan.md`
