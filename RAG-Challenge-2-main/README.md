# 企业文档可信知识库与问答系统

> Trusted Enterprise Document RAG System

这是一个面向普通企业/行业文档的、以评测和可信边界为核心的 RAG 工程化原型。项目基于
已有课程/开源竞赛 RAG 代码进行系统性二次开发，不是从零重写整个 RAG，也不宣称已经
达到企业生产环境要求。

第一版选取“特种设备使用管理相关公开法规、安全技术规范和公开技术资料”作为垂直验证
场景。该场景只用于验证通用架构；核心检索、文档身份、Candidate 接口、版本治理和可信
问答均未硬编码为特种设备专用逻辑，未来可替换为能源规范、制造设备资料、金融制度、
通信运维规范或企业内部制度。

## 为什么进行二次开发

原项目主要解决竞赛中的公司年报问答：

```text
PDF → Chunk → FAISS → Retrieval → Generation
```

审计和真实运行发现，它存在 company-only routing、Structured Output 解析错误、Rerank
分数失真、IndexFlatIP 向量未归一化、Citation 自动补页风险、单文档/竞赛数据耦合以及
企业知识治理与持续评测缺失等问题。

二次开发后的主线是：

```text
Generic Multi-document RAG
  + Reliable Retrieval
  + Traceable Citation
  + Candidate Review Boundary
  + Domain Evaluation / Regression
  + Selective Chinese OCR
  + Version-aware Retrieval
  + Trusted QA Post-answer Enforcement
```

完整的前后对比、失败证据和取舍见
[Failure-driven Iterations](docs/failure_driven_iterations.md)。

## 核心能力

- **Reliable Baseline**：修复 Qwen Structured Output、真实 Rerank score、Embedding L2
  normalization、Boolean `N/A`、虚假引用补页及 Provider/Model 配置混用。
- **Generic Multi-document Retrieval**：问题无需包含 `company_name`；每文档局部 Top-K，
  再全局 merge + Top-K，同时保留 Legacy Company Mode。
- **可追溯 Citation**：Generic Mode 使用 `(document_id, page_number)` 校验模型声明的来源；
  没有合法声明时允许空引用，不自动补来源。
- **Parent Page / Rerank**：复用原项目能力，并修复运行时评分与生命周期问题。
- **Candidate v2**：Agent 只能提交 Candidate Package；路径、别名和 raw-file hash 经校验，
  人工审核前不能写正式 FAISS。
- **选择性中文 OCR**：只对通过触发条件的扫描页运行 OCR；保留 cache、质量门禁和异常横置
  页面 90°/270°恢复证据，不全局强开 OCR。
- **Version Governance**：区分 ACTIVE/SUPERSEDED，支持默认当前版本和明确历史版本检索；
  历史资产独立保存，不删除旧知识。
- **Trusted QA**：pre-generation 信号保持 Shadow；post-generation 仅对结构和 Citation
  确定性非法状态 fail closed，额外 Gate LLM 调用为 0。
- **Evaluation-driven**：固定 Domain、Version 和 Trusted QA Held-out 数据集，保存真实
  Retrieval、Answer Smoke、token、latency、失败分类及回归证据。
- **Frozen R&D V2 Runtime**：真实长研发文档使用唯一 `DENSE_ONLY + SECTION_PATH` 策略；
  启动时校验完整 manifest、hash、count、dimension 和 policy，查询只加载冻结 FAISS，绝不
  隐式重建。

## Architecture

```text
Documents
   ↓
Parsing ── selective OCR / rotation recovery
   ↓
Page + Chunk + stable document_id
   ↓
Normalized Embedding → per-document FAISS IndexFlatIP
   ↓
Generic Retrieval → Version Governance → Parent Page / optional Rerank
   ↓
Trusted QA pre-generation Shadow observation
   ↓
Structured Generation → Citation Membership Validation
   ↓
Deterministic Post-answer Enforcement
   ↓
Answer / N/A + validated sources + internal audit trace
```

Candidate 数据走独立旁路：

```text
Agent Candidate Package → Candidate Zone → Human Review → Approved
                                                        ↓
                                       future formal ingestion boundary
```

Agent 不能直接写正式知识库或 FAISS。详见
[Final Architecture](docs/final_architecture.md) 和
[Candidate Interface v2](docs/candidate_interface.md)。

## 真实评测摘要

不同阶段的指标口径不同，不能合并成一个“最终 Accuracy”。

| 阶段 | 数据范围 | 真实结果 |
| --- | --- | --- |
| Runtime Baseline | 5 PDFs / 599 pages / 1,924 chunks / 15 题 | Structured Output 15/15；Rerank 改序 14/15；Parent Page 15/15 |
| Domain Corpus v0.1 | 8 份审计 PDF；4 份 ACTIVE 入库；34 题 Retrieval | Hit@1 0.814815；Recall@5 0.759259；MRR 0.814815 |
| Corpus v0.2 | 5 份入库文档 / 182 pages / 319 vectors | Hit@1 0.851852；Hit@5 0.925926；Recall@5 0.851852；MRR 0.879630 |
| Version Governance Final | 同一 34 题 Retrieval | Hit@1 0.925926；Hit@5 1.0；MRR 0.953704 |
| Trusted QA Phase 3 | Phase 2 保存结果回放 + 4 题真实 Qwen Smoke | 历史 Citation Failure 2/2 拦截；False Fail-closed 0；真实 Smoke 4/4 结构有效 |
| Full Regression | 全项目 | **288 passed / 0 failed** |

完整口径与限制见 [Final Evaluation Summary](docs/final_evaluation_summary.md)。

### R&D Document RAG V2（冻结）

研发长文档实验已冻结为 `rd-v2-retrieval-final-v1.0`：Dense-only、`SECTION_PATH`、
BM25/Hybrid/Reranker 默认全部关闭。20 条 Answerable HOLDOUT 的一次性结果为 Hit@1 0.20、
Hit@5 0.40、Hit@20 0.40、MRR 0.2625；这些是 Retrieval 指标，不是 Answer Accuracy，且明确
显示真实长文档检索仍有较大改进空间。

工程运行入口位于 `src/rd_v2_runtime.py` 与 `src/rd_v2_api.py`，详细设计见
[R&D V2 Architecture](docs/architecture.md)、[Retrieval Design](docs/retrieval_design.md) 和
[R&D V2 Evaluation Summary](docs/evaluation_summary.md)。真实语料、规范化文件、chunk、索引
与报告均保持本地并由 `.gitignore` 排除。

## Quick Start

推荐 Python 3.11。Windows 已验证 CPU 环境：

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r requirements-windows.txt
Copy-Item .env.example .env
```

在 `.env` 中按实际 Provider 填入 Key。不要提交 `.env`、`env` 或终端日志。

其他平台可使用：

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
```

先执行完全离线的验证：

```powershell
python main.py --help
python -m pytest -q
python scripts/run_trusted_qa_phase3_replay.py
```

最后一条只回放已保存的 Phase 2 输出，不调用 Answer LLM、不重建索引。已有最终证据位于
`reports/` 和 `artifacts/`，面试 Demo 不需要现场重新 OCR、Embedding 或运行完整评测。

R&D V2 可先做完全离线的冻结产物验证和运行时自检：

```powershell
.venv\Scripts\python.exe scripts\build_rd_v2_final_artifact_manifest.py verify
.venv\Scripts\python.exe scripts\run_rd_v2_offline_runtime_smoke.py
.venv\Scripts\python.exe -m uvicorn src.rd_v2_api:app --host 127.0.0.1 --port 8000
```

默认禁止把真实研发上下文发给在线模型，因此 `/query` 会完成本地 Dense 检索后以
`GENERATION_DISABLED_BY_DATA_POLICY` 安全结束。公开演示应使用独立的公开/模拟语料。详见
[R&D V2 Demo Guide](docs/demo_guide.md) 和 [Native Runtime Notes](docs/native_runtime_notes.md)。

### CLI

```powershell
python main.py --help
python main.py parse-pdfs --help
python main.py process-reports --help
python main.py process-questions --help
```

Legacy Competition Mode 默认仍为 `legacy_company`；通用模式可选择 `generic`。实际语料目录、
问题文件和 Provider 配置应在运行前明确确认。Windows 的 FAISS 原生读取器对含中文的绝对
路径存在兼容问题，已验证运行脚本使用项目根相对路径。

## Demo

推荐 5～8 分钟演示：

1. 当前版本法规问题：Answer + 复合 Citation。
2. 明确询问 2017 旧版本：命中独立历史资产。
3. Hard Negative：返回 `N/A + sources=[]`。
4. 回放历史 Citation Membership Failure：展示 2/2 fail closed。
5. 展示 OCR page 37 的已有 90°/270°离线证据。

详细步骤与备用方案见 [Demo Guide](project_delivery/demo_guide.md)。

## Repository Guide

- `src/`：RAG、Candidate、OCR、Version、Trusted QA 核心实现。
- `data/evaluation/`：34 题 Domain、8 题 Version、20 题 Trusted QA Held-out。
- `data/domain_corpus_v0_2/`：冻结场景语料、解析结果、独立 FAISS 与历史版本资产。
- `reports/`：各阶段真实评测、失败分析和运行记录。
- `artifacts/`：Runtime Baseline、Generic Smoke、Candidate v2 导入证据。
- `docs/`：架构、评测和开发时间线。
- `project_delivery/`：简历、面试、Demo、Claim Matrix 和最终交付报告。
- `tests/`：288 项完整回归测试通过。

## Claim Boundary / Known Limitations

- Citation Membership 只证明来源属于实际 Retrieval Evidence，不等价于 semantic entailment
  或 factual correctness。
- 真实研发文档 Dense Retrieval 对 field / exact-term 查询仍明显不足；BM25/Hybrid 未取得稳定
  净收益，PDF-only heuristic path 也只有有限诊断证据。
- Retrieval miss 仍可能导致错误弃答。
- Pre-generation Reject 保持 Shadow，没有 learned confidence 或通用 hallucination detector。
- OCR 是规则驱动的工程适配，存在 CPU 成本和版式泛化边界。
- 尚无 Conflict Resolver、生产级鉴权、异步任务、分布式索引或完整可观测平台。
- 当前数据是公开资料验证场景，不是真实特种设备企业生产项目。
- **PRODUCTION_READY：NO CLAIM。**

详见 [Known Limitations](project_delivery/known_limitations.md) 与
[R&D V2 Known Limitations](docs/known_limitations.md)、
[Claim Matrix](project_delivery/claim_matrix.md)。

## Project Status

- READY_FOR_RESUME：YES
- READY_FOR_INTERVIEW：YES
- READY_FOR_DEMO：YES（优先使用已有 artifact）
- PRODUCTION_READY：NO CLAIM
- Core status：`COMPLETE_POST_ANSWER_ENFORCEMENT_READY`
- Suggested tag：`rag-autumn-recruitment-v1.0`（当前目录不是 Git 仓库，未自动创建）

## Acknowledgement and License

原始竞赛实现来自 Ilya Rice 的 RAG Challenge 方案。本项目保留原许可证，并在此基础上完成
面向通用企业文档、评测与可信边界的二次开发。请参阅 [LICENSE](LICENSE)。
