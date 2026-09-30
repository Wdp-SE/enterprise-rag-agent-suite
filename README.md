# 研发知识版本服务与证据约束变更审查系统

一个面向研发资料生命周期的版本化知识 RAG 与证据约束变更审查 Agent。系统把公开软件资料检索与合成企业工程资料审查放在同一套工作台中：RAG 负责范围受控的版本检索与引用溯源；Agent 基于证据拆解影响候选、标注缺口并提出待审核建议；人工保留最终决策权。本项目是独立工程演示，不是 Autoware 官方产品，也不代表任何上游或企业内部系统。

- [GitHub 源码仓库](https://github.com/Wdp-SE/enterprise-rag-agent-suite)
- [在线工作台](https://enterprise-rag-agent-suite-bfmkgsimdisxcewgco7ydk.streamlit.app/)
- [RAG API 文档](https://version-aware-rag-public-demo.onrender.com/docs)
- [RAG 健康状态](https://version-aware-rag-public-demo.onrender.com/health)
- [最终检索选型报告](evaluation/real_world_retrieval/final_selection/final_selection.md)

> 在线链接指向已有公网服务，实际运行版本以托管平台显示的部署提交为准。

## 项目与架构

这是一个项目：公开 Autoware 资料是当前演示语料；KEP 只启发提案和审查流程设计，不是检索语料。另一种本地运行场景仍使用合成工程资料，不是第二个项目：

1. **公网默认场景：Autoware 规划变更审查**。在固定提交的 Autoware Universe 0.51.0/0.52.0 官方资料中按版本、语言和资料范围检索；当前默认 0.52.0。RAG 检索规划模块、配置和验证资料，并将两条人工复核的图中文字作为绑定原图哈希的派生证据；Agent 按确定性规则识别变更类别，把原始描述拆成有上限的子问题调用 RAG，再将候选证据交给模型辅助分析。结果包含检索轨迹、覆盖状态、结构化证据缺口和人工核对动作。Agent 不写回公开语料或 Autoware 上游。
2. **本地扩展场景：研发工程变更工作台**。使用完全合成的需求、设计、API、测试和运维文档，演示版本 Diff、标识符与追踪关系、RAG 影响发现、证据绑定、修改建议和人工审核。预置案例可继续演示冲突校验、候选版本验证与显式激活；用户自定义需求修改只进入当前审查。默认公网实例不加载这套合成工作流；本地设置 `DEMO_LEGACY_FIXTURES=true` 才能进入。

    公网默认：固定版本 Autoware 资料 → FastAPI BM25 + 经审核图中文字 → 问题/变更描述 → 引用证据 → Agent 辅助分析 → 人工审核
    本地扩展演示：合成研发文件 → 结构解析与元数据 → 版本 Diff / RAG 影响发现 → PatchCandidate → 人工审核 → 安全候选版本

在线工作台用于体验产品流程；API 文档用于查看公开 RAG 接口。当前 Autoware 语料是 0.51.0 与 0.52.0 两个固定提交快照，共 22 份来源、410 个文字检索片段；启动时不抓取上游，也不重建索引。冻结的 16 道检索题对照了 BM25、查询分面和经审核的图片文字。当前选用 `bm25_figure_ocr`：DEV/HOLDOUT 必需来源覆盖与 BM25 持平，图片证据命中从 0/2 提升到 2/2；结果已绑定语料、代码、评测集和侧车指纹。每个切分只有一道无答案题，且仍返回候选，因此该小评测不证明回答准确率或幻觉率，相关指标会在工作台明示。

### 目录职责

- `versioned-rag-service/`：FastAPI 知识服务，负责版本范围内的 BM25 检索、引用依据和可选的引用约束回答。
- `change-review-agent/`：自然语言变更规划、证据约束公开审查 Agent，以及工程资料变更工作流。
- `demo-ui/`：同一产品的 Streamlit 入口；默认公网配置由 `app.py` 加载 `public_workbench.py`，设置本地合成演示开关后由 `app.py` 展示企业式工程资料工作流。
- `project_delivery/v4_change_impact_review/demo_data/`：完全合成的研发资料与结构化清单，不包含企业真实文档。
- `evaluation/agent_query_decomposition/`：规则分类、子问题覆盖和查询预算的轻量离线评测，不等价于端到端检索或答案质量评测。
- `evaluation/change_review_v5/`：32 条 DolphinScheduler 语料上的历史变更审查评测，仅保留为旧版 Agent 规划记录；不代表当前 Autoware 语料效果，也不调用或评分生成模型。
- `evaluation/autoware_retrieval_v1/`：16 道 Autoware 版本化检索评测，对比 BM25、查询分面和图片文字策略；包含图中独有信息与无答案问题，不评分生成答案。

### 变更规划与证据缺口

变更输入保留自然语言原文，并可选补充变更类型和影响范围。未指定类型时，规则从参数/配置、接口/兼容性、规划/轨迹行为、工作流/行为、数据/存储、安全/权限等类别进行确定性识别；无法识别时回退到通用检索，不阻断用户原始描述。Agent 将完整请求和拆分子问题限制在最多 4 次 RAG 查询、最多 5 条模型证据，逐条记录命中与纳入状态。证据缺口除了兼容旧接口的可读文本，也会提供缺口类型、查询、预期资料类别和人工补查动作；模型报告的缺口会标记为“待人工核验”，不会当成事实。

早期查询拆解评测使用 8 条人工编写的合成输入，分类 8/8、标注子问题覆盖 17/17、预算 8/8；它是规则实现的历史小型契约测试，不作为当前效果结论。V5 是 Autoware 语料切换前、基于 DolphinScheduler 的历史变更审查评测：

```powershell
python evaluation/change_review_v5/run_evaluation.py --split dev --policy bm25
```

V5 共 32 条请求、18 个场景族，DEV 25 条、HOLDOUT 7 条；含跨资料、图片线索、无答案和私有范围请求。其规则分类和检索数据只描述旧 DolphinScheduler 版本，不是当前 Autoware 服务的指标，也不代表真实用户分布、答案准确率、幻觉率或公网延迟；越界问题拦截和公开无答案候选噪声见 [V5 历史评测说明](evaluation/change_review_v5/README.md)。当前 Autoware 检索结果以 [Autoware 检索评测 V1](evaluation/autoware_retrieval_v1/README.md) 为准。

## 检索选型：历史基线与当前复评

以下是历史 V1 选型记录：在当时同一份 52 来源语料、同一版本过滤和语言范围、Chunk A、Top-5 条件下，比较了 BM25、真实多语言神经 Dense（multilingual E5）和 Hybrid。以下 Hit@K、MRR 均按 DEV 的 22 条可回答问题计算；耗时是本地进程内 warm retrieval，不含模型加载、HTTP、冷启动或生成。

| 方案 | DEV Hit@1 | DEV Hit@5 | DEV MRR | 双来源完整命中 | P95 |
| --- | ---: | ---: | ---: | ---: | ---: |
| BM25 | 0.3636 | 0.8182 | 0.5295 | 0/2 | 1.36 ms |
| multilingual E5 | 0.2727 | 0.7273 | 0.4508 | 0/2 | 21.94 ms |
| Hybrid，BM25 权重 0.75 | 0.3636 | 0.8182 | 0.5470 | 0/2 | 22.31 ms |
| 锁定的 BM25 HOLDOUT | 0.4286 | 0.7619 | 0.5833 | 0/2 | 1.55 ms |

Hybrid 的最佳配置只让 DEV MRR 小幅增加 0.0175；Hit@1、Hit@5 和跨文档双来源命中均未改善，P95 则显著高于 BM25。因此 V1.0 保留 Chunk A（1250 chars、无 overlap）+ BM25 + Top-5，不设置文档数上限；Hybrid、神经 Dense 和 Rerank 不进入正式检索链路。跨文档题合计双来源完整命中为 0/4。HOLDOUT 是从此前已评测的 46 条题目中做的回顾性确定划分，不是独立真实用户测试，不能据此声称真实用户准确率。

工作台评测页只展示与当前 Autoware 语料和检索实现指纹匹配的冻结结果。早期 DolphinScheduler 语料上的 V1-V4 评测留作历史工程记录，不代表当前语料的在线答案质量。历史选型的方法、切分和失败分析见[最终选型报告](evaluation/real_world_retrieval/final_selection/final_selection.md)。

### V2 检索质量实验

随后在旧版 52 份来源、659 个 chunk 上用独立 40 条查询做了 V2 来源级 DEV/HOLDOUT 对比。字段加权 BM25 候选在 DEV 上表现更好，但未通过锁定 HOLDOUT 晋级门槛，因此没有切换默认策略。这是扩充语料之前的历史实验，不能代表当前 Autoware 语料的质量。指标定义和历史结果见[V2 实验报告](evaluation/real_world_retrieval/quality_v2/report.md)。

### DolphinScheduler 历史 V3 评测（非当前语料）

旧 DolphinScheduler 语料的 V3 冻结了 72 道业务题，按场景家族分为 DEV/HOLDOUT 各 36 道。该轮比较后保留 BM25，一次性 HOLDOUT 的 32 道可回答题中，27 道找齐全部必需来源；8 道多来源题仅 4 道找齐。它反映的是旧语料的历史短板，不是当前 Autoware 服务的评测结论。题库、锁文件、结果与失败题见 [V3 评测说明](evaluation/real_world_retrieval/quality_v3/README.md)和 [V3 报告](evaluation/real_world_retrieval/quality_v3/report.md)。

### DolphinScheduler 历史 V4 图片证据与多资料复评（不代表当前语料）

V4 冻结了 104 道单资料、跨资料、跨版本、截图 OCR、图文联合与无答案问题，按问题族和图片分组为 DEV 51、HOLDOUT 53。经人工复核的 OCR 候选在 HOLDOUT 上将图片 Hit@5 从 0 提升至 100%，完整来源率从 85.7% 提升至 91.8%，跨资料完整命中从 37.5% 提升至 75%；但原文锚点召回从 79.2% 降至 69.8%，超过 5 个百分点退化上限。候选未晋级，公网仍使用 BM25。无答案题仍全部返回候选（4/4），候选噪声指标不是生成幻觉率；nDCG 实现存在重复计数问题，未用于结论。V4 的锁定命令没有代码强制并记录 DEV 晋级门槛；该流程限制和 V5 改进要求已如实记入 [V4 评测说明](evaluation/real_world_retrieval/quality_v4/README.md)。具体逐项结果见 [V4 报告](evaluation/real_world_retrieval/quality_v4/report.md)。

上述图片评测与 OCR 记录均属于 DolphinScheduler 历史语料。当前 Autoware 的图片索引范围、人工复核边界和在线策略见 [Autoware 图片证据说明](versioned-rag-service/public_corpus_autoware/FIGURE_EVIDENCE.md)。

旧 V3/V4 发布记录与当前 Autoware 语料无关；不要用它们宣称当前服务通过 DolphinScheduler 评测校验。当前 Autoware 评测及其指纹由 `/public/workspace` 核验，复算说明见 [Autoware 评测目录](evaluation/autoware_retrieval_v1/README.md)：

运行相关服务测试时，请在 `versioned-rag-service/` 目录执行 `python -m pytest -q`；Autoware 冻结题集与复算方式见评测说明。

### 当前 Autoware 评测

当前主语料、默认版本和线上策略以 [Autoware 语料清单](versioned-rag-service/public_corpus_autoware/corpus_manifest.json)、[图片证据审核清单](versioned-rag-service/public_corpus_autoware/FIGURE_EVIDENCE.md)及 [Autoware 检索评测](evaluation/autoware_retrieval_v1/README.md)为准。16 道题按场景划分为 DEV 11 道、HOLDOUT 5 道。Top-5 上，BM25 与图片文字策略在两组的必需来源 Recall 和完整来源率均为 100%，图片证据 Hit@5 从 0/2 提升到 2/2，错版本为 0；每组仅有 1 道无答案题，且仍召回候选（1/1），不能据此评估拒答能力。报告提供可复算对照，报告只有在语料、检索代码、侧车、配置和评测题指纹全部匹配时才会被 `/public/workspace` 展示。

不要在当前冻结目录重跑 `run_quality_v3.py --split dev`：它会覆盖 `results/dev__bm25.json`，新测得的耗时会改变已锁定的结果哈希。需要重新实验时，应使用独立工作树或新评测版本，并把结果写到独立路径，保留这份冻结记录不变。

### Final selection 的复现边界

`run_selection.py` 提供 `chunk` → `retriever` → `topk` → `diversity` → `holdout` 阶段，没有单条命令完整重跑 final selection。Holdout 受 `selection_lock.json` 及其锁定的 DEV 结果哈希约束；当前冻结结果已包含 Holdout，不能对它随意重复执行。下面只示范 DEV 分块策略阶段，不代表完整选型重跑；该命令会更新 `evaluation/real_world_retrieval/final_selection/results.json`：

```powershell
python .\evaluation\real_world_retrieval\final_selection\run_selection.py chunk --chunk A
```

## 三分钟体验

1. 打开“版本化知识检索”，询问 Start Planner 搜索策略或 Goal Planner 图中的标签；核对答案引用、当前版本和固定来源。
2. 进入“发起变更审查”，自由描述假设变更；也可在可选结构化信息中指定类别与影响范围。查看规则分类、最多 4 条查询的覆盖轨迹、候选证据与缺口。
3. 由人工确认或退回本次影响分析。需要对具体段落制作修改前后草案时，可继续人工审核；该公开资料路径不修改公共语料或上游仓库。
4. 若要在本机展示企业式生命周期闭环，设置 `DEMO_LEGACY_FIXTURES=true` 后重启工作台，再运行合成预置案例；公网演示当前展示公开资料检索与会话变更审查。

## Known Limitations

- 22 份 Autoware 来源仅覆盖规划、路径生成和验证相关模块，不覆盖整个 Autoware；目前只有两张图的可读标签经过人工复核，复杂图形关系不转成文本事实。
- 企业工程工作台使用完全合成的小型文档集与固定案例，用于验证流程与安全边界，不能代表真实企业文档覆盖率或业务效果。
- 历史 V1 四条跨文档题的双来源完整 Top-5 命中为 0/4。扩充语料会改变排序，现有新语料成绩必须单独复评，不能沿用历史指标。
- V1 HOLDOUT 来自此前使用过的题集，是回顾性确定划分；V2 是旧语料的独立锁定题集；V3 是当前语料的新冻结题集，但题目及标注在仓库可见，都不能等同于真实用户开放测试。
- 公开资料变更审查的人工决定会追加写入本地 SQLite，并可下载 JSON；记录按匿名 Streamlit 会话过滤，但没有身份认证，托管实例临时磁盘也可能在重启或重新部署后清空。它不等同集中式审批审计、跨实例任务存储或 ACL/RBAC。V4 预置工程案例使用本地文件 Checkpoint 和 Candidate Version 目录。
- 系统不修改 Autoware 上游，不创建 PR，也不自动发布修改。
- multilingual E5 仅用于选型实验；Hybrid 和 Rerank 均不在正式运行链路中。
- 资料命中和引用来源不等于回答事实已被证明；检索分数只用于排序，不代表真实性。
- 当前版本不实现 locale sibling consistency；语言/版本相关提示不能替代人工核对。
- 规则分类和查询拆解评测集规模小且为人工编写；生产落地前需要基于脱敏真实工单建立分层评测，检查类型混淆、检索缺口与误报，并设置版本化回归门槛。
- 本地 P95 不代表公网延迟或服务等级承诺。
- 公开 RAG API 当前没有访问身份鉴权；若在公网后端配置付费模型密钥，直接调用公开生成接口也会产生费用。系统不设会话调用次数上限，部署者需在模型服务商侧设置预算与费用告警，并监控请求量；这不是企业级成本治理或用户级计费审计。

## 本地启动

本地 clean-clone 已在 Python 3.11 验证通过；这记录的是已验证环境，不代表项目最低 Python 版本。Render 部署配置使用 Python 3.12.8；本文不推测 Streamlit Community Cloud 的 Python 版本。克隆后无需私有企业资料或本机历史 runtime：

    py -3.11 -m venv versioned-rag-service\.venv
    & .\versioned-rag-service\.venv\Scripts\python.exe -m pip install -r versioned-rag-service\requirements-render.txt
    py -3.11 -m venv change-review-agent\.venv
    & .\change-review-agent\.venv\Scripts\python.exe -m pip install -r change-review-agent\requirements.txt
    & .\change-review-agent\.venv\Scripts\python.exe -m pip install -r demo-ui\requirements.txt
    .\start_prototype.ps1

打开 http://127.0.0.1:8502/；本地 RAG API 文档为 http://127.0.0.1:8765/docs。无模型密钥时仍可检索和进行会话内变更审查。默认生成服务为 DashScope/Qwen（`DASHSCOPE_API_KEY`）；也支持 DeepSeek（`RD_V2_GENERATION_PROVIDER=deepseek`、`RD_V2_GENERATION_MODEL=deepseek-v4-flash`、`DEEPSEEK_API_KEY`）。仅在本机 RAG 后端或 Render RAG 后端配置密钥，不要写入仓库、日志或 Streamlit Secrets。详细字段见[部署指南](project_delivery/public_value_prototype/free_deployment_guide.md)和[工作台说明](demo-ui/README.md)。

应用不设固定会话生成次数上限。后端生成开关、模型密钥和供应商服务状态共同决定能否生成；供应商的计费余额、限流和网络超时仍可能导致单次失败。失败时保留可核查的检索证据，不能承诺“只要有余额每次必定成功”。`/health` 可区分关闭生成、缺密钥与已配置但未经实时验证；成功或失败请求返回不含密钥的生成诊断，便于定位问题。当前仅将两张经过人工复核的 Autoware 图中文字纳入检索，不推断复杂图形关系；复核清单见[图片证据说明](versioned-rag-service/public_corpus_autoware/FIGURE_EVIDENCE.md)。

## 资料来源

当前公开语料来自 [Autoware Universe](https://github.com/autowarefoundation/autoware_universe) 0.51.0 与 0.52.0 的固定公开提交，聚焦 Planning 模块；来源 URL、固定 commit、路径、语言、许可证与 SHA-256 见 [Autoware corpus manifest](versioned-rag-service/public_corpus_autoware/corpus_manifest.json)。上游原文及图片均可沿引用查看；派生图片文字额外绑定原图 SHA 与复核记录。本项目与 Autoware 基金会或维护组织无隶属关系。早期 Apache DolphinScheduler 评测和数据仍留作历史工程记录，不再作为公网默认语料。
