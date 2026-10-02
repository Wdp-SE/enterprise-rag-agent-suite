# 研发知识版本服务与变更影响审查工作台（Streamlit）

- [GitHub 源码仓库](https://github.com/Wdp-SE/enterprise-rag-agent-suite)
- [在线工作台](https://enterprise-rag-agent-suite-bfmkgsimdisxcewgco7ydk.streamlit.app/)

公网前端、RAG 后端、语料、检索配置和评测集分别显示版本/指纹，见[发布核验说明](../docs/production_readiness.md)。只有 Git 提交可验证且工作区干净时才会显示构建 SHA；部署后按文档中的 Smoke 命令核对 Streamlit 与 Render 是否指向同一提交。

默认公网入口 [app.py](app.py) 加载 **Autoware 中文研发资料检索与变更审查工作台**。检索语料仅包含 Tomato ROS 社区维护的中文译本：2026-07 当前快照 260 份来源、2026-01 历史快照 259 份来源，共 519 条版本化来源记录、260 个资料主题和 3,806 个检索片段。`latest` 默认只指向 2026-07 快照，用户也可选择 2026-01 历史快照；日期是社区仓库提交时间，不是 Autoware 产品发行版本。该译本不是 Autoware 官方中文资料，服务不会实时追踪上游。

工作台提供中文版本检索、引用溯源和带版本依据的变更影响审查；当前语料没有英文资料或可检索的图片 OCR 证据。KEP 只用于启发变更提案和审核流程，不进入 RAG 语料。变更审查 Agent 保留自然语言原文，可选补充变更类型与影响范围；未填写类型时用确定性规则归类，无法识别时回退到通用检索。Agent 最多发起 4 次 RAG 查询、选取最多 5 条证据，并显示检索轨迹与结构化证据缺口。人工审核决定会追加写入匿名会话对应的本地 SQLite，并保留 JSON 下载；公网托管临时磁盘可能清空，且未实现登录身份、权限或集中审批。记录不写公共基线。

本仓库还包含本地合成研发资料工作台，用于演示文档版本 Diff、追踪关系、PatchCandidate、审核、冲突检测和候选版本安全激活。它使用完全合成资料，不是第二个项目，也不默认加载在公网入口；仅在本机设置 `DEMO_LEGACY_FIXTURES=true` 后重启进入。

## 本地启动

先按[根目录 Quick Start](../README.md)准备环境。本地 clean-clone 已在 Python 3.11 验证通过；该验证记录不定义项目最低 Python 版本。Render 使用仓库配置的 Python 3.12.8；本文不推测 Streamlit Community Cloud 的 Python 版本。然后在仓库根目录运行：

```powershell
.\start_prototype.ps1
```

访问 <http://127.0.0.1:8502/>。脚本使用仓库内固定 Autoware 资料和轻量索引，不需要历史 runtime 或私有文件；本机配置所选供应商的 API Key 后会自动启用回答生成，默认 DeepSeek `deepseek-flash`；没有密钥时仍可检索。运行 `./start_prototype.ps1 -DisableGeneration` 可关闭生成。也可切换到 DashScope/Qwen：设置 `RD_V2_GENERATION_PROVIDER=dashscope` 并配置 `DASHSCOPE_API_KEY`。不要把实际值写进仓库或日志。

手动启动时：在 `versioned-rag-service` 目录运行 `uvicorn src.public_server:app --host 127.0.0.1 --port 8765`，在 `demo-ui` 目录设置 `RAG_API_BASE_URL=http://127.0.0.1:8765` 后运行 `streamlit run app.py --server.port 8502`；使用仓库相应的虚拟环境解释器。

## 操作路径

1. “可信检索问答”：默认检索 `latest`（2026-07 中文社区快照），也可选 2026-01 中文历史快照。界面和 API 对 Autoware 工作区只开放中文检索。查看引用时可核对固定 Git commit 与社区来源。“技术详情”显示的检索得分只用于排序，不代表事实可信度。
2. “发起变更审查”：用自然语言描述假设变更；需要时展开可选字段补充变更类型与影响范围。系统拆分检索子问题并在当前版本资料中寻找证据，展示规则分类、检索轨迹、影响候选和结构化证据缺口；可选片段做修改前后对照，最后由人审核。人工决定绑定当前任务编号，可下载包含请求指纹、证据 ID、决定和时间的会话 JSON，但不会自动进入审批系统。仅有来源原文明确支持的文档关联才会标为已确认；主题相似或模型判断只作为待核对建议。
3. “检索评测”页会说明当前中文语料评测状态。此前英文/双语语料上的结果与当前指纹不匹配，不能作为当前性能数据；中文专用冻结题集和复评完成前，不公布当前检索质量或最优策略。

Agent 查询规划评测见 [`autoware_agent_query_planning_v1`](../evaluation/autoware_agent_query_planning_v1/README.md)，包含 28 条中英文请求，测确定性变更分类、公开范围拦截、子问题内容覆盖和 4 次查询上限，不调用 RAG 或模型。该轮修复期间已经查看留出用例，不能将其作为独立泛化结论；修复后 28 条全量自测为分类 28/28、范围 28/28、必需查询内容 56/56、预算 28/28。这些数值只描述固定规则契约。

## 检索结论与已知限制

公网默认策略暂为 `bm25`，作为可解释基线。之前英文或双语资料集上的指标不适用于当前中文语料；重新评测通过前不宣称策略最优，也不展示旧语料性能数值。

当前语料不是完整 Autoware 资料库，而是一个固定的社区中文译本快照集合。图像像素未执行普遍 OCR，因此图内文字暂不可检索；HTML 转换会索引正文、表格和代码块。检索 Benchmark 不代表答案质量。Agent 规则对新领域术语仍可能回退到通用类别；既有规划评测留出样本已在调试中查看，需用新的锁定评测集验证泛化。公网托管实例不提供企业级登录、权限或持久化集中审批，建议仍需人工复核。

## 云端配置

Streamlit Community Cloud 入口仍是 `demo-ui/app.py`；本文不指定其 Python 版本，以当前应用配置和平台选项为准。至少设置 `APP_ENV="public_demo"` 与 `RAG_API_BASE_URL="<真实 Render URL>"`；完整字段见 [部署指南](../project_delivery/public_value_prototype/free_deployment_guide.md)及[Secrets 示例](.streamlit/secrets.toml.example)。应用本身不设置固定生成次数或自动无限重试；模型服务商的余额、限流和网络状态仍决定单次请求能否完成。在线生成密钥只配置在 Render RAG 后端：默认 DashScope 使用 `DASHSCOPE_API_KEY`；若改用 DeepSeek，设置 `RD_V2_GENERATION_PROVIDER=deepseek`、`RD_V2_GENERATION_MODEL=deepseek-v4-flash` 和 `DEEPSEEK_API_KEY`。不要把模型密钥放进 Streamlit 前端 Secrets，也不要提交 `secrets.toml`。

## UI 回归

```powershell
& ..\change-review-agent\.venv\Scripts\python.exe -m pytest -p no:cacheprovider tests -q
```

资料来源和许可见 [Autoware Corpus Manifest](../versioned-rag-service/public_corpus_autoware/corpus_manifest.json)、[语料说明](../versioned-rag-service/public_corpus_autoware/README.md)、[LICENSE](../versioned-rag-service/public_corpus_autoware/LICENSE) 与 [NOTICE](../versioned-rag-service/public_corpus_autoware/NOTICE)。
