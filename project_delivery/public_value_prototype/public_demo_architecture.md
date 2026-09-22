# Public Demo 架构

    Browser
       │ HTTPS
       ▼
    Streamlit Community Cloud
    UI + Agent orchestration
       │ HTTPS / RAG_API_BASE_URL
       ▼
    Render Free Web Service
    FastAPI + Version-aware RAG
       │ optional
       ▼
    Qwen / DashScope

Agent 继续只通过 HTTP 使用 RAG，不直接读取 FAISS。

| 配置 | local | public_demo |
| --- | --- | --- |
| APP_ENV | local | public_demo |
| RAG URL | 127.0.0.1:8765 | Render HTTPS URL |
| Baseline | 本地合成资料 | Git 内轻量合成 Artifact |
| Session 输出 | 本地 runtime | /tmp 临时目录 |
| Embedder | 原正式配置 | 确定性轻量哈希 Embedder |
| 外部生成 | 默认关闭 | 默认关闭，可显式配置 |
| LLM Budget | 配置保留 | 每 Session fail-closed |
| 错误 | 调试友好 | 隐藏 traceback、业务提示 |

Retriever 语义保持 DENSE_ONLY + SECTION_PATH。Public profile 只替换部署需要的 Embedding 表示和运行目录，没有复制业务实现。

Case A/B Baseline 与 Artifact 只读。Patch、Review、Checkpoint、Candidate 和模拟激活写入 sessions/<session>/<case>；RAG public API 通过 X-Demo-Session-ID 分配临时版本目录。进程重启后旧 Session 允许丢失，并重新加载 Git 内 Baseline。

/health 区分服务存活与 Artifact Ready。UI 不依赖后端成功响应才能启动；超时或 5xx 只有限重试，并显示冷启动提示和重新连接。LLM 额度耗尽时 fail-closed，不生成假结果。
