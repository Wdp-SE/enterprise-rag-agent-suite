# 研发知识版本服务与变更影响审查工作台（Streamlit）

- [GitHub 源码仓库](https://github.com/Wdp-SE/enterprise-rag-agent-suite)
- [在线工作台](https://enterprise-rag-agent-suite-bfmkgsimdisxcewgco7ydk.streamlit.app/)

默认公网入口 [app.py](app.py) 加载 **Autoware 规划研发知识工作台**。RAG 后端固定收录 Autoware Universe 0.51.0 与 0.52.0 的公开资料，默认选择清单声明的当前已收录版本 0.52.0；它不会实时追踪 Autoware 上游。工作台提供版本检索、来源引用与带版本依据的变更影响审查；两条人工复核图中文字作为派生证据，保留原图 SHA 和固定提交链接。KEP 只用于启发变更提案和审核流程，不进入 RAG 语料。变更审查 Agent 保留自然语言原文，可选补充变更类型与影响范围；未填写类型时用确定性规则归类，无法识别时回退到通用检索。Agent 最多发起 4 次 RAG 查询、选取最多 5 条证据，并显示检索轨迹与结构化证据缺口。人工审核决定会追加写入匿名会话对应的本地 SQLite，并保留 JSON 下载；公网托管临时磁盘可能清空，且未实现登录身份、权限或集中审批。记录不写公共基线。

本仓库还包含本地合成研发资料工作台，用于演示文档版本 Diff、追踪关系、PatchCandidate、审核、冲突检测和候选版本安全激活。它使用完全合成资料，不是第二个项目，也不默认加载在公网入口；仅在本机设置 `DEMO_LEGACY_FIXTURES=true` 后重启进入。

## 本地启动

先按[根目录 Quick Start](../README.md)准备环境。本地 clean-clone 已在 Python 3.11 验证通过；该验证记录不定义项目最低 Python 版本。Render 使用仓库配置的 Python 3.12.8；本文不推测 Streamlit Community Cloud 的 Python 版本。然后在仓库根目录运行：

```powershell
.\start_prototype.ps1
```

访问 <http://127.0.0.1:8502/>。脚本使用仓库内固定 Autoware 资料和轻量索引，不需要历史 runtime 或私有文件；没有模型密钥仍可检索，模型未启用时会明确说明生成未配置。默认生成服务为 DashScope/Qwen，需在本机**环境变量**配置 `DASHSCOPE_API_KEY`。也可使用 DeepSeek：配置 `DEEPSEEK_API_KEY`，并在启动前设置 `RD_V2_GENERATION_PROVIDER=deepseek`（可选设置 `RD_V2_GENERATION_MODEL=deepseek-v4-flash`）。然后运行 `./start_prototype.ps1 -EnableGeneration`。不要把实际值写进仓库或日志。

手动启动时：在 `versioned-rag-service` 目录运行 `uvicorn src.public_server:app --host 127.0.0.1 --port 8765`，在 `demo-ui` 目录设置 `RAG_API_BASE_URL=http://127.0.0.1:8765` 后运行 `streamlit run app.py --server.port 8502`；使用仓库相应的虚拟环境解释器。

## 操作路径

1. “可信检索问答”：默认 0.52.0，可切换到 0.51.0；输入关于 Start/Goal Planner、planning validator 或 trajectory checker 的问题，再核对带版本固定来源的引用。可问搜索优先级图有哪些标签，或 Goal Planner 图片中的 drivable area / obstacle stop 标记。“技术详情”才显示检索得分，该分数不是事实可信度。
2. “发起变更审查”：用自然语言描述假设变更；需要时展开可选字段补充变更类型与影响范围。系统拆分检索子问题并在当前版本资料中寻找证据，展示规则分类、检索轨迹、影响候选和结构化证据缺口；可选片段做修改前后对照，最后由人审核。人工决定绑定当前任务编号，可下载包含请求指纹、证据 ID、决定和时间的会话 JSON，但不会自动进入审批系统。仅有来源原文明确支持的文档关联才会标为已确认；主题相似或模型判断只作为待核对建议。
3. “检索评测”页按当前 Autoware 语料与实现指纹展示 16 道冻结检索题的对照。`bm25_figure_ocr` 在 Top-5 必需来源指标不低于 BM25 的同时命中 2/2 图中文字证据；Dev 与 Holdout 各只有一道无答案题，仍均召回候选（1/1），所以不能声称具备可靠拒答或高答案准确率。旧 Apache DolphinScheduler 的 V1-V4 结果仅作历史工程记录，不能套用到 Autoware。服务未配置在线模型或生成未通过引用校验时，问答页保留可核对的检索候选与明确状态。

查询拆解评测使用 8 条手工样例测类型分类、子问题覆盖及 4 次查询上限：`python evaluation/agent_query_decomposition/run_evaluation.py`。这是规则规划契约的轻量离线评测，不代表端到端检索准确率、回答正确率或线上延迟。

## 检索结论与已知限制

当前公网服务使用 `bm25_figure_ocr` 与 Top-5；文字检索仍以 BM25 为基础，只把命中至少两个图中文字词且不挤掉 Top-5 唯一来源的审核图中文字加入证据。Autoware 0.51/0.52 语料为固定快照，不设置来源上限。旧 DolphinScheduler 语料上的 multilingual E5、Hybrid 及 V1-V4 数字都不代表当前 Autoware 检索表现；新的小型 HOLDOUT 也不是独立真实用户测试。题集和对照见[Autoware 检索评测说明](../evaluation/autoware_retrieval_v1/README.md)。

旧 DolphinScheduler 语料上的 V2-V4 检索实验、指标与图片清单保留在 `evaluation/real_world_retrieval/`，作为历史工程记录；它们不能说明当前 Autoware 语料的检索效果。当前策略与冻结题集结果以 [Autoware 检索评测说明](../evaluation/autoware_retrieval_v1/README.md)为准。

当前 22 份 Autoware 来源只覆盖规划、路径生成和验证相关模块，不覆盖整个 Autoware；目前只有两张图的清晰标签经过人工复核，复杂图形关系不转成文本事实。Dev/Holdout 各只有一道无答案题，且都返回了候选；拒答阈值仍需扩大题集后再评估。规则分类使用小型关键词表，遇到领域新词时可能回退为通用类别；审查状态保存在当前 Session，下载审查 JSON 需要用户自行保存，不修改公共语料或 Autoware 上游。系统不实现 locale sibling consistency；影响候选需要人工复核，审查结果不会写回公共资料。

## 云端配置

Streamlit Community Cloud 入口仍是 `demo-ui/app.py`；本文不指定其 Python 版本，以当前应用配置和平台选项为准。至少设置 `APP_ENV="public_demo"` 与 `RAG_API_BASE_URL="<真实 Render URL>"`；完整字段见 [部署指南](../project_delivery/public_value_prototype/free_deployment_guide.md)及[Secrets 示例](.streamlit/secrets.toml.example)。应用本身不设置固定生成次数或自动无限重试；模型服务商的余额、限流和网络状态仍决定单次请求能否完成。在线生成密钥只配置在 Render RAG 后端：默认 DashScope 使用 `DASHSCOPE_API_KEY`；若改用 DeepSeek，设置 `RD_V2_GENERATION_PROVIDER=deepseek`、`RD_V2_GENERATION_MODEL=deepseek-v4-flash` 和 `DEEPSEEK_API_KEY`。不要把模型密钥放进 Streamlit 前端 Secrets，也不要提交 `secrets.toml`。

## UI 回归

```powershell
& ..\change-review-agent\.venv\Scripts\python.exe -m pytest -p no:cacheprovider tests -q
```

资料来源和许可证见 [Corpus Manifest](../versioned-rag-service/public_corpus/corpus_manifest.json)、[LICENSE](../versioned-rag-service/public_corpus/LICENSE) 与 [NOTICE](../versioned-rag-service/public_corpus/NOTICE)。
