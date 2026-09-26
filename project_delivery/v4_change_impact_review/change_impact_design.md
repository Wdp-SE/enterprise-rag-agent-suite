# 变更影响分析设计

## 输入与输出

输入是同一需求文档的旧/新 EngineeringItem、当前 Scope、TraceLink 和当前 Dense 检索结果；输出是 `ADDED / MODIFIED / REMOVED / UNCHANGED` 变化列表以及显式影响和语义候选影响。Diff 以稳定 external_identifier 对齐，保留新旧内容、版本和哈希，不做不可解释的复杂语义 Diff。

## 检索顺序

1. 先应用 organization/project/document/version Scope。
2. 对查询中的工程编号做 Exact Identifier Match。
3. 复用当前正式 Dense 检索补充语义候选。
4. 用 Confirmed TraceLink 展开已确认关系。

正式检索仍是 Dense 基线，没有引入 BM25/RRF。Exact ID 是确定性增强，不改变既有 FAISS 数学和产物格式。

## 关系判定

显式 Trace 命中的设计、API 和测试项以 `EXPLICIT_TRACE + CONFIRMED` 输出。Dense 发现且未被显式关系覆盖的运维项以 `RETRIEVAL_SUGGESTION + SUGGESTED` 输出。Agent 和 UI 不得把 Suggested 写成已确认事实。

## Demo Golden Case

`REQ-023` 从 500 并发改为 1000，增加 200 MB/s，并把同步接口改为异步任务接口。固定期望为：

- 已确认：`DES-014`、`API-008`、`TC-102`
- 疑似影响：`OPS-006`

主 Demo 使用完全合成 DOCX。库存生成时只登记各文档拥有的主业务项，文档中出现的其他编号作为交叉引用输入，避免同一 external_identifier 被多份文档重复建模。

## 失败与边界

空查询、未知 changed_item、越界 Scope 和不存在的版本会拒绝或返回空结果。语义相似只能形成候选；没有人工确认路径将其写回 Confirmed Trace。固定评测数据较小，只证明闭环和规则，不能外推为生产召回率。
