# 研发知识版本服务与变更影响审查系统

一个面向研发资料生命周期的版本化知识 RAG 与证据约束变更审查 Agent。系统把公开软件资料检索与合成企业工程资料审查放在同一套工作台中：RAG 负责范围受控的版本检索与引用溯源；Agent 基于证据拆解影响候选、标注缺口并提出待审核建议；人工保留最终决策权。本项目是独立工程演示，不是 Apache 官方产品，也不代表任何上游或企业内部系统。

- [GitHub 源码仓库](https://github.com/Wdp-SE/enterprise-rag-agent-suite)
- [在线工作台](https://enterprise-rag-agent-suite-bfmkgsimdisxcewgco7ydk.streamlit.app/)
- [RAG API 文档](https://version-aware-rag-public-demo.onrender.com/docs)
- [RAG 健康状态](https://version-aware-rag-public-demo.onrender.com/health)
- [最终检索选型报告](evaluation/real_world_retrieval/final_selection/final_selection.md)

> 在线链接指向已有公网服务，实际运行版本以托管平台显示的部署提交为准。

## 项目与架构

这是一个项目、两种运行场景，不是两个独立项目：

1. **公网默认场景：公开资料知识服务**。在 Apache DolphinScheduler 固定提交快照中按版本、语言和资料范围检索；支持带引用问答，也支持自然语言变更描述。Agent 按确定性规则识别变更类别，把原始描述拆成有上限的子问题调用 RAG，再将候选证据交给模型辅助分析。结果包含检索轨迹、覆盖状态、结构化证据缺口和人工核对动作。原始资料与变更结果均不写回 Apache 上游。
2. **本地扩展场景：研发工程变更工作台**。使用完全合成的需求、设计、API、测试和运维文档，演示版本 Diff、标识符与追踪关系、RAG 影响发现、证据绑定、修改建议和人工审核。预置案例可继续演示冲突校验、候选版本验证与显式激活；用户自定义需求修改只进入当前审查。默认公网实例不加载这套合成工作流；本地设置 `DEMO_LEGACY_FIXTURES=true` 才能进入。

    公网默认：固定版本公开语料 → FastAPI BM25 → 问题/变更描述 → 引用证据 → Agent 辅助分析 → 人工审核
    本地扩展演示：合成研发文件 → 结构解析与元数据 → 版本 Diff / RAG 影响发现 → PatchCandidate → 人工审核 → 安全候选版本

在线工作台用于体验产品流程；API 文档用于查看公开 RAG 接口。当前公开语料是 Apache DolphinScheduler 3.4.2 与 3.4.3 的固定提交快照，共 132 份来源、1322 个文字检索片段；默认版本由语料清单的 `current_version` 指向 3.4.3，并不实时追踪上游发布。启动时不抓取上游，也不重建索引。V4 在当前资料上重新核验 BM25，并测试了经过人工复核的截图 OCR。OCR 候选因图片命中提升但原文锚点召回退化超限而未晋级，公网默认继续用 BM25；工作台会显示实际对照结果和未晋级原因。

### 目录职责

- `versioned-rag-service/`：FastAPI 知识服务，负责版本范围内的 BM25 检索、引用依据和可选的引用约束回答。
- `change-review-agent/`：自然语言变更规划、证据约束公开审查 Agent，以及工程资料变更工作流。
- `demo-ui/`：同一产品的 Streamlit 入口；默认公网配置由 `app.py` 加载 `public_workbench.py`，设置本地合成演示开关后由 `app.py` 展示 V4 工程资料工作流。
- `project_delivery/v4_change_impact_review/demo_data/`：完全合成的研发资料与结构化清单，不包含企业真实文档。
- `evaluation/agent_query_decomposition/`：规则分类、子问题覆盖和查询预算的轻量离线评测，不等价于端到端检索或答案质量评测。

### 变更规划与证据缺口

变更输入保留自然语言原文，并可选补充变更类型和影响范围。未指定类型时，规则从参数/配置、接口/兼容性、工作流/行为、数据/存储、安全/权限等类别进行确定性识别；无法识别时回退到通用检索，不阻断用户原始描述。Agent 将完整请求和拆分子问题限制在最多 4 次 RAG 查询、最多 5 条模型证据，逐条记录命中与纳入状态。证据缺口除了兼容旧接口的可读文本，也会提供缺口类型、查询、预期资料类别和人工补查动作；模型报告的缺口会标记为“待人工核验”，不会当成事实。

查询拆解评测使用 8 条人工编写的合成输入，测变更类别分类、标注子问题覆盖和查询预算。运行方式：

```powershell
python evaluation/agent_query_decomposition/run_evaluation.py
```

当前 8 条固定样例的规则分类为 8/8，标注子问题覆盖为 17/17，查询预算为 8/8；这些结果仅验证规则与拆解契约，不代表真实用户分布、RAG Recall、答案准确率、幻觉率或公网延迟。

## 检索选型：历史基线与当前复评

以下是历史 V1 选型记录：在当时同一份 52 来源语料、同一版本过滤和语言范围、Chunk A、Top-5 条件下，比较了 BM25、真实多语言神经 Dense（multilingual E5）和 Hybrid。以下 Hit@K、MRR 均按 DEV 的 22 条可回答问题计算；耗时是本地进程内 warm retrieval，不含模型加载、HTTP、冷启动或生成。

| 方案 | DEV Hit@1 | DEV Hit@5 | DEV MRR | 双来源完整命中 | P95 |
| --- | ---: | ---: | ---: | ---: | ---: |
| BM25 | 0.3636 | 0.8182 | 0.5295 | 0/2 | 1.36 ms |
| multilingual E5 | 0.2727 | 0.7273 | 0.4508 | 0/2 | 21.94 ms |
| Hybrid，BM25 权重 0.75 | 0.3636 | 0.8182 | 0.5470 | 0/2 | 22.31 ms |
| 锁定的 BM25 HOLDOUT | 0.4286 | 0.7619 | 0.5833 | 0/2 | 1.55 ms |

Hybrid 的最佳配置只让 DEV MRR 小幅增加 0.0175；Hit@1、Hit@5 和跨文档双来源命中均未改善，P95 则显著高于 BM25。因此 V1.0 保留 Chunk A（1250 chars、无 overlap）+ BM25 + Top-5，不设置文档数上限；Hybrid、神经 Dense 和 Rerank 不进入正式检索链路。跨文档题合计双来源完整命中为 0/4。HOLDOUT 是从此前已评测的 46 条题目中做的回顾性确定划分，不是独立真实用户测试，不能据此声称真实用户准确率。

工作台评测页优先展示与当前语料和检索实现指纹匹配的 V4 BM25 基线及图片 OCR 候选取舍；V3 和下方早期字符哈希 Dense 对照明确标为历史实验，不代表当前语料的在线答案质量。历史选型的方法、切分和失败分析见[最终选型报告](evaluation/real_world_retrieval/final_selection/final_selection.md)。

### V2 检索质量实验

随后在旧版 52 份来源、659 个 chunk 上用独立 40 条查询做了 V2 来源级 DEV/HOLDOUT 对比。字段加权 BM25 候选在 DEV 上表现更好，但未通过锁定 HOLDOUT 晋级门槛，因此没有切换默认策略。这是扩充语料之前的历史实验，不能代表当前 132 份来源的质量。指标定义、历史结果和扩充后的回归诊断见[V2 实验报告](evaluation/real_world_retrieval/quality_v2/report.md)。

### V3 扩充语料评测

面向当前 132 份来源、1322 个片段，V3 新建并冻结了 72 道业务题，按场景家族分为 DEV/HOLDOUT 各 36 道，避免同一场景家族跨组。DEV 比较 BM25 与三种来源多样化候选：候选多找到一题的必需来源，却挤掉了部分含关键原文的片段，因此在打开 HOLDOUT 前锁定 BM25。BM25 在一次性 HOLDOUT 的 32 道可回答题中，27 道找齐全部必需来源；8 道多来源题只有 4 道找齐，返回片段找到 37/49 个原文证据锚点。该结果验证了当前运行策略的离线检索表现，也暴露跨资料、跨版本核对短板；它不是答案准确率、幻觉率或公网性能证明。题库、锁文件、结果与失败题见 [V3 评测说明](evaluation/real_world_retrieval/quality_v3/README.md)和 [V3 报告](evaluation/real_world_retrieval/quality_v3/report.md)。

### V4 图片证据与多资料复评

V4 冻结了 104 道单资料、跨资料、跨版本、截图 OCR、图文联合与无答案问题，按问题族和图片分组为 DEV 51、HOLDOUT 53。经人工复核的 OCR 候选在 HOLDOUT 上将图片 Hit@5 从 0 提升至 100%，完整来源率从 85.7% 提升至 91.8%，跨资料完整命中从 37.5% 提升至 75%；但原文锚点召回从 79.2% 降至 69.8%，超过 5 个百分点退化上限。候选未晋级，公网仍使用 BM25。无答案题仍全部返回候选（4/4），候选噪声指标不是生成幻觉率；nDCG 实现存在重复计数问题，未用于结论。具体逐项门槛与 SHA 记录见 [V4 评测说明](evaluation/real_world_retrieval/quality_v4/README.md)和 [V4 报告](evaluation/real_world_retrieval/quality_v4/report.md)。

原文配图另有[固定版本图片证据清单](versioned-rag-service/public_corpus/FIGURE_EVIDENCE.md)：132 份来源里扫描到 307 张按提交固定的图片；15 张截图通过固定提交校验和人工 OCR 复核，共整理出 30 条中英文派生证据。它们能覆盖截图上清晰可读的文字和值，不包含复杂箭头、拓扑或未读出内容。OCR 融合策略虽然找图更好，但在前五名里挤掉了关键文字证据，所以没有部署为默认策略。后续优先评估文字与图片的并行证据通道。

V3 是历史评测。其旧发布清单中的 `retrieval_policy.json`、V3 candidate-selection 与 holdout-execution 哈希已和仓库当前文件不一致；不要用它宣称当前服务通过 V3 发布校验，也不应通过重写旧 V3 记录来掩盖偏差。当前 BM25 的语料和实现指纹由 V4 服务端摘要校验，V4 runner 的指标单测可在仓库根目录运行：

```powershell
python -m pytest -p no:cacheprovider evaluation/real_world_retrieval/quality_v4 -q
```

不要在当前冻结目录重跑 `run_quality_v3.py --split dev`：它会覆盖 `results/dev__bm25.json`，新测得的耗时会改变已锁定的结果哈希。需要重新实验时，应使用独立工作树或新评测版本，并把结果写到独立路径，保留这份冻结记录不变。

### Final selection 的复现边界

`run_selection.py` 提供 `chunk` → `retriever` → `topk` → `diversity` → `holdout` 阶段，没有单条命令完整重跑 final selection。Holdout 受 `selection_lock.json` 及其锁定的 DEV 结果哈希约束；当前冻结结果已包含 Holdout，不能对它随意重复执行。下面只示范 DEV 分块策略阶段，不代表完整选型重跑；该命令会更新 `evaluation/real_world_retrieval/final_selection/results.json`：

```powershell
python .\evaluation\real_world_retrieval\final_selection\run_selection.py chunk --chunk A
```

## 三分钟体验

1. 打开“版本化知识检索”，询问 DolphinScheduler 参数优先级；核对答案引用、版本和固定来源。
2. 进入“发起变更审查”，自由描述假设变更；也可在可选结构化信息中指定类别与影响范围。查看规则分类、最多 4 条查询的覆盖轨迹、候选证据与缺口。
3. 由人工确认或退回本次影响分析。需要对具体段落制作修改前后草案时，可继续人工审核；该公开资料路径不修改公共语料或上游仓库。
4. 若要在本机展示企业式生命周期闭环，设置 `DEMO_LEGACY_FIXTURES=true` 后重启工作台，再运行合成预置案例；公网演示当前展示公开资料检索与会话变更审查。

## Known Limitations

- 132 份语料仍是官方资料的有限子集，不覆盖 DolphinScheduler 全部功能和历史；人工复核截图 OCR 当前用于独立实验，未进入公网默认 BM25 排序。
- 企业工程工作台使用完全合成的小型文档集与固定案例，用于验证流程与安全边界，不能代表真实企业文档覆盖率或业务效果。
- 历史 V1 四条跨文档题的双来源完整 Top-5 命中为 0/4。扩充语料会改变排序，现有新语料成绩必须单独复评，不能沿用历史指标。
- V1 HOLDOUT 来自此前使用过的题集，是回顾性确定划分；V2 是旧语料的独立锁定题集；V3 是当前语料的新冻结题集，但题目及标注在仓库可见，都不能等同于真实用户开放测试。
- 公开资料变更审查的结果及人工决定只存在当前 Session；可下载 JSON 供人工留档。V4 预置工程案例使用本地文件 Checkpoint 和 Candidate Version 目录。系统尚无持久化身份、集中式审批审计、跨实例任务存储或 ACL/RBAC。
- 系统不修改 Apache 上游，不创建 PR，也不自动发布修改。
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

应用不设固定会话生成次数上限。后端生成开关、模型密钥和供应商服务状态共同决定能否生成；供应商的计费余额、限流和网络超时仍可能导致单次失败。失败时保留可核查的检索证据，不能承诺“只要有余额每次必定成功”。`/health` 可区分关闭生成、缺密钥与已配置但未经实时验证；成功或失败请求返回不含密钥的生成诊断，便于定位问题。原文配图可指向固定来源，**图中文字目前未纳入正式索引与检索**。

## 资料来源

语料来自 [Apache DolphinScheduler](https://github.com/apache/dolphinscheduler) 官方固定版本资料、Release、DSIP Issue 和明确关联的 PR。来源 URL、tag 对应 commit、路径、语言、许可证与 SHA-256 见 [corpus_manifest.json](versioned-rag-service/public_corpus/corpus_manifest.json)。Apache License 与 NOTICE 随快照保留；本项目与 Apache 基金会无隶属关系。
