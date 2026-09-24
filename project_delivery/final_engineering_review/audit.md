# Final Engineering Review — 审查与限量修改计划

> 本文记录整改前的问题证据与原定审查计划；最终实施状态、验证结果和剩余限制见 [final_review.md](final_review.md)。

审查日期：2026-09-24。基线：`feature/public-value-prototype` 的 `204a033cde7bca0f3510b4c2e69f2127e4ef3a7b`；恢复标签 `backup/pre-final-engineering-review` 位于上一提交。审查开始时没有已跟踪文件修改；原有三份未跟踪 DOCX 不属于本轮范围。当前提交只在本地，远端仍是 `9d8fe47`。

本报告先记录审查结论与可实施计划，不将既有测试或本地截图冒充公网验收。审查证据来自根 README、`demo-ui/`、`RAG-Challenge-2-main/`、`OpenManus-rag/`、`evaluation/real_world_retrieval/`、`project_delivery/real_public_release/`、语料 manifest、策略报告、浏览器 Smoke 记录及相关测试。

## 业务闭环与可信边界

目标用户是开发、测试、设计和研发资料维护人员；触发方式是用户主动检索或发起会话内假设变更。公开入口使用 Apache DolphinScheduler 的有限官方公开资料快照，绝非 Apache 官方系统或企业生产平台。RAG 提供版本/语言范围过滤、证据与来源、可核验的文字或字面值差异提示；Agent 通过 RAG HTTP 与已有 Diff/Impact 接口构造影响候选和会话草案，由人审核。公开流程不接 Git/Jira/CI 事件，不修改公共语料或 Apache 上游，不产生真正的公开候选版本。证据：`README.md:3-40`、`demo-ui/app.py:45-49`、`demo-ui/public_workbench.py:131-177,351-436`、`OpenManus-rag/app/public_review.py:89-149`。

版本/语言条件在 `RAG-Challenge-2-main/src/public_knowledge.py:176-198` 的候选筛选中生效；`zh_preferred` 只是同分时优先中文，而非中文硬过滤。资料类型展示为元数据，当前公开 `/public/search` 契约没有资料类型过滤项（`src/public_api.py:20-30`），因此不能声称支持按类型限定检索。文档原文的 3.4.2/3.4.3 commit 与 SHA-256 可复核；Release、Issue、PR 是固定的本地快照，但网页链接本身可能继续变化。`corpus_manifest.json` 记录来源、版本、语言、类型、抓取时间和哈希。

无答案问题仍可能返回候选。在线生成由模型按证据回答并可弃答，服务端只验证引用 ID 属于本次检索，不能证明每句话被语义蕴含；无密钥、弃答或异常时不展示伪造答案。既有 3 个故意无答案问题均得到候选（`retrieval_policy_report.md:23-24`）。UI 在 `demo-ui/public_workbench.py:255-278,547-560` 明示此界限。一致性提醒只比较检索到的同文档/章节版本文字及明确参数字面值，不裁决哪份资料一定正确（`src/public_knowledge.py:210-263`）。

## 问题分级与证据

| 等级 | 问题及证据 | 影响与处理建议 |
| --- | --- | --- |
| **P0** | `OpenManus-rag/app/public_review.py:46-82,113-149` 对 DSIP 提案/PR 的**任意段落**都把文档级显式引用送入段落级 Impact，随后显示 `CONFIRMED`。真实 `Code of Conduct` 段落也可触发该结果；现有 `tests/test_public_review.py:67-74` 反而固定了这一行为。 | 用户可能把“PR 明确引用 DSIP 文档”误读成“此段变更确定影响 PR”。应将文档级已确认关联单独展示，所有仅由检索发现的段落影响仍为建议。 |
| **P1** | `evaluation/real_world_retrieval/make_queries.py:90-98` 把第二来源标到 `ds-034..037`，而真正跨文档题是 `ds-035..038`；已生成 `ground_truth.jsonl:34-38` 因此错配。`benchmark.py:40-42` 的 Hit@K 只要求任一来源命中。 | 四题的 Ground Truth 解释不可信，现有跨文档 Hit@5 不能代表两个来源都找齐。修正 ID 对应并增加双来源完整召回指标，重跑评测及策略选择，更新数字和限制。内存重算显示总体策略排序暂未改变，但须以正式重跑为准。 |
| **P1** | `RAG-Challenge-2-main/src/public_knowledge.py:118-138` 只校验 manifest 与原始来源哈希，预生成 `chunks.json`、`dense_vectors.npy` 只检查行数。用临时副本改写一个 chunk 内容后，`PublicKnowledgeIndex` 仍成功启动。 | 被损坏的索引可作为“官方证据”显示。应为两个预生成资产固定 SHA-256，启动先校验再加载，保留来源哈希校验并增加篡改回归。 |
| **P1** | `RAG-Challenge-2-main/src/public_api.py:113-119` 接受调用方自选的 `X-Demo-Session-ID`；`src/public_server.py:21-39` 只有每 ID 计数，字典无上限。 | 启用付费模型后可轮换 ID 绕开预算且持续增长内存。应加可配置的进程级总调用上限，并记录其随进程重启而重置、不能代替认证或平台配额。 |
| **P1** | `demo-ui/services/rag_client.py:37-69` 对超时后的 POST 也会重试；公开 `/public/query` 在服务端先消耗预算再调用模型（`src/public_api.py:112-139`）。 | 第一次模型调用已完成但客户端超时时，重试可能重复计费和消耗会话次数。仅生成请求应禁止自动重试；证据检索等只读请求保留现有策略。与上一项合并为一次生成成本保护修改。 |
| **P1** | `README.md:9`、`project_delivery/public_value_prototype/free_deployment_guide.md:3,6`、`project_delivery/real_public_release/report.md:3` 仍称新版“未提交”；事实上本地 `204a033` 已存在。根 Quick Start 安装的 RAG `requirements-render.txt` 没有 pytest，部署指南却直接要求运行 RAG 测试。 | 发布状态和新克隆复现说明不准确。改为“本地已提交、未推送/未部署”，补足测试依赖步骤，并将三分钟体验中的生成回答写为有密钥时才可用。 |
| **P2** | `demo-ui/docs/known_limitations.md:9` 说 BM25 禁用，实际只适用于旧合成运行时；旧 `external_user_trial_guide.md` 仍描述 Case A/B 与发布候选版本。 | 历史文档应标记适用范围，本轮不全面翻修。当前公开 UI 的“已知限制”页已正确描述新流程。 |
| **P2** | `demo-ui/public_workbench.py:510` 对 Release/Issue/PR 链接统一称“固定版本官方原文”，而这些 URL 不是 commit-pinned blob。 | 固定的是本地快照；可在后续小文案轮次区分在线页面与快照，不改变当前归属信息。 |
| **P3** | 未有双语神经 Embedding 的公平基线、较大独立测试集、真实历史变更的可核验影响 Ground Truth；也没有企业认证、ACL、审计留存或多实例预算。 | 属于单独实验/产品工程，不在这次收口加入。 |

## 五项限量修改计划

1. **纠正“已确认关系”语义（P0）。** 风险：把文档链接展示成段落确定影响。方案：Impact 接口只接收候选检索结果；单独保留 PR 明确引用 DSIP 的文档关联及原文 URL，UI 明示关联不等于本次段落受影响。预计文件：`OpenManus-rag/app/public_review.py`、`OpenManus-rag/tests/test_public_review.py`、`demo-ui/public_workbench.py`、相应 UI 测试。收益：避免最直接的业务误导。
2. **修正跨文档评测标签（P1）。** 风险：错配 Ground Truth 使跨文档能力结论失真。方案：按 `ds-035..038` 的实际问题核对并生成双来源标签，增加“两个来源均在 Top-5”指标，重跑现有评测和策略选择，更新受影响报告/说明。预计文件：`evaluation/real_world_retrieval/make_queries.py`、`benchmark.py`、`ground_truth.jsonl`、结果 JSON、策略报告、根 README/验收报告中受影响指标及最小测试。收益：可解释、可复现的策略依据。
3. **校验预生成检索资产（P1）。** 风险：原始资料未变而索引内容改变仍被当作官方依据。方案：在策略元数据记录 `chunks.json` 与 `dense_vectors.npy` 的哈希并于启动前验证；生成策略的脚本同步写入这些哈希；增加篡改测试。预计文件：`RAG-Challenge-2-main/src/public_knowledge.py`、`public_corpus/retrieval_policy.json`、`tests/test_public_knowledge.py`、`evaluation/real_world_retrieval/select_policy.py`。收益：闭合快照到检索证据的完整性链。
4. **给公开生成增加成本保护（P1）。** 风险：轮换匿名会话 ID 绕过次数限制；客户端超时自动重试可能重复模型调用。方案：保留每会话限制，另加小而可配置的进程级上限；仅 `/public/query` 禁止自动重试，搜索等只读请求保持原有重试。满额时 UI 仍可检索证据。预计文件：`RAG-Challenge-2-main/src/public_server.py`、`tests/test_public_server.py`、`demo-ui/services/rag_client.py`、`demo-ui/services/public_knowledge_client.py`、`demo-ui/tests/test_clients.py`、`render.yaml`、部署指南。收益：降低意外付费与重复请求风险；明确进程级限制非生产配额。
5. **同步发布状态与复现说明（P1）。** 风险：公开 README 告诉读者错误的提交状态，测试步骤在新环境缺依赖。方案：只改有效入口文档中的状态、生成条件和 pytest 安装步骤；历史报告注明记录时点。预计文件：`README.md`、`project_delivery/public_value_prototype/free_deployment_guide.md`、`project_delivery/real_public_release/report.md`。收益：对面试和新克隆复现更诚实。

以上计划不涉及新框架、索引策略改造、自动上游写入或纯视觉优化；评测修正若改变默认策略，应先按既定选择规则核验，不人工指定赢家。

## 十五个面试追问的可回答性

| 问题 | 当前证据/缺口 |
| --- | --- |
| 1. 为什么不是普通 PDF RAG？ | 有固定版本、语言/来源元数据、Manifest 哈希、差异提醒、真实来源链接；但语料是 Markdown/网页快照，不应声称公开版在做 PDF OCR。 |
| 2. 为什么需要 Agent？ | Agent 编排假设变更、Diff、Impact 候选、草案和人工审核；不只是问答，见 `public_review.py`。 |
| 3. Agent 如何知道受影响资料？ | 显式 DSIP↔PR 仅证明文档关系；其他候选由检索发现，缺口是本轮要纠正的段落级措辞。 |
| 4. 没有 TraceLink 怎么办？ | 返回 `SUGGESTED`/人工核对，不能称确定影响。 |
| 5. 为什么语义相关不是依赖？ | 检索分数只度量排序信号，不具备变更传播的因果/结构证明。 |
| 6. 版本可信如何实现？ | 3.4.2/3.4.3 快照、commit、语言/版本筛选与来源哈希；预生成索引哈希缺口待修。 |
| 7. 中英文冲突怎么办？ | 显式展示 locale/版本及原文；差异提醒不判真伪，人工复核。 |
| 8. 为什么选 BM25？ | 46 题同条件中综合指标最好；跨文档标签待修且小样本，不能推广全站。 |
| 9. 为什么没用 Rerank？ | 当前免费部署条件下无可复现双语模型评测，报告明确 NOT EVALUATED。 |
| 10. Dense 为何不能代表 Neural Dense？ | 当前是 512 维确定性字符 n-gram 哈希，不含神经模型训练语义。 |
| 11. 没答案怎么办？ | 检索候选仍可能出现；生成可弃答，失败只显示待核对候选，引用校验不等于事实校验。 |
| 12. 为什么使用真实公开资料？ | 可让来源、版本、许可证与评测样本被外部核对，避免把合成夹具包装为真实验证。 |
| 13. Agent 为什么不直接修改上游？ | 假设性变更缺真实授权和完整 Ground Truth；Session 审核不等于发布。 |
| 14. 真实资料如何验证 Agent？ | 现有显式 DSIP↔PR 文档关联及流程/隔离测试；缺 3–5 个可靠历史影响真值样本，不制造准确率。 |
| 15. 企业落地还缺什么？ | 权限/数据许可、持久审计、多实例预算与状态、正式变更源集成、规模化评测和人工治理；不能声称已具备。 |

## 此轮不做的实验

当前只有一条可明确核对的 DSIP↔PR 显式文档关联，无法可靠构造 3–5 个带完整 changed-files/影响真值的历史回放样本。不要把搜索候选当 Ground Truth。建议把真正的双语 Neural Dense + 独立保留查询集作为**后续单独实验**；它不阻止当前版本作为有清晰限制的公开原型展示，但在实验前不得声称 BM25 优于神经语义检索。
