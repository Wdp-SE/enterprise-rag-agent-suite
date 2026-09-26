# 架构

系统只有一条正式业务链：

    规范化研发文档
      -> VersionLifecycleService
      -> 内容哈希与增量向量复用
      -> ACTIVE 版本索引
      -> 冻结资产校验
      -> Dense-only 范围检索
      -> 同章节有界上下文
      -> 结构化回答
      -> 引用成员校验
      -> Trusted QA 失败关闭
      -> API 响应

src/document_lifecycle.py 管理文档、版本、章节差异和活动索引。
src/rd_v2_runtime.py 加载冻结资产并执行 DENSE_ONLY + SECTION_PATH 检索。
src/context_expansion.py 只处理已校验的冻结分块。
src/answer_generation.py 只提供研发文档证据约束下的结构化回答。
src/trusted_qa 负责检索信号、回答审计与确定性强制策略。
src/rd_v2_api.py 是唯一 Web API。

启动时先校验资产 COMPLETE 状态、文件哈希、向量数量、维度、有限值、单位范数和策略字段。任一校验失败均拒绝启动。
