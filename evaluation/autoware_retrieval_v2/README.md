# Autoware 检索扩充试验 V2（历史试跑）

这是扩大 Autoware Planning 语料时的中间试跑记录，不是当前策略晋级依据，也不用于宣传当前检索指标。其 HOLDOUT 在开发过程中已被查看；后续正式结果改由新的冻结题集 V3 报告，线上评测状态也只绑定 V3。

V2 使用 32 道问题（DEV 23 / HOLDOUT 9），用于检查新加入的 Freespace Planner、Intersection Velocity Planner 与既有规划验证资料是否能被检索。题目、锁文件、runner 和初步结果都保留在本目录，便于追溯从原 16 题 V1 到正式 V3 的题集扩展过程。不可将这份 HOLDOUT 结果称为未触碰的独立测试集。

当前 Autoware 语料说明、43 道正式冻结题与策略选择请查看 [V3 评测](../autoware_retrieval_v3/README.md)。V1 则保留为最初 16 题的历史基线。
