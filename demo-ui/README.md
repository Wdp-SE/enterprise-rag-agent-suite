# 研发知识版本服务与变更影响审查工作台（Streamlit）

- [GitHub 源码仓库](https://github.com/Wdp-SE/enterprise-rag-agent-suite)
- [在线工作台](https://enterprise-rag-agent-suite-bfmkgsimdisxcewgco7ydk.streamlit.app/)

默认入口 [app.py](app.py) 展示 **Apache DolphinScheduler 官方公开资料**：左侧导航按“知识服务”“变更审查”“系统说明”分组，提供总览、可信检索问答、版本与历史、资料与来源、会话审查各步骤、检索评测与已知限制。首页说明来源与非官方身份。知识服务支持 3.4.2 / 3.4.3 固定版本、中文优先/中英双语检索、真实官方原文引用和可核验的资料差异提醒。变更审查 Agent 调用当前版本 RAG 证据，整理待核查影响与修改建议，草案和人工审核状态只留在当前 Streamlit 会话，不写公共基线。

![本地 V1.0 候选工作台首页截图（非当前公网页面）](../project_delivery/final_engineering_review/home.png)

## 本地启动

先按[根目录 Quick Start](../README.md)准备环境。本地 clean-clone 已在 Python 3.11 验证通过；该验证记录不定义项目最低 Python 版本。Render 使用仓库配置的 Python 3.12.8；本文不推测 Streamlit Community Cloud 的 Python 版本。然后在仓库根目录运行：

```powershell
.\start_prototype.ps1
```

访问 <http://127.0.0.1:8502/>。脚本使用仓库内固定的官方资料和轻量索引，不需要历史 runtime 或私有文件；没有模型密钥仍可检索和审查。默认生成服务为 DashScope/Qwen，需在本机**环境变量**配置 `DASHSCOPE_API_KEY`。也可使用 DeepSeek：配置 `DEEPSEEK_API_KEY`，并在启动前设置 `RD_V2_GENERATION_PROVIDER=deepseek`（可选设置 `RD_V2_GENERATION_MODEL=deepseek-v4-flash`）。然后运行 `./start_prototype.ps1 -EnableGeneration`。不要把实际值写进仓库或日志。

手动启动时：在 `versioned-rag-service` 目录运行 `uvicorn src.public_server:app --host 127.0.0.1 --port 8765`，在 `demo-ui` 目录设置 `RAG_API_BASE_URL=http://127.0.0.1:8765` 后运行 `streamlit run app.py --server.port 8502`；使用仓库相应的虚拟环境解释器。

## 操作路径

1. “可信检索问答”：选版本和语言，输入问题，先查看答案，再核对引用依据 Top 3；其余结果折叠。“技术详情”才显示检索得分，该分数不是事实可信度。
2. “新建变更审查”：选择真实官方文档和段落，输入假设内容，查看 Diff、可能受影响的资料与官方链接、会话草案，最后人工审核。仅官方 PR 明确引用 DSIP 的关系会标记为已确认；语义检索只标记建议。
3. “检索评测”页面保留早期字符哈希 Dense 的历史对照，不代表真实 multilingual E5 选型结果。V1.0 当前正式策略为 Chunk A（1250 chars、无 overlap）+ BM25 + Top-5；同条件 E5/Hybrid 对照及 HOLDOUT 边界见[最终选型报告](../evaluation/real_world_retrieval/final_selection/final_selection.md)。服务未配置在线模型或生成未通过引用校验时，问答页只展示待核对的检索候选。

原合成 Case A/B 仍供测试使用。仅需复现这些历史测试夹具界面时，显式设置 `DEMO_LEGACY_FIXTURES=true`；公网默认不会展示或加载合成案例。

## V1.0 检索结论与已知限制

正式检索保持 BM25 + Top-5、Chunk A 为 1250 chars 且无 overlap，不设置文档数上限。multilingual E5 与 Hybrid 仅用于同条件选型比较，不进入正式链路；Hybrid 的 MRR 仅小幅增加，Hit@1、Hit@5、双来源完整命中没有改善，P95 明显高于 BM25。四条跨文档题双来源完整命中为 0/4。HOLDOUT 是既有 46 条题目的回顾性确定划分，不是独立真实用户测试。

语料仅是 52 份官方资料的有限子集。Agent 工作状态保存在当前 Session 沙箱，不修改公共语料或 Apache 上游。系统不实现 locale sibling consistency；影响候选需要人工复核，审查结果不会写回公共资料。详细结果见[最终选型报告](../evaluation/real_world_retrieval/final_selection/final_selection.md)。

## 云端配置

Streamlit Community Cloud 入口仍是 `demo-ui/app.py`；本文不指定其 Python 版本，以当前应用配置和平台选项为准。至少设置 `APP_ENV="public_demo"` 与 `RAG_API_BASE_URL="<真实 Render URL>"`；完整字段见 [部署指南](../project_delivery/public_value_prototype/free_deployment_guide.md)及[Secrets 示例](.streamlit/secrets.toml.example)。应用本身不设置固定生成次数；模型服务商的限流和计费规则仍适用。在线生成密钥只配置在 Render RAG 后端：默认 DashScope 使用 `DASHSCOPE_API_KEY`；若改用 DeepSeek，设置 `RD_V2_GENERATION_PROVIDER=deepseek`、`RD_V2_GENERATION_MODEL=deepseek-v4-flash` 和 `DEEPSEEK_API_KEY`。不要把模型密钥放进 Streamlit 前端 Secrets，也不要提交 `secrets.toml`。

## UI 回归

```powershell
& ..\change-review-agent\.venv\Scripts\python.exe -m pytest -p no:cacheprovider tests -q
```

资料来源和许可证见 [Corpus Manifest](../versioned-rag-service/public_corpus/corpus_manifest.json)、[LICENSE](../versioned-rag-service/public_corpus/LICENSE) 与 [NOTICE](../versioned-rag-service/public_corpus/NOTICE)。
