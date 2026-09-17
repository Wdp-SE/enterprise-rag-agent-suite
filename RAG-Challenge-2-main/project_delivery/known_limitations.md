# Known Limitations

## 1. Citation Membership 不等于 Semantic Entailment

当前 Validator 证明 `(document_id,page_number)` 来自实际 Retriever 结果，但不证明该页
语义支持答案全部事实，也不验证多文档覆盖完整性。

## 2. Retrieval Miss 会造成 False Abstention

Phase 2 有 1 个 Answerable 因目标文档/页未进 Top-5 返回 N/A。Post-answer policy 无法凭空
恢复缺失证据；本阶段没有改 Top-K 或检索算法掩盖该问题。

## 3. Pre-generation Reject 仍是 Shadow

Answerable/Unanswerable cosine 明显重叠，Held-out Hard Negative 的平均 Top1 甚至更高。
因此 pre-generation decision 不改变回答，`UNCERTAIN` 也不会自动拒答。

## 4. 没有 Learned Confidence

系统没有训练 calibration model，也不把多个高度相关的 Top-K score 合成伪概率。

## 5. 没有 Universal Hallucination Detection

Post-answer Enforcement 只覆盖结构无效、无 Citation、Citation Membership 失败及状态矛盾。
Citation 合法但内容错误的答案仍可能通过。

## 6. 没有 Conflict Resolver

Version Governance 解决明确的新旧版本选择，不检测或自动裁决两个有效来源之间的语义冲突。

## 7. Domain Evaluation 规模有限

当前固定资产为 34 题 Domain、8 题 Version、20 题 Trusted QA Held-out 和少量 Answer Smoke。
它适合秋招项目证据，不足以代表真实企业长尾流量。

## 8. OCR 是规则驱动工程适配

OCR trigger、block retention 和 rotation recovery 在当前中文法规 corpus 上验证，没有做跨版式、
跨语言或大规模 OCR benchmark。

## 9. CPU OCR 成本

EasyOCR 在 CPU 环境耗时较高，因此依赖页级 trigger/cache；不适合未经容量评估直接处理大规模
持续文档流。

## 10. Windows 原生路径兼容性

Docling Parse v2 和 FAISS 原生绑定在含中文绝对路径下出现过读取问题。当前使用 ASCII staging
或仓库根相对路径规避；这不是跨平台问题的完整解决方案。

## 11. Provider 与 Token 观测不完整

Answer/Rerank 可记录 usage，但 DashScope Embedding 响应没有同口径 token 数据；批量生产级
trace、成本告警和 SLA 尚未实现。

## 12. Candidate 不是完整 Knowledge Governance

Candidate v2 提供结构、路径、hash、引用与人工审核边界，但没有 Duplicate/Conflict/Freshness
全套治理，也不会在 APPROVED 后自动正式入库。

## 13. 缺少生产基础设施

没有生产级认证授权、租户隔离、审计平台、异步队列、分布式索引、在线扩缩容、备份恢复和
告警体系。

## 14. 公开资料验证不等于行业部署

特种设备资料来自公开法规/规范，只是首个垂直验证场景。项目没有真实企业内部数据、用户流量
或生产运行证据。

## 15. Production Readiness

`PRODUCTION_READY = NO CLAIM`。当前定位是 engineering-oriented、evaluation-driven、
trusted QA prototype。

## 工程意义

Known Limitations 不是隐藏缺点，而是说明每个指标和安全机制能证明什么、不能证明什么，避免
在简历、面试和后续迭代中扩大 Claim。
