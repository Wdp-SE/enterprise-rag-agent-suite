# 4-minute interview demo script

## 0:00–0:30 — Position the two projects

“这是两个冻结项目的统一 Demo。下面一层是面向大型研发文档的 RAG，上面一层是模板驱动的 Document Workflow Agent。RAG 解决资料怎么找，Agent 解决找到资料后怎样完成标准化业务流程。”

Point to the sidebar: RAG Healthy, Artifact Ready, Agent Ready, and Synthetic / Public data. Mention DENSE_ONLY + SECTION_PATH briefly.

## 0:30–1:30 — Show retrieval Evidence

Open **研发文档 RAG**, keep **Evidence Retrieval**, choose `项目目标是什么？`, Top K 5, and click **检索 Evidence**. Expand the first result and show Rank, Document, Page, Section Path, Similarity, and original content.

“这里调用的是 `/retrieve`，返回原始 Evidence 和可追溯元数据，不调用生成模型。`/query` 是给最终问答用的，而上层 Agent 使用 Retrieval-only 接口，避免 RAG 生成一次、Agent 再生成一次。”

## 1:30–3:30 — Run the Document Workflow

Open **文档工作流 Agent**, click **加载 Demo Template**. Point out the real TemplateParser output: template name, sections, table and fields, then expand the PENDING SectionTask plan. Click **开始生成草稿**.

After completion, show the real Summary: section count, RAG calls, unique Evidence, MISSING count, PARTIAL, and Human Review YES. Expand one COMPLETE section to show its queries, Evidence IDs, document/page/section, and draft preview. Expand the performance section:

“吞吐能力没有足够 Evidence，所以系统没有编数字，而是写入 MISSING。Workflow 因此保持 PARTIAL，Finalization Guard 也不会把它伪装成 COMPLETE。”

Show the real Trace timeline, then download `draft.docx`. Mention that Evidence and Trace JSON are also downloadable and the original template is not modified.

## 3:30–4:00 — Close

“这个 Demo 展示的边界是：RAG 提供可靠检索和出处，Agent 用固定高层 Workflow 组织 Evidence、处理缺失并生成待审核草稿。它不是自动审批或生产发布系统，最终文档始终需要人工审核。”

