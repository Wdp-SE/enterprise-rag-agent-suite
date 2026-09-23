# 免费公网部署与验收指南

本仓库的公开演示使用合成研发资料。RAG 服务和 Streamlit 应用已经各有公网地址；新版本是否已上线取决于平台实际部署的 GitHub 提交，不能只凭网址存在判断。

- GitHub：[Wdp-SE/enterprise-rag-agent-suite](https://github.com/Wdp-SE/enterprise-rag-agent-suite)
- 部署分支：`feature/public-value-prototype`
- [Streamlit 工作台](https://enterprise-rag-agent-suite-bfmkgsimdisxcewgco7ydk.streamlit.app/)
- [Render RAG API 文档](https://version-aware-rag-public-demo.onrender.com/docs)
- [Render RAG 健康状态](https://version-aware-rag-public-demo.onrender.com/health)

## Render：版本可信 RAG

仓库根目录的 `render.yaml` 是配置来源：`RAG-Challenge-2-main` 为根目录，Free Web Service，Python 3.12.8，构建命令 `pip install -r requirements-render.txt`，启动命令 `uvicorn src.rd_v2_api:app --host 0.0.0.0 --port $PORT`，健康检查 `/health`。

正式公网配置加载 `public_demo_artifacts/rd-v2-public-demo-v1`，设置 `APP_ENV=public_demo`、临时候选版本目录 `/tmp/public-demo-candidates`，并保持 `RD_V2_ALLOW_EXTERNAL_GENERATION=false`。它不依赖被 Git 忽略的 `data/rd_v2_corpus/`，也不在启动时重建 OCR、Embedding 或 FAISS。当前演示无需数据库、Redis、持久磁盘、Worker 或个人模型密钥。

只读验证：

```powershell
cd RAG-Challenge-2-main
.\.venv\Scripts\python.exe scripts\public_demo_smoke.py --base-url https://version-aware-rag-public-demo.onrender.com
```

该命令只调用 `/health` 与 `/retrieve`，检查当前有效版本；不调用 `/query`、不发布候选版本。部署失败时检查 Render Build/Runtime 日志、Python 版本、根目录、依赖、资产相对路径和 `$PORT`。Render Free 空闲后可能休眠，首次请求须允许冷启动时间。

## Streamlit Community Cloud：业务工作台

已有应用的设置应为：

| 字段 | 值 |
|---|---|
| Repository | `Wdp-SE/enterprise-rag-agent-suite` |
| Branch | `feature/public-value-prototype` |
| Main file path | `demo-ui/app.py` |
| Python | 3.12 |
| 依赖 | `demo-ui/requirements.txt` |

在 Streamlit Cloud 的 Secrets 页面按 [示例](../../demo-ui/.streamlit/secrets.toml.example) 配置 `APP_ENV="public_demo"`、`RAG_API_BASE_URL="https://version-aware-rag-public-demo.onrender.com"`、临时 `DEMO_RUNTIME_ROOT`、`DEMO_ALLOW_RAG_QUERY=false`、超时/重试与 Session 预算。不要将实际 `secrets.toml` 或 API Key 提交到 Git。公开主流程不需要 `DASHSCOPE_API_KEY`；在线生成保持禁用。

发布新 UI 后先在平台确认部署提交与目标提交一致，再用真实浏览器完成：工作台加载、RAG Ready、Case A / Case B 分析、引用依据、Patch Review、候选版本和安全发布，并在另一 Session 检查隔离。主页截图来自本分支的本地公开合成配置，不代替线上验收。

## 本地复现

新克隆用户按[根目录 Quick Start](../../README.md)安装 Python 3.12 环境，再执行 `start_prototype.ps1`。脚本使用仓库已跟踪的公开合成资产和系统临时运行目录；不需要私有语料或历史 `runtime/`。

平台参考：[Render Blueprint](https://render.com/docs/blueprint-spec)、[Render Free](https://render.com/docs/free)、[Streamlit Cloud 部署](https://docs.streamlit.io/deploy/streamlit-community-cloud/deploy-your-app/deploy)、[Streamlit Secrets](https://docs.streamlit.io/develop/concepts/connections/secrets-management)。本地性能报告不等于公网端到端延迟，免费服务也不提供生产 SLA。
