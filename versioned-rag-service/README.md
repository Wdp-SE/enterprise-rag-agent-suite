# 中文边缘 AI 研发知识 RAG 服务

FastAPI 服务仅加载 Seeed Studio Wiki 中 reComputer Industrial / Jetson 的固定中文公开快照。语料包含 18 份来源、394 个文本片段，固定到 `Seeed-Studio/wiki-documents` commit `1eadc6584f962b6efdbdb3e49b2b4ce30c85be08`。它是精选公开资料快照，不代表完整产品资料、企业内部验证或设备兼容性认证。

## 当前服务

- `GET /health`：服务状态、运行策略和构建/语料/配置/评测指纹。
- `GET /public/workspace`：中文工作区、设备/软件范围、来源清单与经指纹校验的评测摘要。
- `GET /public/documents`、`GET /public/document`：固定来源文档和片段。
- `POST /public/search`：仅用当前中文资料检索，可按设备型号、模组 SKU、载板和 JetPack/L4T 软件范围过滤。
- `POST /public/query`：返回引用证据；仅在服务端开启生成且供应商可用时生成回答。
- `POST /public/review-advice`：基于本轮提交的证据生成待审核的影响候选，不修改源资料。

当前检索默认 BM25。离线 22 题评测中，BM25 与分面 RRF 在 DEV/HOLDOUT 来源召回与完整来源集率相同，因此保留 BM25。每个切分只有 1 道语料外题，检索仍返回候选；检索候选不等于正确答案，回答拒绝率与 LLM 事实性仍需独立人工评测。12 题 Agent 评测只报告规则分类、范围缺口、人工审核边界与必需来源覆盖，没有宣称最终建议准确率。详细分母、指纹和复算命令见 [`evaluation/edge_ai_retrieval_v2`](../evaluation/edge_ai_retrieval_v2/README.md) 与 [`evaluation/edge_ai_change_review_v2`](../evaluation/edge_ai_change_review_v2/README.md)。旧领域评测保留作历史记录，索引见 [`evaluation/archive`](../evaluation/archive/README.md)，不代表当前语料成绩。

当前入库文本中的图片不含已审核 OCR 派生证据；服务使用绑定语料 manifest 的空图片 sidecar 和锁文件，避免误混入其他语料图片数据。图像像素内的文字暂不可检索。

## 本地启动

从仓库根目录使用 `start_prototype.ps1`，或在服务目录内运行：

```powershell
$env:RAG_PUBLIC_CORPUS_ROOT = "public_corpus_edge_ai"
$env:RAG_PUBLIC_RETRIEVAL_CONFIG = "public_corpus_edge_ai/public_retrieval_runtime.json"
..\.venv\Scripts\python.exe -m uvicorn src.public_server:app --host 127.0.0.1 --port 8765
```

示例运行变量位于 [`.env.example`](.env.example)。生成密钥只配置在后端服务环境；没有密钥时仍可检索和组织审查证据。

## 发布 Smoke

发布核对脚本要求 UI 与 RAG 使用相同提交 SHA、工作区必须是 `edge_ai_device`、语言必须为中文、评测需匹配当前指纹，并执行两条公开资料探针及一条不触发检索/生成的企业内测数据拒绝探针。它不会调用模型供应商。

```powershell
..\.venv\Scripts\python.exe scripts/public_release_smoke.py --help
```

部署模板将 `RAG_PUBLIC_CORPUS_ROOT` 与检索配置指向 `public_corpus_edge_ai/`。GitHub `main` 更新与 Render 部署是不同步骤；部署后需运行 Smoke 核对在线版本。
