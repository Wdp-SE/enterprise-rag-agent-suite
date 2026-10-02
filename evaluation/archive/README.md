# 历史评测归档说明

本目录页说明仓库中仍保留的旧评测目录及其边界。为保留开发轨迹，它们没有从 Git 历史和仓库文件中抹除；这些题集、语料指纹和报告不属于当前活动产品，不能当作 Seeed/Jetson 语料的成绩，也不会由当前 API 或工作台读取。

当前活动评测只有：

- [`../edge_ai_retrieval_v2`](../edge_ai_retrieval_v2/README.md)：Seeed 中文固定快照检索 DEV/HOLDOUT。
- [`../edge_ai_change_review_v2`](../edge_ai_change_review_v2/README.md)：Jetson 设备变更审查流程评测；不声称 LLM 影响建议的人工准确率。

仓库顶层其余评测目录均为历史材料，包括 Autoware、DolphinScheduler、旧合成演示、旧检索策略探索和旧 Agent 查询规划实验。它们保留原始题目与指标，便于追溯历史决策，但不参与当前默认数据加载、发布验证、检索配置或求职项目的当前性能介绍。

更换语料、代码或评测题集后，只有与当前发布指纹一致的冻结报告才能被工作台展示。旧结果不得迁移为新语料的基准，也不能用来声称新领域有效。
