# RAG V3 五分钟面试演示

## 0:00–0:40 文档目录

打开“研发文档 RAG”。展开“当前文档目录”，指出 `REQ V1.0` 是
`SUPERSEDED`，`REQ V2.0` 是 `ACTIVE`。说明 `document_id` 保持稳定，
版本是独立元数据，默认检索依据状态而不是版本字符串排序。

## 0:40–1:30 默认当前知识

检索范围选“全部当前有效文档”，提问“最大并发是多少？”。展示回答或
Evidence 来自 `REQ V2.0 / ACTIVE`，内容为 1000，并指出页码与 Section
引用。

## 1:30–2:10 历史版本

检索范围切换到“指定版本 / 历史版本”，选择 `REQ V1.0 / SUPERSEDED`。
再次提问，展示历史答案 500。强调这是显式历史查询，普通查询不会混入
旧版本。

## 2:10–2:50 文档范围

切换到“指定文档”，只选择 DESIGN。检索一个设计问题，展示所有结果都
来自设计文档。解释 Scope 在候选向量阶段生效，结果是范围内真实 Top K。

## 2:50–3:50 Version Diff

展开“版本对比”，选择 `REQ V1.0 → V2.0`。展示四个计数以及 Section
明细：容量指标 `MODIFIED`、吞吐指标 `ADDED`、旧约束 `REMOVED`、系统
概述 `UNCHANGED`，并展开新旧页码与哈希。

## 3:50–5:00 Agent Freshness

切换到“文档工作流 Agent”。说明每条 Evidence 显示 Version 和 Freshness。
演示或讲解 checkpoint 场景：任务中断时引用 V1，期间激活 V2；Resume
把 V1 标为 `STALE`，只重新检索受影响 SectionTask，获得 V2 `FRESH`
Evidence。未受影响的已完成 Section 不重复调用 RAG，陈旧 Evidence 不能
通过 Finalization Guard。

结束时明确：这是基础版本治理、范围感知检索、增量内容更新、确定性
Section Diff 与 Evidence Freshness；不包含 ACL，也不宣称生产级 QPS。

