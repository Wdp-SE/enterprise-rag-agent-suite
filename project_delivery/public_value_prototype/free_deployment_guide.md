# 免费公网部署指南

## 前提

- Repository：Wdp-SE/enterprise-rag-agent-suite
- 验证 Branch：feature/public-value-prototype
- Python：3.12
- 所有资料为合成数据
- 本轮没有替用户创建平台应用或配置真实 Secret

## Render RAG

仓库根目录已提供 render.yaml。Render Dashboard 选择 New → Blueprint 并连接仓库与分支。

- Root Directory：RAG-Challenge-2-main
- Build：pip install -r requirements-render.txt
- Start：uvicorn src.rd_v2_api:app --host 0.0.0.0 --port $PORT
- Health：/health
- Plan：Free
- APP_ENV=public_demo
- RD_V2_ARTIFACT_ROOT=public_demo_artifacts/rd-v2-public-demo-v1
- RD_V4_VERSION_STORE_ROOT=/tmp/public-demo-candidates
- MAX_LLM_CALLS_PER_SESSION=3
- RD_V2_ALLOW_EXTERNAL_GENERATION=false

如需 Qwen，由所有者在 Render Environment 添加 DASHSCOPE_API_KEY，并显式把 RD_V2_ALLOW_EXTERNAL_GENERATION 设为 true。不要把 Key 写入仓库。

部署后用 public_demo_smoke.py 对真实 URL 执行只读 /health 和 /retrieve；该 Smoke 不发布 Candidate、不激活版本、不调用 /query。

Render Free 会在空闲后休眠，首次访问可能冷启动，适合演示而非生产 SLA：
- https://render.com/docs/blueprint-spec
- https://render.com/docs/web-services
- https://render.com/docs/free
- https://render.com/docs/monorepo-support

## Streamlit Community Cloud

- Repository：Wdp-SE/enterprise-rag-agent-suite
- Branch：feature/public-value-prototype（人工合并后改为 main）
- Main file：demo-ui/app.py
- Python：3.12

在 Advanced settings → Secrets 填入 demo-ui/.streamlit/secrets.toml.example 中的字段，把 RAG_API_BASE_URL 换成真实 Render URL，不提交 secrets.toml。

官方说明：
- https://docs.streamlit.io/deploy/streamlit-community-cloud/deploy-your-app/deploy
- https://docs.streamlit.io/deploy/streamlit-community-cloud/deploy-your-app/app-dependencies
- https://docs.streamlit.io/deploy/streamlit-community-cloud/deploy-your-app/file-organization
- https://docs.streamlit.io/develop/concepts/connections/secrets-management

## 人工验收

1. Render 休眠时确认 Streamlit 首页仍显示。
2. 点击重新连接，确认状态恢复。
3. 分别选择 Case A/B，并完成一次 Case A 主 Demo。
4. 新浏览器 Session 不应看到旧 Session 状态。
5. 检查平台日志不含正文和 Secret。
6. 将真实 URL 填入 README。
7. 邀请 3～5 名用户按试用指南执行。

Local Retrieval P50/P95 不能当成公网端到端延迟；公网延迟必须部署后单独记录。
