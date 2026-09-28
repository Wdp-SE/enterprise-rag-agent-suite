# 官方公开资料工作台：部署与验收

下面的公网链接指向已有服务；实际运行版本以托管平台显示的部署提交为准。界面截图见[首页截图](../final_engineering_review/home.png)。本地 clean-clone 已在 Python 3.11 验证通过；此记录不定义项目最低 Python 版本。

- GitHub：[Wdp-SE/enterprise-rag-agent-suite](https://github.com/Wdp-SE/enterprise-rag-agent-suite)
- GitHub 与 Streamlit 部署分支：`main`
- [Streamlit 工作台](https://enterprise-rag-agent-suite-bfmkgsimdisxcewgco7ydk.streamlit.app/)
- [Render API 文档](https://version-aware-rag-public-demo.onrender.com/docs)
- [Render 健康状态](https://version-aware-rag-public-demo.onrender.com/health)

## 当前语料、检索策略与限制

公开语料是 Apache DolphinScheduler 3.4.2 / 3.4.3 的固定官方资料快照，共 **132 份来源、1322 个检索片段**；清单中的 `current_version` 为 **3.4.3**，也是未指定版本时的默认检索范围。运行中的默认检索策略是 BM25、Top-5；启动时不实时追踪上游，也不重建索引。

当前语料的 [V3 冻结评测](../../evaluation/real_world_retrieval/quality_v3/report.md)包含 72 道新业务题，按场景家族分成 DEV / HOLDOUT 各 36 道（各有 32 道可回答）。DEV 比较 BM25 与三种来源多样化候选：后者多找齐一题的必需来源，却挤掉部分含关键原文的片段，因此在打开 HOLDOUT 前锁定 BM25，随后仅对 BM25 运行一次 HOLDOUT。

| V3 指标 | DEV BM25 | HOLDOUT BM25 |
| --- | ---: | ---: |
| 全部必需来源完整命中 | 30/32 | 27/32 |
| 多来源题完整命中 | 6/8 | 4/8 |
| 返回片段中的原文证据锚点 | 44/48 | 37/49 |

这些是固定题集上的离线 Top-5 检索结果；多来源、跨版本及精确操作依据仍有漏检，不能把来源命中率解读为答案准确率、幻觉率或公网性能。资料仍只是官方文档的有限子集；图片内文字尚未进入正式索引。Agent 草案与审核状态只在当前 Session 沙箱内，不修改公共语料或 Apache 上游。较早 52 来源语料上的 V1/V2 结果仅是历史记录，见[旧版最终选型报告](../../evaluation/real_world_retrieval/final_selection/final_selection.md)。

## Render：FastAPI

[render.yaml](../../render.yaml) 指定 Free Web Service、`versioned-rag-service` 根目录、Python 3.12.8、`pip install -r requirements-render.txt`、`uvicorn src.public_server:app --host 0.0.0.0 --port $PORT` 和 `/health`。公开服务从仓库内 `public_corpus/` 加载 **132 份官方资料、1322 个片段及 BM25 策略文件**供 `/public/*` 使用；不依赖历史合成 Artifact。启动时不抓取网络资料、不运行 OCR、不重建 Embedding/FAISS；不需要 PostgreSQL、Redis、持久磁盘或 Worker。

当前 Render RAG 后端的 DeepSeek 生成配置应为：

```text
APP_ENV=public_demo
RD_V2_ALLOW_EXTERNAL_GENERATION=true
RD_V2_GENERATION_PROVIDER=deepseek
RD_V2_GENERATION_MODEL=deepseek-v4-flash
DEEPSEEK_API_KEY=<仅在 Render 环境变量中设置实际密钥>
```

`render.yaml` 是仓库部署清单；Render 控制台手动设置的环境变量可能与它不同。核对当前服务的 Environment 页面和实际部署提交，尤其是生成开关、provider、model 和密钥是否存在。密钥只放在 Render RAG 后端，不得写入仓库、日志或 Streamlit Secrets。缺少所选服务的密钥时仍可用 `/public/search`、真实文档目录与假设变更审查；`/public/query` 在找到证据时返回 `GENERATION_NOT_CONFIGURED` 和检索证据，不会伪造答案。服务端会校验模型引用确实来自本次检索。应用未设置固定会话生成次数；模型服务商自身的限流和计费规则仍适用。匿名 Session ID 不是身份认证。生成请求超时后客户端不自动重试，以免重复调用模型。

部署新版后的检索核验：

```powershell
$base = 'https://version-aware-rag-public-demo.onrender.com'
Invoke-RestMethod "$base/health"
Invoke-RestMethod "$base/public/workspace"
Invoke-RestMethod "$base/public/documents"
$body = @{ query = 'DolphinScheduler 参数优先级从高到低是什么？'; version = '3.4.3'; language = 'zh_preferred' } | ConvertTo-Json
Invoke-RestMethod "$base/public/search" -Method Post -ContentType 'application/json; charset=utf-8' -Body ([Text.Encoding]::UTF8.GetBytes($body))
```

若需要验证 DeepSeek 是否真的能生成，单独运行下面的请求；它可能产生模型费用：

```powershell
Invoke-RestMethod "$base/public/query" -Method Post -ContentType 'application/json; charset=utf-8' -Body ([Text.Encoding]::UTF8.GetBytes($body))
```

`/public/workspace` 应显示 3.4.2 / 3.4.3、132 个来源、1322 个片段、默认 BM25 和 `v3_validated`。`/health` 中 `generation.status=CONFIGURED_UNVERIFIED` 只证明服务进程发现了生成开关及所选密钥配置，**不证明**供应商实际可调用；用 `/public/query` 的真实请求核验。`status=OK` 且返回带来源的回答表示本次调用成功；若返回 `GENERATION_NOT_CONFIGURED` 或供应商错误状态，检查 Render 的实际环境变量和响应中的非敏感诊断字段。Render Free 可能冷启动；观察 Build/Runtime logs 和根目录、依赖、资产路径、`$PORT`、内存。原有 `scripts/public_demo_smoke.py` 面向历史合成接口，**不能用于**新版公开服务。

## Streamlit Community Cloud

| 字段 | 值 |
| --- | --- |
| Repository | `Wdp-SE/enterprise-rag-agent-suite` |
| Branch | `main` |
| Main file path | `demo-ui/app.py` |
| Python | 本文不指定；以 Streamlit Community Cloud 当前应用配置和平台选项为准 |
| Dependency file | `demo-ui/requirements.txt` |

按 [Secrets 示例](../../demo-ui/.streamlit/secrets.toml.example)设置 `APP_ENV="public_demo"`、`DEMO_LEGACY_FIXTURES=false`、`RAG_API_BASE_URL="https://version-aware-rag-public-demo.onrender.com"` 与超时/重试参数。**不要**把模型 API Key 放进 Streamlit：模型调用只由 Render 后端执行；DeepSeek 的生成开关、provider、model 和密钥按上文配置在 Render。`DEMO_LEGACY_FIXTURES=true` 仅用于历史合成夹具，不应设置在公网 App。

部署后用真实浏览器验收：首页两个模块和 Apache 来源声明；中文、英文、中英混合检索；历史版本 Scope；配置了模型时的有引用回答；DSIP-107 假设变更的已确认 PR 关系与其他“建议”关系；人工审核；另开 Session 不看到前一会话草案。确认公共资料 Manifest 的哈希不变。

## 本地复现和回归

按[根目录 Quick Start](../../README.md)装好依赖后执行 `./start_prototype.ps1`，打开 <http://127.0.0.1:8502/>。有密钥时可运行 `./start_prototype.ps1 -EnableGeneration`；无需提供密钥也可完成其余 Smoke。端口占用时指定 `-RagPort` 与 `-UiPort`。原有三个未跟踪 DOCX、用户 runtime 与私有文件不参与新 Clone 启动。

```powershell
Push-Location versioned-rag-service
& .\.venv\Scripts\python.exe -m pip install 'pytest>=8.3,<9'
& .\.venv\Scripts\python.exe -m pytest tests -q
Pop-Location
Push-Location change-review-agent
& .\.venv\Scripts\python.exe -m pytest tests -q
Pop-Location
Push-Location demo-ui
& ..\change-review-agent\.venv\Scripts\python.exe -m pytest -p no:cacheprovider tests -q
Pop-Location
```

当前真实检索的题库、Ground Truth、冻结记录与逐条结果见 [V3 评测目录](../../evaluation/real_world_retrieval/quality_v3/)；固定来源、SHA-256、Apache LICENSE/NOTICE 在 [public_corpus](../../versioned-rag-service/public_corpus/)。V3 成绩与已知限制见[评测报告](../../evaluation/real_world_retrieval/quality_v3/report.md)。本地检索 P50/P95 不包括公网冷启动、HTTP 与 LLM 时间，不代表公网 SLA。
