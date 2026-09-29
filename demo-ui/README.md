# 研发知识版本服务与变更影响审查工作台（Streamlit）

- [GitHub 源码仓库](https://github.com/Wdp-SE/enterprise-rag-agent-suite)
- [在线工作台](https://enterprise-rag-agent-suite-bfmkgsimdisxcewgco7ydk.streamlit.app/)

默认公网入口 [app.py](app.py) 加载 **Apache DolphinScheduler 官方公开资料工作台**。知识服务从 RAG 后端的固定语料清单读取当前版本与历史版本，默认选择清单声明的当前已收录版本；它不会实时追踪 Apache 上游。工作台提供中文优先/中英双语检索、官方原文引用和可核验的资料差异提醒。变更审查 Agent 保留自然语言原文，可选补充变更类型与影响范围；未填写类型时用确定性规则归类，无法识别时回退到通用检索。Agent 最多发起 4 次 RAG 查询、选取最多 5 条证据，并显示检索轨迹与结构化证据缺口。人工审核决定和可下载记录只留在当前 Streamlit 会话，不写公共基线。

本仓库还包含本地合成研发资料工作台，用于演示文档版本 Diff、追踪关系、PatchCandidate、审核、冲突检测和候选版本安全激活。它使用完全合成资料，不是第二个项目，也不默认加载在公网入口；仅在本机设置 `DEMO_LEGACY_FIXTURES=true` 后重启进入。

## 本地启动

先按[根目录 Quick Start](../README.md)准备环境。本地 clean-clone 已在 Python 3.11 验证通过；该验证记录不定义项目最低 Python 版本。Render 使用仓库配置的 Python 3.12.8；本文不推测 Streamlit Community Cloud 的 Python 版本。然后在仓库根目录运行：

```powershell
.\start_prototype.ps1
```

访问 <http://127.0.0.1:8502/>。脚本使用仓库内固定的官方资料和轻量索引，不需要历史 runtime 或私有文件；没有模型密钥仍可检索和审查。默认生成服务为 DashScope/Qwen，需在本机**环境变量**配置 `DASHSCOPE_API_KEY`。也可使用 DeepSeek：配置 `DEEPSEEK_API_KEY`，并在启动前设置 `RD_V2_GENERATION_PROVIDER=deepseek`（可选设置 `RD_V2_GENERATION_MODEL=deepseek-v4-flash`）。然后运行 `./start_prototype.ps1 -EnableGeneration`。不要把实际值写进仓库或日志。

手动启动时：在 `versioned-rag-service` 目录运行 `uvicorn src.public_server:app --host 127.0.0.1 --port 8765`，在 `demo-ui` 目录设置 `RAG_API_BASE_URL=http://127.0.0.1:8765` 后运行 `streamlit run app.py --server.port 8502`；使用仓库相应的虚拟环境解释器。

## 操作路径

1. “可信检索问答”：选版本和语言，输入问题，先查看答案，再核对引用依据 Top 3；其余结果折叠。“技术详情”才显示检索得分，该分数不是事实可信度。
2. “发起变更审查”：用自然语言描述假设变更；需要时展开可选字段补充变更类型与影响范围。系统拆分检索子问题并在当前版本资料中寻找证据，展示规则分类、检索轨迹、影响候选和结构化证据缺口；可选片段做修改前后对照，最后由人审核。人工决定绑定当前任务编号，可下载包含请求指纹、证据 ID、决定和时间的会话 JSON，但不会自动进入审批系统。仅官方 PR 明确引用 DSIP 的关系会标记为已确认；语义检索只标记建议。
3. “检索评测”页面保留早期字符哈希 Dense 的历史对照，不代表真实 multilingual E5 选型结果，也不是当前扩充语料的质量指标。当前默认为 Chunk A（1250 chars、无 overlap）+ BM25 + Top-5；它已在 V3 的 DEV 上锁定并经过一次性 HOLDOUT 检验。旧语料上的 E5/Hybrid 对照及边界见[历史最终选型报告](../evaluation/real_world_retrieval/final_selection/final_selection.md)。服务未配置在线模型或生成未通过引用校验时，问答页只展示待核对的检索候选。

查询拆解评测使用 8 条手工样例测类型分类、子问题覆盖及 4 次查询上限：`python evaluation/agent_query_decomposition/run_evaluation.py`。这是规则规划契约的轻量离线评测，不代表端到端检索准确率、回答正确率或线上延迟。

## 检索结论与已知限制

当前运行默认仍为 BM25 + Top-5、Chunk A 为 1250 chars 且无 overlap，不设置文档数上限。旧版 52 份来源上的 multilingual E5 与 Hybrid 仅用于同条件选型比较，不进入正式链路；当时 Hybrid 的 MRR 仅小幅增加，Hit@1、Hit@5、双来源完整命中没有改善，P95 明显高于 BM25。V1 的四条跨文档题双来源完整命中为 0/4；其 HOLDOUT 是既有 46 条题目的回顾性确定划分，不是独立真实用户测试。

历史 V2 检索质量实验在扩充之前的 52 份来源和 659 个 chunk 上比较了 BM25 与实验性字段加权候选。候选只在 DEV 上提升跨文档完整命中，未通过一次性 HOLDOUT 门槛，因此工作台没有切换默认策略。当前语料已扩至 132 份来源和 1322 个 chunk，并已通过下面的 V3 独立评测；不能把 V2 历史成绩当作当前成绩。结果和指标定义见[V2 检索质量实验报告](../evaluation/real_world_retrieval/quality_v2/report.md)。

针对当前语料，V3 冻结 72 道新业务题，按场景家族划分 DEV/HOLDOUT 各 36 道；在 DEV 比较三种来源多样化候选后锁定 BM25，并只运行一次 BM25 的 HOLDOUT。HOLDOUT 的 32 道可回答题中，27 道找齐全部必需来源；8 道多来源题有 4 道找齐，返回片段找到 37/49 个原文锚点。检索表现不等于生成答案的准确率或幻觉率，也不能代表真实用户开放提问。复现 DEV 基线时从仓库根目录运行 `python evaluation/real_world_retrieval/quality_v3/run_quality_v3.py --split dev --policy bm25`；题库与锁定边界见[V3 评测说明](../evaluation/real_world_retrieval/quality_v3/README.md)，一次性结果与失败题见[V3 报告](../evaluation/real_world_retrieval/quality_v3/report.md)。已开封的 HOLDOUT 不应重复运行或用于继续调参。

132 份语料仍是官方资料的有限子集，原文图片中的文字尚未纳入正式索引或检索；界面的配图提示不是 OCR 结果。规则分类使用小型关键词表，遇到领域新词时可能回退为通用类别；审查状态保存在当前 Session，下载审查 JSON 需要用户自行保存，不修改公共语料或 Apache 上游。系统不实现 locale sibling consistency；影响候选需要人工复核，审查结果不会写回公共资料。历史选型详见[最终选型报告](../evaluation/real_world_retrieval/final_selection/final_selection.md)。

## 云端配置

Streamlit Community Cloud 入口仍是 `demo-ui/app.py`；本文不指定其 Python 版本，以当前应用配置和平台选项为准。至少设置 `APP_ENV="public_demo"` 与 `RAG_API_BASE_URL="<真实 Render URL>"`；完整字段见 [部署指南](../project_delivery/public_value_prototype/free_deployment_guide.md)及[Secrets 示例](.streamlit/secrets.toml.example)。应用本身不设置固定生成次数或自动无限重试；模型服务商的余额、限流和网络状态仍决定单次请求能否完成。在线生成密钥只配置在 Render RAG 后端：默认 DashScope 使用 `DASHSCOPE_API_KEY`；若改用 DeepSeek，设置 `RD_V2_GENERATION_PROVIDER=deepseek`、`RD_V2_GENERATION_MODEL=deepseek-v4-flash` 和 `DEEPSEEK_API_KEY`。不要把模型密钥放进 Streamlit 前端 Secrets，也不要提交 `secrets.toml`。

## UI 回归

```powershell
& ..\change-review-agent\.venv\Scripts\python.exe -m pytest -p no:cacheprovider tests -q
```

资料来源和许可证见 [Corpus Manifest](../versioned-rag-service/public_corpus/corpus_manifest.json)、[LICENSE](../versioned-rag-service/public_corpus/LICENSE) 与 [NOTICE](../versioned-rag-service/public_corpus/NOTICE)。
