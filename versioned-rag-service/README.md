# PP-Human 版本化研发知识服务

FastAPI 服务为 PP-Human 研发文档检索和变更审查 Agent 提供同一套中文、版本化证据。活动语料固定于 PaddlePaddle/PaddleDetection 仓库的六个正式版本，默认 v2.9.0；检索来源包含固定 commit、路径和文件哈希，历史版本查询不会用最新版资料代替。

## 语料状态

当前索引包含 83 条版本来源、14 个文档主题、761 个片段，覆盖 v2.5.0 至 v2.9.0（含 v2.8.1）。仅收录 PP-Human 中文教程及直接配置文件。Apache-2.0 许可依据记录在每条来源中；不包含模型权重、影像、视频或数据集。

新语料已可检索，但 PP-Human 专项检索与 Agent 冻结评测仍待建立，因此服务标注 `new_corpus_pending_rebenchmark`，不能把历史语料的指标作为当前效果。

## API

- `GET /health`：进程健康、语料就绪和构建指纹。
- `GET /public/workspace`：当前版本、可查询历史版本、来源数量、中文范围及评测状态。
- `GET /public/documents`：按版本列出固定来源和标题。
- `POST /public/search`、`POST /public/query`：检索或生成带引用回答，语言和版本范围由服务端语料清单验证。
- `POST /public/review-advice`：Agent 提交已检索证据 ID，回答只能引用本次提交的证据。

## 本地启动

从服务目录执行：

```powershell
$env:RAG_PUBLIC_CORPUS_ROOT = "public_corpus_pphuman"
$env:RAG_PUBLIC_RETRIEVAL_CONFIG = "public_corpus_pphuman/public_retrieval_runtime.json"
..\.venv\Scripts\python.exe -m uvicorn src.public_server:app --host 127.0.0.1 --port 8765
```

要启用回答生成，在后端进程设置 `RD_V2_ALLOW_EXTERNAL_GENERATION=true`、`RD_V2_GENERATION_PROVIDER=deepseek` 和 `DEEPSEEK_API_KEY`。密钥仅放在服务端或部署平台的密钥存储中。

## 来源导入和评测

`config/pphuman_source_selection.json` 是正文路径白名单。`scripts/build_pphuman_corpus.py` 从本地官方仓库读取固定 tag，只能构建到空的输出目录；会生成来源清单、索引、版本关系和排除项审计。缺少的历史文件必须记录为缺失，禁止从后续版本补写。

```powershell
$env:PYTHONPATH = "."
python scripts/build_pphuman_corpus.py --repository-root <PaddleDetection本地仓库路径> --output <新的空目录>
python -m pytest -q tests/test_pphuman_corpus.py tests/test_pphuman_server.py
```

只有在 PP-Human 版本化检索和变更审查题集冻结并通过独立 holdout 后，才能公布准确率或切换检索策略。其他语料的报告不得用于表示本服务的效果。
