# 检索设计

正式策略固定为 DENSE_ONLY，向量文本表示固定为 SECTION_PATH。

查询流程：

1. 校验查询和 RetrievalScope。
2. 在文档目录中筛选符合范围且版本状态允许的分块。
3. 使用隔离进程生成归一化查询向量。
4. 对候选向量执行精确内积，等价于单位向量余弦相似度。
5. 使用稳定的分块下标处理并列分数。
6. 取 dense_top_k，再截取 final_top_k。
7. 在同文档、同版本、同章节内追加锚点和邻近分块。

运行资产若声明启用词法检索、混合融合或重排器，FrozenArtifactValidator 会以 POLICY_CONFIGURATION_MISMATCH 拒绝加载。这些路径不属于正式运行代码。
