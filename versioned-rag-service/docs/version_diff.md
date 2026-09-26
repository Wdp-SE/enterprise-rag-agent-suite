# 版本差异

版本差异以规范化 section_path 作为稳定章节身份，以内容哈希判断内容变化。

输出类型：

- ADDED：新版本新增章节。
- REMOVED：新版本删除章节。
- MODIFIED：章节身份不变但内容哈希变化。
- UNCHANGED：章节身份与内容哈希均不变。

每条差异保留旧、新章节快照和 document_id、from_version_id、to_version_id，可用于审计、变更说明和增量更新验证。
