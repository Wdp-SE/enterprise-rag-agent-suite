# Final Evaluation Summary

## 1. 口径原则

本项目按阶段保存真实运行结果。Runtime 年报样本、Domain 34 题、Version 8 题、Trusted QA
Held-out 20 题以及 Answer Smoke 的目标不同，不能合并为一个“最终 Accuracy”。本文只整理
仓库内已有 artifact，不重新调用模型，也不补造缺失指标。

## 2. Reliable Runtime Baseline

来源：`artifacts/baseline_runtime/`。

| 项目 | 结果 |
| --- | ---: |
| 测试 PDF | 5 |
| 结构化页面 | 599 |
| Chunk | 1,924 |
| 正式问题 | 15 |
| Structured Output | 15/15 |
| Rerank 改变向量初排 | 14/15 |
| Parent Page 关联正确 | 15/15 |
| 当时本地回归 | 31 passed |

5 个新建 FAISS 均为归一化 `IndexFlatIP`；文档向量范数约为 1，查询范数约为 1，真实分数
落在 [-1, 1]。15 题人工精确匹配为 11/15，只是小样本运行诊断，不是业务准确率或比赛分数。
当次总 token 188,605，包含 Rerank 与 Generation，不含 Provider 未返回的 Embedding token。

## 3. Domain Corpus v0.1

来源：`reports/domain_evaluation_v0_1/`。

- 8 份公开 PDF、318 页完成审计。
- 4 份 ACTIVE 且 Native Text 可用的文档正式入库。
- 入库规模：128 pages、241 chunks / normalized vectors。
- Evaluation：34 题，其中 27 Answerable、7 Unanswerable；题型含 single、cross、version。

| Retrieval 指标 | 数值 |
| --- | ---: |
| Hit@1 | 0.814815 |
| Hit@3 | 0.814815 |
| Hit@5 | 0.814815 |
| Recall@5 | 0.759259 |
| MRR | 0.814815 |

版本题当时为 0，真实暴露了“当前扫描版未入库 + 无版本路由”的缺口。3 题 Answer/Rerank
Smoke 消耗 12,697 tokens；完整 34 题 Answer Evaluation 预计超过 100K，因此按资源边界停止，
没有编造完整 Answer Accuracy。

## 4. Corpus v0.2 与 OCR

来源：`reports/domain_evaluation_v0_2/`。

- 5 份默认入库文档、182 pages、319 normalized vectors。
- 旧 4 文档的 241 vectors 在配置和 hash 一致后复用；只为 TSG 08—2026 新增 78 vectors。
- TSG 08—2026 共 54 页；第 37 页经显式 90°/270°恢复，270°候选通过。
- Full OCR Quality Gate：54/54 页面通过；没有重复 OCR 其他页面。

| Retrieval 指标 | 数值 |
| --- | ---: |
| Hit@1 | 0.851852 |
| Hit@3 | 0.888889 |
| Hit@5 | 0.925926 |
| Recall@5 | 0.851852 |
| MRR | 0.879630 |

OCR 阶段早期 0.65 threshold 会过滤 confidence=0.621376 的有效“1.1 目的”文本；后续 0.60
全局阈值又被低置信有效日期/条款与噪声重叠证明不足，最终使用通用混合保留规则。以上只
代表当前 corpus 的工程校准，不是通用 OCR Accuracy。

## 5. Version Governance Final

来源：`reports/version_governance/`。

- TSG 08—2017：独立历史资产，46 pages、110 chunks / vectors，状态 SUPERSEDED。
- TSG 08—2026：当前 ACTIVE 文档。
- 原 5 题版本子集 Hit@1/3/5 与 MRR 从 0.6 提升到 1.0。
- 独立 8 题 Version Evaluation 的 OFF/ON Hit@1 从 0.75 提升到 1.0。

同一 34 题最终结果：

| Retrieval 指标 | 数值 |
| --- | ---: |
| Hit@1 | 0.925926 |
| Hit@3 | 0.962963 |
| Hit@5 | 1.000000 |
| Recall@5 | 0.944444 |
| MRR | 0.953704 |

简历中可写“同一 34 题 Retrieval Evaluation 的 Hit@1 从 0.815 提升至 0.926”，但必须说明
这是 Domain Corpus / OCR / Version Governance 阶段的检索指标，不是 Answer Accuracy。

## 6. Trusted QA Phase 1

来源：`reports/trusted_qa_shadow_v0_1/`。

Domain 34 题的 pre-generation Shadow：

- Answerable：27；Unanswerable：7。
- False Reject：0；False Accept：0；UNCERTAIN：18。
- Coverage：0.470588（47.06%）。
- 没有任何 REJECT，因此 Reject Precision 不可计算；不能据此上线 pre-generation reject。
- 6 题真实 Qwen Answer Smoke 消耗 11,822 tokens：3 个 Answerable 有实质答案与合法
  Citation，3 个 Hard Negative 为 N/A。

## 7. Trusted QA Phase 2

来源：`reports/trusted_qa_phase2/`。

- 冻结 Held-out：20 题，10 Answerable、10 Unanswerable。
- Unanswerable 中：7 Hard Negative、3 Easy Negative。
- Frozen policy 未按结果调整，holdout contamination=false。
- Answerable Top1 cosine mean=0.712550；Hard Negative mean=0.720500。
- Pre-generation：7 ANSWER、0 REJECT、13 UNCERTAIN；Hard Negative 有 3 个反事实 ANSWER。
- 结论：`POST_ANSWER_ENFORCEMENT_ONLY`。

10 题真实 Answer Smoke：Structured Output 10/10；5 个 Hard Negative 全部 N/A；发现 1 个
Retrieval miss 和 2 个真实 Citation Membership Failure。实际 Answer tokens 为 23,183。

## 8. Trusted QA Phase 3

来源：`reports/trusted_qa_phase3/`。

Phase 2 保存输出的确定性离线回放：

| 指标 | 结果 |
| --- | ---: |
| 历史 Citation Failure 拦截 | 2/2 |
| 已知合法答案保留 | 2/2 |
| 正确 N/A 保留 | 5/5 |
| False Fail-closed | 0 |
| Gate 额外 LLM 调用 | 0 |

真实 ENFORCE Smoke：4 题，2 Answerable 均 `PASS`，2 Hard Negative 均
`VALID_ABSTENTION`，Structured Output 4/4；Prompt/Completion/Total tokens 为
8,424/968/9,392，平均 latency 2,376.577 ms。本轮未随机复现 Citation Failure，因此两个
Phase 2 保存失败仍是正式回归证据。

## 9. 为什么没有部署 cosine Reject

Domain 34 题中 Answerable Top1 范围为 0.4434～0.8334，Unanswerable 为
0.4765～0.6862，存在明显重叠。诊断阈值 0.70475 虽覆盖 7/7 Unanswerable，却误拒
6/27 Answerable；Top1-Top2 margin AUC 只有 0.468254。Phase 2 Held-out 中 Hard Negative
均值甚至高于 Answerable。项目因此保留 pre-generation Shadow，不为简历效果上线无证据阈值。

## 10. 最终回归

- Trusted QA Phase 3 完成时：220 passed / 0 failed。
- 第三方 warning：DashScope Assistants API deprecated；不是项目回归。
- Finalization 会再次执行 Full regression、`pip check`、关键 import 和 CLI help，并将结果
  写入最终交付报告。

## 11. 不能从这些指标推出什么

- 不能称为最终 Answer Accuracy、Production Accuracy 或法律问答准确率。
- Citation Membership 不代表 Citation semantic support。
- 2/2 历史拦截不是大样本生产统计。
- 公开法规场景验证不代表真实特种设备企业部署。
- 220 tests 证明已编码行为的回归稳定性，不证明所有业务输入均正确。
