# 官方公开资料工作台：部署与验收

下面的公网链接指向已有服务；实际运行版本以托管平台显示的部署提交为准。界面截图见[首页截图](../final_engineering_review/home.png)。本地 clean-clone 已在 Python 3.11 验证通过；此记录不定义项目最低 Python 版本。

- GitHub：[Wdp-SE/enterprise-rag-agent-suite](https://github.com/Wdp-SE/enterprise-rag-agent-suite)
- 分支：feature/public-value-prototype
- [Streamlit 工作台](https://enterprise-rag-agent-suite-bfmkgsimdisxcewgco7ydk.streamlit.app/)
- [Render API 文档](https://version-aware-rag-public-demo.onrender.com/docs)
- [Render 健康状态](https://version-aware-rag-public-demo.onrender.com/health)

## V1.0 检索策略与限制

正式策略为 Chunk A（1250 chars、无 overlap）+ BM25 + Top-5，不设置文档数上限。BM25、multilingual E5 与 Hybrid 已在相同资料、版本过滤、语言范围和 Top-5 条件下比较。Hybrid 最佳配置只有轻微 MRR 改善，Hit@1、Hit@5 和跨文档双来源完整命中均未改善，P95 明显高于 BM25，因此 E5、Hybrid、Rerank 不进入正式链路。四条跨文档题的双来源完整命中为 0/4。HOLDOUT 是既有题集的回顾性确定划分，不是独立真实用户测试。完整数值见[最终选型报告](../../evaluation/real_world_retrieval/final_selection/final_selection.md)。

最终选型工具 `run_selection.py` 分为 `chunk` → `retriever` → `topk` → `diversity` → `holdout` 阶段，不提供单条完整重跑命令。Holdout 受 `selection_lock.json` 中锁定的 DEV 结果哈希约束，不能对当前冻结结果随意重复执行。README 中的示例只运行 DEV 分块策略阶段，并会更新 `final_selection/results.json`。

公开展示限制：官方资料仅为 52 份有限子集；Agent 草案与审核状态只在当前 Session 沙箱内，不修改公共语料或 Apache 上游；当前 V1.0 不实现 locale sibling consistency。检索命中和来源引用不等于内容事实已被证明。

## Render：FastAPI

[render.yaml](../../render.yaml) 已指定 Free Web Service、`RAG-Challenge-2-main` 根目录、Python 3.12.8、`pip install -r requirements-render.txt`、`uvicorn src.public_server:app --host 0.0.0.0 --port $PORT` 和 `/health`。原有合成 Artifact 与旧 FastAPI 入口只保留在仓库内供回归夹具使用；公网服务仅从仓库内 `public_corpus/` 加载 **52 份官方资料、659 个片段、BM25 策略文件**供 `/public/*` 公开知识端点使用。启动时不抓取网络资料、不运行 OCR、不重建 Embedding/FAISS；不需要 PostgreSQL、Redis、持久磁盘或 Worker。

新部署清单使用 `APP_ENV=public_demo`、`RD_V2_ALLOW_EXTERNAL_GENERATION=true` 与每会话预算；当前公开入口不依赖历史合成 Artifact。服务端仅在生成开关开启且 Render 环境已配置 `DASHSCOPE_API_KEY` 时初始化 DashScope/Qwen。缺少密钥时仍可用 `/public/search`、真实文档目录与假设变更审查；`/public/query` 会返回检索证据和 `GENERATION_NOT_CONFIGURED`，不会伪造答案或因缺少密钥导致服务启动失败。密钥只在 Render 平台的环境变量设置，不得写入代码、日志或文档。服务端会校验 LLM 引用确实来自本次检索，并限制每 Session 与每进程调用次数。当前默认每会话 3 次、每进程 30 次；进程重启后计数重置。匿名 Session ID 不是身份认证，也不能替代 Render/DashScope 平台的费用配额。生成请求超时后客户端不自动重试，以免重复调用模型。

部署新版后的只读核验：

```powershell
$base = 'https://version-aware-rag-public-demo.onrender.com'
Invoke-RestMethod "$base/health"
Invoke-RestMethod "$base/public/workspace"
Invoke-RestMethod "$base/public/documents"
$body = @{ query = 'DolphinScheduler 参数优先级从高到低是什么？'; version = '3.4.3'; language = 'zh_preferred' } | ConvertTo-Json
Invoke-RestMethod "$base/public/search" -Method Post -ContentType 'application/json; charset=utf-8' -Body ([Text.Encoding]::UTF8.GetBytes($body))
```

`/public/workspace` 应显示 3.4.2 / 3.4.3、52 个来源与默认 BM25。若线上仍返回 404，说明 Render 尚未部署本轮代码。Render Free 可能冷启动；观察 Build/Runtime logs 和根目录、依赖、资产路径、`$PORT`、内存。原有 `scripts/public_demo_smoke.py` 面向历史合成接口，**不能用于**新版公开服务；请以 `/public/workspace` 与真实资料检索验收。

## Streamlit Community Cloud

| 字段 | 值 |
| --- | --- |
| Repository | `Wdp-SE/enterprise-rag-agent-suite` |
| Branch | `feature/public-value-prototype` |
| Main file path | `demo-ui/app.py` |
| Python | 本文不指定；以 Streamlit Community Cloud 当前应用配置和平台选项为准 |
| Dependency file | `demo-ui/requirements.txt` |

按 [Secrets 示例](../../demo-ui/.streamlit/secrets.toml.example)设置 `APP_ENV="public_demo"`、`DEMO_LEGACY_FIXTURES=false`、`RAG_API_BASE_URL="https://version-aware-rag-public-demo.onrender.com"`、超时/重试和 `MAX_LLM_CALLS_PER_SESSION=3`。**不要**把 `DASHSCOPE_API_KEY` 放进 Streamlit：模型调用只由 Render 后端执行。`DEMO_LEGACY_FIXTURES=true` 仅用于历史合成夹具，不应设置在公网 App。

部署后用真实浏览器验收：首页两个模块和 Apache 来源声明；中文、英文、中英混合检索；历史版本 Scope；配置了模型时的有引用回答；DSIP-107 假设变更的已确认 PR 关系与其他“建议”关系；人工审核；另开 Session 不看到前一会话草案。确认公共资料 Manifest 的哈希不变。

## 本地复现和回归

按[根目录 Quick Start](../../README.md)装好依赖后执行 `./start_prototype.ps1`，打开 <http://127.0.0.1:8502/>。有密钥时可运行 `./start_prototype.ps1 -EnableGeneration`；无需提供密钥也可完成其余 Smoke。端口占用时指定 `-RagPort` 与 `-UiPort`。原有三个未跟踪 DOCX、用户 runtime 与私有文件不参与新 Clone 启动。

```powershell
Push-Location RAG-Challenge-2-main
& .\.venv\Scripts\python.exe -m pip install 'pytest>=8.3,<9'
& .\.venv\Scripts\python.exe -m pytest tests -q
Pop-Location
Push-Location OpenManus-rag
& .\.venv\Scripts\python.exe -m pytest tests -q
Pop-Location
Push-Location demo-ui
& ..\OpenManus-rag\.venv\Scripts\python.exe -m pytest -p no:cacheprovider tests -q
Pop-Location
```

真实检索对照、Ground Truth 和逐条结果在 [evaluation/real_world_retrieval](../../evaluation/real_world_retrieval/)；固定来源、SHA-256、Apache LICENSE/NOTICE 在 [public_corpus](../../RAG-Challenge-2-main/public_corpus/)。最终选型结果与已知限制见[最终检索选型报告](../../evaluation/real_world_retrieval/final_selection/final_selection.md)。本地检索 P50/P95 不包括公网冷启动、HTTP 与 LLM 时间，不代表公网 SLA。
