# RAG Autumn Recruitment Finalization Report

生成日期：2026-09-04  
项目名称：企业文档可信知识库与问答系统  
阶段结论：`COMPLETE_POST_ANSWER_ENFORCEMENT_READY`

本报告汇总已有代码、离线评测、真实模型 Smoke Test 和最终回归证据。本轮只整理文档、交付材料与仓库卫生，不修改 Retriever、Embedding、OCR、Version、Trusted QA 等冻结核心逻辑。

## 1. 项目状态

| 交付目标 | 结论 | 依据 |
| --- | --- | --- |
| `READY_FOR_RESUME` | **YES** | 有可核验指标、明确个人改造边界和不过度表述的简历材料 |
| `READY_FOR_INTERVIEW` | **YES** | 有最终架构、失败驱动迭代、37 个问答和 6 个 STAR 故事 |
| `READY_FOR_DEMO` | **YES** | 有固定证据、演示顺序、异常分支和离线回放方案 |
| `PRODUCTION_READY` | **NO CLAIM** | 尚缺生产级鉴权、异步任务、分布式部署、监控告警和更大规模外部验证 |

项目来自竞赛型年报 RAG 的二次开发，不宣称从零自研全部基础组件。特种设备使用管理公开资料只是第一个垂直验证场景，不代表真实行业生产落地。

## 2. 最终架构

主链路：

```text
PDF / public documents
  -> Parsing + selective Chinese OCR / rotation recovery
  -> Chunk + normalized Embedding + per-document FAISS
  -> Generic or Legacy routing
  -> Version-aware eligibility and intent resolution
  -> local Top-K per document -> global merge -> global Top-K
  -> Parent Page -> optional DashScope Rerank
  -> Structured Generation
  -> post-answer structural and Citation Membership enforcement
  -> Answer / explicit N/A
```

候选知识旁路：

```text
Agent Candidate Package
  -> Candidate v1/v2 detection and normalization
  -> metadata / citation / path / hash validation
  -> Candidate Zone
  -> Human Review -> APPROVED extension point
```

Agent 不能通过该接口直接调用 Embedding、写 FAISS 或发布正式知识。完整模块边界见 [final_architecture.md](../docs/final_architecture.md)。

## 3. 已完成工作

1. 修复 Qwen Structured Output、DashScope Rerank score、Embedding L2 Normalize、Citation 自动补页、Boolean N/A、日志泄漏和 Provider/Model 配置问题。
2. 将 `company_name -> company FAISS` 竞赛链路解耦为 Generic Multi-document Retrieval，同时保留默认 Legacy Mode。
3. 建立稳定 `document_id` 传播以及 `(document_id, page_number)` Generic Citation 校验。
4. 建立 Candidate v1/v2 接口，验证 alias、引用、跨平台路径与 raw-file SHA-256；人工审核前不入正式知识库。
5. 接入公开垂直语料，构建 Domain Evaluation Dataset；实现选择性中文 OCR、质量门禁与异常旋转恢复。
6. 建立 ACTIVE/SUPERSEDED 版本治理、历史资产和 Version-aware Retrieval。
7. 完成 Trusted QA 信号审计、Shadow Gate、Held-out Validation 和保守的 post-answer enforcement。
8. 保存阶段性 JSON/Markdown 证据，最终整理 README、架构、评测、Demo、简历和面试材料。

## 4. 真实评测结论

各阶段数据集、链路和指标口径不同，因此不得把下表合并为单一“系统准确率”。

| 阶段 | 样本/资产 | 真实结果 |
| --- | --- | --- |
| Runtime Baseline | 5 PDF，599 页，1,924 chunks，15 题 | Structured Output 15/15；Parent Page 15/15；Rerank 改序 14/15；Rerank+Generation 188,605 tokens |
| Domain v0.1 | 34 题：27 answerable / 7 unanswerable | Hit@1/3/5 0.814815；Recall@5 0.759259；MRR 0.814815 |
| Corpus v0.2 | 5 indexed docs，182 页，319 vectors；同一 34 题 | Hit@1 0.851852；Hit@3 0.888889；Hit@5 0.925926；Recall@5 0.851852；MRR 0.879630 |
| Version Governance Final | 同一 34 题 | Hit@1 0.925926；Hit@3 0.962963；Hit@5 1.0；Recall@5 0.944444；MRR 0.953704 |
| Version independent set | 8 题 | Version OFF/ON Hit@1：0.75 -> 1.0 |
| Trusted QA Phase 2 | 20 held-out：10 answerable / 10 unanswerable | 7 ANSWER / 0 REJECT / 13 UNCERTAIN；3 个 hard negative false accept，证明 pre-generation gate 不宜强制上线 |
| Trusted QA Phase 3 replay | 保存结果回放 | Citation Failure 2/2 拦截；Valid Answer 2/2 保留；Correct N/A 5/5 保留；False Fail-closed 0；额外模型调用 0 |
| Trusted QA Phase 3 real smoke | 4 题 | Structured 4/4；2 个 answerable 通过；2 个 hard negative 合法 abstain；总计 9,392 tokens；平均 2,376.577 ms |

Answerable 与 Unanswerable cosine 分布重叠：前者 top1 范围约 `0.4434-0.8334`，后者约 `0.4765-0.6862`。诊断阈值 `0.70475` 虽能拒绝 7/7 unanswerable，也会误拒 6/27 answerable；因此没有把单一 cosine threshold 包装成可靠拒答方案。

更完整证据和口径见 [final_evaluation_summary.md](../docs/final_evaluation_summary.md) 以及 `reports/`、`artifacts/` 中的冻结结果。

## 5. 最终测试与运行验证

2026-09-04 在项目 `.venv` 中执行：

| 检查 | 结果 |
| --- | --- |
| `.venv\\Scripts\\python.exe -m pytest -q` | **220 passed / 0 failed / 1 warning，4.66s** |
| `.venv\\Scripts\\python.exe -m pip check` | **No broken requirements found** |
| 关键模块 import smoke | **PASS** |
| `python main.py --help` | **PASS**，可列出 5 个 CLI command |
| `python main.py process-questions --help` | **PASS**，包含 `legacy_company` / `generic` routing mode |

唯一测试警告来自已安装的 DashScope SDK：其 `dashscope.assistants` API 被标记为 deprecated。当前项目不依赖 Assistants API，该提示不影响现有主链路；后续升级 SDK 时仍需回归。

本轮没有调用在线模型、没有重新解析 PDF、没有重新 Embedding、没有重建 FAISS。

## 6. Demo 交付

推荐采用“固定证据优先、少量在线调用可选”的方式：

1. 展示 Generic 问题无需 `company_name`；
2. 展示当前版本回答及 `(document_id, page_number)` Citation；
3. 展示明确历史版本问题；
4. 回放 Citation Membership Failure 被 fail closed；
5. 展示 OCR page 37 的已有 90°/270°恢复证据；
6. 最后说明 Candidate 只进入人工审核区，不直接入库。

完整演示脚本见 [demo_guide.md](demo_guide.md)。Demo 不应现场重跑 OCR、Embedding、全量评测或依赖临时联网。

## 7. 简历材料

建议项目名：**企业文档可信知识库与问答系统**。

建议表述必须包含：

- 在既有竞赛型 RAG 基础上完成可靠性修复和通用化二次开发；
- 以特种设备使用管理相关公开资料作为首个垂直验证场景；
- 明确引用校验、版本治理、Candidate 审核边界和拒答机制的能力边界；
- 只引用可复跑或有冻结 artifact 的真实指标。

可直接编辑的长短版本见 [resume_material.md](resume_material.md)，允许/禁止表述见 [claim_matrix.md](claim_matrix.md)。

## 8. 面试准备

材料已经覆盖：

- 37 个项目技术问答；
- 30 秒、1 分钟、3 分钟、5 分钟项目陈述；
- 6 个失败驱动 STAR 故事；
- 原项目与个人二次开发贡献边界；
- 为什么不选择 GraphRAG、全局 OCR、单阈值拒答等设计。

入口分别为 [interview_qa.md](interview_qa.md)、[project_pitch.md](project_pitch.md)、[failure_stories.md](failure_stories.md) 和 [my_contribution.md](my_contribution.md)。

## 9. 安全与仓库卫生

检查结论：

- 未在可分发源码、README 和新增交付文档中发现硬编码真实 API Key；示例代码通过环境变量读取凭据。
- 敏感模式扫描仅命中本地 `env` 文件；没有读取或输出其中的值。
- `env`、`.env*`（保留空值 `.env.example`）、虚拟环境、缓存、临时目录和本地运行日志已加入 `.gitignore`。
- 可分发材料中未发现当前用户个人绝对路径。
- 当前目录不是 Git working tree，因此 `.gitignore` 无法替代压缩/上传前的人工文件清单检查。

发布前必须排除本地 `env`、`.venv`、缓存、终端日志及不必要的原始运行中间产物；如果 `env` 中曾存放真实凭据，应在公开仓库前主动轮换。空配置模板见 [../.env.example](../.env.example)。

## 10. 已知限制

- Citation Membership 只证明引用来自检索证据集合，不证明语义蕴含或事实完整性。
- Reject Gate 不是通用 LLM 不确定性估计；pre-generation 信号仍保持 Shadow，强制边界仅覆盖结构错误和引用越界等可证明失败。
- 评测集规模有限，且主要来自首个公开垂直场景；不代表跨行业或生产流量结论。
- OCR 为选择性工程策略，对复杂版式、低清扫描和其他语言仍可能失败。
- 版本治理依赖已登记的文档身份与关系，不会自动发现互联网中的最新法规。
- Candidate approval 仅建立人工边界，尚未实现完整冲突检测、知识健康和自动正式 Ingestion。
- 当前仍保留 Legacy Competition Mode 与若干比赛兼容路径。
- 缺少生产级鉴权、租户隔离、异步队列、可观测性、容量规划和灾备。

详见 [known_limitations.md](known_limitations.md)。

## 11. 声明边界

可以声明：

- 完成竞赛型 RAG 到通用多文档 RAG 的最小侵入解耦；
- 真实运行过 DashScope/Qwen Structured Generation 与 Rerank Smoke；
- 完成复合 Citation Membership Validation、候选知识审核边界、版本感知检索和选择性 OCR；
- 建立固定离线评测与失败驱动迭代闭环；
- 最终本地回归为 220 passed。

不得声明：

- 从零独立研发整个 RAG 框架；
- 已部署到真实特种设备企业或生产环境；
- Citation 已完成 semantic entailment verification；
- 已消除幻觉或拥有通用置信度；
- 已达到 Production Ready；
- 未实际执行的大规模准确率、延迟或成本数据。

## 12. 建议 Git Tag

建议版本标签：`rag-autumn-recruitment-v1.0`。

当前目录没有 `.git`，因此本轮**没有**执行 commit 或 tag。应在确认正确 Git 仓库和待提交文件后手动执行：

```bash
git status --short
git check-ignore -v env .env .venv tmp
git add README.md .gitignore .env.example docs project_delivery
git commit -m "Finalize enterprise trusted RAG autumn recruitment release"
git tag -a rag-autumn-recruitment-v1.0 -m "Autumn recruitment RAG project release"
```

若这是从上游复制出的非 Git 目录，优先回到保留历史的真实 clone 中迁移本次变更；不要仅为打标签而伪造开发历史。

## 13. 后续方向

冻结当前简历版本后，未来改进应单独开分支并重新建立证据：

1. 增加跨行业与时间切分的外部评测；
2. 研究 Citation semantic support/entailment，但避免把 LLM 自评包装成真值；
3. 补齐 Candidate duplicate/conflict/health 与 approved ingestion；
4. 生产化需要 auth、tenant isolation、async job、metrics/tracing 和故障恢复；
5. 对 DashScope SDK 升级进行单独兼容性回归。

这些是未来路线，不属于当前已完成能力。

## 14. 冻结建议

建议将当前状态冻结为秋招展示基线。冻结范围包括：Retriever、per-document FAISS、Top-K、Rerank、Chunk/Embedding、OCR、Version Governance、Trusted QA enforcement 与现有评测集。

后续面试准备应优先练习 Demo、指标口径、失败故事和边界说明，而不是继续叠加算法。若必须改核心能力，应新建分支、定义新评测假设，并重新运行完整回归和对应真实 Smoke。

最终判定：

```text
READY_FOR_RESUME   = YES
READY_FOR_INTERVIEW = YES
READY_FOR_DEMO     = YES
PRODUCTION_READY   = NO CLAIM
```
