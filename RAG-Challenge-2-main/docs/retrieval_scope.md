# 范围检索

RetrievalScope 支持 project_ids、document_types、document_ids、version_ids 与 include_superseded。

默认只检索 ACTIVE 版本。只有显式设置 include_superseded=true 才允许历史版本进入候选集。指定 version_ids 时，版本必须存在且属于范围中的文档。

范围筛选发生在相似度计算前，因此越权文档不会先被召回后再隐藏。范围仅改变候选集合，不改变向量、分数或排序规则。
