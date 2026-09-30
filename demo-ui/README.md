# 研发知识版本服务与变更影响审查工作台（Streamlit）

- [GitHub 源码仓库](https://github.com/Wdp-SE/enterprise-rag-agent-suite)
- [在线工作台](https://enterprise-rag-agent-suite-bfmkgsimdisxcewgco7ydk.streamlit.app/)

默认公网入口 [app.py](app.py) 加载 **Autoware 研发资料检索与变更审查工作台**。固定语料包括官方 Autoware Documentation 英文 `main` / `1.9.0` 快照、Tomato ROS 社区中文译本，以及 Universe Planning 英文 `0.51.0` / `0.52.0` 快照。语料共 1,148 条版本/语言来源、660 个不同资料主题/路径和 7,927 个检索片段。默认 `latest` 组合 Documentation `main` 与 Universe `0.52.0`，不代表同一个软件发行版本，也不会实时追踪上游。260 页社区中文译文中 44 页的 canonical 路径匹配当前官方英文快照，216 页的对应关系未核实；系统会显示这一来源边界。

工作台提供版本与语言检索、引用溯源和带版本依据的变更影响审查；两条人工复核的 Universe 图片文字作为派生证据，保留原图 SHA 和固定来源。KEP 只用于启发变更提案和审核流程，不进入 RAG 语料。变更审查 Agent 保留自然语言原文，可选补充变更类型与影响范围；未填写类型时用确定性规则归类，无法识别时回退到通用检索。Agent 最多发起 4 次 RAG 查询、选取最多 5 条证据，并显示检索轨迹与结构化证据缺口。人工审核决定会追加写入匿名会话对应的本地 SQLite，并保留 JSON 下载；公网托管临时磁盘可能清空，且未实现登录身份、权限或集中审批。记录不写公共基线。

本仓库还包含本地合成研发资料工作台，用于演示文档版本 Diff、追踪关系、PatchCandidate、审核、冲突检测和候选版本安全激活。它使用完全合成资料，不是第二个项目，也不默认加载在公网入口；仅在本机设置 `DEMO_LEGACY_FIXTURES=true` 后重启进入。

## 本地启动

先按[根目录 Quick Start](../README.md)准备环境。本地 clean-clone 已在 Python 3.11 验证通过；该验证记录不定义项目最低 Python 版本。Render 使用仓库配置的 Python 3.12.8；本文不推测 Streamlit Community Cloud 的 Python 版本。然后在仓库根目录运行：

```powershell
.\start_prototype.ps1
```

访问 <http://127.0.0.1:8502/>。脚本使用仓库内固定 Autoware 资料和轻量索引，不需要历史 runtime 或私有文件；没有模型密钥仍可检索，模型未启用时会明确说明生成未配置。默认生成服务为 DashScope/Qwen，需在本机**环境变量**配置 `DASHSCOPE_API_KEY`。也可使用 DeepSeek：配置 `DEEPSEEK_API_KEY`，并在启动前设置 `RD_V2_GENERATION_PROVIDER=deepseek`（可选设置 `RD_V2_GENERATION_MODEL=deepseek-v4-flash`）。然后运行 `./start_prototype.ps1 -EnableGeneration`。不要把实际值写进仓库或日志。

手动启动时：在 `versioned-rag-service` 目录运行 `uvicorn src.public_server:app --host 127.0.0.1 --port 8765`，在 `demo-ui` 目录设置 `RAG_API_BASE_URL=http://127.0.0.1:8765` 后运行 `streamlit run app.py --server.port 8502`；使用仓库相应的虚拟环境解释器。

## 操作路径

1. “可信检索问答”：默认使用 Documentation `main` + Universe `0.52.0`；也可分别选择 Documentation `1.9.0`、Universe `0.52.0` / `0.51.0` 或全部快照。默认语言为“中文优先”，也可严格只查中文、只查英文或同时检索。示例覆盖 Autoware 启动、日志和规划架构的中文问题，以及 Planning Validator、Trajectory Checker 的英文问题。查看引用时可核对固定 Git commit、社区译文页面、路径对应状态和原文来源。“技术详情”显示的检索得分只用于排序，不代表事实可信度。
2. “发起变更审查”：用自然语言描述假设变更；需要时展开可选字段补充变更类型与影响范围。系统拆分检索子问题并在当前版本资料中寻找证据，展示规则分类、检索轨迹、影响候选和结构化证据缺口；可选片段做修改前后对照，最后由人审核。人工决定绑定当前任务编号，可下载包含请求指纹、证据 ID、决定和时间的会话 JSON，但不会自动进入审批系统。仅有来源原文明确支持的文档关联才会标为已确认；主题相似或模型判断只作为待核对建议。
3. “检索评测”页会说明当前双语语料尚未完成冻结 Benchmark。旧 Autoware V3 43 题评测针对扩充前的小语料，指纹与当前后端索引不匹配，不能用作当前成绩。新增 10 条中英检索冒烟题只验证严格语言过滤和预期来源是否进入 Top-5，不是准确率或泛化评测。旧 Apache DolphinScheduler 的 V1-V4 结果仅作历史工程记录，不能套用到 Autoware。

查询拆解评测使用 8 条手工样例测类型分类、子问题覆盖及 4 次查询上限：`python evaluation/agent_query_decomposition/run_evaluation.py`。这是规则规划契约的轻量离线评测，不代表端到端检索准确率、回答正确率或线上延迟。

## 检索结论与已知限制

语料扩充后公网默认策略恢复为 BM25 基线。官方英文 Documentation、社区中文翻译和 Universe Planning 来自不同仓库与固定快照；默认范围是显式组合，不能把中文译本一概视作与当前官方英文版本严格等价。旧 DolphinScheduler 及 Autoware V3/V4 指标都不代表当前 Autoware 双语语料表现。完整策略选型需要冻结中英文 DEV/HOLDOUT 题集，覆盖必需来源召回、跨资料完整命中、版本正确率、无答案候选、图像证据覆盖和延迟；当前状态与计划见[双语评测说明](../evaluation/autoware_bilingual_v1/README.md)。旧 DolphinScheduler 的 V2-V4 实验保留在 `evaluation/real_world_retrieval/` 作为历史记录。

当前语料仍不是完整 Autoware 资料库；260 页中文社区译文中有 216 页未匹配到官方 Documentation `main` 的同路径页面，具体版本对应关系未知。HTML 转换会索引正文、表格和代码块；图像像素未由导入器识别，alt/图片说明不等于 OCR。只有两张 Universe 图片的标签经过人工 OCR 复核，复杂图形关系不转成文本事实。当前新语料尚无可报告的双语质量基准；规则分类也可能因领域新词回退到通用类别。审查状态保存在当前 Session，下载审查 JSON 需要用户自行保存；系统不实现 locale sibling consistency，变更建议仍需人工复核。

## 云端配置

Streamlit Community Cloud 入口仍是 `demo-ui/app.py`；本文不指定其 Python 版本，以当前应用配置和平台选项为准。至少设置 `APP_ENV="public_demo"` 与 `RAG_API_BASE_URL="<真实 Render URL>"`；完整字段见 [部署指南](../project_delivery/public_value_prototype/free_deployment_guide.md)及[Secrets 示例](.streamlit/secrets.toml.example)。应用本身不设置固定生成次数或自动无限重试；模型服务商的余额、限流和网络状态仍决定单次请求能否完成。在线生成密钥只配置在 Render RAG 后端：默认 DashScope 使用 `DASHSCOPE_API_KEY`；若改用 DeepSeek，设置 `RD_V2_GENERATION_PROVIDER=deepseek`、`RD_V2_GENERATION_MODEL=deepseek-v4-flash` 和 `DEEPSEEK_API_KEY`。不要把模型密钥放进 Streamlit 前端 Secrets，也不要提交 `secrets.toml`。

## UI 回归

```powershell
& ..\change-review-agent\.venv\Scripts\python.exe -m pytest -p no:cacheprovider tests -q
```

资料来源和许可见 [Autoware Corpus Manifest](../versioned-rag-service/public_corpus_autoware/corpus_manifest.json)、[语料说明](../versioned-rag-service/public_corpus_autoware/README.md)、[LICENSE](../versioned-rag-service/public_corpus_autoware/LICENSE) 与 [NOTICE](../versioned-rag-service/public_corpus_autoware/NOTICE)。
